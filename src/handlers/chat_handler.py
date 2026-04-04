# File: chat_handler.py
import json
#import tiktoken
import re
from typing import List, Dict, Any, Optional
from main_logger import logger

from characters.character import Character

from managers.api_preset_resolver import ApiPresetResolver
from managers.llm_request_runner import LLMRequestRunner
from managers.model_config_loader import ModelConfigLoader
from managers.tools.legacy_executor import LegacyToolExecutor
from managers.tools.tool_manager import ToolManager

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.param_mapper import build_unified_generation_params

from core.events import get_event_bus

class ChatModel:
    def __init__(self, settings):
        self.last_key = 0
        self.settings = settings
        self.event_bus = get_event_bus()

        # Presets
        self.preset_resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)

        preset_settings = self.preset_resolver.resolve()
        logger.info(f"Initializing ChatModel with preset: {preset_settings.preset_name}")

        self.api_model = preset_settings.api_model
        self.gpt4free_model = str(self.settings.get("gpt4free_model", "") or "")

        # Runtime config
        self.cfg_loader = ModelConfigLoader(self.settings)
        self.cfg = self.cfg_loader.load()

        self.tool_manager = ToolManager()

        # Retry runner
        self.request_runner = LLMRequestRunner(
            settings=self.settings,
            preset_resolver=self.preset_resolver,
            event_bus=self.event_bus
        )


        self.current_character: Character = None
        self.GameMaster: Character = None
        self.characters = {}

        self.legacy_tools = LegacyToolExecutor(
            settings=self.settings,
            tool_manager=self.tool_manager,
            preset_resolver=self.preset_resolver
        )

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
        
    def generate(
        self,
        messages: List[Dict[str, Any]],
        stream_callback: callable = None,
        preset_id: Optional[int] = None
    ) -> Optional[str]:
        
        if messages is None:
            messages = []
        raw_text, success = self._generate_chat_response(
            combined_messages=messages,
            stream_callback=stream_callback,
            preset_id=preset_id
        )
        if not success:
            return None
        return raw_text

    def _generate_chat_response(self, combined_messages, stream_callback: callable = None, preset_id: Optional[int] = None):
        max_attempts = self.cfg.max_request_attempts
        retry_delay = self.cfg.request_delay
        request_timeout = 45

        self._log_generation_start(preset_id)

        tools_on = self.settings.get("TOOLS_ON", True)
        tools_mode = self.settings.get("TOOLS_MODE", "native")
        if tools_mode == "off":
            tools_on = False

        _ALL_TOOLS = ["calculator", "web_search", "google_search", "web_reader"]
        enabled_tools = [n for n in _ALL_TOOLS if self.settings.get(f"TOOL_ENABLED_{n}", True)]

        if not enabled_tools:
            tools_on = False

        if tools_on and tools_mode == "legacy":
            tools_desc = json.dumps(self.tool_manager._filtered_schema(enabled_tools))
            legacy_prompt = self.tool_manager.tools_prompt().format(tools_json=tools_desc)

            already = False
            for m in (combined_messages[:3] if isinstance(combined_messages, list) else []):
                if isinstance(m, dict) and m.get("role") == "system" and m.get("content") == legacy_prompt:
                    already = True
                    break

            if not already:
                combined_messages.insert(0, {"role": "system", "content": legacy_prompt})


        # Capture the last built LLMRequest so we can save it for finetune data collection
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
                gemini_thinking_budget=getattr(cfg, "gemini_thinking_budget", None),
                force_params=getattr(cfg, "preset_forced_params", frozenset()),
            )

            dialect = "gemini" if preset_settings.dialect_id == "gemini_generate_content" else "openai"

            prebuilt_payload = (
                self.tool_manager.get_tools_payload(dialect, enabled_tools)
                if tools_on and tools_mode == "native" else None
            )

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
                capabilities=dict(preset_settings.capabilities or {}),

                stream=bool(self.settings.get("ENABLE_STREAMING", False)) and stream_callback is not None,
                stream_cb=stream_callback,
                tools_on=tools_on,
                tools_mode=tools_mode,
                tools_payload=prebuilt_payload,
                tools_dialect=dialect,
                extra=params,
                tool_manager=self.tool_manager,
                settings=self.settings,
            )

            req.extra["tool_manager"] = self.tool_manager
            _last_req[0] = req
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
            )
        except Exception as e:
            logger.error(f"Runner failed unexpectedly: {e}", exc_info=True)
            return None, False

        # ── Finetune data collection hook ─────────────────────────────────────
        if response_text and _last_req[0]:
            try:
                from managers.finetune_collector import FineTuneCollector
                fc = FineTuneCollector.instance
                if fc and fc.is_enabled():
                    char = self.current_character
                    # Query game connection status (non-blocking)
                    game_connected = False
                    try:
                        from core.events import Events
                        res = self.event_bus.emit_and_wait(
                            Events.Server.GET_GAME_CONNECTION, timeout=0.3
                        )
                        game_connected = bool(res[0]) if res else False
                    except Exception:
                        game_connected = False
                    fc.save_sample(
                        req=_last_req[0],
                        response_text=response_text,
                        character_id=char.char_id if char else "unknown",
                        character_name=char.name if char else "unknown",
                        game_connected=game_connected,
                    )
            except Exception as _ft_err:
                logger.debug(f"[FinetuneCollector] save_sample skipped: {_ft_err}")

        if response_text and tools_on and tools_mode == "legacy":
            response_text = self.legacy_tools.process(
                response_text=response_text,
                messages=combined_messages,
                generate_fn=self._generate_chat_response,
                stream_callback=stream_callback,
                preset_id=preset_id,
                depth=0
            )

        if response_text:
            cleaned_response = self._clean_response(response_text)
            if cleaned_response:
                return cleaned_response, True
            logger.warning("Response became empty after cleaning.")
            return None, False

        return None, False
    
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
        logger.info(f"API URL: {preset_settings.api_url}, API Model: {preset_settings.api_model}")

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
