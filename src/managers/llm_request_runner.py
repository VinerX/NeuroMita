# src/managers/llm_request_runner.py
from __future__ import annotations

import concurrent.futures
import os
import time
from typing import Any, Callable, Optional

from main_logger import logger
from core.events import Events
from utils import save_combined_messages

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

        last_error_message: Optional[str] = None
        last_provider_name: Optional[str] = None
        last_model_name: Optional[str] = None

        try:
            base_preset = self.preset_resolver.resolve(preset_id)
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to resolve preset: {e}", exc_info=True)
            return LLMResponse(text=None, error_message=f"Failed to resolve preset: {e}")

        try:
            from managers.provider_manager import ProviderManager
            pm = ProviderManager()
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to init ProviderManager: {e}", exc_info=True)
            return LLMResponse(text=None, error_message=f"Failed to initialize ProviderManager: {e}")

        for attempt in range(1, int(max_attempts) + 1):
            logger.info(f"Generation attempt {attempt}/{max_attempts}")

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
                logger.error(f"[LLMRequestRunner] Failed to build request: {e}", exc_info=True)
                last_error_message = f"Failed to build request: {e}"
                req = None

            if req is None:
                if attempt < max_attempts:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                    time.sleep(float(retry_delay))
                continue

            try:
                response = self._call_with_timeout(
                    pm.generate,
                    args=(req,),
                    timeout=float(request_timeout)
                )
                if response and response.text:
                    return response

                if response:
                    last_provider_name = response.provider_name or last_provider_name
                    last_model_name = response.model or last_model_name
                    finish_reason = f", finish_reason={response.finish_reason}" if response.finish_reason else ""
                    last_error_message = response.error_message or f"Provider returned empty response{finish_reason}."
                    logger.error(
                        f"Generation attempt {attempt} returned no text. "
                        f"provider={last_provider_name}, model={last_model_name}{finish_reason}, "
                        f"error={last_error_message}"
                    )
                else:
                    last_error_message = "Provider returned no response object."
                    logger.error(f"Generation attempt {attempt} returned no response object.")
            except concurrent.futures.TimeoutError:
                last_error_message = f"Attempt {attempt} timed out after {request_timeout}s."
                logger.error(last_error_message)
            except Exception as e:
                last_error_message = f"Error during generation attempt {attempt}: {e}"
                logger.error(f"Error during generation attempt {attempt}: {e}", exc_info=True)

            if attempt < max_attempts:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                time.sleep(float(retry_delay))

        if last_error_message:
            logger.error(f"All generation attempts failed. Last error: {last_error_message}")
        else:
            logger.error("All generation attempts failed.")
        return LLMResponse(
            text=None,
            model=last_model_name,
            provider_name=last_provider_name,
            error_message=last_error_message or "All generation attempts failed.",
        )

    def _call_with_timeout(self, func, args=(), kwargs=None, timeout: float = 30.0):
        if kwargs is None:
            kwargs = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)
