# src/handlers/chat_handler.py
import re
import threading
from typing import List, Dict, Any, Optional

from main_logger import logger
from utils import _, mask_sensitive, redact_image_payloads

from characters.character import Character

from managers.api_preset_resolver import ApiPresetResolver
from managers.llm_request_runner import LLMRequestRunner
from managers.model_config_loader import ModelConfigLoader
from managers.tools.tool_manager import ToolManager

from handlers.llm_providers.base import LLMRequest, LLMResponse
from utils.openrouter_routing import (
    build_openrouter_session_id,
    normalize_openrouter_routing,
)
from handlers.llm_providers.param_mapper import build_unified_generation_params

from core.events import get_event_bus
from core.executors import Pools, executors
from core.services import use
from services.contracts import GameLinkService


def _debug_dumps_enabled(settings: Any) -> bool:
    import os

    env_value = str(os.environ.get("NEUROMITA_DEBUG_DUMPS", "")).strip().lower()
    if env_value in {"1", "true", "yes", "on"}:
        return True
    try:
        return bool(settings.get("DEBUG_SAVE_LLM_DUMPS", False))
    except Exception:
        return False


from utils.context_token_stats import compute_token_usage as _compute_token_usage


def _save_last_request_context(req, character_name: str = "") -> None:
    """Всегда сохраняет последний запрос в SavedMessages/last_request_context.json."""
    import json
    import os
    from datetime import datetime, timezone

    _KEEP = {
        "temperature", "max_tokens", "max_response_tokens", "top_p", "top_k",
        "presence_penalty", "frequency_penalty",
        "openrouter_routing",
        "openrouter_session_id",
    }
    try:
        base = os.environ.get("NEUROMITA_BASE_DIR", "")
        out_dir = os.path.join(base, "SavedMessages") if base else "SavedMessages"
        os.makedirs(out_dir, exist_ok=True)
        extra_raw = getattr(req, "extra", {}) or {}
        messages = redact_image_payloads(getattr(req, "messages", []))
        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "model": getattr(req, "model", None),
            "provider_name": getattr(req, "provider_name", None),
            "protocol_id": getattr(req, "protocol_id", None),
            "dialect_id": getattr(req, "dialect_id", None),
            "character_name": character_name or "",
            "extra": {k: v for k, v in extra_raw.items() if k in _KEEP},
            "token_usage": _compute_token_usage(messages),
            "messages": messages,
        }
        with open(os.path.join(out_dir, "last_request_context.json"), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception as _e:
        logger.debug(f"[ContextSave] {_e}")


def _save_last_response_context(req, response: LLMResponse, *, raw_response_text: str = "", cleaned_response_text: str = "") -> None:
    """Дописывает последний ответ и usage в last_request_context.json."""
    import json
    import os
    from datetime import datetime, timezone

    try:
        base = os.environ.get("NEUROMITA_BASE_DIR", "")
        out_dir = os.path.join(base, "SavedMessages") if base else "SavedMessages"
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "last_request_context.json")

        record: Dict[str, Any] = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    record = loaded
            except Exception:
                record = {}

        if not record:
            extra_raw = getattr(req, "extra", {}) or {}
            record = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "model": getattr(req, "model", None),
                "provider_name": getattr(req, "provider_name", None),
                "protocol_id": getattr(req, "protocol_id", None),
                "dialect_id": getattr(req, "dialect_id", None),
                "character_name": "",
                "extra": extra_raw,
                "messages": redact_image_payloads(getattr(req, "messages", [])),
            }

        usage = getattr(response, "usage", None)
        usage_payload = None
        if usage is not None:
            usage_payload = {
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                "reasoning_tokens": int(getattr(usage, "reasoning_tokens", 0) or 0),
                "cached_prompt_tokens": int(getattr(usage, "cached_prompt_tokens", 0) or 0),
                "cache_write_tokens": int(getattr(usage, "cache_write_tokens", 0) or 0),
                "cost": getattr(usage, "cost", None),
                "cost_currency": getattr(usage, "cost_currency", None),
                "cost_source": getattr(usage, "cost_source", None),
                "raw": getattr(usage, "raw", {}) or {},
            }

        record.update({
            "response_timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "response": cleaned_response_text or getattr(response, "text", "") or "",
            "response_raw": raw_response_text or getattr(response, "text", "") or "",
            "response_model": getattr(response, "model", None) or getattr(req, "model", None),
            "response_provider_name": getattr(response, "provider_name", None) or getattr(req, "provider_name", None),
            "finish_reason": getattr(response, "finish_reason", None),
            "usage": usage_payload,
        })

        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception as _e:
        logger.debug(f"[ContextSaveResponse] {_e}")


