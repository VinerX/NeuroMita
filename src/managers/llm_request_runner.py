# src/managers/llm_request_runner.py
from __future__ import annotations

import concurrent.futures
import os
import time
from typing import Any, Callable, Optional

from main_logger import logger
from core.events import Events
from core.executors import PoolSaturated, Pools, executors
from handlers.llm_providers.errors import (
    LLMProviderError,
    build_configuration_error,
    build_provider_error,
    coerce_provider_error,
)
from utils import _, save_combined_messages

from managers.api_preset_resolver import ApiPresetResolver, PresetSettings
from handlers.llm_providers.base import LLMResponse
from handlers.llm_providers.base import RequestCancellation


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
        self._timed_out_call = False

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
        suppress_failure_events: bool = False,
    ) -> Optional[LLMResponse]:
        if messages is None:
            messages = []
        self.last_error = None
        self._timed_out_call = False

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
                suppress_failure_events=bool(suppress_failure_events),
                chain_pos=chain_idx,
                chain_total=total_presets,
            )
            last_response = response
            if response and response.text:
                self.last_error = None
                if chain_idx > 1:
                    logger.info(f"[LLMRequestRunner] Fallback preset '{preset_label}' succeeded.")
                return response
            if self._timed_out_call:
                break

        # Вся цепочка пресетов исчерпана — терминальный отказ генерации.
        logger.error("All generation attempts failed across preset chain.")
        if self.last_error and not suppress_failure_events:
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
        suppress_failure_events: bool,
        chain_pos: int,
        chain_total: int,
    ) -> LLMResponse:
        preset_tag = f"[{chain_pos}/{chain_total} {base_preset.preset_name}]"

        last_error_message: Optional[str] = None
        last_provider_name: Optional[str] = None
        last_model_name: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            logger.info(f"{preset_tag} Generation attempt {attempt}/{max_attempts}")

            if self._debug_dumps_enabled():
                try:
                    _base = os.environ.get("NEUROMITA_BASE_DIR", "")
                    _log_path = os.path.join(_base, "SavedMessages", "last_attempt_log") if _base else "SavedMessages/last_attempt_log"
                    executors().try_submit(Pools.DEBUG_DUMP, save_combined_messages, list(messages), _log_path)
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
                    if not suppress_failure_events:
                        self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                    time.sleep(retry_delay)
                continue

            req.extra = dict(getattr(req, "extra", None) or {})
            req.extra.setdefault("http_timeout_seconds", float(request_timeout))
            req.extra.setdefault(
                "http_connect_timeout_seconds",
                min(15.0, max(1.0, float(request_timeout))),
            )
            req.extra.setdefault(
                "http_read_timeout_seconds",
                max(1.0, float(request_timeout) - 5.0),
            )
            cancellation = RequestCancellation()
            req.extra["_request_cancellation"] = cancellation

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
                    cancellation=cancellation,
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
                self._timed_out_call = True
                last_error_message = f"Attempt {attempt} timed out after {request_timeout}s."
                logger.error(f"{preset_tag} {last_error_message}")
                self.last_error = LLMProviderError(
                    provider=getattr(req, "provider_name", "unknown"),
                    friendly_message=_("Ошибка сети - Сервер не ответил вовремя.", "Network error - The server did not respond in time."),
                    provider_message=last_error_message,
                    retryable=False,
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

            should_retry = bool(
                attempt < max_attempts and (
                    self.last_error is None or bool(getattr(self.last_error, "retryable", False))
                )
            )
            if should_retry:
                if not suppress_failure_events:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                time.sleep(retry_delay)
            elif attempt < max_attempts and self.last_error is not None:
                logger.info(
                    f"{preset_tag} Stopping retries after non-retryable failure: "
                    f"{self.last_error.to_console_summary()}"
                )
                break

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

    def _call_with_timeout(
        self,
        func,
        args=(),
        kwargs=None,
        timeout: float = 30.0,
        cancellation: RequestCancellation | None = None,
    ):
        """Вызвать func с ограничением по времени.

        Раньше здесь был `with ThreadPoolExecutor(...)`: его __exit__ делает
        shutdown(wait=True), поэтому после TimeoutError вызывающий всё равно
        досиживал до конца HTTP-запроса — таймаут был декоративным. Плюс на
        каждую попытку создавался новый пул.
        """
        if kwargs is None:
            kwargs = {}
        pool = executors().pool(Pools.LLM_HTTP)
        try:
            future = pool.try_submit(func, *args, **kwargs)
        except PoolSaturated as exc:
            raise RuntimeError(
                "LLM HTTP pool is saturated by unfinished provider requests"
            ) from exc
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            if cancellation is not None:
                cancellation.cancel()
            future.cancel()
            try:
                future.result(timeout=min(1.0, max(0.1, float(timeout) * 0.05)))
            except concurrent.futures.TimeoutError:
                abandoned = pool.abandon(future)
                logger.warning(
                    "LLM provider did not stop within the cancellation grace period; "
                    "the detached daemon worker will be ignored"
                    + (" and its pool slot was replaced" if abandoned else "")
                )
            except Exception:
                pass
            raise

    def _debug_dumps_enabled(self) -> bool:
        env_value = str(os.environ.get("NEUROMITA_DEBUG_DUMPS", "")).strip().lower()
        if env_value in {"1", "true", "yes", "on"}:
            return True
        try:
            return bool(self.settings.get("DEBUG_SAVE_LLM_DUMPS", False))
        except Exception:
            return False

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
        # Ключ требуем только у официальных облачных провайдеров (openai/gemini).
        # 'common' — это произвольный OpenAI-совместимый эндпоинт: помимо
        # localhost-серверов (LM Studio / Ollama) бывают и безключевые шлюзы,
        # self-hosted и LAN/туннели, поэтому ключ для него не обязателен.
        if (
            provider in {"openai", "gemini"}
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
