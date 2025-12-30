import datetime
import re
import copy

from typing import Optional

from handlers.chat_handler import ChatModel
from utils import _, process_text_to_voice
from core.events import get_event_bus, Events, Event
from main_logger import logger
from managers.character_manager import CharacterManager
from managers.api_preset_resolver import ApiPresetResolver
from managers.game_state_manager import GameState
from managers.context_counter import ContextCounter

# Контроллер для работы с моделью LLM

class ModelController:
    def __init__(self, settings, pip_installer):
        self.settings = settings
        self.event_bus = get_event_bus()

        self.lazy_load_batch_size = 50
        self.total_messages_in_history = 0
        self.loaded_messages_offset = 0
        self.loading_more_history = False

        self.preset_resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)

        self.model = ChatModel(settings, pip_installer)

        self.context_counter = ContextCounter(encoding_model="gpt-4o-mini")
        self._base_prompt_cache: dict[tuple[str, str], list[dict]] = {}

        self.game_state = GameState()
        self._temporary_system_infos: list[dict] = []

        initial_char = str(self.settings.get("CHARACTER") or "")
        self.character_manager = CharacterManager(initial_character_id=initial_char)

        self.model.current_character = self.character_manager.current_character
        self.model.GameMaster = self.character_manager.GameMaster

        self.model.characters = self.character_manager.characters

        self._subscribe_to_events()
        
    def _subscribe_to_events(self):
        # Существующие события
        self.event_bus.subscribe("model_settings_loaded", self._on_model_settings_loaded, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)
        self.event_bus.subscribe(Events.Model.GET_GAME_STATE, self._on_get_game_state, weak=False)
        
        # События персонажей
        self.event_bus.subscribe(Events.Model.GET_ALL_CHARACTERS, self._on_get_all_characters, weak=False)
        self.event_bus.subscribe(Events.Model.GET_CURRENT_CHARACTER, self._on_get_current_character, weak=False)
        self.event_bus.subscribe(Events.Model.SET_CHARACTER_TO_CHANGE, self._on_set_character_to_change, weak=False)
        self.event_bus.subscribe(Events.Model.CHECK_CHANGE_CHARACTER, self._on_check_change_character, weak=False)
        self.event_bus.subscribe(Events.Model.GET_CHARACTER, self._on_get_character, weak=False)
        self.event_bus.subscribe(Events.Model.RELOAD_CHARACTER_DATA, self._on_reload_character_data, weak=False)
        self.event_bus.subscribe(Events.Model.RELOAD_CHARACTER_PROMPTS, self._on_reload_character_prompts, weak=False)
        self.event_bus.subscribe(Events.Model.CLEAR_CHARACTER_HISTORY, self._on_clear_character_history, weak=False)
        self.event_bus.subscribe(Events.Model.CLEAR_ALL_HISTORIES, self._on_clear_all_histories, weak=False)
        
        # События истории
        self.event_bus.subscribe(Events.Model.LOAD_HISTORY, self._on_load_history, weak=False)
        self.event_bus.subscribe(Events.Model.LOAD_MORE_HISTORY, self._on_load_more_history, weak=False)
        self.event_bus.subscribe(Events.Model.PEEK_TEMPORARY_SYSTEM_INFOS, self._on_peek_temporary_system_infos, weak=False)
        
        # События информации
        self.event_bus.subscribe(Events.Model.GET_CHARACTER_NAME, self._on_get_character_name, weak=False)
        self.event_bus.subscribe(Events.Model.GET_CURRENT_CONTEXT_TOKENS, self._on_get_current_context_tokens, weak=False)
        self.event_bus.subscribe(Events.Model.CALCULATE_COST, self._on_calculate_cost, weak=False)
        self.event_bus.subscribe(Events.Model.GET_DEBUG_INFO, self._on_get_debug_info, weak=False)
        
        # События игры
        self.event_bus.subscribe(Events.Server.SET_GAME_DATA, self._on_set_game_data, weak=False)
        self.event_bus.subscribe(Events.Model.ADD_TEMPORARY_SYSTEM_INFO, self._on_add_temporary_system_info, weak=False)
        
        # События генерации
        self.event_bus.subscribe(Events.Model.GENERATE_RESPONSE, self._on_generate_response, weak=False)
        
        # События для обновления промптов
        self.event_bus.subscribe(Events.Model.RELOAD_PROMPTS_ASYNC, self._on_reload_prompts_async, weak=False)

        
    def _on_model_settings_loaded(self, event: Event):
        data = event.data
        if data.get('api_key'):
            self.model.api_key = data['api_key']
        if data.get('api_url'):
            self.model.api_url = data['api_url']
        if data.get('api_model'):
            self.model.api_model = data['api_model']
        if 'makeRequest' in data:
            self.model.makeRequest = data['makeRequest']
            
    def _on_setting_changed(self, event: Event):
        key = event.data.get('key')
        value = event.data.get('value')

        if key == "CHARACTER":
            self.change_character(value)
            return

        if hasattr(self.model, "cfg") and self.model.cfg:
            self.model.cfg.apply_setting(key, value)
                
    def change_character(self, character):
        if not character:
            return
        self.character_manager.set_character_to_change(character)
        self.character_manager.check_change_current_character()

        # Синхронизируем ссылки в ChatModel для совместимости
        self.model.current_character = self.character_manager.current_character
        self.model.characters = self.character_manager.characters
        self.model.GameMaster = self.character_manager.GameMaster
    
    # События персонажей
    def _on_get_all_characters(self, event: Event):
        return self.character_manager.get_all_characters()
    
    def _on_get_current_character(self, event: Event):
        ch = self.character_manager.current_character
        if not ch:
            return None

        return {
            'name': getattr(ch, 'name', ''),
            'char_id': getattr(ch, 'char_id', ''),
            'is_cartridge': bool(getattr(ch, 'is_cartridge', False)),
            'silero_command': getattr(ch, 'silero_command', ''),
            'short_name': getattr(ch, 'short_name', ''),
            'miku_tts_name': getattr(ch, 'miku_tts_name', 'Player'),
            'silero_turn_off_video': bool(getattr(ch, 'silero_turn_off_video', False)),
        }

    
    def _on_set_character_to_change(self, event: Event):
        character_name = (event.data or {}).get('character')
        if character_name:
            self.character_manager.set_character_to_change(character_name)
    
    def _on_check_change_character(self, event: Event):
        self.character_manager.check_change_current_character()


        self.model.current_character = self.character_manager.current_character
        self.model.characters = self.character_manager.characters
        self.model.GameMaster = self.character_manager.GameMaster
    
    def _on_get_character(self, event: Event):
        data = event.data or {}
        character_id = data.get('char_id') or data.get('character') or data.get('name')
        return self.character_manager.get_character(character_id)
    
    def _on_reload_character_prompts(self, event: Event):
        character_name = (event.data or {}).get('character')
        ch = self.character_manager.get_character(character_name) if character_name else None
        if ch and hasattr(ch, 'reload_prompts'):
            ch.reload_prompts()
    
    def _on_reload_character_prompts(self, event: Event):
        character_name = event.data.get('character')
        if character_name and hasattr(self.model, 'characters'):
            char = self.model.characters.get(character_name)
            if char and hasattr(char, 'reload_prompts'):
                char.reload_prompts()
    
    def _on_clear_character_history(self, event: Event):
        ch = self.character_manager.current_character
        if ch and hasattr(ch, 'clear_history'):
            ch.clear_history()
    
    def _on_clear_all_histories(self, event: Event):
        for ch in self.character_manager.characters.values():
            if hasattr(ch, 'clear_history'):
                ch.clear_history()
    
    # События истории
    def _on_load_history(self, event: Event):
        self.loaded_messages_offset = 0
        self.total_messages_in_history = 0
        self.loading_more_history = False

        ch = self.character_manager.current_character
        if not ch:
            self.event_bus.emit("history_loaded", {
                'messages': [],
                'total_messages': 0,
                'loaded_offset': 0
            })
            return

        chat_history = ch.load_history()
        all_messages = chat_history["messages"]
        self.total_messages_in_history = len(all_messages)

        max_display_messages = int(self.settings.get("MAX_CHAT_HISTORY_DISPLAY", 100))
        start_index = max(0, self.total_messages_in_history - max_display_messages)
        messages_to_load = all_messages[start_index:]

        self.loaded_messages_offset = len(messages_to_load)

        self.event_bus.emit("history_loaded", {
            'messages': messages_to_load,
            'total_messages': self.total_messages_in_history,
            'loaded_offset': self.loaded_messages_offset
        })
    
    def _on_load_more_history(self, event: Event):
        if self.loaded_messages_offset >= self.total_messages_in_history:
            return

        self.loading_more_history = True
        try:
            ch = self.character_manager.current_character
            if not ch:
                return

            chat_history = ch.load_history()
            all_messages = chat_history["messages"]

            lazy_load_batch_size = self.lazy_load_batch_size
            end_index = self.total_messages_in_history - self.loaded_messages_offset
            start_index = max(0, end_index - lazy_load_batch_size)
            messages_to_prepend = all_messages[start_index:end_index]

            if messages_to_prepend:
                self.loaded_messages_offset += len(messages_to_prepend)

                self.event_bus.emit("more_history_loaded", {
                    'messages': messages_to_prepend,
                    'loaded_offset': self.loaded_messages_offset
                })
        finally:
            self.loading_more_history = False

    

    def _on_peek_temporary_system_infos(self, event: Event):
        return list(self._temporary_system_infos)
    
    # События информации
    def _on_get_character_name(self, event: Event):
        ch = self.character_manager.current_character
        return ch.name if ch else ""
    
    def _on_get_current_context_tokens(self, event: Event):
        ch = self.character_manager.current_character
        if not ch:
            return 0

        char_id = getattr(ch, "char_id", "") or ""
        if not char_id:
            return 0

        event_type = "chat"

        base = self._base_prompt_cache.get((char_id, event_type))
        if not base:
            return 0

        user_input_res = self.event_bus.emit_and_wait(Events.Speech.GET_USER_INPUT, timeout=1.0)
        user_text = user_input_res[0] if user_input_res else ""

        try:
            extra_infos_res = self.event_bus.emit_and_wait(Events.Model.PEEK_TEMPORARY_SYSTEM_INFOS, timeout=1.0)
            extra_infos = extra_infos_res[0] if extra_infos_res and isinstance(extra_infos_res[0], list) else []
        except Exception:
            extra_infos = []

        messages = list(base)
        if extra_infos:
            messages.extend([x for x in extra_infos if isinstance(x, dict)])

        messages = self.context_counter.with_user_text(messages, str(user_text or ""))

        return self.context_counter.count_tokens(messages)
    
    def _on_calculate_cost(self, event: Event):
        tokens = self._on_get_current_context_tokens(event)
        cfg = getattr(self.model, "cfg", None)
        if not cfg:
            return 0.0

        try:
            return (float(tokens) / 1000.0) * float(cfg.token_cost_input)
        except Exception:
            return 0.0
    
    def _on_get_debug_info(self, event: Event):
        ch = self.character_manager.current_character
        if ch and hasattr(ch, 'current_variables_string'):
            return ch.current_variables_string()
        return "Debug info not available"
    
    # События игры
    def _on_set_game_data(self, event: Event):
        self.game_state.update_from_event_data(event.data or {})
    
    def _on_add_temporary_system_info(self, event: Event):
        content = (event.data or {}).get('content', '')
        if not content:
            return False
        self._temporary_system_infos.append({"role": "system", "content": str(content)})
        return True

    def _on_get_game_state(self, event: Event):
        return self.game_state.to_prompt_dict()
    
    # События генерации
    def _on_generate_response(self, event: Event):
        user_input = event.data.get('user_input', '') or ''
        system_input = event.data.get('system_input', '') or ''
        image_data = event.data.get('image_data', []) or []
        stream_callback = event.data.get('stream_callback', None)
        message_id = event.data.get('message_id', None)
        event_type = (event.data.get('event_type') or 'chat') or 'chat'
        preset_id_override = event.data.get('preset_id', None)

        # character override from upstream (server/game/react)
        character_override = (
            event.data.get('character')
            or event.data.get('character_id')
            or event.data.get('char_id')
        )

        # ----------------------------
        # helpers
        # ----------------------------
        def _is_current_label(label: str | None) -> bool:
            s = str(label or "").strip()
            return s in ("", "Current", "Текущий", _("Текущий", "Current"))

        def _resolve_label_to_preset_id(label: str | None) -> Optional[int]:
            if label is None:
                return None
            if _is_current_label(label):
                return None
            s = str(label).strip()
            try:
                return int(s)
            except ValueError:
                pass
            try:
                return self.preset_resolver.resolve_preset_id_by_name(s)
            except Exception:
                return None

        def _get_char_provider_label(char_id: str, char_name: str) -> str:
            # поддержка обоих вариантов ключа: id и name (на случай старых настроек)
            v = self.settings.get(f"CHAR_PROVIDER_{char_id}", None)
            if v is None and char_name:
                v = self.settings.get(f"CHAR_PROVIDER_{char_name}", None)
            return str(v if v is not None else "Current")

        # ----------------------------
        # choose character for this request
        # ----------------------------
        char = self.character_manager.current_character
        if character_override:
            try:
                cand = self.character_manager.get_character(str(character_override))
                if cand:
                    char = cand
                else:
                    logger.warning(f"Character override '{character_override}' not found, using current character.")
            except Exception as e:
                logger.warning(f"Character override failed: {e}")

        if not char:
            logger.error("Генерация невозможна: текущий персонаж не выбран.")
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                'error': _("Персонаж не выбран.", "Character not selected.")
            })
            return None

        char_id = getattr(char, 'char_id', '') or ''
        char_name = getattr(char, 'name', '') or ''

        # ----------------------------
        # compress branch
        # ----------------------------
        if event_type == 'compress':
            messages = []
            if system_input:
                messages.append({"role": "system", "content": system_input})

            preset_id = preset_id_override
            if preset_id is None:
                hc_provider = self.settings.get("HC_PROVIDER", "Current")
                preset_id = _resolve_label_to_preset_id(str(hc_provider))
                if preset_id is None and not _is_current_label(str(hc_provider)):
                    logger.warning(f"[compress] HC_PROVIDER='{hc_provider}' не найден, используем текущий пресет.")

            self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION)

            try:
                raw_text = self.model.generate(messages, stream_callback=None, preset_id=preset_id)
                return raw_text
            except Exception as e:
                logger.error(f"Ошибка при сжатии истории через GENERATE_RESPONSE: {e}", exc_info=True)
                return None

        # ----------------------------
        # collect game_state & temporary system infos (controller-side if present)
        # ----------------------------
        try:
            game_state = self.game_state.to_prompt_dict()  # if you moved it to controller
        except Exception:
            game_state = {
                'distance': getattr(self.model, "distance", 0.0),
                'roomPlayer': getattr(self.model, "roomPlayer", -1),
                'roomMita': getattr(self.model, "roomMita", -1),
                'nearObjects': getattr(self.model, "nearObjects", ''),
                'actualInfo': getattr(self.model, "actualInfo", ''),
            }

        # temporary infos queue: controller-first, fallback to model legacy field
        extra_system_infos = []
        if hasattr(self, "_temporary_system_infos"):
            extra_system_infos = list(self._temporary_system_infos or [])
            self._temporary_system_infos.clear()
        else:
            extra_system_infos = list(getattr(self.model, "infos_to_add_to_history", []) or [])
            if hasattr(self.model, "infos_to_add_to_history"):
                self.model.infos_to_add_to_history.clear()

        # cfg (если есть ModelRuntimeConfig), иначе fallback на старые поля модели
        cfg = getattr(self.model, "cfg", None)

        def _cfg_get(attr: str, default):
            if cfg is not None and hasattr(cfg, attr):
                return getattr(cfg, attr)
            return getattr(self.model, attr, default)

        screen_quality = self.settings.get("SCREEN_CAPTURE_QUALITY", 75)
        screen_quality = int(screen_quality) if str(screen_quality) != '' else 75

        image_quality_cfg = {
            'enabled': bool(_cfg_get("image_quality_reduction_enabled", False)),
            'start_index': int(_cfg_get("image_quality_reduction_start_index", 25)),
            'use_percentage': bool(_cfg_get("image_quality_reduction_use_percentage", False)),
            'min_quality': int(_cfg_get("image_quality_reduction_min_quality", 30)),
            'decrease_rate': int(_cfg_get("image_quality_reduction_decrease_rate", 5)),
            'screen_capture_quality': screen_quality,
        }

        separate_prompts = bool(self.settings.get("SEPARATE_PROMPTS", True))
        save_missed_history = bool(self.settings.get("SAVE_MISSED_HISTORY", True))
        memory_limit = int(_cfg_get("memory_limit", 40))

        is_game_master = bool(
            char == getattr(self.model, "GameMaster", None) or (getattr(char, "char_id", "") == "GameMaster")
        )

        # ----------------------------
        # build prompt for the chosen character
        # ----------------------------
        try:
            prompt_res = self.event_bus.emit_and_wait(
                Events.Prompt.BUILD_PROMPT,
                {
                    'character_id': char_id,
                    'event_type': event_type,
                    'user_input': user_input,
                    'system_input': system_input,
                    'image_data': image_data,
                    'memory_limit': memory_limit,
                    'is_game_master': is_game_master,
                    'save_missed_history': save_missed_history,
                    'image_quality': image_quality_cfg,
                    'separate_prompts': separate_prompts,
                    'extra_system_infos': extra_system_infos,
                    'game_state': game_state,
                },
                timeout=10.0
            )
        except Exception as e:
            logger.error(f"Ошибка при BUILD_PROMPT: {e}", exc_info=True)
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                'error': _("Не удалось сформировать промпт.", "Failed to build prompt.")
            })
            return None

        if not prompt_res or not isinstance(prompt_res[0], dict):
            logger.error("BUILD_PROMPT не вернул валидный результат")
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                'error': _("Не удалось сформировать промпт.", "Failed to build prompt.")
            })
            return None

        prompt_data = prompt_res[0]
        combined_messages = prompt_data.get("messages", []) or []
        history_for_save = prompt_data.get("history_messages", []) or []

        # ----------------------------
        # preset routing (react/char_provider)
        # ----------------------------
        preset_id: Optional[int] = None

        if event_type == 'react':
            react_provider_label = str(self.settings.get("REACT_PROVIDER", _("Текущий", "Current")))
            if not _is_current_label(react_provider_label):
                preset_id = _resolve_label_to_preset_id(react_provider_label)
                if preset_id is None:
                    logger.warning(f"REACT_PROVIDER '{react_provider_label}' не найден, используем CHAR_PROVIDER.")

            if preset_id is None:
                char_provider_label = _get_char_provider_label(char_id, char_name)
                preset_id = _resolve_label_to_preset_id(char_provider_label)

                if preset_id is not None:
                    logger.info(f"react: используем CHAR_PROVIDER preset ID: {preset_id}")
                elif not _is_current_label(char_provider_label):
                    logger.warning(f"react: CHAR_PROVIDER='{char_provider_label}' не найден, используем текущий пресет.")
        else:
            char_provider_label = _get_char_provider_label(char_id, char_name)
            preset_id = _resolve_label_to_preset_id(char_provider_label)

            if preset_id is not None:
                logger.info(f"chat: используем character-specific preset ID: {preset_id}")
            elif not _is_current_label(char_provider_label):
                logger.warning(f"chat: CHAR_PROVIDER='{char_provider_label}' не найден, используем текущий пресет.")

        self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION, {
            "character": getattr(char, "name", "") or getattr(char, "char_id", "") or "Мита",
            "char_id": getattr(char, "char_id", "") or ""
        })

        # ----------------------------
        # generate
        # ----------------------------
        try:
            use_stream_cb = stream_callback if event_type != 'react' else None
            raw_text = self.model.generate(
                combined_messages,
                stream_callback=use_stream_cb,
                preset_id=preset_id
            )

            if not raw_text:
                logger.warning("LLM generation failed or returned empty.")
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                    'error': _("Не удалось получить ответ.", "Text generation failed.")
                })
                return None

            # IMPORTANT: process response using the chosen character (not current_character)
            processed_response_text = char.process_response_nlp_commands(
                raw_text,
                self.settings.get("SAVE_MISSED_MEMORY", False)
            )

            final_response_text = processed_response_text

            # command replacer (как было)
            try:
                use_cmd_replacer = self.settings.get("USE_COMMAND_REPLACER", False)
                if use_cmd_replacer:
                    if not hasattr(self, 'model_handler'):
                        from handlers.embedding_handler import EmbeddingModelHandler
                        self.model_handler = EmbeddingModelHandler()
                    if not hasattr(self, 'parser'):
                        from utils.command_parser import CommandParser
                        self.parser = CommandParser(model_handler=self.model_handler)

                    final_response_text, __ = self.parser.parse_and_replace(
                        processed_response_text,
                        min_similarity_threshold=float(self.settings.get("MIN_SIMILARITY_THRESHOLD", 0.40)),
                        category_switch_threshold=float(self.settings.get("CATEGORY_SWITCH_THRESHOLD", 0.18)),
                        skip_comma_params=bool(self.settings.get("SKIP_COMMA_PARAMETERS", True))
                    )
            except Exception as ex:
                logger.error(f"Error during command replacement: {ex}", exc_info=True)

            assistant_message_content = final_response_text

            if bool(self.settings.get("REPLACE_IMAGES_WITH_PLACEHOLDERS", False)):
                assistant_message_content = re.sub(
                    r'https?://\S+\.(?:png|jpg|jpeg|gif|bmp)|data:image/\S+;base64,\S+',
                    '[Изображение]',
                    assistant_message_content
                )

            assistant_message = {"role": "assistant", "content": assistant_message_content}
            assistant_message["time"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

            # Save history only for non-react (react separated)
            if event_type != 'react':
                history_for_save.append(assistant_message)

                self.event_bus.emit(Events.History.SAVE_AFTER_RESPONSE, {
                    'character_id': char_id,
                    'messages': history_for_save
                })
            else:
                logger.info("[react] История не сохраняется (react branch separated).")

            self.event_bus.emit(Events.Model.ON_SUCCESSFUL_RESPONSE)
            return final_response_text

        except Exception as e:
            logger.error(f"Error during LLM response generation or processing: {e}", exc_info=True)
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {'error': str(e)})
            return f"Ошибка: {e}"


    def _on_raw_generate(self, event: Event):
        """
        Обрабатывает Events.LLM.RAW_GENERATE:
        data: {
            'messages': List[dict],
            'preset_id': Optional[int]
        }
        Возвращает tuple (response_text: str | None, success: bool)
        """
        messages = event.data.get('messages') or []
        preset_id = event.data.get('preset_id', None)

        if not hasattr(self.model, '_generate_chat_response'):
            return (None, False)

        try:
            response_text, success = self.model._generate_chat_response(
                combined_messages=messages,
                stream_callback=None,
                preset_id=preset_id
            )
            return (response_text, success)
        except Exception as e:
            logger.error(f"Ошибка в RAW_GENERATE: {e}", exc_info=True)
            return (None, False)
    
    def _on_reload_character_data(self, event: Event):
        if hasattr(self.model, 'current_character'):
            char = self.model.current_character
            if hasattr(char, 'reload_character_data'):
                char.reload_character_data()

    def _on_reload_prompts_async(self, event: Event):
        loop_res = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
        loop = loop_res[0] if loop_res else None
        
        logger.info("Запрос на асинхронное обновление промптов...")
        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
            'coroutine': self._async_reload_prompts(),
            'callback': None 
        })

    async def _async_reload_prompts(self):
        try:
            from utils.prompt_downloader import PromptDownloader
            import asyncio
            downloader = PromptDownloader()
            
            # Используем asyncio.get_event_loop() для получения текущего loop
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, downloader.download_and_replace_prompts)
            
            if success:
                if hasattr(self.model, 'current_character_to_change'):
                    character_name = self.model.current_character_to_change
                    character = self.model.characters.get(character_name)
                    if character:
                        await loop.run_in_executor(None, character.reload_prompts)
                    else:
                        logger.error("Персонаж для перезагрузки не найден")
                
                self.event_bus.emit("reload_prompts_success")
            else:
                self.event_bus.emit("reload_prompts_failed", {"error": "Download failed"})
        except Exception as e:
            logger.error(f"Ошибка при обновлении промптов: {e}")
            self.event_bus.emit("reload_prompts_failed", {"error": str(e)})

    def _get_character_provider_label(self, char_id: str) -> str:
        if not char_id:
            return "Current"
        key = f"CHAR_PROVIDER_{char_id}"
        return self.settings.get(key, "Current")
    
    def _cache_base_prompt(self, char_id: str, event_type: str, messages: list[dict]) -> None:
        """
        Кэшируем базовый промпт БЕЗ user-сообщения.
        Важно: копию, чтобы tool-рекурсия/провайдеры не мутировали кэш.
        """
        if not char_id:
            return
        if not isinstance(messages, list):
            return

        safe = copy.deepcopy(messages)

        # убираем последний user-message (PromptController всегда добавляет user chunk в конце)
        if safe and isinstance(safe[-1], dict) and safe[-1].get("role") == "user":
            safe = safe[:-1]

        self._base_prompt_cache[(char_id, event_type)] = safe

    def _is_current_provider_label(self, label: str) -> bool:
        s = str(label or "").strip()
        return s in ("", "Current", "Текущий", _("Текущий", "Current"))

    def _resolve_provider_label_to_preset_id(self, label: str | None) -> int | None:
        if label is None:
            return None
        if self._is_current_provider_label(label):
            return None

        s = str(label).strip()
        try:
            return int(s)
        except ValueError:
            pass

        pid = self.preset_resolver.resolve_preset_id_by_name(s)
        return pid