class ChatModel:
    def __init__(self, settings):
        self._error_state = threading.local()
        self._last_error_global = None
        self._last_error_lock = threading.Lock()
        self.last_key = 0
        self.settings = settings
        self.event_bus = get_event_bus()

        self.preset_resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)

        preset_settings = self.preset_resolver.resolve()
        logger.info(f"Initializing ChatModel with preset: {preset_settings.preset_name}")

        self.api_model = preset_settings.api_model
        self.gpt4free_model = str(self.settings.get("gpt4free_model", "") or "")

        self.cfg_loader = ModelConfigLoader(self.settings)
        self.cfg = self.cfg_loader.load()

        self.tool_manager = ToolManager()

        self.request_runner = LLMRequestRunner(
            settings=self.settings,
            preset_resolver=self.preset_resolver,
            event_bus=self.event_bus
        )

        self.current_character: Character = None
        self.GameMaster: Character = None
        self.characters = {}

        self._model_token_limits: Dict[str, int] = {
            "gpt-4o-mini": 128000,
            "gpt-4o": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
            "gemini-1.5-flash": 1000000,
            "gemini-1.5-pro": 1000000,
            "gemini-pro": 32768,
        }

        self.HideAiData = True
        self.last_error = None

    @property
    def last_error(self):
        if hasattr(self._error_state, "last_error"):
            return self._error_state.last_error
        with self._last_error_lock:
            return self._last_error_global

    @last_error.setter
    def last_error(self, value) -> None:
        self._error_state.last_error = value
        with self._last_error_lock:
            self._last_error_global = value

    def close(self) -> None:
        self.request_runner.close()

    def generate(
        self,
        messages: List[Dict[str, Any]],
        stream_callback: callable = None,
        stream_event_callback: callable = None,
        preset_id: Optional[int] = None,
        *,
        request_id: str = "",
        capabilities_override: Optional[Dict[str, Any]] = None,
        request_options_override: Optional[Dict[str, Any]] = None,
        structured_model: Optional[type] = None,
    ) -> Optional[LLMResponse]:
        if messages is None:
            messages = []
        response, success = self._generate_chat_response(
            combined_messages=messages,
            stream_callback=stream_callback,
            stream_event_callback=stream_event_callback,
            preset_id=preset_id,
            request_id=request_id,
            capabilities_override=capabilities_override,
            request_options_override=request_options_override,
            structured_model=structured_model,
        )
        if not success:
            return None
        return response

    def _generate_chat_response(
        self,
        combined_messages,
        stream_callback: callable = None,
        stream_event_callback: callable = None,
        preset_id: Optional[int] = None,
        *,
        request_id: str = "",
        capabilities_override: Optional[Dict[str, Any]] = None,
        request_options_override: Optional[Dict[str, Any]] = None,
        structured_model: Optional[type] = None,
    ):
        request_options = dict(request_options_override or {})
        max_attempts = int(request_options.get("max_attempts", self.cfg.max_request_attempts) or 1)
        retry_delay = float(request_options.get("retry_delay", self.cfg.request_delay) or 0.0)
        request_timeout = float(request_options.get("request_timeout", 240) or 240)
        suppress_failure_events = bool(request_options.get("suppress_failure_events", False))

        self._log_generation_start(preset_id)

        _last_req: list = [None]

        def build_request(preset_settings, effective_model: str) -> LLMRequest:
            cfg = self.cfg_loader.effective_for_preset(self.cfg, preset_settings, effective_model)

            params = build_unified_generation_params(
                settings=self.settings,
                temperature=cfg.temperature,
                max_response_tokens=cfg.max_response_tokens,
                presence_penalty=cfg.presence_penalty,
                frequency_penalty=cfg.frequency_penalty,
                log_probability=cfg.log_probability,
                top_k=cfg.top_k,
                top_p=cfg.top_p,
                thinking_budget=cfg.thinking_budget,
                enable_thinking=cfg.enable_thinking,
                reasoning_effort=getattr(cfg, "reasoning_effort", None),
                gemini_thinking_budget=getattr(cfg, "gemini_thinking_budget", None),
                force_params=getattr(cfg, "preset_forced_params", frozenset()),
            )
            if request_id:
                params["request_id"] = str(request_id)

            caps = dict(preset_settings.capabilities or {})
            if isinstance(capabilities_override, dict):
                caps.update(capabilities_override)

            req = LLMRequest(
                model=effective_model,
                messages=combined_messages,
                api_key=preset_settings.api_key,
                api_url=preset_settings.api_url,

                protocol_id=preset_settings.protocol_id,
                dialect_id=preset_settings.dialect_id,
                provider_name=preset_settings.provider_name,
                headers=dict(preset_settings.headers or {}),
                transforms=list(preset_settings.transforms or []),
                capabilities=caps,

                stream=(
                    bool(self.settings.get("ENABLE_STREAMING", False))
                    and (stream_callback is not None or stream_event_callback is not None)
                ),
                stream_cb=stream_callback,
                stream_event_cb=stream_event_callback,
                extra=params,
                tool_manager=self.tool_manager,
                settings=self.settings,
                structured_model=structured_model,
            )

            req.extra["tool_manager"] = self.tool_manager
            req.extra["http_timeout_seconds"] = float(request_timeout)
            if preset_settings.protocol_id == "openrouter_default":
                routing = normalize_openrouter_routing(preset_settings.openrouter_routing)
                if routing:
                    req.extra["openrouter_routing"] = routing
                req.extra["openrouter_tail_system_to_user"] = bool(
                    (preset_settings.openrouter_routing or {}).get("tail_system_to_user", True)
                )
                session_id = build_openrouter_session_id(
                    getattr(getattr(self, "current_character", None), "char_id", "") or "",
                    getattr(getattr(self, "current_character", None), "name", "") or "",
                )
                if session_id:
                    req.extra["openrouter_session_id"] = session_id
            _last_req[0] = req
            _char = getattr(self, "current_character", None)
            if _debug_dumps_enabled(self.settings):
                try:
                    executors().try_submit(
                        Pools.DEBUG_DUMP,
                        _save_last_request_context,
                        req,
                        character_name=getattr(_char, "name", "") or "",
                    )
                except Exception:
                    pass
            return req

        try:
            response_text = self.request_runner.run(
                messages=combined_messages,
                preset_id=preset_id,
                stream_callback=stream_callback,
                build_request=build_request,
                max_attempts=max_attempts,
                retry_delay=retry_delay,
                request_timeout=request_timeout,
                suppress_failure_events=suppress_failure_events,
            )
        except Exception as e:
            logger.error(f"Runner failed unexpectedly: {e}", exc_info=True)
            self.last_error = None
            return None, False

        self.last_error = self.request_runner.last_error

        if response_text and _last_req[0]:
            try:
                from managers.finetune_collector import FineTuneCollector
                fc = FineTuneCollector.instance
                if fc and fc.is_enabled():
                    char = self.current_character
                    game_connected = bool(use(GameLinkService).is_connected())
                    sample_id = fc.save_sample(
                        req=_last_req[0],
                        response_text=response_text.text,
                        character_id=char.char_id if char else "unknown",
                        character_name=char.name if char else "unknown",
                        game_connected=game_connected,
                    )
                    if sample_id:
                        if not isinstance(response_text.raw, dict):
                            response_text.raw = {}
                        response_text.raw["finetune_sample_id"] = sample_id
            except Exception as _ft_err:
                logger.debug(f"[FinetuneCollector] save_sample skipped: {_ft_err}")

        if response_text:
            raw_response_text = response_text.text or ""
            cleaned_response = self._clean_response(response_text.text)
            if cleaned_response:
                response_text.text = cleaned_response
                if _last_req[0] and _debug_dumps_enabled(self.settings):
                    try:
                        executors().try_submit(
                            Pools.DEBUG_DUMP,
                            _save_last_response_context,
                            _last_req[0],
                            response_text,
                            raw_response_text=raw_response_text,
                            cleaned_response_text=cleaned_response,
                        )
                    except Exception:
                        pass
                return response_text, True
            logger.warning("Response became empty after cleaning.")
            response_text.text = None
            response_text.error_message = response_text.error_message or "Response became empty after cleaning."
            return response_text, False

        return response_text, False

    def get_last_error_message(self) -> str:
        if self.last_error:
            try:
                return self.last_error.to_user_message()
            except Exception:
                return str(self.last_error)
        return _("Не удалось получить ответ.", "Failed to get a response.")

    def _log_generation_start(self, preset_id: Optional[int] = None):
        logger.info("Preparing to generate LLM response.")
        preset_settings = self.preset_resolver.resolve(preset_id)

        logger.info(f"Using preset: {preset_settings.preset_name}")
        logger.info(f"Protocol: {preset_settings.protocol_id} | Dialect: {preset_settings.dialect_id} | Provider: {preset_settings.provider_name}")
        logger.info(f"Capabilities: {preset_settings.capabilities}")
        logger.info(f"Max Response Tokens: {self.cfg.max_response_tokens}, Temperature: {self.cfg.temperature} (base; preset overrides applied separately)")
        logger.info(
            f"Presence Penalty: {self.cfg.presence_penalty} (Used: {bool(self.settings.get('USE_MODEL_PRESENCE_PENALTY'))})"
        )
        logger.info(f"API URL: {mask_sensitive(preset_settings.api_url)}, API Model: {preset_settings.api_model}")

    def try_print_error(self, completion_or_error):
        logger.warning("Attempting to print error details from API response/error object.")
        if not completion_or_error:
            logger.warning("No error object or completion data to parse.")
            return

        if hasattr(completion_or_error, 'error') and completion_or_error.error:
            error_data = completion_or_error.error
            logger.warning(
                f"API Error: Code={getattr(error_data, 'code', 'N/A')}, Message='{getattr(error_data, 'message', 'N/A')}', Type='{getattr(error_data, 'type', 'N/A')}'")
            if hasattr(error_data, 'param') and error_data.param:
                logger.warning(f"  Param: {error_data.param}")
        elif isinstance(completion_or_error, dict) and 'error' in completion_or_error:
            error_data = completion_or_error['error']
            logger.warning(f"API Error (from dict): {error_data}")
        elif hasattr(completion_or_error, 'message'):
            logger.warning(f"API Error: {completion_or_error.message}")
        else:
            logger.warning(f"Could not parse detailed error. Raw object: {str(completion_or_error)[:500]}")

    def _clean_response(self, response_text: str) -> str:
        if not isinstance(response_text, str):
            logger.warning(f"Clean response expected string, got {type(response_text)}. Returning as is.")
            return response_text

        cleaned = response_text
        if cleaned.startswith("```json\n") and cleaned.endswith("\n```"):
            cleaned = cleaned[len("```json\n"):-len("\n```")]
        elif cleaned.startswith("```\n") and cleaned.endswith("\n```"):
            cleaned = cleaned[len("```\n"):-len("\n```")]
        elif cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned[3:-3]

        return cleaned.strip()

    def reload_promts(self):
        logger.info("Reloading current character data.")
        if self.current_character:
            self.current_character.reload_character_data()
            logger.info(f"Character {self.current_character.name} data reloaded.")
        else:
            logger.warning("No current character selected to reload.")
