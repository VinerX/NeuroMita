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
            preset_chain = self.preset_resolver.resolve_chain(preset_id)
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to resolve preset chain: {e}", exc_info=True)
            return None

        if not preset_chain:
            logger.error("[LLMRequestRunner] Empty preset chain (no main, no fallbacks).")
            return None

        try:
            from managers.provider_manager import ProviderManager
            pm = ProviderManager()
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to init ProviderManager: {e}", exc_info=True)
            return None

        total_presets = len(preset_chain)
        for chain_idx, base_preset in enumerate(preset_chain, start=1):
            preset_label = base_preset.preset_name or f"preset#{chain_idx}"
            if chain_idx > 1:
                logger.warning(
                    f"[LLMRequestRunner] Switching to fallback {chain_idx}/{total_presets}: "
                    f"'{preset_label}' model='{base_preset.api_model}'"
                )

            response_text = self._run_on_preset(
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
            if response_text:
                if chain_idx > 1:
                    logger.info(f"[LLMRequestRunner] Fallback preset '{preset_label}' succeeded.")
                return response_text

        logger.error("All generation attempts failed across preset chain.")
        return None

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
    ) -> Optional[str]:
        import os
        preset_tag = f"[{chain_pos}/{chain_total} {base_preset.preset_name}]"

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

            try:
                req = build_request(preset_attempt, effective_model)
            except Exception as e:
                logger.error(f"{preset_tag} Failed to build request: {e}", exc_info=True)
                req = None

            if req is None:
                if attempt < max_attempts:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                    time.sleep(retry_delay)
                continue

            try:
                response_text = self._call_with_timeout(
                    pm.generate,
                    args=(req,),
                    timeout=request_timeout,
                )
                if response_text:
                    return response_text
            except concurrent.futures.TimeoutError:
                logger.error(f"{preset_tag} Attempt {attempt} timed out after {request_timeout}s.")
            except Exception as e:
                logger.error(f"{preset_tag} Error during attempt {attempt}: {e}", exc_info=True)

            if attempt < max_attempts:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                time.sleep(retry_delay)

        return None

    def _call_with_timeout(self, func, args=(), kwargs=None, timeout: float = 30.0):
        if kwargs is None:
            kwargs = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)
