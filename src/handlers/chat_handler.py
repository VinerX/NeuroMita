# File: chat_handler.py
import base64
import concurrent.futures
import datetime
import json
import time
#import tiktoken
import os
import re
import importlib
from typing import List, Dict, Any, Optional
from io import BytesIO # Добавлено для обработки изображений
from tools.manager import ToolManager,mk_tool_call_msg,mk_tool_resp_msg
from main_logger import logger

from characters.character import Character
from utils.pip_installer import PipInstaller

from utils import SH, save_combined_messages # Keep utils
from utils import _ as translate

from core.events import get_event_bus, Events

class ChatModel:
    def __init__(self, settings, pip_installer: PipInstaller):
        self.last_key = 0
        self.pip_installer = pip_installer
        self.g4fClient = None
        self.g4f_available = False
        self.settings = settings
        self.event_bus = get_event_bus()

        preset_settings = self.load_preset_settings()
        logger.info(f"Initializing ChatModel with preset: {preset_settings['preset_name']}")

        self.api_model = preset_settings['api_model']
        self.gpt4free_model = preset_settings['g4f_model'] if preset_settings['is_g4f'] else self.settings.get("gpt4free_model", "")

        self._initialize_g4f()

        self.tool_manager = ToolManager()

        try:
            import tiktoken
            self.tokenizer = tiktoken.encoding_for_model("gpt-4o-mini")
            self.hasTokenizer = True
            logger.info("Tiktoken успешно инициализирован.")
        except ImportError:
            logger.warning("Модуль 'tiktoken' не найден. Подсчет токенов будет недоступен.")
            self.hasTokenizer = False
        except Exception as e:
            logger.error(f"Ошибка инициализации tiktoken: {e}")
            self.hasTokenizer = False

        self.max_response_tokens = int(self.settings.get("MODEL_MAX_RESPONSE_TOKENS", 3200))
        self.temperature = float(self.settings.get("MODEL_TEMPERATURE", 0.5))
        self.presence_penalty = float(self.settings.get("MODEL_PRESENCE_PENALTY", 0.0))
        self.top_k = int(self.settings.get("MODEL_TOP_K", 0))
        self.top_p = float(self.settings.get("MODEL_TOP_P", 1.0))
        self.thinking_budget = float(self.settings.get("MODEL_THINKING_BUDGET", 0.0))
        self.presence_penalty = float(self.settings.get("MODEL_PRESENCE_PENALTY", 0.0))
        self.frequency_penalty = float(self.settings.get("MODEL_FREQUENCY_PENALTY", 0.0))
        self.log_probability = float(self.settings.get("MODEL_LOG_PROBABILITY", 0.0))

        self.token_cost_input = float(self.settings.get("TOKEN_COST_INPUT", 0.0432))
        self.token_cost_output = float(self.settings.get("TOKEN_COST_OUTPUT", 0.1728))
        self.max_model_tokens = int(self.settings.get("MAX_MODEL_TOKENS", 128000))

        self.memory_limit = int(self.settings.get("MODEL_MESSAGE_LIMIT", 40))

        self.enable_history_compression_on_limit = bool(self.settings.get("ENABLE_HISTORY_COMPRESSION_ON_LIMIT", False))
        self.enable_history_compression_periodic = bool(self.settings.get("ENABLE_HISTORY_COMPRESSION_PERIODIC", False))
        self.history_compression_periodic_interval = int(self.settings.get("HISTORY_COMPRESSION_PERIODIC_INTERVAL", 20))
        self.history_compression_prompt_template = str(self.settings.get("HISTORY_COMPRESSION_PROMPT_TEMPLATE", "Prompts/System/compression_prompt.txt"))
        self.history_compression_output_target = str(self.settings.get("HISTORY_COMPRESSION_OUTPUT_TARGET", "memory"))

        self._messages_since_last_periodic_compression = 0

        self.current_character: Character = None
        self.GameMaster: Character = None
        self.characters = {}  # optional alias для legacy

        # Настройки для снижения качества изображений в истории (используются выше по цепочке при сборке промпта)
        self.image_quality_reduction_enabled = bool(self.settings.get("IMAGE_QUALITY_REDUCTION_ENABLED", False))
        self.image_quality_reduction_start_index = int(self.settings.get("IMAGE_QUALITY_REDUCTION_START_INDEX", 25))
        self.image_quality_reduction_use_percentage = bool(self.settings.get("IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE", False))
        min_quolity = self.settings.get("IMAGE_QUALITY_REDUCTION_MIN_QUALITY", 30)
        self.image_quality_reduction_min_quality = int(min_quolity) if min_quolity != '' else 30
        self.image_quality_reduction_decrease_rate = int(self.settings.get("IMAGE_QUALITY_REDUCTION_DECREASE_RATE", 5))

        # Game-specific state (пока оставляем, как договорились — перенос потом)
        self.distance = 0.0
        self.roomPlayer = -1
        self.roomMita = -1
        self.nearObjects = ""
        self.actualInfo = ""

        self.infos_to_add_to_history: List[Dict] = []

        # Mapping of model names to their token limits
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
        self.max_request_attempts = int(self.settings.get("MODEL_MESSAGE_ATTEMPTS_COUNT", 5))
        self.request_delay = float(self.settings.get("MODEL_MESSAGE_ATTEMPTS_TIME", 0.20))

    def load_preset_settings(self, preset_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Загружает настройки из пресета по ID.
        Если preset_id не указан, берёт текущий из LAST_API_PRESET_ID.
        """
        if preset_id is None:
            preset_id = self.settings.get("LAST_API_PRESET_ID", 0)
            logger.info(f"Loading current preset ID: {preset_id}")
        else:
            logger.info(f"Loading specific preset ID: {preset_id}")
        
        preset_data = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_FULL, {'id': preset_id}, timeout=1.0)
        if preset_data and preset_data[0]:
            preset = preset_data[0]
            logger.info(f"Preset {preset_id} loaded successfully: {preset.get('name', 'Unknown')}")
            
            url = preset.get('url', '')
            if preset.get('url_tpl'):
                model = preset.get('default_model', '')
                url = preset['url_tpl'].format(model=model) if '{model}' in preset['url_tpl'] else preset['url_tpl']
                if preset.get('add_key') and preset.get('key'):
                    sep = '&' if '?' in url else '?'
                    url = f"{url}{sep}key={preset['key']}"

            # ВАЖНО: если gemini_case в шаблоне настраиваемый (None), берём фактическое значение из state
            effective_gemini = preset.get('gemini_case', False)
            if preset.get('gemini_case') is None:
                state = self.event_bus.emit_and_wait(Events.ApiPresets.LOAD_PRESET_STATE, {'id': preset_id}, timeout=1.0)
                if state and state[0]:
                    effective_gemini = bool(state[0].get('gemini_case', False))

            return {
                'api_key': preset.get('key', ''),
                'api_url': url,
                'api_model': preset.get('default_model', ''),
                'make_request': preset.get('use_request', False),
                'gemini_case': effective_gemini,
                'is_g4f': preset.get('is_g4f', False),
                'g4f_model': preset.get('default_model', '') if preset.get('is_g4f') else '',
                'preset_name': preset.get('name', 'Unknown'),
                'reserve_keys': preset.get('reserve_keys', []),
            }
        else:
            logger.error(f"Failed to load preset ID {preset_id}: using fallback from settings")
            # Для обратной совместимости берем резервные ключи из settings
            reserve_keys_str = self.settings.get("NM_API_KEY_RES", "")
            reserve_keys = [key.strip() for key in reserve_keys_str.split() if key.strip()] if reserve_keys_str else []
            
            return {
                'api_key': self.settings.get("NM_API_KEY", ""),
                'api_url': self.settings.get("NM_API_URL", ""),
                'api_model': self.settings.get("NM_API_MODEL", ""),
                'make_request': self.settings.get("NM_API_REQ", False),
                'gemini_case': self.settings.get("GEMINI_CASE", False),
                'is_g4f': self.settings.get("gpt4free", False),
                'g4f_model': self.settings.get("gpt4free_model", ""),
                'preset_name': 'Fallback',
                'reserve_keys': reserve_keys,
            }


    def _initialize_g4f(self):
        logger.info("Проверка и инициализация g4f (после возможного обновления при запуске)...")
        try:
            from g4f.client import Client as g4fClient
            logger.info("g4f найден (при проверке), попытка инициализации клиента...")
            try:
                self.g4fClient = g4fClient()
                self.g4f_available = True
                logger.info("g4fClient успешно инициализирован.")
            except Exception as e:
                logger.error(f"Ошибка при инициализации g4fClient: {e}")
                self.g4fClient = None
                self.g4f_available = False
        except ImportError:
            logger.info("Модуль g4f не найден (при проверке). Попытка первоначальной установки...")

            target_version = self.settings.get("G4F_VERSION", "0.4.7.7")  # Using "0.x.y.z" format
            package_spec = f"g4f=={target_version}" if target_version != "latest" else "g4f"

            if self.pip_installer:
                success = self.pip_installer.install_package(
                    package_spec,
                    description=f"Первоначальная установка g4f версии {target_version}..."
                )
                if success:
                    logger.success("Первоначальная установка g4f (файлы) прошла успешно. Очистка кэша импорта...")
                    try:
                        importlib.invalidate_caches()
                        logger.info("Кэш импорта очищен.")
                    except Exception as e_invalidate:
                        logger.error(f"Ошибка при очистке кэша импорта: {e_invalidate}")

                    logger.info("Повторная попытка импорта и инициализации...")
                    try:
                        from g4f.client import Client as g4fClient  # Re-import
                        logger.info("Повторный импорт g4f успешен. Попытка инициализации клиента...")
                        try:
                            self.g4fClient = g4fClient()
                            self.g4f_available = True
                            logger.info("g4fClient успешно инициализирован после установки.")
                        except Exception as e_init_after_install:  # More specific exception name
                            logger.error(f"Ошибка при инициализации g4fClient после установки: {e_init_after_install}")
                            self.g4fClient = None
                            self.g4f_available = False
                    except ImportError:
                        logger.error("Не удалось импортировать g4f даже после успешной установки и очистки кэша.")
                        self.g4fClient = None
                        self.g4f_available = False
                    except Exception as e_import_after:
                        logger.error(f"Непредвиденная ошибка при повторном импорте/инициализации g4f: {e_import_after}")
                        self.g4fClient = None
                        self.g4f_available = False
                else:
                    logger.error("Первоначальная установка g4f не удалась (ошибка pip).")
                    self.g4fClient = None
                    self.g4f_available = False
            else:
                logger.error("Экземпляр PipInstaller не передан в ChatModel, установка g4f невозможна.")
                self.g4fClient = None
                self.g4f_available = False
        except Exception as e_initial:
            logger.error(f"Непредвиденная ошибка при первичной инициализации g4f: {e_initial}")
            self.g4fClient = None
            self.g4f_available = False
    
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
        max_attempts = self.max_request_attempts
        retry_delay = self.request_delay
        request_timeout = 45

        self._log_generation_start(preset_id)

        self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION)

        tools_on = self.settings.get("TOOLS_ON", True)
        tools_mode = self.settings.get("TOOLS_MODE", "native")

        if tools_mode == "off":
            tools_on = False

        if tools_on and tools_mode == "legacy":
            tools_desc = json.dumps(self.tool_manager.json_schema())
            legacy_prompt = self.tool_manager.tools_prompt().format(tools_json=tools_desc)
            combined_messages.insert(0, {"role": "system", "content": legacy_prompt})

        for attempt in range(1, max_attempts + 1):
            logger.info(f"Generation attempt {attempt}/{max_attempts}")
            
            response_text = None

            save_combined_messages(combined_messages, "SavedMessages/last_attempt_log")

            try:
                logger.info("Generating response...")
                
                from managers.provider_manager import ProviderManager
                from handlers.llm_providers.base import LLMRequest
                
                # Подгружаем пресет для текущей попытки
                preset_settings = self.load_preset_settings(preset_id)
                
                # Обработка резервных ключей из пресета
                current_api_key = preset_settings['api_key']
                reserve_keys = preset_settings.get('reserve_keys', [])
                
                if attempt > 1 and reserve_keys:
                    new_key = self.GetReserveKey(current_api_key, reserve_keys, attempt - 1)
                    if new_key and new_key != current_api_key:
                        logger.info(f"Attempt {attempt}: switching to reserve key (masked): {SH(new_key)}")
                        preset_settings['api_key'] = new_key
                        # Обновляем URL если нужно (для Gemini с ?key=)
                        if preset_settings['make_request'] and "key=" in preset_settings['api_url']:
                            preset_settings['api_url'] = re.sub(r"key=[^&]*", f"key={new_key}", preset_settings['api_url'])
                
                effective_model = preset_settings['api_model']
                use_gpt4free_for_this_attempt = preset_settings['is_g4f'] or \
                                            (bool(self.settings.get("GPT4FREE_LAST_ATTEMPT")) and attempt >= max_attempts)
                
                if use_gpt4free_for_this_attempt:
                    effective_model = preset_settings['g4f_model'] or self.gpt4free_model
                    logger.info(f"Using g4f for attempt {attempt} with model: {effective_model}")
                
                params = self.get_params(effective_model)
                
                tools_payload = None
                if tools_on and tools_mode == "native":
                    if preset_settings['make_request'] and preset_settings['gemini_case']:
                        tools_payload = self.tool_manager.get_tools_payload("gemini")
                    elif preset_settings['make_request']:
                        tools_payload = self.tool_manager.get_tools_payload("deepseek")
                    else:
                        tools_payload = self.tool_manager.get_tools_payload("openai")
                
                # Передаем сообщения как есть - форматирование происходит в provider
                req = LLMRequest(
                    model=effective_model,
                    messages=combined_messages,
                    api_key=preset_settings['api_key'],
                    api_url=preset_settings['api_url'],
                    make_request=preset_settings['make_request'],
                    gemini_case=preset_settings['gemini_case'],
                    g4f_flag=use_gpt4free_for_this_attempt,
                    g4f_model=preset_settings['g4f_model'],
                    stream=bool(self.settings.get("ENABLE_STREAMING", False)) and stream_callback is not None,
                    stream_cb=stream_callback,
                    tools_on=tools_on,
                    tools_mode=tools_mode,
                    tools_payload=tools_payload,
                    extra=params,
                    tool_manager=self.tool_manager
                )
                
                logger.notify(f"req: {json.dumps(preset_settings)}")
                
                req.extra['tool_manager'] = self.tool_manager
                
                logger.info(f"Request configured: provider={preset_settings['preset_name']}, model={effective_model}, stream={req.stream}")
                
                pm = ProviderManager()
                response_text = self._execute_with_timeout(
                    pm.generate,
                    args=(req,),
                    timeout=request_timeout
                )

                if response_text and tools_on and tools_mode == "legacy":
                    response_text = self._handle_legacy_tool_calls(response_text, combined_messages, stream_callback)

                if response_text:
                    cleaned_response = self._clean_response(response_text)
                    logger.info(f"Successful response received (attempt {attempt}).")
                    if cleaned_response:
                        return cleaned_response, True
                    else:
                        logger.warning("Response became empty after cleaning.")
                else:
                    logger.warning(f"Attempt {attempt} yielded no response or an error handled within generation.")

            except concurrent.futures.TimeoutError:
                logger.error(f"Attempt {attempt} timed out after {request_timeout}s.")
            except Exception as e:
                logger.error(f"Error during generation attempt {attempt}: {str(e)}", exc_info=True)

            if attempt < max_attempts:
                logger.info(f"Waiting {retry_delay}s before next attempt...")
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                time.sleep(retry_delay)

        logger.error("All generation attempts failed.")
        return None, False

    def _execute_with_timeout(self, func, args=(), kwargs={}, timeout=30):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                logger.error(f"Function {func.__name__} timed out after {timeout} seconds.")
                raise
            except Exception as e:
                logger.error(f"Exception in function {func.__name__} executed with timeout: {e}")
                raise

    def GetReserveKey(self, current_key: str, reserve_keys: List[str], attempt_index: int) -> str | None:
        """
        Получает резервный ключ из списка.
        current_key - текущий ключ из пресета
        reserve_keys - список резервных ключей из пресета
        attempt_index - индекс попытки (0-based)
        """
        all_keys = []
        if current_key:
            all_keys.append(current_key)
        
        # Добавляем резервные ключи из пресета
        if reserve_keys:
            all_keys.extend(reserve_keys)

        seen = set()
        unique_keys = [x for x in all_keys if not (x in seen or seen.add(x))]

        if not unique_keys:
            logger.error("No API keys available")
            return None

        if len(unique_keys) == 1:
            return unique_keys[0]
        
        # Циклический перебор ключей
        key_index = attempt_index % len(unique_keys)
        selected_key = unique_keys[key_index]

        logger.info(
            f"Selected API key index: {key_index} (masked: {SH(selected_key)}) from {len(unique_keys)} unique keys.")
        return selected_key


    def _log_generation_start(self, preset_id: Optional[int] = None):
        logger.info("Preparing to generate LLM response.")
        preset_settings = self.load_preset_settings(preset_id)
        logger.info(f"Using preset: {preset_settings['preset_name']}")
        logger.info(f"Max Response Tokens: {self.max_response_tokens}, Temperature: {self.temperature}")
        logger.info(
            f"Presence Penalty: {self.presence_penalty} (Used: {bool(self.settings.get('USE_MODEL_PRESENCE_PENALTY'))})")
        logger.info(f"API URL: {preset_settings['api_url']}, API Model: {preset_settings['api_model']}")
        logger.info(f"g4f Enabled: {preset_settings['is_g4f']}, g4f Model: {preset_settings.get('g4f_model', 'N/A')}")
        logger.info(f"Custom Request: {preset_settings['make_request']}")
        if preset_settings['make_request']:
            logger.info(f"  Gemini Case: {preset_settings['gemini_case']}")

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


    def _get_provider_key(self, model_name: str) -> str:
        if not model_name: return 'openai'
        model_name_lower = model_name.lower()
        if 'gpt-4' in model_name_lower or 'gpt-3.5' in model_name_lower: return 'openai'
        if 'gemini' in model_name_lower or 'gemma' in model_name_lower: return 'gemini'
        if 'claude' in model_name_lower: return 'anthropic'
        if 'deepseek' in model_name_lower: return 'deepseek'
        logger.info(f"Unknown provider for model '{model_name}', defaulting to 'openai' parameter naming conventions.")
        return 'openai'

    def reload_promts(self):
        logger.info("Reloading current character data.")
        if self.current_character:
            self.current_character.reload_character_data()
            logger.info(f"Character {self.current_character.name} data reloaded.")
        else:
            logger.warning("No current character selected to reload.")

    def add_temporary_system_info(self, content: str):
        system_info_message = {"role": "system", "content": content}
        self.infos_to_add_to_history.append(system_info_message)
        logger.info(f"Queued temporary system info: {content[:100]}...")

    # region TokensCounting
    def get_max_model_tokens(self) -> int:
        """
        Возвращает максимальное количество токенов для текущей активной модели.
        """
        # Берем модель из текущего пресета
        preset_settings = self.load_preset_settings()
        current_model = preset_settings['api_model']
        
        if preset_settings['is_g4f']:
            current_model = preset_settings.get('g4f_model', '') or self.gpt4free_model

        # Возвращаем лимит из настроек, если он задан и больше 0, иначе из маппинга
        if self.max_model_tokens > 0:
             return self.max_model_tokens
        return self._model_token_limits.get(current_model, 128000)

    
    def get_current_context_token_count(self) -> int:
        if not self.hasTokenizer:
            return 0

        if not self.current_character:
            return 0

        # Текущий ввод пользователя (как и раньше)
        user_input = self.event_bus.emit_and_wait(Events.Speech.GET_USER_INPUT)
        user_input_from_gui = user_input[0] if user_input else ""

        # Конфиг качества изображений — чтобы PromptController/HistoryController собрали тот же контекст,
        # что и реальная генерация (но без compression).
        screen_quality = self.settings.get("SCREEN_CAPTURE_QUALITY", 75)
        screen_quality = int(screen_quality) if str(screen_quality) != '' else 75

        image_quality_cfg = {
            'enabled': bool(self.settings.get("IMAGE_QUALITY_REDUCTION_ENABLED", False)),
            'start_index': int(self.settings.get("IMAGE_QUALITY_REDUCTION_START_INDEX", 25)),
            'use_percentage': bool(self.settings.get("IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE", False)),
            'min_quality': int(self.settings.get("IMAGE_QUALITY_REDUCTION_MIN_QUALITY", 30) or 30),
            'decrease_rate': int(self.settings.get("IMAGE_QUALITY_REDUCTION_DECREASE_RATE", 5)),
            'screen_capture_quality': screen_quality,
        }

        separate_prompts = bool(self.settings.get("SEPARATE_PROMPTS", True))
        is_game_master = (self.current_character == getattr(self, "GameMaster", None))

        # Важно: не сохраняем missed history и не запускаем compression (это только для токенкаунта)
        try:
            prompt_res = self.event_bus.emit_and_wait(
                Events.Prompt.BUILD_PROMPT,
                {
                    'character_id': getattr(self.current_character, "char_id", ""),
                    'event_type': 'chat',
                    'user_input': user_input_from_gui,
                    'system_input': '',
                    'image_data': [],
                    'memory_limit': int(self.memory_limit),
                    'is_game_master': bool(is_game_master),
                    'save_missed_history': False,
                    'image_quality': image_quality_cfg,
                    'separate_prompts': separate_prompts,
                    'extra_system_infos': list(self.infos_to_add_to_history) if self.infos_to_add_to_history else [],
                    'game_state': {
                        'distance': float(getattr(self, "distance", 0.0)),
                        'roomPlayer': int(getattr(self, "roomPlayer", -1)),
                        'roomMita': int(getattr(self, "roomMita", -1)),
                        'nearObjects': str(getattr(self, "nearObjects", "")),
                        'actualInfo': str(getattr(self, "actualInfo", "")),
                    },
                    'disable_history_compression': True,
                },
                timeout=2.0
            )
        except Exception:
            return 0

        if not prompt_res or not isinstance(prompt_res[0], dict):
            return 0

        combined_messages: List[Dict[str, Any]] = prompt_res[0].get("messages", []) or []

        total_tokens = 0
        for msg in combined_messages:
            if not isinstance(msg, dict) or "content" not in msg:
                continue

            content = msg["content"]

            if isinstance(content, str):
                total_tokens += len(self.tokenizer.encode(content))
                continue

            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "text" and item.get("text"):
                        total_tokens += len(self.tokenizer.encode(item["text"]))
                    elif item.get("type") == "image_url" and item.get("image_url", {}).get("url"):
                        # как и раньше: грубая оценка “картинка ~1000 токенов”
                        total_tokens += 1000

        return total_tokens

    def calculate_cost_for_current_context(self) -> float:
        """
        Рассчитывает ориентировочную стоимость текущего контекста в токенах.
        """
        if not self.hasTokenizer:
            logger.warning("Tokenizer not available, cannot calculate cost accurately.")
            return 0.0

        token_count = self.get_current_context_token_count()
        # Используем стоимость из настроек
        cost = (token_count / 1000) * self.token_cost_input
        return cost

    #endregion

    def get_room_name(self, room_id):  # This seems generally useful, kept.
        room_names = {
            0: "Кухня",
            1: "Зал",
            2: "Комната",
            3: "Туалет",
            4: "Подвал"
        }
        return room_names.get(room_id, "?")

    def add_temporary_system_message(self, messages: List[Dict], content: str):
        if not isinstance(messages, list):
            logger.error("add_temporary_system_message ожидает список сообщений.")
            return
        system_message = {
            "role": "system",
            "content": content
        }
        messages.append(system_message)
        logger.debug(f"Временно добавлено системное сообщение в переданный список: {content[:100]}...")

    def get_params(self, model=None):
        current_model = model if model is not None else self.api_model
        provider_key = self._get_provider_key(current_model)

        params = {}

        # Температура часто называется одинаково
        if self.temperature is not None:
            params['temperature'] = self.temperature

        # Макс. токены - названия могут различаться
        if bool(self.settings.get("USE_MODEL_MAX_RESPONSE_TOKENS")) and self.max_response_tokens is not None:
            if provider_key == 'openai' or provider_key == 'deepseek' or provider_key == 'anthropic':
                params['max_tokens'] = self.max_response_tokens
            elif provider_key == 'gemini':
                params['maxOutputTokens'] = self.max_response_tokens
            # Добавьте другие провайдеры

        # Штраф за присутствие - названия могут различаться, и параметр может отсутствовать у некоторых провайдеров
        if bool(self.settings.get("USE_MODEL_PRESENCE_PENALTY")) and self.presence_penalty is not None:
            if provider_key == 'openai' or provider_key == 'deepseek':
                params['presence_penalty'] = self.presence_penalty
            elif provider_key == 'gemini':
                params['presencePenalty'] = self.presence_penalty

        if bool(self.settings.get("USE_MODEL_FREQUENCY_PENALTY")) and self.frequency_penalty is not None:
            if provider_key == 'openai' or provider_key == 'deepseek':
                params['frequency_penalty'] = self.frequency_penalty
            elif provider_key == 'gemini':
                params['frequencyPenalty'] = self.frequency_penalty

        if bool(self.settings.get("USE_MODEL_LOG_PROBABILITY")) and self.log_probability is not None:
            if provider_key == 'openai' or provider_key == 'deepseek':
                params['logprobs'] = self.log_probability  # OpenAI/DeepSeek
            # Gemini не имеет прямого аналога logprobs в том же виде

        # Добавляем top_k, top_p и thought_process, если они заданы
        if bool(self.settings.get("USE_MODEL_TOP_K")) and self.top_k > 0:
            if provider_key == 'openai' or provider_key == 'deepseek' or provider_key == 'anthropic':
                params['top_k'] = self.top_k
            elif provider_key == 'gemini':
                params['topK'] = self.top_k

        if bool(self.settings.get("USE_MODEL_TOP_P")):
            if provider_key == 'openai' or provider_key == 'deepseek' or provider_key == 'anthropic':
                params['top_p'] = self.top_p
            elif provider_key == 'gemini':
                params['topP'] = self.top_p

        if bool(self.settings.get("USE_MODEL_THINKING_BUDGET")):
            params['thinking_budget'] = self.thinking_budget
            # Anthropic, например, не имеет прямого аналога этого параметра в том же виде.
            # Поэтому мы просто не добавляем его для Anthropic.

        # Добавьте другие параметры аналогично
        # if self.some_other_param is not None:
        #     if provider_key == 'openai': params['openai_name'] = self.some_other_param
        #     elif provider_key == 'gemini': params['gemini_name'] = self.some_other_param
        #     # и т.д.

        params = self.remove_unsupported_params(current_model, params)

        return params

    def clear_endline_sim(self, params):
        for key, value in params.items():
            if isinstance(value, str):
                params[key] = value.replace("'\x00", "").replace("\x00", "")

    def remove_unsupported_params(self, model, params):
        """Тут удаляем все лишние параметры"""
        if model in ("gemini-2.5-pro-exp-03-25", "gemini-2.5-flash-preview-04-17"):
            params.pop("presencePenalty", None)
        return params


    def _handle_legacy_tool_calls(self, response_text: str, messages: List[Dict], stream_callback,
                                  _depth: int = 0) -> str:
        if _depth > 3:
            logger.error("Слишком много рекурсивных legacy tool-вызовов.")
            return response_text

        parse_regex = self.settings.get("LEGACY_TOOLS_PARSE_REGEX",
                                                   r'\{.*?"tool":\s*"(.*?)",\s*"args":\s*(\{.*?\})\}')
        matches = re.findall(parse_regex, response_text)

        if not matches:
            return response_text  # Нет вызовов — возвращаем как есть

        for tool_name, args_str in matches:
            try:
                args = json.loads(args_str)
                logger.info(f"Legacy tool call: {tool_name}({args})")
                tool_result = self.tool_manager.run(tool_name, args)

                # Добавляем служебные сообщения
                messages.append(mk_tool_call_msg(tool_name, args))
                messages.append(mk_tool_resp_msg(tool_name, tool_result))

                # Удаляем вызов из ответа (чтобы не путать)
                response_text = re.sub(parse_regex, "", response_text).strip()

            except Exception as e:
                logger.error(f"Ошибка legacy tool: {e}")
                self.add_temporary_system_message(messages, f"Tool call failed: {e}")

        # Рекурсивно генерируем новый ответ с обновленными messages
        new_response, _ = self._generate_chat_response(messages, stream_callback)
        return new_response or response_text

    def get_character_provider(self) -> str:
        if not self.current_character:
            return "Current"  # По умолчанию, если персонаж не выбран
        key = f"CHAR_PROVIDER_{self.current_character.char_id}"
        return self.settings.get(key, "Current")  # 'Current' по умолчанию
    
    def _get_preset_id_by_name(self, display_name: str) -> Optional[int]:
        """
        Возвращает ID пользовательского пресета по его отображаемому имени.
        Используется для REACT_PROVIDER и аналогичных настроек.
        """
        if not display_name:
            return None
        try:
            meta_res = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
            meta = meta_res[0] if meta_res else None
            if not meta:
                return None
            custom_list = meta.get('custom', []) or []
            for pm in custom_list:
                # pm — это PresetMeta dataclass
                if getattr(pm, 'name', None) == display_name:
                    return getattr(pm, 'id', None)
        except Exception as e:
            logger.error(f"Failed to resolve preset id by name '{display_name}': {e}", exc_info=True)
        return None