# src/managers/llm_request_runner.py
from __future__ import annotations

import concurrent.futures
import time
from typing import Any, Callable, Optional

from main_logger import logger
from core.events import Events
from utils import save_combined_messages

from managers.api_preset_resolver import ApiPresetResolver, PresetSettings


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
    ) -> Optional[str]:
        if messages is None:
            messages = []

        try:
            base_preset = self.preset_resolver.resolve(preset_id)
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to resolve preset: {e}", exc_info=True)
            return None

        try:
            from managers.provider_manager import ProviderManager
            pm = ProviderManager()
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to init ProviderManager: {e}", exc_info=True)
            return None

        for attempt in range(1, int(max_attempts) + 1):
            logger.info(f"Generation attempt {attempt}/{max_attempts}")

            try:
                save_combined_messages(messages, "SavedMessages/last_attempt_log")
            except Exception:
                pass

            preset_attempt = self.preset_resolver.apply_key_rotation(base_preset, attempt)
            effective_model = (preset_attempt.api_model or "").strip()

            try:
                req = build_request(preset_attempt, effective_model)
            except Exception as e:
                logger.error(f"[LLMRequestRunner] Failed to build request: {e}", exc_info=True)
                req = None

            if req is None:
                if attempt < max_attempts:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                    time.sleep(float(retry_delay))
                continue

            try:
                response_text = self._call_with_timeout(
                    pm.generate,
                    args=(req,),
                    timeout=float(request_timeout)
                )
                if response_text:
                    return response_text
            except concurrent.futures.TimeoutError:
                logger.error(f"Attempt {attempt} timed out after {request_timeout}s.")
            except Exception as e:
                logger.error(f"Error during generation attempt {attempt}: {e}", exc_info=True)

            if attempt < max_attempts:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                time.sleep(float(retry_delay))

        logger.error("All generation attempts failed.")
        return None

    def _call_with_timeout(self, func, args=(), kwargs=None, timeout: float = 30.0):
        if kwargs is None:
            kwargs = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            
            start_time = time.time()
            while time.time() - start_time < timeout:
                if future.done():
                    return future.result()
                
                # Даем возможность другим потокам/событиям выполниться.
                # В контексте Qt/asyncio это помогает избежать полной заморозки,
                # хотя сам метод остается синхронным.
                time.sleep(0.01)
            
            # Если вышли из цикла по таймауту
            future.cancel()
            raise concurrent.futures.TimeoutError(f"Request timed out after {timeout}s")