# src/managers/llm_request_runner.py
from __future__ import annotations

import concurrent.futures
import os
import time
from typing import Any, Callable, Optional

from main_logger import logger
from core.events import Events
from handlers.llm_providers.errors import (
    LLMProviderError,
    build_configuration_error,
    build_provider_error,
    coerce_provider_error,
)
from utils import _, save_combined_messages

from managers.api_preset_resolver import ApiPresetResolver, PresetSettings
from handlers.llm_providers.base import LLMResponse


class LLMRequestRunner:
    """
    Отвечает только за:
    - retry loop
    - timeout выполнения provider_manager.generate
    - задержку между попытками
    - ротацию ключей через ApiPresetResolver

    NOTE: GPT4FREE_LAST_ATTEMPT removed from logic.
    """

    def __init__(
        self,
        settings: Any,
        preset_resolver: ApiPresetResolver,
        event_bus: Any,
    ):
        self.settings = settings
        self.preset_resolver = preset_resolver
        self.event_bus = event_bus
        self.last_error: Optional[LLMProviderError] = None

    def run(
        self,
        *,
        messages: list,
        preset_id: Optional[int],
        stream_callback: Optional[Callable[[str], None]],
        build_request: Callable[[PresetSettings, str], Any],
        max_attempts: int,
        retry_delay: float,
        request_timeout: float,
    ) -> Optional[LLMResponse]:
        if messages is None:
            messages = []
        self.last_error = None

        try:
            preset_chain = self.preset_resolver.resolve_chain(preset_id)
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to resolve preset chain: {e}", exc_info=True)
            return LLMResponse(text=None, error_message=f"Failed to resolve preset: {e}")

        if not preset_chain:
            logger.error("[LLMRequestRunner] Empty preset chain (no main, no fallbacks).")
            return LLMResponse(text=None, error_message="Empty preset chain (no main, no fallbacks).")

        try:
            from managers.provider_manager import ProviderManager
            pm = ProviderManager()
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to init ProviderManager: {e}", exc_info=True)
            return LLMResponse(text=None, error_message=f"Failed to initialize ProviderManager: {e}")

        total_presets = len(preset_chain)
        last_response: Optional[LLMResponse] = None
        for chain_idx, base_preset in enumerate(preset_chain, start=1):
            preset_label = base_preset.preset_name or f"preset#{chain_idx}"
            if chain_idx > 1:
                logger.warning(
                    f"[LLMRequestRunner] Switching to fallback {chain_idx}/{total_presets}: "
                    f"'{preset_label}' model='{base_preset.api_model}'"
                )

            response = self._run_on_preset(
                base_preset=base_preset,
                messages=messages,
                build_request=build_request,
                pm=pm,
                max_attempts=int(max_attempts),
                retry_delay=float(retry_delay),
                request_timeout=float(request_timeout),
                chain_pos=chain_idx,
                chain_total=total_presets,
            )
            last_response = response
            if response and response.text:
                self.last_error = None
                if chain_idx > 1:
                    logger.info(f"[LLMRequestRunner] Fallback preset '{preset_label}' succeeded.")
                return response

        # Вся цепочка пресетов исчерпана — терминальный отказ генерации.
        logger.error("All generation attempts failed across preset chain.")
        if self.last_error:
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": self.last_error.to_user_message(),
                "details": self.last_error.to_console_summary(),
            })
        if last_response is not None:
            return last_response
        return LLMResponse(text=None, error_message="All generation attempts failed.")

    def _run_on_preset(
        self,
        *,
        base_preset: PresetSettings,
        messages: list,
        build_request: Callable[[PresetSettings, str], Any],
        pm: Any,
        max_attempts: int,
        retry_delay: float,
        request_timeout: float,
        chain_pos: int,
        chain_total: int,
    ) -> LLMResponse:
        preset_tag = f"[{chain_pos}/{chain_total} {base_preset.preset_name}]"

        last_error_message: Optional[str] = None
        last_provider_name: Optional[str] = None
        last_model_name: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            logger.info(f"{preset_tag} Generation attempt {attempt}/{max_attempts}")

            try:
                _base = os.environ.get("NEUROMITA_BASE_DIR", "")
                _log_path = os.path.join(_base, "SavedMessages", "last_attempt_log") if _base else "SavedMessages/last_attempt_log"
                save_combined_messages(messages, _log_path)
            except Exception:
                pass

            preset_attempt = self.preset_resolver.apply_key_rotation(base_preset, attempt)
            effective_model = (preset_attempt.api_model or "").strip()
            last_provider_name = preset_attempt.provider_name
            last_model_name = effective_model

            try:
                req = build_request(preset_attempt, effective_model)
            except Exception as e:
                logger.error(f"{preset_tag} Failed to build request: {e}", exc_info=True)
                last_error_message = f"Failed to build request: {e}"
                self.last_error = build_provider_error(
                    provider=getattr(preset_attempt, "provider_name", "unknown"),
                    provider_message=last_error_message,
                    url=getattr(preset_attempt, "api_url", None),
                )
                req = None

            if req is None:
                if attempt < max_attempts:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                    time.sleep(retry_delay)
                continue

            validation_error = self._validate_request(req)
            if validation_error is not None:
                self.last_error = validation_error
                last_error_message = validation_error.to_user_message()
                logger.error(
                    f"{preset_tag} Generation attempt {attempt} aborted before provider call: "
                    f"{validation_error.to_console_summary()}"
                )
                break

            try:
                response = self._call_with_timeout(
                    pm.generate,
                    args=(req,),
                    timeout=request_timeout,
                )
                if response and response.text:
                    self.last_error = None
                    return response

                if response:
                    last_provider_name = response.provider_name or last_provider_name
                    last_model_name = response.model or last_model_name
                    finish_reason = f", finish_reason={response.finish_reason}" if response.finish_reason else ""
                    last_error_message = response.error_message or f"Provider returned empty response{finish_reason}."
                    self.last_error = build_provider_error(
                        provider=last_provider_name or getattr(req, "provider_name", "unknown"),
                        provider_message=last_error_message,
                        url=getattr(req, "api_url", None),
                    )
                    logger.error(
                        f"Generation attempt {attempt} returned no text. "
                        f"provider={last_provider_name}, model={last_model_name}{finish_reason}, "
                        f"error={last_error_message}"
                    )
                else:
                    last_error_message = "Provider returned no response object."
                    self.last_error = build_provider_error(
                        provider=getattr(req, "provider_name", "unknown"),
                        provider_message=last_error_message,
                        url=getattr(req, "api_url", None),
                    )
                    logger.error(f"Generation attempt {attempt} returned no response object.")
            except concurrent.futures.TimeoutError:
                last_error_message = f"Attempt {attempt} timed out after {request_timeout}s."
                logger.error(f"{preset_tag} {last_error_message}")
                self.last_error = LLMProviderError(
                    provider=getattr(req, "provider_name", "unknown"),
                    friendly_message=_("Ошибка сети - Сервер не ответил вовремя.", "Network error - The server did not respond in time."),
                    provider_message=last_error_message,
                    retryable=True,
                    url=getattr(req, "api_url", None),
                )
            except Exception as e:
                last_error_message = f"Error during generation attempt {attempt}: {e}"
                self.last_error = coerce_provider_error(
                    getattr(req, "provider_name", "unknown"),
                    e,
                    url=getattr(req, "api_url", None),
                )
                if isinstance(self.last_error, LLMProviderError):
                    logger.error(
                        f"{preset_tag} Error during generation attempt {attempt}: {self.last_error.to_console_summary()}"
                    )
                else:
                    logger.error(
                        f"{preset_tag} Error during generation attempt {attempt}: {self.last_error.to_console_summary()}",
                        exc_info=True,
                    )

            if attempt < max_attempts:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                time.sleep(retry_delay)

        if last_error_message:
            logger.error(f"{preset_tag} All generation attempts failed. Last error: {last_error_message}")
        else:
            logger.error(f"{preset_tag} All generation attempts failed.")
        return LLMResponse(
            text=None,
            model=last_model_name,
            provider_name=last_provider_name,
            error_message=(
                self.last_error.to_user_message()
                if self.last_error
                else last_error_message or "All generation attempts failed."
            ),
        )

    def _call_with_timeout(self, func, args=(), kwargs=None, timeout: float = 30.0):
        if kwargs is None:
            kwargs = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)

    def _validate_request(self, req) -> Optional[LLMProviderError]:
        provider = getattr(req, "provider_name", "unknown") or "unknown"
        url = getattr(req, "api_url", None)
        model = str(getattr(req, "model", "") or "").strip()

        if not str(provider).strip():
            return build_configuration_error(
                "unknown",
                "API provider not configured",
                url=url,
            )
        if not str(url or "").strip():
            return build_configuration_error(
                provider,
                "API preset not configured: missing API URL",
                url=url,
            )
        if not model:
            return build_configuration_error(
                provider,
                "API preset not configured: missing API model",
                url=url,
            )
        if (
            provider in {"common", "openai", "gemini"}
            and str(url or "").startswith(("http://", "https://"))
            and "localhost" not in str(url or "").lower()
            and "127.0.0.1" not in str(url or "").lower()
            and not str(getattr(req, "api_key", "") or "").strip()
        ):
            return build_configuration_error(
                provider,
                "API preset not configured: missing API key",
                url=url,
            )
        return None
