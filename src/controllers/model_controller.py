from handlers.chat_handler import ChatModel
from utils import _, process_text_to_voice
from core.events import get_event_bus, Events, Event
from main_logger import logger

# Контроллер для работы с моделью LLM

class ModelController:
    def __init__(self, settings, pip_installer):
        self.settings = settings
        self.event_bus = get_event_bus()

        self.lazy_load_batch_size = 50
        self.total_messages_in_history = 0
        self.loaded_messages_offset = 0
        self.loading_more_history = False

        # Исправленный вызов: теперь только 2 аргумента (settings, pip_installer)
        self.model = ChatModel(settings, pip_installer)
        self._subscribe_to_events()
        
    def _subscribe_to_events(self):
        # Существующие события
        self.event_bus.subscribe("model_settings_loaded", self._on_model_settings_loaded, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)
        
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
        elif key == "MODEL_MAX_RESPONSE_TOKENS":
            self.model.max_response_tokens = int(value)
        elif key == "MODEL_TEMPERATURE":
            self.model.temperature = float(value)
        elif key == "MODEL_PRESENCE_PENALTY":
            self.model.presence_penalty = float(value)
        elif key == "MODEL_FREQUENCY_PENALTY":
            self.model.frequency_penalty = float(value)
        elif key == "MODEL_LOG_PROBABILITY":
            self.model.log_probability = float(value)
        elif key == "MODEL_TOP_K":
            self.model.top_k = int(value)
        elif key == "MODEL_TOP_P":
            self.model.top_p = float(value)
        elif key == "MODEL_THOUGHT_PROCESS":
            self.model.thinking_budget = float(value)
        elif key == "MODEL_MESSAGE_LIMIT":
            self.model.memory_limit = int(value)
        elif key == "MODEL_MESSAGE_ATTEMPTS_COUNT":
            self.model.max_request_attempts = int(value)
        elif key == "MODEL_MESSAGE_ATTEMPTS_TIME":
            self.model.request_delay = float(value)
        elif key == "IMAGE_QUALITY_REDUCTION_ENABLED":
            self.model.image_quality_reduction_enabled = bool(value)
        elif key == "IMAGE_QUALITY_REDUCTION_START_INDEX":
            self.model.image_quality_reduction_start_index = int(value)
        elif key == "IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE":
            self.model.image_quality_reduction_use_percentage = bool(value)
        elif key == "IMAGE_QUALITY_REDUCTION_MIN_QUALITY":
            self.model.image_quality_reduction_min_quality = int(value)
        elif key == "IMAGE_QUALITY_REDUCTION_DECREASE_RATE":
            self.model.image_quality_reduction_decrease_rate = int(value)
        elif key == "ENABLE_HISTORY_COMPRESSION_ON_LIMIT":
            self.model.enable_history_compression_on_limit = bool(value)
        elif key == "ENABLE_HISTORY_COMPRESSION_PERIODIC":
            self.model.enable_history_compression_periodic = bool(value)
        elif key == "HISTORY_COMPRESSION_OUTPUT_TARGET":
            self.model.history_compression_output_target = str(value)
        elif key == "HISTORY_COMPRESSION_PERIODIC_INTERVAL":
            self.model.history_compression_periodic_interval = int(value)
        elif key == "HISTORY_COMPRESSION_MIN_PERCENT_TO_COMPRESS":
            self.model.history_compression_min_messages_to_compress = float(value)
        elif key == "TOKEN_COST_INPUT":
            self.model.token_cost_input = float(value)
        elif key == "TOKEN_COST_OUTPUT":
            self.model.token_cost_output = float(value)
        elif key == "MAX_MODEL_TOKENS":
            self.model.max_model_tokens = int(value)
                
    def change_character(self, character):
        if character:
            self.model.current_character_to_change = character
            self.model.check_change_current_character()
    
    # События персонажей
    def _on_get_all_characters(self, event: Event):
        if hasattr(self.model, 'get_all_mitas'):
            return self.model.get_all_mitas()
        return []
    
    def _on_get_current_character(self, event: Event):
        if hasattr(self.model, 'current_character'):
            char = self.model.current_character
            return {
                'name': char.name if hasattr(char, 'name') else '',
                'char_id': char.char_id if hasattr(char, 'char_id') else '',
                'is_cartridge': char.is_cartridge if hasattr(char, 'is_cartridge') else False,
                'silero_command': getattr(char, 'silero_command', ''),
                'short_name': getattr(char, 'short_name', ''),
                'miku_tts_name': getattr(char, 'miku_tts_name', 'Player'),
                'silero_turn_off_video': getattr(char, 'silero_turn_off_video', False),
            }
        return None
    
    def _on_set_character_to_change(self, event: Event):
        character_name = event.data.get('character')
        if character_name and hasattr(self.model, 'current_character_to_change'):
            self.model.current_character_to_change = character_name
    
    def _on_check_change_character(self, event: Event):
        if hasattr(self.model, 'check_change_current_character'):
            self.model.check_change_current_character()
    
    def _on_get_character(self, event: Event):
        character_name = event.data.get('name')
        if character_name and hasattr(self.model, 'characters'):
            return self.model.characters.get(character_name)
        return None
    
    def _on_reload_character_data(self, event: Event):
        if hasattr(self.model, 'current_character'):
            char = self.model.current_character
            if hasattr(char, 'reload_character_data'):
                char.reload_character_data()
    
    def _on_reload_character_prompts(self, event: Event):
        character_name = event.data.get('character')
        if character_name and hasattr(self.model, 'characters'):
            char = self.model.characters.get(character_name)
            if char and hasattr(char, 'reload_prompts'):
                char.reload_prompts()
    
    def _on_clear_character_history(self, event: Event):
        if hasattr(self.model, 'current_character'):
            char = self.model.current_character
            if hasattr(char, 'clear_history'):
                char.clear_history()
    
    def _on_clear_all_histories(self, event: Event):
        if hasattr(self.model, 'characters'):
            for character in self.model.characters.values():
                if hasattr(character, 'clear_history'):
                    character.clear_history()
    
    # События истории
    def _on_load_history(self, event: Event):
        self.loaded_messages_offset = 0
        self.total_messages_in_history = 0
        self.loading_more_history = False
        
        chat_history = self.model.current_character.load_history()
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
            chat_history = self.model.current_character.load_history()
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
    
    # События информации
    def _on_get_character_name(self, event: Event):
        return self.model.current_character.name
    
    def _on_get_current_context_tokens(self, event: Event):
        if hasattr(self.model, 'get_current_context_token_count'):
            return self.model.get_current_context_token_count()
        return 0
    
    def _on_calculate_cost(self, event: Event):
        self.model.token_cost_input = float(self.settings.get("TOKEN_COST_INPUT", 0.000001))
        self.model.token_cost_output = float(self.settings.get("TOKEN_COST_OUTPUT", 0.000002))
        self.model.max_model_tokens = int(self.settings.get("MAX_MODEL_TOKENS", 32000))
        
        if hasattr(self.model, 'calculate_cost_for_current_context'):
            return self.model.calculate_cost_for_current_context()
        return 0.0
    
    def _on_get_debug_info(self, event: Event):
        if hasattr(self.model, 'current_character'):
            char = self.model.current_character
            if hasattr(char, 'current_variables_string'):
                return char.current_variables_string()
        return "Debug info not available"
    
    # События игры
    def _on_set_game_data(self, event: Event):
        self.model.distance = event.data.get('distance', 0.0)
        self.model.roomPlayer = event.data.get('roomPlayer', -1)
        self.model.roomMita = event.data.get('roomMita', -1)
        self.model.nearObjects = event.data.get('nearObjects', '')
        self.model.actualInfo = event.data.get('actualInfo', '')
    
    def _on_add_temporary_system_info(self, event: Event):
        content = event.data.get('content', '')
        if content and hasattr(self.model, 'add_temporary_system_info'):
            self.model.add_temporary_system_info(content)
    
    # События генерации
    def _on_generate_response(self, event: Event):
        user_input = event.data.get('user_input', '')
        system_input = event.data.get('system_input', '')
        image_data = event.data.get('image_data', [])
        stream_callback = event.data.get('stream_callback', None)
        message_id = event.data.get('message_id', None)
        event_type = event.data.get('event_type', None)

        if event_type == 'react' and hasattr(self.model, 'generate_react'):
            return self.model.generate_react(user_input, system_input, image_data, stream_callback, message_id)

        if hasattr(self.model, 'generate_response'):
            return self.model.generate_response(user_input, system_input, image_data, stream_callback, message_id)
        return None
    
    def _on_reload_prompts_async(self, event: Event):
        # Получаем главный asyncio-loop через событие
        loop_res = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
        loop = loop_res[0] if loop_res else None
        
        logger.info("Запрос на асинхронное обновление промптов...")
        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
            'coroutine': self._async_reload_prompts(),
            'callback': None  # Можно добавить callback для обработки результата, если нужно
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