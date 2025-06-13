# File: chat_model.py
import base64
import concurrent.futures
import datetime
import time
import requests
#import tiktoken
from openai import OpenAI
import re
import importlib
from typing import List, Dict, Any, Optional
import queue
import os  # Added for os.environ
from PIL import Image # Добавлено для обработки изображений
from io import BytesIO # Добавлено для обработки изображений

from Logger import logger
from characters import CrazyMita, KindMita, ShortHairMita, CappyMita, MilaMita, CreepyMita, SleepyMita, GameMaster, \
    SpaceCartridge, DivanCartridge  # Updated imports
from character import Character  # Character base
from utils.PipInstaller import PipInstaller

from utils import SH, save_combined_messages, calculate_cost_for_combined_messages, process_text_to_voice # Keep utils


# from promptPart import PromptPart, PromptType # No longer needed


class ChatModel:
    def __init__(self, gui, api_key, api_key_res, api_url, api_model, api_make_request, pip_installer: PipInstaller):
        self.last_key = 0
        self.gui = gui
        self.pip_installer = pip_installer
        self.g4fClient = None
        self.g4f_available = False
        self._initialize_g4f()  # Keep g4f initialization

        self.api_key = api_key
        self.api_key_res = api_key_res
        self.api_url = api_url
        self.api_model = api_model
        self.gpt4free_model = self.gui.settings.get("gpt4free_model")
        self.makeRequest = api_make_request  # This seems to be a boolean flag

        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.api_url)
            logger.info("OpenAI client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            self.client = None

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

        self.max_response_tokens = int(self.gui.settings.get("MODEL_MAX_RESPONSE_TOKENS", 3200))
        self.temperature = float(self.gui.settings.get("MODEL_TEMPERATURE", 0.5))
        self.presence_penalty = float(self.gui.settings.get("MODEL_PRESENCE_PENALTY", 0.0))
        self.top_k = int(self.gui.settings.get("MODEL_TOP_K", 0))
        self.top_p = float(self.gui.settings.get("MODEL_TOP_P", 1.0))
        self.thinking_budget = float(self.gui.settings.get("MODEL_THINKING_BUDGET", 0.0))
        self.presence_penalty = float(self.gui.settings.get("MODEL_PRESENCE_PENALTY", 0.0))
        self.frequency_penalty = float(self.gui.settings.get("MODEL_FREQUENCY_PENALTY", 0.0))
        self.log_probability = float(self.gui.settings.get("MODEL_LOG_PROBABILITY", 0.0))

        # Настройки стоимости токенов и лимитов
        self.token_cost_input = float(self.gui.settings.get("TOKEN_COST_INPUT", 0.0432))
        self.token_cost_output = float(self.gui.settings.get("TOKEN_COST_OUTPUT", 0.1728))
        self.max_model_tokens = int(self.gui.settings.get("MAX_MODEL_TOKENS", 128000)) # Default to a common large limit

        self.memory_limit = int(self.gui.settings.get("MODEL_MESSAGE_LIMIT", 40))  # For historical messages

        # Настройки для сжатия истории
        self.enable_history_compression_on_limit = bool(self.gui.settings.get("ENABLE_HISTORY_COMPRESSION_ON_LIMIT", False))
        self.enable_history_compression_periodic = bool(self.gui.settings.get("ENABLE_HISTORY_COMPRESSION_PERIODIC", False))
        self.history_compression_periodic_interval = int(self.gui.settings.get("HISTORY_COMPRESSION_PERIODIC_INTERVAL", 20))
        self.history_compression_prompt_template = str(self.gui.settings.get("HISTORY_COMPRESSION_PROMPT_TEMPLATE", "Prompts/System/compression_prompt.txt"))
        self.history_compression_output_target = str(self.gui.settings.get("HISTORY_COMPRESSION_OUTPUT_TARGET", "memory"))

        self._messages_since_last_periodic_compression = 0 # Счетчик сообщений с момента последнего периодического сжатия

        self.current_character: Character = None
        self.current_character_to_change = str(self.gui.settings.get("CHARACTER"))
        self.characters: Dict[str, Character] = {}

        # Настройки для снижения качества изображений в истории
        self.image_quality_reduction_enabled = bool(self.gui.settings.get("IMAGE_QUALITY_REDUCTION_ENABLED", False))
        self.image_quality_reduction_start_index = int(self.gui.settings.get("IMAGE_QUALITY_REDUCTION_START_INDEX", 25))
        self.image_quality_reduction_use_percentage = bool(self.gui.settings.get("IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE", False))
        min_quolity = self.gui.settings.get("IMAGE_QUALITY_REDUCTION_MIN_QUALITY", 30)
        self.image_quality_reduction_min_quality = int(min_quolity) if min_quolity!='' else 30
        self.image_quality_reduction_decrease_rate = int(self.gui.settings.get("IMAGE_QUALITY_REDUCTION_DECREASE_RATE", 5))


        # Game-specific state - these should ideally be passed to character or managed elsewhere if possible
        # For now, keeping them here as per original. DSL might need them injected into character.variables.
        self.distance = 0.0
        self.roomPlayer = -1
        self.roomMita = -1
        self.nearObjects = ""
        self.actualInfo = ""

        self.infos_to_add_to_history: List[Dict] = []  # For temporary system messages to be added to history

        # Mapping of model names to their token limits
        self._model_token_limits: Dict[str, int] = {
            "gpt-4o-mini": 128000,
            "gpt-4o": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
            "gemini-1.5-flash": 1000000, # Примерный лимит для Gemini 1.5 Flash
            "gemini-1.5-pro": 1000000,   # Примерный лимит для Gemini 1.5 Pro
            "gemini-pro": 32768,        # Примерный лимит для Gemini Pro
            # Добавьте другие модели по мере необходимости
        }

        self.init_characters()
        self.HideAiData = True  # Unused?
        self.max_request_attempts = int(self.gui.settings.get("MODEL_MESSAGE_ATTEMPTS_COUNT", 5))
        self.request_delay = float(self.gui.settings.get("MODEL_MESSAGE_ATTEMPTS_TIME", 0.20))

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

            target_version = self.gui.settings.get("G4F_VERSION", "0.4.7.7")  # Using "0.x.y.z" format
            package_spec = f"g4f=={target_version}" if target_version != "latest" else "g4f"

            if self.pip_installer:
                success = self.pip_installer.install_package(
                    package_spec,
                    description=f"Первоначальная установка g4f версии {target_version}..."
                )
                if success:
                    logger.info("Первоначальная установка g4f (файлы) прошла успешно. Очистка кэша импорта...")
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

    def init_characters(self):
        self.crazy_mita_character = CrazyMita("Crazy", "Crazy Mita", "/speaker mita", short_name="CrazyMita", miku_tts_name="/set_person CrazyMita", silero_turn_off_video=True)
        self.kind_mita_character = KindMita("Kind", "Kind Mita", "/speaker kind", short_name="MitaKind", miku_tts_name="/set_person KindMita", silero_turn_off_video=True)
        self.cappy_mita_character = CappyMita("Cappy","Cappy Mita", "/speaker cap", short_name="CappieMita", miku_tts_name="/set_person CapMita", silero_turn_off_video=True)
        self.shorthair_mita_character = ShortHairMita("ShortHair","ShortHair Mita", "/speaker shorthair", short_name="ShorthairMita", miku_tts_name="/set_person ShortHairMita", silero_turn_off_video=True)
        self.mila_character = MilaMita("Mila","Mila", "/speaker mila", short_name="Mila", miku_tts_name="/set_person MilaMita", silero_turn_off_video=True)
        self.sleepy_character = SleepyMita("Sleepy","Sleepy Mita", "/speaker dream", short_name="SleepyMita", miku_tts_name="/set_person SleepyMita", silero_turn_off_video=True)
        self.creepy_character = CreepyMita("Creepy","Creepy Mita", "/speaker ghost", short_name="GhostMita", miku_tts_name="/set_person GhostMita", silero_turn_off_video=True)

        self.cart_space = SpaceCartridge("Cart_portal", "Cart_portal", "/speaker wheatley", short_name="Player", miku_tts_name="/set_person Player", silero_turn_off_video=True,is_cartridge=True)
        self.cart_divan = DivanCartridge("Cart_divan", "Cart_divan", "/speaker engineer", short_name="Player", miku_tts_name="/set_person Player", silero_turn_off_video=True,is_cartridge=True)
        self.GameMaster = GameMaster("GameMaster", "GameMaster", "/speaker dryad", short_name="PhoneMita", miku_tts_name="/set_person PhoneMita", silero_turn_off_video=True)

        self.characters = {
            self.crazy_mita_character.char_id: self.crazy_mita_character,
            self.kind_mita_character.char_id: self.kind_mita_character,
            self.cappy_mita_character.char_id: self.cappy_mita_character,
            self.shorthair_mita_character.char_id: self.shorthair_mita_character,
            self.mila_character.char_id: self.mila_character,
            self.sleepy_character.char_id: self.sleepy_character,
            self.creepy_character.char_id: self.creepy_character,
            self.cart_space.char_id: self.cart_space,
            self.cart_divan.char_id: self.cart_divan,
            self.GameMaster.char_id: self.GameMaster,
        }
        self.current_character = self.characters.get(self.current_character_to_change) or self.crazy_mita_character

    def get_all_mitas(self):
        logger.info(f"Available characters: {list(self.characters.keys())}")
        return list(self.characters.keys())

    def update_openai_client(self, reserve_key_token=None):
        logger.info("Attempting to update OpenAI client.")
        key_to_use = reserve_key_token if reserve_key_token else self.api_key

        if not key_to_use:
            logger.error("No API key available to update OpenAI client.")
            self.client = None
            return

        try:
            if self.api_url:
                logger.info(f"Using API key (masked): {SH(key_to_use)} and base URL: {self.api_url}")
                self.client = OpenAI(api_key=key_to_use, base_url=self.api_url)
            else:
                logger.info(f"Using API key (masked): {SH(key_to_use)} (no custom base URL)")
                self.client = OpenAI(api_key=key_to_use)
            logger.info("OpenAI client updated successfully.")
        except Exception as e:
            logger.error(f"Failed to update OpenAI client: {e}")
            self.client = None
    def generate_response(
            self,
            user_input : str,
            system_input : str = "",
            image_data : list[bytes] | None = None
    ):
        # 0. Подготовка -----------------------------------------------------------------
        if image_data is None:
            image_data = []

        self.check_change_current_character()

        # 1. История --------------------------------------------------------------------
        history_data           = self.current_character.history_manager.load_history()
        llm_messages_history   = history_data.get("messages", [])

        if self.infos_to_add_to_history:
            llm_messages_history.extend(self.infos_to_add_to_history)
            self.infos_to_add_to_history.clear()

        # 2. Игровые переменные ---------------------------------------------------------
        self.current_character.set_variable("GAME_DISTANCE",self.distance)
        self.current_character.set_variable("GAME_ROOM_PLAYER",self.get_room_name(self.roomPlayer))
        self.current_character.set_variable("GAME_ROOM_MITA",self.get_room_name(self.roomMita))
        self.current_character.set_variable("GAME_NEAR_OBJECTS",self.nearObjects)
        self.current_character.set_variable("GAME_ACTUAL_INFO",self.actualInfo)

        # 3. Шахматы --------------------------------------------------------------------
        chess_system_message_for_llm_content: Optional[str] = None

        if hasattr(self.current_character, 'chess_state_queue') \
        and self.current_character.chess_state_queue is not None \
        and self.current_character.get_variable("playingChess", False):

            chess_state_details_string = "Шахматная игра активна. Обновление состояния..."
            latest_chess_state_data: Optional[Dict[str, Any]] = None

            while not self.current_character.chess_state_queue.empty():
                try:
                    latest_chess_state_data = self.current_character.chess_state_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception as e:
                    logger.error(f"[{self.current_character.char_id}] Ошибка чтения chess_state_queue: {e}")
                    latest_chess_state_data = {"error": f"Ошибка чтения состояния: {e}"}
                    break

            if latest_chess_state_data:
                # ---- формируем подробную строку ----------------------------------------
                fen                    = latest_chess_state_data.get('fen',                 'N/A')
                current_board_turn     = latest_chess_state_data.get('turn',               'N/A')
                legal_moves_uci        = latest_chess_state_data.get('legal_moves_uci',    [])
                is_game_over           = latest_chess_state_data.get('is_game_over',       False)
                outcome                = latest_chess_state_data.get('outcome_message',    'Игра продолжается')
                elo                    = latest_chess_state_data.get('current_elo',        'N/A')
                player_gui_is_white    = latest_chess_state_data.get('player_is_white_in_gui', True)
                last_board_move_san    = latest_chess_state_data.get('last_move_san',      'Нет (начало игры)')

                llm_color_textual   = "белыми" if not player_gui_is_white else "черными"
                gui_color_textual   = "белыми" if player_gui_is_white  else "черными"

                llm_actual_color_string = 'white' if not player_gui_is_white else 'black'
                gui_actual_color_string = 'white' if player_gui_is_white  else 'black'

                s = []
                s.append(f"--- СОСТОЯНИЕ ШАХМАТНОЙ ПАРТИИ (Maia ELO {elo}) ---")
                s.append(f"ТЫ ИГРАЕШЬ: {llm_color_textual}.")
                s.append(f"ТВОЙ ОППОНЕНТ (Игрок GUI) ИГРАЕТ: {gui_color_textual}.")

                # последний ход ----------------------------------------------------------
                if last_board_move_san != 'Нет (начало игры)':
                    last_mover_actual_color_string = 'black' if current_board_turn == 'white' else 'white'
                    if last_mover_actual_color_string == llm_actual_color_string:
                        s.append(f"ПОСЛЕДНИЙ ХОД СДЕЛАЛ ТЫ ({llm_color_textual}): {last_board_move_san}.")
                    elif last_mover_actual_color_string == gui_actual_color_string:
                        s.append(f"ПОСЛЕДНИЙ ХОД СДЕЛАЛ Игрок GUI ({gui_color_textual}): {last_board_move_san}.")
                    else:
                        s.append(f"ПОСЛЕДНИЙ ХОД НА ДОСКЕ: {last_board_move_san} (не удалось определить автора).")
                else:
                    s.append("ПОСЛЕДНИЙ ХОД: Это начало партии, ходов еще не было.")

                s.append(f"ТЕКУЩАЯ ПОЗИЦИЯ (FEN): {fen}.")
                s.append(f"СЕЙЧАС ХОДЯТ: {'белые' if current_board_turn == 'white' else 'черные'}.")

                is_llm_turn_now = (current_board_turn == llm_actual_color_string)

                # статус игры ------------------------------------------------------------
                if is_game_over:
                    s.append("СТАТУС ИГРЫ: ОКОНЧЕНА.")
                    s.append(f"РЕЗУЛЬТАТ: {outcome}.")
                    if latest_chess_state_data.get("game_resigned_by_llm"):
                        s.append("Ты сдал эту партию.")
                    elif latest_chess_state_data.get("game_stopped_by_llm"):
                        s.append("Ты остановил эту партию.")
                else:
                    s.append("СТАТУС ИГРЫ: ПРОДОЛЖАЕТСЯ.")
                    if is_llm_turn_now:
                        s.append("ЭТО ТВОЙ ХОД.")
                        if legal_moves_uci:
                            max_display = 15
                            valid_moves = [m for m in legal_moves_uci if m]
                            s.append(f"ТВОИ ЛЕГАЛЬНЫЕ ХОДЫ (UCI, первые {max_display}): "
                                    f"{', '.join(valid_moves[:max_display])}"
                                    + ("." if len(valid_moves)<=max_display
                                        else f" (показаны первые {max_display} из {len(valid_moves)})."))
                            s.append("Используй тег <MakeChessMoveAsLLM>uci_ход</MakeChessMoveAsLLM> чтобы сделать ход.")
                            s.append("Пример: <MakeChessMoveAsLLM>e2e4</MakeChessMoveAsLLM>")
                            # Подсказка о превращении пешки
                            if any(len(m)==5 and m[4] in 'qrbn' for m in valid_moves):
                                s.append("Для превращения пешки добавь букву фигуры, напр.: e7e8q.")
                        else:
                            s.append("У ТЕБЯ НЕТ ДОСТУПНЫХ ХОДОВ.")
                    else:
                        s.append(f"СЕЙЧАС ХОД {gui_color_textual.upper()} (GUI). Ожидай.")

                # Ошибки модуля
                if latest_chess_state_data.get("error"):
                    s.append(f"СИСТЕМНОЕ СООБЩЕНИЕ ШАХМАТНОГО МОДУЛЯ: {latest_chess_state_data['error']}.")
                if latest_chess_state_data.get("error_move") and is_llm_turn_now:
                    s.append(f"ВАЖНО: Предыдущий ход ({latest_chess_state_data['error_move']}) неверен: "
                            f"{latest_chess_state_data.get('error_message_for_move','Неверный ход')}.")

                s.append("--- КОНЕЦ ШАХМАТНОЙ ИНФОРМАЦИИ ---")
                chess_system_message_for_llm_content = "\n".join(s)

                logger.info(f"[{self.current_character.char_id}] Chess system msg formed.")
            else:
                msg = ("Шахматная игра активна, но нет данных от модуля. "
                    "Запрашиваю текущее состояние.")
                chess_system_message_for_llm_content = msg
                logger.info(f"[{self.current_character.char_id}] {msg}")
                if hasattr(self.current_character, '_send_chess_command'):
                    self.current_character._send_chess_command({"action": "get_state"})

        # 4. Системные промпты / память -------------------------------------------------
        combined_messages = []

        separate_prompts =  bool(self.gui.settings.get("SEPARATE_PROMPTS", True))
        messages = self.current_character.get_full_system_setup_for_llm(separate_prompts)
        combined_messages.extend(messages)


        # Добавляем шахматы (если сформировано)
        if chess_system_message_for_llm_content:
            combined_messages.append({"role": "system",
                                    "content": chess_system_message_for_llm_content})



        # 5. История памяти
        llm_messages_history = self.process_history_compression(llm_messages_history)

        if self.current_character != self.GameMaster:
            # Определяем сообщения, которые будут "потеряны"
            missed_messages = llm_messages_history[:-self.memory_limit]
            llm_messages_history_limited = llm_messages_history[-self.memory_limit:]
        else:
            # Для GameMaster также определяем потерянные сообщения, если лимит превышен
            missed_messages = llm_messages_history[:-8]
            llm_messages_history_limited = llm_messages_history[-8:]

        # Если включена настройка сохранения пропущенных сообщений и есть что сохранять
        if missed_messages and bool(self.gui.settings.get("SAVE_MISSED_HISTORY", True)):
            logger.info(
                f"Сохраняю {len(missed_messages)} пропущенных сообщений для персонажа {self.current_character.char_id}.")
            self.current_character.history_manager.save_missed_history(missed_messages)

        # Применяем снижение качества к изображениям в истории, если включено
        if self.image_quality_reduction_enabled:
            llm_messages_history_limited = self._apply_history_image_quality_reduction(llm_messages_history_limited)

        event_system_infos = self.current_character.get_system_infos()
        if event_system_infos:
            llm_messages_history_limited.extend(event_system_infos)

        combined_messages.extend(llm_messages_history_limited)


        # 6. Добавляем system_input -----------------------------------------------------
        if system_input:
            llm_messages_history_limited.append({"role": "system", "content": system_input})

        # 7. Пользовательское сообщение (текст + картинки) ------------------------------
        user_message_for_history = None
        user_content_chunks = []

        if user_input:
            user_content_chunks.append({"type": "text", "text": user_input})

        for img_bytes in image_data:
            user_content_chunks.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
                }
            })

        if user_content_chunks:
            user_message_for_history = {"role": "user", "content": user_content_chunks}
            combined_messages.append(user_message_for_history)

        if user_message_for_history:
            user_message_for_history["time"] = datetime.datetime.now().strftime("%d.%m.%Y_%H.%M")
            llm_messages_history_limited.append(user_message_for_history)


        # 8. Генерация ответа -----------------------------------------------------------
        try:
            llm_response_content, success = self._generate_chat_response(combined_messages)

            if not success or not llm_response_content:
                logger.warning("LLM generation failed or returned empty.")
                return "..."

            processed_response_text = self.current_character.process_response_nlp_commands(llm_response_content)

            # --- Встраивание «command replacer» (embeddings) ---------------------------
            final_response_text = processed_response_text
            try:
                use_cmd_replacer  = self.gui.settings.get("USE_COMMAND_REPLACER", False)
                enable_by_default = os.environ.get("ENABLE_COMMAND_REPLACER_BY_DEFAULT", "0") == "1"

                if use_cmd_replacer and enable_by_default:
                    if not hasattr(self, 'model_handler'):
                        from utils.embedding_handler import EmbeddingModelHandler
                        self.model_handler = EmbeddingModelHandler()
                    if not hasattr(self, 'parser'):
                        from utils.command_parser import CommandParser
                        self.parser = CommandParser(model_handler=self.model_handler)

                    min_sim     = float(self.gui.settings.get("MIN_SIMILARITY_THRESHOLD", 0.40))
                    cat_switch  = float(self.gui.settings.get("CATEGORY_SWITCH_THRESHOLD", 0.18))
                    skip_comma  = bool (self.gui.settings.get("SKIP_COMMA_PARAMETERS", True))

                    logger.info(f"Attempting command replacement on: {processed_response_text[:100]}...")
                    final_response_text, _ = self.parser.parse_and_replace(
                        processed_response_text,
                        min_similarity_threshold=min_sim,
                        category_switch_threshold=cat_switch,
                        skip_comma_params=skip_comma
                    )
                    logger.info(f"After command replacement: {final_response_text[:100]}...")
                elif use_cmd_replacer and not enable_by_default:
                    logger.info("Command replacer enabled in settings but disabled by ENV.")
                else:
                    logger.info("Command replacer disabled.")
            except Exception as ex:
                logger.error(f"Error during command replacement: {ex}", exc_info=True)
                # остаётся processed_response_text

            # 9. Сохраняем историю / TTS --------------------------------------------------
            assistant_message_content = final_response_text

            # Проверяем настройку замены изображений заглушками
            if bool(self.gui.settings.get("REPLACE_IMAGES_WITH_PLACEHOLDERS", False)):
                logger.info("Настройка REPLACE_IMAGES_WITH_PLACEHOLDERS включена. Заменяю изображения заглушками.")
                # Здесь предполагается, что final_response_text - это строка.
                # Если модель может возвращать изображения в ответе, нужно будет адаптировать эту логику.
                # Пока что просто добавляем заглушку, если в ответе есть что-то похожее на изображение (хотя модель не должна их генерировать в текстовом ответе).
                # В будущем, если модель сможет генерировать изображения, нужно будет обрабатывать мультимодальный контент и здесь.
                # Для текущей реализации, где модель возвращает только текст, эта заглушка не сработает для изображений,
                # но она готова к будущим изменениям, если модель начнет возвращать структурированный контент с изображениями.
                # Пока что, если в ответе есть URL или base64, мы можем это заменить.
                # Это очень грубая эвристика для текстового ответа.
                assistant_message_content = re.sub(r'https?://\S+\.(?:png|jpg|jpeg|gif|bmp)|data:image/\S+;base64,\S+', '[Изображение]', assistant_message_content)


            assistant_message = {"role": "assistant", "content": assistant_message_content}
            assistant_message["time"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

            llm_messages_history_limited.append(assistant_message)

            self.current_character.save_character_state_to_history(llm_messages_history_limited)

            if self.current_character != self.GameMaster or bool(self.gui.settings.get("GM_VOICE")):
                self.gui.textToTalk           = process_text_to_voice(final_response_text)
                self.gui.textSpeaker          = self.current_character.silero_command
                self.gui.textSpeakerMiku      = self.current_character.miku_tts_name
                self.gui.silero_turn_off_video= self.current_character.silero_turn_off_video
                logger.info(f"TTS Text: {self.gui.textToTalk}, Speaker: {self.gui.textSpeaker}")

            self.gui.update_debug_info()
            return final_response_text

        except Exception as e:
            logger.error(f"Error during LLM response generation or processing: {e}", exc_info=True)
            return f"Ошибка: {e}"

    def process_history_compression(self,llm_messages_history):
        """Сжимает старые воспоминания"""

        compress_percent = float(self.gui.settings.get("HISTORY_COMPRESSION_MIN_PERCENT_TO_COMPRESS",0.85))
        if self.enable_history_compression_on_limit and len(llm_messages_history) >= self.memory_limit*compress_percent:

            messages_to_compress = llm_messages_history[:round(-self.memory_limit*compress_percent)]
            logger.info(f"История превышает лимит. Попытка сжать {len(messages_to_compress)} сообщений.")

            compressed_summary = self._compress_history(messages_to_compress)

            if compressed_summary:
                if self.history_compression_output_target == "memory":
                    # Добавляем в MemorySystem
                    if hasattr(self.current_character, 'memory_system') and self.current_character.memory_system:
                        self.current_character.memory_system.add_memory(content=compressed_summary,memory_type="summary")
                        logger.info("Сжатая сводка добавлена в MemorySystem.")
                    else:
                        logger.warning("MemorySystem недоступен для добавления сжатой сводки.")
                elif self.history_compression_output_target == "history":
                    summary_message = {"role": "system", "content": f"[HISTORY SUMMARY]: {compressed_summary}"}
                    # Оставляем self.memory_limit - 1 самых новых сообщений и добавляем сводку в начало
                    # Убедимся, что self.memory_limit > 0, чтобы избежать отрицательных индексов
                    messages_to_keep = llm_messages_history[-self.memory_limit + 1:] if self.memory_limit > 0 else []
                    llm_messages_history = [summary_message] + messages_to_keep
                    logger.info("Сжатая сводка добавлена в начало истории, старые сообщения удалены.")
                else:
                    logger.warning(f"Неизвестный target для сжатия истории: {self.history_compression_output_target}")

                logger.info(f"История сокращена до {len(llm_messages_history)} сообщений после сжатия по лимиту.")
            else:
                logger.warning("Сжатие истории по лимиту не удалось (недостаточно сообщений для сжатия).")

        # Логика периодического сжатия
        if self.enable_history_compression_periodic:
            self._messages_since_last_periodic_compression += 1
            if self._messages_since_last_periodic_compression >= self.history_compression_periodic_interval:
                # Берем самые старые сообщения для периодического сжатия
                messages_to_compress = llm_messages_history[:self.history_compression_periodic_interval]

                if not messages_to_compress:
                    logger.info("Нет сообщений для периодического сжатия.")
                    self._messages_since_last_periodic_compression = 0 # Сбрасываем счетчик
                    return llm_messages_history # Возвращаем текущую историю без изменений

                logger.info(f"Периодическое сжатие: попытка сжать {len(messages_to_compress)} сообщений.")
                compressed_summary = self._compress_history(messages_to_compress)

                if compressed_summary:
                    if self.history_compression_output_target == "memory":
                        if hasattr(self.current_character, 'memory_system') and self.current_character.memory_system:
                            self.current_character.memory_system.add_memory(compressed_summary, memory_type="summary")
                            logger.info("Сжатая сводка добавлена в MemorySystem.")
                        else:
                            logger.warning("MemorySystem недоступен для добавления сжатой сводки.")
                        # После добавления в память, просто обрезаем историю до лимита
                        llm_messages_history = llm_messages_history[-self.memory_limit:]
                    elif self.history_compression_output_target == "history":
                        summary_message = {"role": "system", "content": f"[HISTORY SUMMARY]: {compressed_summary}"}
                        # Оставляем сообщения после сжатых и добавляем сводку в начало
                        remaining_messages = llm_messages_history[len(messages_to_compress):]
                        # Затем обрезаем до self.memory_limit, учитывая, что summary_message уже добавлен
                        messages_to_keep = remaining_messages[-self.memory_limit + 1:] if self.memory_limit > 0 else []
                        llm_messages_history = [summary_message] + messages_to_keep
                        logger.info("Сжатая сводка добавлена в начало истории, старые сообщения удалены.")
                    else:
                        logger.warning(
                            f"Неизвестный target для сжатия истории: {self.history_compression_output_target}")

                    logger.info(f"История сокращена до {len(llm_messages_history)} сообщений после периодического сжатия.")
                else:
                    logger.warning("Периодическое сжатие истории не удалось.")

                self._messages_since_last_periodic_compression = 0  # Сбрасываем счетчик
        return llm_messages_history

    def check_change_current_character(self):
        if not self.current_character_to_change:
            return
        if self.current_character_to_change in self.characters:
            if not self.current_character or self.current_character.name != self.current_character_to_change:
                logger.info(f"Changing character to {self.current_character_to_change}")
                self.current_character = self.characters[self.current_character_to_change]
                self.current_character.reload_character_data()
            self.current_character_to_change = ""
        else:
            logger.warning(f"Attempted to change to unknown character: {self.current_character_to_change}")
            self.current_character_to_change = ""

    def _generate_chat_response(self, combined_messages):
        max_attempts = self.max_request_attempts
        retry_delay = self.request_delay
        request_timeout = 45

        self._log_generation_start()
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Generation attempt {attempt}/{max_attempts}")
            response_text = None

            save_combined_messages(combined_messages, "SavedMessages/last_attempt_log")

            try:
                if bool(self.gui.settings.get("NM_API_REQ", False)):
                    formatted_for_request = combined_messages
                    if bool(self.gui.settings.get("GEMINI_CASE", False)):
                        formatted_for_request = self._format_messages_for_gemini(combined_messages)

                    response_text = self._execute_with_timeout(
                        self._generate_request_response,
                        args=(formatted_for_request,),
                        timeout=request_timeout
                    )
                else:
                    use_gpt4free_for_this_attempt = bool(self.gui.settings.get("gpt4free")) or \
                                                    (bool(self.gui.settings.get(
                                                        "GPT4FREE_LAST_ATTEMPT")) and attempt >= max_attempts)

                    if use_gpt4free_for_this_attempt:
                        logger.info("Using gpt4free for this attempt.")
                    elif attempt > 1 and self.api_key_res:
                        logger.info("Attempting with reserve API key.")
                        self.update_openai_client(reserve_key_token=self.GetOtherKey())

                    response_text = self._generate_openapi_response(combined_messages,
                                                                    use_gpt4free=use_gpt4free_for_this_attempt)

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

    def _log_generation_start(self):
        logger.info("Preparing to generate LLM response.")
        logger.info(f"Max Response Tokens: {self.max_response_tokens}, Temperature: {self.temperature}")
        logger.info(
            f"Presence Penalty: {self.presence_penalty} (Used: {bool(self.gui.settings.get('USE_MODEL_PRESENCE_PENALTY'))})")
        logger.info(f"API URL: {self.api_url}, API Model: {self.api_model}")
        logger.info(f"g4f Enabled: {bool(self.gui.settings.get('gpt4free'))}, g4f Model: {self.gpt4free_model}")
        logger.info(f"Custom Request (NM_API_REQ): {bool(self.gui.settings.get('NM_API_REQ', False))}")
        if bool(self.gui.settings.get('NM_API_REQ', False)):
            logger.info(f"  Custom Request Model (NM_API_MODEL): {self.gui.settings.get('NM_API_MODEL')}")
            logger.info(f"  Gemini Case for Custom Req: {bool(self.gui.settings.get('GEMINI_CASE', False))}")

    def _format_messages_for_gemini(self, combined_messages):
        formatted_messages = []
        for i, msg in enumerate(combined_messages):
            if msg["role"] == "system":
                formatted_messages.append({"role": "user", "content": f"[System Instruction]: {msg['content']}"})
            elif msg["role"] == "assistant":
                formatted_messages.append({"role": "model", "content": msg['content']})
            else:  # user
                formatted_messages.append(msg)
        return formatted_messages

    def _generate_request_response(self, formatted_messages):
        try:
            if bool(self.gui.settings.get("GEMINI_CASE", False)):
                logger.info("Dispatching to Gemini request generation.")
                return self.generate_request_gemini(formatted_messages)
            else:
                logger.info("Dispatching to common request generation.")
                return self.generate_request_common(formatted_messages)
        except Exception as e:
            logger.error(f"Error in _generate_request_response dispatcher: {str(e)}", exc_info=True)
            return None

    def _generate_openapi_response(self, combined_messages, use_gpt4free=False):
        target_client = None
        model_to_use = ""

        if use_gpt4free:
            if not self.g4f_available or not self.g4fClient:
                logger.error("gpt4free selected, but client is not available.")
                return None
            target_client = self.g4fClient
            model_to_use = self.gui.settings.get("gpt4free_model", "gpt-3.5-turbo")
            logger.info(f"Using g4f client with model: {model_to_use}")
        else:
            if not self.client:
                logger.info("OpenAI client not initialized. Attempting to re-initialize.")
                self.update_openai_client()
                if not self.client:
                    logger.error("OpenAI client is not available after re-initialization attempt.")
                    return None
            target_client = self.client
            model_to_use = self.api_model
            logger.info(f"Using OpenAI compatible client with model: {model_to_use}")

        try:
            self.change_last_message_to_user_for_gemini(model_to_use, combined_messages)

            # Удаляем поле 'time' из сообщений, так как OpenAI API его не поддерживает
            cleaned_messages = []
            for msg in combined_messages:
                cleaned_msg = {k: v for k, v in msg.items() if k != "time"}
                cleaned_messages.append(cleaned_msg)

            final_params = self.get_final_params(model_to_use, cleaned_messages)

            logger.info(
                f"Requesting completion from {model_to_use} with temp={final_params.get('temperature')}, max_tokens={final_params.get('max_tokens')}")
            completion = target_client.chat.completions.create(**final_params)

            if completion and completion.choices:
                response_content = completion.choices[0].message.content
                logger.info("Completion successful.")
                return response_content.strip() if response_content else None
            else:
                logger.warning("No completion choices received or completion object is empty.")
                if completion: self.try_print_error(completion)
                return None
        except Exception as e:
            logger.error(f"Error during OpenAI/g4f API call: {str(e)}", exc_info=True)
            if hasattr(e, 'response') and e.response:
                logger.error(f"API Error details: Status={e.response.status_code}, Body={e.response.text}")
            return None

    def change_last_message_to_user_for_gemini(self, api_model, combined_messages):
        if combined_messages and ("gemini" in api_model.lower() or "gemma" in api_model.lower()) and \
                combined_messages[-1]["role"] == "system":
            logger.info(f"Adjusting last message for {api_model}: system -> user with [SYSTEM INFO] prefix.")
            combined_messages[-1]["role"] = "user"
            combined_messages[-1]["content"] = f"[SYSTEM INFO] {combined_messages[-1]['content']}"

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

    def _process_image_quality(self, image_bytes: bytes, target_quality: int) -> bytes | None:
        """
        Обрабатывает байты изображения, изменяя его качество JPEG.
        Если target_quality == 0, возвращает None (для удаления изображения).
        """
        if not image_bytes:
            return None

        if target_quality <= 0:
            logger.info("Изображение будет удалено (target_quality <= 0).")
            return None

        try:
            original_size = len(image_bytes)
            img = Image.open(BytesIO(image_bytes))
            # Конвертируем в RGB, если режим не RGB (например, RGBA), чтобы избежать ошибок при сохранении JPEG
            if img.mode != 'RGB':
                img = img.convert('RGB')

            byte_arr = BytesIO()
            img.save(byte_arr, format='JPEG', quality=target_quality)
            processed_bytes = byte_arr.getvalue()
            processed_size = len(processed_bytes)
            logger.debug(f"Качество изображения изменено на {target_quality}. Размер: {original_size} байт -> {processed_size} байт.")
            return processed_bytes
        except Exception as e:
            logger.error(f"Ошибка при обработке качества изображения: {e}", exc_info=True)
            return image_bytes # Возвращаем исходные байты в случае ошибки

    def _apply_history_image_quality_reduction(self, messages: List[Dict]) -> List[Dict]:
        """
        Применяет снижение качества к изображениям в истории сообщений на основе настроек.
        """
        if not messages:
            return messages

        history_length = len(messages)
        actual_start_index = 0

        if self.image_quality_reduction_use_percentage:
            actual_start_index = int(history_length * (self.image_quality_reduction_start_index / 100.0))
        else:
            actual_start_index = self.image_quality_reduction_start_index

        # Убедимся, что start_index не выходит за пределы истории
        actual_start_index = max(0, min(actual_start_index, history_length))

        logger.info(f"Применение снижения качества изображений: длина истории {history_length}, фактический старт {actual_start_index}")

        updated_messages = []
        for i, msg in enumerate(messages):
            # Сообщения до actual_start_index остаются без изменений
            if i < actual_start_index:
                updated_messages.append(msg)
                continue

            # Обрабатываем только сообщения, которые содержат изображения
            if msg.get("role") in ["user", "assistant"] and isinstance(msg.get("content"), list):
                new_content_chunks = []
                image_processed = False
                for item in msg["content"]:
                    if item.get("type") == "image_url" and item.get("image_url") and item["image_url"].get("url"):
                        image_processed = True
                        base64_url = item["image_url"]["url"]
                        # Извлекаем только base64 данные
                        if "," in base64_url:
                            img_base64 = base64_url.split(',')[1]
                        else:
                            img_base64 = base64_url # Если нет префикса, предполагаем, что это чистый base64

                        try:
                            img_bytes = base64.b64decode(img_base64)

                            # Вычисляем целевое качество
                            # Индекс сообщения относительно начала зоны снижения качества
                            relative_index = i - actual_start_index

                            # Начальное качество для снижения. Берем из настроек захвата экрана.
                            initial_quality = int(self.gui.settings.get("SCREEN_CAPTURE_QUALITY", 75))

                            calculated_quality = initial_quality - (self.image_quality_reduction_decrease_rate * relative_index)

                            # Ограничиваем качество минимальным значением
                            target_quality = max(self.image_quality_reduction_min_quality, calculated_quality)

                            logger.info(f"Сообщение {i}: относительный индекс {relative_index}, рассчитанное качество {calculated_quality}, целевое качество {target_quality}")

                            processed_bytes = self._process_image_quality(img_bytes, target_quality)

                            if processed_bytes:
                                new_content_chunks.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64.b64encode(processed_bytes).decode('utf-8')}"
                                    }
                                })
                            else:
                                logger.info(f"Изображение в сообщении {i} удалено (качество <= 0).")
                                # Если processed_bytes None, изображение удаляется, не добавляем его в new_content_chunks
                        except Exception as e:
                            logger.error(f"Ошибка при обработке изображения в истории сообщения {i}: {e}", exc_info=True)
                            new_content_chunks.append(item) # В случае ошибки оставляем исходный элемент
                    else:
                        new_content_chunks.append(item) # Добавляем текстовые части и другие типы контента

                if image_processed: # Если в сообщении были изображения, обновляем его
                    if new_content_chunks:
                        new_msg = msg.copy()
                        new_msg["content"] = new_content_chunks
                        updated_messages.append(new_msg)
                    else:
                        # Если все изображения были удалены и нет другого контента, можно удалить сообщение
                        # Или оставить его только с текстом, если он был
                        if any(item.get("type") == "text" for item in msg["content"]):
                            new_msg = msg.copy()
                            new_msg["content"] = [item for item in msg["content"] if item.get("type") == "text"]
                            updated_messages.append(new_msg)
                        else:
                            logger.info(f"Сообщение {i} полностью удалено, так как все изображения были удалены и нет текста.")
                else:
                    updated_messages.append(msg) # Если изображений не было, добавляем сообщение как есть
            else:
                updated_messages.append(msg) # Добавляем сообщения без изображений как есть

        return updated_messages

    # def generate_request_gemini(self, combined_messages):
    #     params_for_gemini = self.get_params(model="gemini-pro")
    #     self.clear_endline_sim(params_for_gemini) # Added from other versions

    #     gemini_contents = []
    #     for msg in combined_messages: 
    #         role = "model" if msg["role"] == "assistant" else msg["role"]
    #         if role not in ["user", "model"]: 
    #             logger.warning(f"Invalid role '{role}' for Gemini, converting to 'user'. Content: {msg['content'][:50]}")
    #             role = "user" 
    #         gemini_contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    #     data = {
    #         "contents": gemini_contents,
    #         "generationConfig": params_for_gemini
    #     }

    #     headers = {"Content-Type": "application/json"} 

    #     api_url_with_key = self.api_url 
    #     if ":generateContent" not in api_url_with_key and not api_url_with_key.endswith("/generateContent"):
    #          api_url_with_key = api_url_with_key.replace("/v1beta/models/", "/v1beta/models/") + ":generateContent" # Ensure correct path
    #          if "?key=" not in api_url_with_key and self.api_key: 
    #              api_url_with_key += f"?key={self.api_key}"

    #     logger.info(f"Sending request to Gemini API: {api_url_with_key}")

    #     try:
    #         response = requests.post(api_url_with_key, headers=headers, json=data, timeout=40)
    #         response.raise_for_status() 

    #         response_data = response.json()
    #         if response_data.get("candidates"):
    #             generated_text = response_data["candidates"][0].get("content", {}).get("parts", [{}])[0].get("text", "")
    #             logger.info("Gemini response successful.")
    #             return generated_text
    #         else:
    #             logger.warning(f"Gemini response missing candidates. Full response: {response_data}")
    #             if "promptFeedback" in response_data:
    #                 logger.warning(f"Gemini Prompt Feedback: {response_data['promptFeedback']}")
    #             return None
    #     except requests.exceptions.HTTPError as http_err:
    #         logger.error(f"Gemini API HTTP error: {http_err} - Response: {http_err.response.text}")
    #         return None
    #     except Exception as e:
    #         logger.error(f"Error during Gemini API request: {str(e)}", exc_info=True)
    #         return None

    # def generate_request_common(self, combined_messages):
    #     model_name = self.gui.settings.get("NM_API_MODEL", self.api_model)
    #     params_for_common = self.get_params(model=model_name)
    #     self.clear_endline_sim(params_for_common) # Added from other versions

    #     data = {
    #         "model": model_name,
    #         "messages": combined_messages, 
    #         **params_for_common 
    #     }

    #     headers = {
    #         "Content-Type": "application/json",
    #     }
    #     if self.api_key: 
    #         headers["Authorization"] = f"Bearer {self.api_key}"

    #     logger.info(f"Sending request to common API: {self.api_url} with model: {model_name}")

    #     try:
    #         response = requests.post(self.api_url, headers=headers, json=data, timeout=40)
    #         response.raise_for_status()

    #         response_data = response.json()
    #         if response_data.get("choices"):
    #             generated_text = response_data["choices"][0].get("message", {}).get("content", "")
    #             logger.info("Common API response successful.")
    #             return generated_text
    #         else:
    #             logger.warning(f"Common API response missing choices. Full response: {response_data}")
    #             return None
    #     except requests.exceptions.HTTPError as http_err:
    #         logger.error(f"Common API HTTP error: {http_err} - Response: {http_err.response.text}")
    #         return None
    #     except Exception as e:
    #         logger.error(f"Error during common API request: {str(e)}", exc_info=True)
    #         return None

    def _get_provider_key(self, model_name: str) -> str:
        if not model_name: return 'openai'
        model_name_lower = model_name.lower()
        if 'gpt-4' in model_name_lower or 'gpt-3.5' in model_name_lower: return 'openai'
        if 'gemini' in model_name_lower or 'gemma' in model_name_lower: return 'gemini'
        if 'claude' in model_name_lower: return 'anthropic'
        if 'deepseek' in model_name_lower: return 'deepseek'
        logger.info(f"Unknown provider for model '{model_name}', defaulting to 'openai' parameter naming conventions.")
        return 'openai'

    # def get_params(self, model: str = None) -> Dict[str, Any]:
    #     current_model_name = model if model is not None else self.api_model
    #     provider_key = self._get_provider_key(current_model_name)

    #     params: Dict[str, Any] = {}

    #     if self.temperature is not None:
    #         params['temperature'] = self.temperature

    #     if self.max_response_tokens is not None:
    #         if provider_key in ['openai', 'deepseek', 'anthropic']: 
    #             params['max_tokens'] = self.max_response_tokens
    #         elif provider_key == 'gemini':
    #             params['maxOutputTokens'] = self.max_response_tokens

    #     if self.presence_penalty is not None and bool(self.gui.settings.get("USE_MODEL_PRESENCE_PENALTY", False)):
    #         if provider_key in ['openai', 'deepseek']:
    #             params['presence_penalty'] = self.presence_penalty
    #         elif provider_key == 'gemini': 
    #             logger.info(f"Presence penalty not directly supported by Gemini config for model {current_model_name}. Skipping.")

    #     params = self.remove_unsupported_params(current_model_name, params)
    #     return params

    # def get_final_params(self, model_name: str, messages: List[Dict]) -> Dict[str, Any]:
    #     final_params = {
    #         "model": model_name,
    #         "messages": messages,
    #         **self.get_params(model=model_name)
    #     }
    #     self.clear_endline_sim(final_params) # Added from other versions
    #     return final_params

    # def clear_endline_sim(self,params):
    #     for key, value in params.items():
    #         if isinstance(value, str):
    #             params[key] = value.replace("'\x00", "") 

    # def remove_unsupported_params(self,model,params):
    #     """Тут удаляем все лишние параметры"""
    #     if model in ("gemini-2.5-pro-exp-03-25","gemini-2.5-flash-preview-04-17"):
    #         params.pop("presencePenalty", None) # This was for Gemini, but get_params already skips it.
    #         # However, if presence_penalty (OpenAI style) was added by mistake, this would remove it.
    #         # More robustly, check for actual Gemini param names if they were added by mistake.
    #         # For now, keeping this as it was in the provided code.
    #     return params



    def _compress_history(self, messages_to_compress: List[Dict]) -> Optional[str]:
        """
        Сжимает историю диалога, используя LLM для создания краткой сводки.
        """
        try:
            # 1. Загрузка промпта из файла
            with open(self.history_compression_prompt_template, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            # 2. Форматирование сообщений для промпта
            formatted_messages = "\n".join([
                f"[{msg.get('time', '')}] [{'Player' if msg['role'] == 'user' else 'Character or System'}]: {msg['content']}"
                if msg.get('time')
                else f"[{'Player' if msg['role'] == 'user' else 'Character or System'}]: {msg['content']}"
                for msg in messages_to_compress
            ])

            # 3. Формирование полного промпта
            full_prompt = prompt_template.replace("{history_messages}", formatted_messages)
            full_prompt = full_prompt.replace("{your character}", self.current_character.name)

            # 4. Вызов LLM для получения сжатой сводки
            system_message = {"role": "system", "content": full_prompt}
            compressed_summary, success = self._generate_chat_response([system_message])

            if success and compressed_summary:
                logger.info("История успешно сжата.")
                return compressed_summary
            else:
                logger.warning("Не удалось сжать историю.")
                return None

        except Exception as e:
            logger.error(f"Ошибка при сжатии истории: {e}", exc_info=True)
            return None

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
        current_model = self.api_model
        if bool(self.gui.settings.get("gpt4free")):
            current_model = self.gpt4free_model
        elif bool(self.gui.settings.get("NM_API_REQ", False)):
            current_model = self.gui.settings.get("NM_API_MODEL")

        # Возвращаем лимит из настроек, если он задан и больше 0, иначе из маппинга
        if self.max_model_tokens > 0:
             return self.max_model_tokens
        return self._model_token_limits.get(current_model, 128000) # Возвращаем дефолт, если модель не найдена

    def get_current_context_token_count(self) -> int:
        """
        Считает количество токенов в текущем контексте, который будет отправлен в LLM.
        Это включает системные промпты, историю и текущий ввод пользователя.
        """
        if not self.hasTokenizer:
            return 0

        # Логика формирования combined_messages из generate_response
        combined_messages = []

        # 1. Системные промпты / память
        separate_prompts = bool(self.gui.settings.get("SEPARATE_PROMPTS", True))
        messages = self.current_character.get_full_system_setup_for_llm(separate_prompts)
        combined_messages.extend(messages)


        # Добавляем шахматы (если сформировано) - для точного подсчета нужно бы формировать, но пока заглушка
        # В реальной ситуации здесь нужно было бы вызвать логику формирования chess_system_message_for_llm_content
        # Для простоты пока не включаем, так как это усложнит подсчет без реального запроса
        # if hasattr(self.current_character, 'chess_state_queue') and self.current_character.get_variable("playingChess", False):
        #     combined_messages.append({"role": "system", "content": "Chess game state (placeholder)"})

        # 2. История памяти
        history_data = self.current_character.history_manager.load_history()
        llm_messages_history = history_data.get("messages", [])

        if self.current_character != self.GameMaster:
            llm_messages_history_limited = llm_messages_history[-self.memory_limit:]
        else:
            llm_messages_history_limited = llm_messages_history[-8:]

        # Применяем снижение качества к изображениям в истории, если включено
        if self.image_quality_reduction_enabled:
            llm_messages_history_limited = self._apply_history_image_quality_reduction(llm_messages_history_limited)

        combined_messages.extend(llm_messages_history_limited)

        # 3. Временные системные сообщения
        if self.infos_to_add_to_history:
            combined_messages.extend(self.infos_to_add_to_history)

        event_system_infos = self.current_character.get_system_infos(clear=False)
        if event_system_infos:
            combined_messages.extend(event_system_infos)

        # 4. Текущий ввод пользователя (если есть)
        user_input_from_gui = self.gui.user_entry.get("1.0", "end-1c").strip()
        if user_input_from_gui:
            combined_messages.append({"role": "user", "content": user_input_from_gui})

        total_tokens = 0
        for msg in combined_messages:
            if isinstance(msg, dict) and "content" in msg:
                content = msg["content"]
                if isinstance(content, str):
                    total_tokens += len(self.tokenizer.encode(content))
                elif isinstance(content, list):  # Для мультимодального контента
                    for item in content:
                        if item.get("type") == "text" and item.get("text"):
                            total_tokens += len(self.tokenizer.encode(item["text"]))
                        elif item.get("type") == "image_url" and item.get("image_url", {}).get("url"):
                            # Для изображений, добавляем фиксированное количество токенов или 0,
                            # так как tiktoken не считает токены изображений напрямую.
                            # Google Gemini Vision Pro оценивает изображения по-разному,
                            # но для общего подсчета можно использовать приближение.
                            # Например, 1 изображение = 1000 токенов (очень грубо)
                            total_tokens += 1000 # Примерное количество токенов за изображение
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

    def GetOtherKey(self) -> str | None:
        all_keys = []
        if self.api_key:
            all_keys.append(self.api_key)

        reserve_keys_str = self.gui.settings.get("NM_API_KEY_RES", "")
        if reserve_keys_str:
            all_keys.extend([key.strip() for key in reserve_keys_str.split() if key.strip()])

        seen = set()
        unique_keys = [x for x in all_keys if not (x in seen or seen.add(x))]

        if not unique_keys:
            logger.warning("No API keys configured (main or reserve).")
            return None

        if len(unique_keys) == 1:
            self.last_key = 0
            return unique_keys[0]
        self.last_key = (self.last_key + 1) % len(unique_keys)
        selected_key = unique_keys[self.last_key]

        logger.info(
            f"Selected API key index: {self.last_key} (masked: {SH(selected_key)}) from {len(unique_keys)} unique keys.")
        return selected_key

    def _format_multimodal_content_for_gemini(self, message_content):
        """Форматирует содержимое сообщения для Gemini API, поддерживая текст и изображения."""
        parts = []
        if isinstance(message_content, list):
            for item in message_content:
                if item["type"] == "text":
                    parts.append({"text": item["text"]})
                elif item["type"] == "image_url":
                    # Gemini API ожидает base64-кодированные изображения
                    parts.append(
                        {"inline_data": {"mime_type": "image/jpeg", "data": item["image_url"]["url"].split(',')[1]}})
        else:  # Если content - это просто строка (старый формат)
            parts.append({"text": message_content})
        return parts

    # region невошедшие (из старых версий, но могут быть полезны или заменены)
    def get_room_name(self, room_id):  # This seems generally useful, kept.
        room_names = {
            0: "Кухня",
            1: "Зал",
            2: "Комната",
            3: "Туалет",
            4: "Подвал"
        }
        return room_names.get(room_id, "?")

    # This method was in the "невошедшие" section of V1/V3 but has a different signature than add_temporary_system_info.
    # The current `add_temporary_system_info` which uses `self.infos_to_add_to_history` is the primary mechanism in the new system.
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

    # endregion

    # region Old but working

    def generate_request_gemini(self, combined_messages):
        params = self.get_params()
        self.clear_endline_sim(params)

        contents = []
        for msg in combined_messages:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            # Если роль "system", преобразуем в "user" с префиксом
            if role == "system":
                role = "user"
                if isinstance(msg["content"], list):
                    # Если content уже список частей, добавляем системный промт как первую текстовую часть
                    msg_content = [{"type": "text", "text": "[System Prompt]:"}] + msg["content"]
                else:
                    # Если content - строка, добавляем префикс к строке
                    msg_content = f"[System Prompt]: {msg['content']}"
            else:
                msg_content = msg["content"]

            contents.append({
                "role": role,
                "parts": self._format_multimodal_content_for_gemini(msg_content)
            })

        data = {
            "contents": contents,
            "generationConfig": params
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        logger.info("Отправляю запрос к Gemini.")
        logger.debug(f"Отправляемые данные (Gemini): {data}")  # Добавляем логирование содержимого
        save_combined_messages(data, "SavedMessages/last_gemini_log")
        response = requests.post(self.api_url, headers=headers, json=data)

        if response.status_code == 200:
            response_data = response.json()
            generated_text = response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get(
                "text", "")
            logger.info("Answer: \n" + generated_text)
            return generated_text
        else:
            logger.error(f"Ошибка: {response.status_code}, {response.text}")
            return None

    def generate_request_common(self, combined_messages):
        data = {
            "model": self.gui.settings.get("NM_API_MODEL"),
            "messages": [
                {"role": msg["role"], "content": msg["content"]} for msg in combined_messages
            ]
        }

        # Объединяем params в data
        params = self.get_params()
        self.clear_endline_sim(params)
        data.update(params)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        logger.info("Отправляю запрос к RequestCommon.")
        logger.debug(f"Отправляемые данные (RequestCommon): {data}")  # Добавляем логирование содержимого
        save_combined_messages(data, "SavedMessages/last_request_common_log")
        response = requests.post(self.api_url, headers=headers, json=data)

        if response.status_code == 200:
            response_data = response.json()
            # Формат ответа DeepSeek отличается от Gemini
            generated_text = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.info("Common request: \n" + generated_text)
            return generated_text
        else:
            logger.error(f"Ошибка: {response.status_code}, {response.text}")
            return None

    def get_params(self, model=None):
        current_model = model if model is not None else self.api_model
        provider_key = self._get_provider_key(current_model)

        params = {}

        # Температура часто называется одинаково
        if self.temperature is not None:
            params['temperature'] = self.temperature

        # Макс. токены - названия могут различаться
        if bool(self.gui.settings.get("USE_MODEL_MAX_RESPONSE_TOKENS")) and self.max_response_tokens is not None:
            if provider_key == 'openai' or provider_key == 'deepseek' or provider_key == 'anthropic':
                params['max_tokens'] = self.max_response_tokens
            elif provider_key == 'gemini':
                params['maxOutputTokens'] = self.max_response_tokens
            # Добавьте другие провайдеры

        # Штраф за присутствие - названия могут различаться, и параметр может отсутствовать у некоторых провайдеров
        if bool(self.gui.settings.get("USE_MODEL_PRESENCE_PENALTY")) and self.presence_penalty is not None:
            if provider_key == 'openai' or provider_key == 'deepseek':
                params['presence_penalty'] = self.presence_penalty
            elif provider_key == 'gemini':
                params['presencePenalty'] = self.presence_penalty

        if bool(self.gui.settings.get("USE_MODEL_FREQUENCY_PENALTY")) and self.frequency_penalty is not None:
            if provider_key == 'openai' or provider_key == 'deepseek':
                params['frequency_penalty'] = self.frequency_penalty
            elif provider_key == 'gemini':
                params['frequencyPenalty'] = self.frequency_penalty

        if bool(self.gui.settings.get("USE_MODEL_LOG_PROBABILITY")) and self.log_probability is not None:
            if provider_key == 'openai' or provider_key == 'deepseek':
                params['logprobs'] = self.log_probability  # OpenAI/DeepSeek
            # Gemini не имеет прямого аналога logprobs в том же виде

        # Добавляем top_k, top_p и thought_process, если они заданы
        if bool(self.gui.settings.get("USE_MODEL_TOP_K")) and self.top_k > 0:
            if provider_key == 'openai' or provider_key == 'deepseek' or provider_key == 'anthropic':
                params['top_k'] = self.top_k
            elif provider_key == 'gemini':
                params['topK'] = self.top_k

        if bool(self.gui.settings.get("USE_MODEL_TOP_P")):
            if provider_key == 'openai' or provider_key == 'deepseek' or provider_key == 'anthropic':
                params['top_p'] = self.top_p
            elif provider_key == 'gemini':
                params['topP'] = self.top_p

        if bool(self.gui.settings.get("USE_MODEL_THINKING_BUDGET")):
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

    def get_final_params(self, model, messages):
        """Модель, сообщения и параметры"""
        final_params = {
            "model": model,
            "messages": messages,
        }
        final_params.update(self.get_params(model))

        self.clear_endline_sim(final_params)

        return final_params

    def clear_endline_sim(self, params):
        for key, value in params.items():
            if isinstance(value, str):
                params[key] = value.replace("'\x00", "").replace("\x00", "")

    def remove_unsupported_params(self, model, params):
        """Тут удаляем все лишние параметры"""
        if model in ("gemini-2.5-pro-exp-03-25", "gemini-2.5-flash-preview-04-17"):
            params.pop("presencePenalty", None)
        return params

    def process_commands(self, response, messages):
        """
        Обрабатывает команды типа <c>...</c> в ответе.
        Команды могут быть: "Достать бензопилу", "Выключить игрока" и другие.
        """
        start_tag = "<c>"
        end_tag = "</c>"
        search_start = 0  # Указатель для поиска новых команд

        while start_tag in response[search_start:] and end_tag in response[search_start:]:
            try:
                # Находим команду
                start_index = response.index(start_tag, search_start) + len(start_tag)
                end_index = response.index(end_tag, start_index)
                command = response[start_index:end_index]

                # Логируем текущую команду
                logger.info(f"Обработка команды: {command}")

                # Обработка команды
                if command == "Достать бензопилу":
                    ...
                    #add_temporary_system_message(messages, "Игрок был не распилен, произошла ошибка")

                    #if self.gui:
                    #   self.gui.close_app()

                elif command == "Выключить игрока":
                    ...
                    #add_temporary_system_message(messages, "Игрок был отпавлен в главное меню, но скоро он вернется...")

                    #if self.gui:
                    #   self.gui.close_app()

                else:
                    # Обработка неизвестных команд
                    #add_temporary_system_message(messages, f"Неизвестная команда: {command}")
                    logger.info(f"Неизвестная команда: {command}")

                # Сдвигаем указатель поиска на следующий символ после текущей команды
                search_start = end_index + len(end_tag)

            except ValueError as e:
                self.add_temporary_system_message(messages, f"Ошибка обработки команды: {e}")
                break

        return response

    #region TokensCounting

    #endregion

