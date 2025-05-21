import concurrent.futures
import time

import requests
import tiktoken
from openai import OpenAI
#from huggingface_hub import HfApi
#from mistralai import Mistral as MistralClient

import re

from Logger import logger
from characters import *
from character import GameMaster, SpaceCartridge, DivanCartridge
from utils.PipInstaller import PipInstaller
import importlib
from utils import *


class ChatModel:
    def __init__(self, gui, api_key, api_key_res, api_url, api_model, api_make_request, pip_installer: PipInstaller):

        # Временное решение, чтобы возвращать работоспособность старого формата

        self.last_key = 0
        self.OldSystem = False

        self.gui = gui

        self.pip_installer = pip_installer  # Сохраняем установщик

        # Инициализация переменных g4f
        self.g4fClient = None
        self.g4f_available = False
        self._initialize_g4f()

        # try:
        #     from g4f.client import Client as g4fClient
        # except:
        #     logger.info("Не установлен G4F, устанавливаю стабильную версию g4f==0.4.7.7")
        #     #pip install --upgrade g4f==0.4.7.7

        try:
            self.api_key = api_key
            self.api_key_res = api_key_res
            self.api_url = api_url
            self.api_model = api_model
            self.gpt4free_model = self.gui.settings.get("gpt4free_model")
            self.makeRequest = api_make_request

            # self.g4fClient = g4fClient()
            # logger.info(f"g4fClient успешно инициализирован. Какой же кайф, будто бы теперь без None живем")

            #self.hugging_face_client = HfApi()
            #self.mistral_client = MistralClient()

            self.client = OpenAI(api_key=self.api_key, base_url=self.api_url)

            logger.info("Со старта удалось запустить OpenAi client")
        except:
            logger.info("Со старта не получилось запустить OpenAi client")

        try:
            self.tokenizer = tiktoken.encoding_for_model("gpt-4o-mini")
            self.hasTokenizer = True
        except:
            logger.info("Тиктокен не сработал( Ну и пофиг, на билдах он никогда и не работал")
            self.hasTokenizer = False

        # Инициализация переменных
        self.max_response_tokens = int(
            self.gui.settings.get("MODEL_MAX_RESPONSE_TOKENS", 3200))  # Получаем из настроек, если есть, иначе дефолт
        self.temperature = float(self.gui.settings.get("MODEL_TEMPERATURE", 0.5))
        self.presence_penalty = float(self.gui.settings.get("MODEL_PRESENCE_PENALTY", 0.0))  #

        """ Очень спорно уже """
        self.cost_input_per_1000 = 0.0432
        self.cost_response_per_1000 = 0.1728
        """"""

        self.memory_limit = int(self.gui.settings.get("MODEL_MESSAGE_LIMIT", 40))  # Ограничение на сообщения

        """New System"""
        self.current_character = None
        self.current_character_to_change = str(self.gui.settings.get("CHARACTER"))
        self.characters = None

        """То, что нужно будет убрать в одну переменную"""

        self.distance = 0.0
        self.roomPlayer = -1
        self.roomMita = -1

        self.nearObjects = ""
        self.actualInfo = ""

        """То, что нужно будет убрать в одну переменную"""

        self.LongMemoryRememberCount = 0

        self.infos = []

        # Загрузка данных из файлов

        self.init_characters()

        self.HideAiData = True

        # Настройки реквестов
        self.max_request_attempts = int(self.gui.settings.get("MODEL_MESSAGE_ATTEMPTS_COUNT", 5))
        self.request_delay = float(self.gui.settings.get("MODEL_MESSAGE_ATTEMPTS_TIME", 0.20))

    def _initialize_g4f(self):
        """Пытается импортировать g4f, установить если не найден, и инициализировать клиент."""
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

            target_version = self.gui.settings.get("G4F_VERSION", "4.7.7")
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
                        from g4f.client import Client as g4fClient
                        logger.info("Повторный импорт g4f успешен. Попытка инициализации клиента...")
                        try:
                            self.g4fClient = g4fClient()
                            self.g4f_available = True
                            logger.info("g4fClient успешно инициализирован после установки.")
                        except Exception as e:
                            logger.error(f"Ошибка при инициализации g4fClient после установки: {e}")
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
        """
        Инициализирует возможных персонажей
        """
        self.crazy_mita_character = CrazyMita("Crazy",
                                              "/speaker mita",
                                              short_name="CrazyMita",
                                              miku_tts_name="/set_person CrazyMita",
                                              silero_turn_off_video=True)
        self.cappy_mita_character = CappyMita("Cappy",
                                              "/speaker cap",
                                              short_name="CappieMita",
                                              miku_tts_name="/set_person CapMita",
                                              silero_turn_off_video=True)
        self.cart_space = SpaceCartridge("Cart_portal",
                                         "/speaker  wheatley",
                                         short_name="Player",
                                         miku_tts_name="/set_person Player",
                                         silero_turn_off_video=True)
        self.kind_mita_character = KindMita("Kind",
                                            "/speaker kind",
                                            short_name="MitaKind",
                                            miku_tts_name="/set_person KindMita",
                                            silero_turn_off_video=True)
        self.shorthair_mita_character = ShortHairMita("ShortHair",
                                                      "/speaker  shorthair",
                                                      short_name="ShorthairMita",
                                                      miku_tts_name="/set_person ShortHairMita",
                                                      silero_turn_off_video=True)
        self.mila_character = MilaMita("Mila",
                                       "/speaker mila",
                                       short_name="Mila",
                                       miku_tts_name="/set_person MilaMita",
                                       silero_turn_off_video=True)
        self.sleepy_character = SleepyMita("Sleepy",
                                           "/speaker dream",
                                           short_name="SleepyMita",
                                           miku_tts_name="/set_person SleepyMita",
                                           silero_turn_off_video=True)
        self.cart_divan = DivanCartridge("Cart_divan",
                                         "/speaker engineer",
                                         short_name="Player",
                                         miku_tts_name="/set_person Player",
                                         silero_turn_off_video=True)
        self.creepy_character = CreepyMita("Creepy",
                                           "/speaker ghost",
                                           short_name="GhostMita",  # TODO: вместо крипи будет гост
                                           miku_tts_name="/set_person GhostMita",
                                           silero_turn_off_video=True)  #Спикер на рандом поставил
        self.GameMaster = GameMaster("GameMaster",
                                     "/speaker dryad",
                                     short_name="PhoneMita",  # TODO: чето подобрать
                                     miku_tts_name="/set_person PhoneMita",
                                     silero_turn_off_video=True)  # Спикер на рандом поставил

        # Словарь для сопоставления имен персонажей с их объектами
        self.characters = {
            self.crazy_mita_character.name: self.crazy_mita_character,
            self.kind_mita_character.name: self.kind_mita_character,
            self.cappy_mita_character.name: self.cappy_mita_character,
            self.cart_space.name: self.cart_space,
            self.cart_divan.name: self.cart_divan,
            self.shorthair_mita_character.name: self.shorthair_mita_character,
            self.mila_character.name: self.mila_character,
            self.sleepy_character.name: self.sleepy_character,
            self.creepy_character.name: self.creepy_character,
            self.GameMaster.name: self.GameMaster
        }

        self.current_character = self.crazy_mita_character

    def get_all_mitas(self):
        logger.info(f"Characters {self.characters.keys()}")
        return list(self.characters.keys())

    def update_openai_client(self, reserve_key=False):
        logger.info("Попытка обновить клиент")
        if reserve_key and self.api_key_res != "":
            logger.info("С резервным ключом")
            key = reserve_key
        else:
            logger.info("С основным ключом")
            key = self.api_key

        try:
            if self.api_url != "":
                logger.info("И ключ и ссылка")
                self.client = OpenAI(api_key=key,
                                     base_url=self.api_url)
            else:
                logger.info("Только ключ")
                self.client = OpenAI(api_key=key)
        except Exception as e:
            logger.info(f"update_openai_client не сработал {e}")

    def generate_response(self, user_input, system_input=""):

        self.check_change_current_character()

        # Загрузка истории из файла
        data = self.current_character.load_history()
        messages = data.get("messages", [])
        if len(self.infos) > 0:
            logger.info("Попытался расширить messages")
            messages.extend(self.infos)
            self.infos.clear()
        self.current_character.process_logic(messages)

        # Добавление информации о времени и пользовательского ввода

        messages = self.current_character.add_context(messages)
        messages = self._add_input(user_input, system_input, messages)

        # Ограничение на количество сообщений
        if self.current_character == self.GameMaster:
            messages = messages[-8:]
        else:
            messages = messages[-self.memory_limit:]

        # Обновление текущего настроения
        timed_system_message = self.current_character.current_variables()

        combined_messages, messages = self._combine_messages_character(self.current_character, messages,
                                                                       timed_system_message)

        # Генерация ответа с использованием клиента
        try:

            response, success = self._generate_chat_response(combined_messages)

            if not success:
                logger.warning("Неудачная генерация")
                return response
            elif response == "":
                logger.warning("Пустая генерация")
                return response

            response_message = {
                "role": "assistant",
                "content": response
            }
            messages.append(response_message)

            # Процессинг ответа: изменяем показатели и сохраняем историю
            response = self.current_character.process_response(response)

            logger.info(f"До фразы {response}")

            if self.current_character == self.GameMaster and not bool(self.gui.settings.get("GM_VOICE")):
                pass
            else:
                self.gui.textToTalk = self.process_text_to_voice(response)
                self.gui.textSpeaker = self.current_character.silero_command
                self.gui.textSpeakerMiku = self.current_character.miku_tts_name

                self.gui.silero_turn_off_video = self.current_character.silero_turn_off_video
                logger.info("self.gui.textToTalk: " + self.gui.textToTalk)
                logger.info("self.gui.textSpeaker: " + self.gui.textSpeaker)

            self.current_character.safe_history(messages, timed_system_message)

            self.gui.update_debug_info()
            return response
        except Exception as e:
            logger.error(f"Ошибка на фазе генерации: {e}")
            return f"Ошибка на фазе генерации: {e}"

    def save_chat_history(self):
        self.current_character.safe_history()

    def check_change_current_character(self):
        """
        Проверяет и изменяет текущего персонажа на основе значения `current_character_to_change`.

        Если `current_character_to_change` соответствует имени одного из персонажей,
        текущий персонаж (`current_character`) обновляется, а `current_character_to_change` сбрасывается.
        """
        if not self.current_character_to_change:
            return  # Если строка пустая, ничего не делаем

        # Проверяем, есть ли имя в словаре
        if self.current_character_to_change in self.characters:
            logger.info(f"Меняю персонажа на {self.current_character_to_change}")
            self.current_character = self.characters[self.current_character_to_change]
            self.current_character_to_change = ""  # Сбрасываем значение

    def _add_input(self, user_input, system_input, messages):
        """Добавляет то самое последнее сообщение"""

        if system_input != "":
            messages.append({"role": "system", "content": system_input})
        if user_input != "":
            messages.append({"role": "user", "content": user_input})
        return messages

    def get_room_name(self, room_id):
        # Сопоставление ID комнаты с её названием
        room_names = {
            0: "Кухня",  # Кухня
            1: "Зал",  # Главная комната
            2: "Комната",  # Спальня
            3: "Туалет",  # Туалет
            4: "Подвал"  # Подвал
        }

        # Возвращаем название комнаты, если оно есть, иначе возвращаем сообщение о неизвестной комнате
        return room_names.get(room_id, "?")

    def _combine_messages_character(self, character, messages, timed_system_message):
        """Комбинирование всех сообщений перед отправкой"""
        # Чем выше здесь, тем дальше от начала будет

        combined_messages = character.prepare_fixed_messages()

        # Добавляем timed_system_message, если это словарь
        if isinstance(timed_system_message, dict) and timed_system_message["content"] != "":
            combined_messages.append(timed_system_message)
            logger.info("timed_system_message успешно добавлено.")

        if self.nearObjects != "" and self.nearObjects != "-":
            text = f"В радиусе от тебя следующие объекты (object tree) {self.nearObjects}"
            messageNear = {"role": "system", "content": text}
            combined_messages.append(messageNear)

        if self.actualInfo != "" and self.actualInfo != "-":
            messageActual = {"role": "system", "content": self.actualInfo}
            combined_messages.append(messageActual)

        # Добавляем messages, если они не пустые
        if messages:
            combined_messages.extend(messages)
            logger.info(f"messages успешно добавлены. Количество: {len(messages)}")
        messages = character.prepare_float_messages(messages)

        #combined_messages = character.add_context(combined_messages)

        return combined_messages, messages

    def _generate_chat_response(self, combined_messages):
        """Генерирует ответ с использованием единого цикла"""
        max_attempts = self.max_request_attempts  # Общее максимальное количество попыток
        retry_delay = self.request_delay  # Задержка между попытками в секундах
        request_timeout = 45  # Таймаут для запросов в секундах

        # Определяем провайдера для первой попытки
        #use_gemini = self.makeRequest and not bool(self.gui.settings.get("gpt4free"))

        self._log_generation_start()
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Попытка генерации {attempt}/{max_attempts}")
            response = None

            # Логируем начало генерации

            save_combined_messages(combined_messages)

            try:
                # Через реквест
                if bool(self.gui.settings.get("NM_API_REQ", False)):  #

                    if bool(self.gui.settings.get("GEMINI_CASE", False)):
                        combined_messages = self._format_messages_for_gemini(combined_messages)

                    response = self._execute_with_timeout(
                        self._generate_request_response,
                        args=(combined_messages,),
                        timeout=request_timeout
                    )

                # Через openapi
                else:
                    # Переключаем ключи начиная со второй попытки

                    if bool(self.gui.settings.get("GPT4FREE_LAST_ATTEMPT")) and attempt >= max_attempts:
                        logger.warning("Пробую gtp4free как последнюю попытку")
                        response = self._generate_openapi_response(combined_messages, use_gpt4free=True)

                    else:
                        if attempt > 1:
                            key = self.GetOtherKey()
                            logger.info(f"Пробую другой ключ {self.last_key} {key}")
                            self.update_openai_client(reserve_key=key)

                        response = self._generate_openapi_response(combined_messages)

                if response:
                    response = self._clean_response(response)
                    logger.info(f"Успешный ответ")
                    if response:
                        return response, True

            except Exception as e:
                logger.error(f"Ошибка генерации: {str(e)}")

            # Если ответа нет - ждем перед следующей попыткой
            if attempt < max_attempts:
                logger.warning(f"Ожидание {retry_delay} сек. перед повторной попыткой...")
                time.sleep(retry_delay)

        logger.error("Все попытки исчерпаны")
        return None, False

    def _execute_with_timeout(self, func, args=(), kwargs={}, timeout=30):
        """Выполняет функцию с ограничением по времени"""
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)

    def _log_generation_start(self):
        logger.info("Перед отправкой на генерацию")

        if bool(self.gui.settings.get("gpt4free")):
            logger.info(f"gpt4free model {self.gpt4free_model}")
        else:
            logger.info(f"API Key: {SH(self.api_key)}")
            logger.info(f"API Key res: {SH(self.api_key_res)}")
            logger.info(f"API URL: {self.api_url}")
            logger.info(f"API Model: {self.api_model}")
            logger.info(f"Make Request: {self.makeRequest}")
            logger.info(f"NM_API_REQ {self.gui.settings.get("NM_API_REQ", False)}")
            logger.info(f"GEMINI_CASE {self.gui.settings.get("GEMINI_CASE", False)}")

    def _format_messages_for_gemini(self, combined_messages):
        #TODO Надо кароче первые сообщения сделать системными

        formatted_messages = []
        for msg in combined_messages:
            if msg["role"] == "system":
                formatted_messages.append({"role": "user", "content": f"[System Prompt]: {msg['content']}"})
            else:
                formatted_messages.append(msg)
        save_combined_messages(formatted_messages, "Gem")
        return formatted_messages

    def _generate_request_response(self, formatted_messages):
        try:
            if bool(self.gui.settings.get("GEMINI_CASE", False)):
                response = self.generate_request_gemini(formatted_messages)
            else:
                response = self.generate_request_common(formatted_messages)
            logger.info(f"Ответ Gemini: {response}", )
            return response
        except Exception as e:
            logger.error("Что-то не так при генерации Gemini", str(e))
            return None

    def _generate_openapi_response(self, combined_messages, use_gpt4free=False):
        if not self.client:
            logger.info("Попытка переподключения клиента")
            self.update_openai_client()

        try:

            logger.info(f"Перед запросом  {len(combined_messages)}")

            if bool(self.gui.settings.get("gpt4free")) or use_gpt4free:
                logger.info("gpt4free case")

                self.gpt4free_model = self.gui.settings.get("gpt4free_model")
                self.change_last_message_to_user_for_gemini(self.gpt4free_model, combined_messages)

                final_params = self.get_final_params(self.gpt4free_model, combined_messages)
                completion = self.g4fClient.chat.completions.create(**final_params)
            else:
                self.change_last_message_to_user_for_gemini(self.api_model, combined_messages)

                # Сообщения фильтруются по структуре отдельно, не как простой параметр}
                final_params = self.get_final_params(self.api_model, combined_messages)
                completion = self.client.chat.completions.create(**final_params)
            logger.info(f"after completion{completion}")

            if completion:
                if completion.choices:
                    response = completion.choices[0].message.content
                    logger.info(f"response {response}")
                    return response.lstrip("\n")
                else:
                    logger.warning("completion.choices пусто")
                    logger.warning(completion)
                    self.try_print_error(completion)
                    return None
            else:
                logger.warning("completion пусто")
                return None

        except Exception as e:
            logger.error(f"Что-то не так при генерации OpenAI: {str(e)}")
            return None

    def change_last_message_to_user_for_gemini(self, api_model, combined_messages):
        if "gemini" in api_model or "gemma" in api_model and combined_messages[-1]["role"] == "system":
            logger.info("gemini последнее системное сообщение на юзерское")
            combined_messages[-1]["role"] = "user"
            combined_messages[-1]["content"] = "[SYSTEM INFO]" + combined_messages[-1]["content"]

    def _save_and_calculate_cost(self, combined_messages):
        save_combined_messages(combined_messages)
        try:
            self.gui.last_price = calculate_cost_for_combined_messages(self, combined_messages,
                                                                       self.cost_input_per_1000)
            logger.info(f"Calculated cost: {self.gui.last_price}")
        except Exception as e:
            ...
            logger.info("Не получилось сделать с токенайзером, это скорее всего особенность билда")
            #logger.info("Не получилось сделать с токенайзером", str(e))

    def try_print_error(self, completion):
        try:
            if not completion or not hasattr(completion, 'error'):
                logger.warning("Ошибка: объект completion не содержит информации об ошибке.")
                return

            error = completion.error
            if not error:
                logger.warning("Ошибка: объект completion.error пуст.")
                return

            # Основное сообщение об ошибке

            logger.warning(f"ChatCompletion ошибка: {error}")

            # Дополнительные метаданные об ошибке
            if hasattr(error, 'metadata'):
                metadata = error.metadata
                if metadata:
                    logger.warning("Метаданные ошибки:")
                    if hasattr(metadata, 'raw'):
                        logger.warning(f"Raw данные: {metadata.raw}")
                    if hasattr(metadata, 'provider_name'):
                        logger.warning(f"Провайдер: {metadata.provider_name}")
                    if hasattr(metadata, 'isDownstreamPipeClean'):
                        logger.warning(f"Состояние downstream: {metadata.isDownstreamPipeClean}")
                    if hasattr(metadata, 'isErrorUpstreamFault'):
                        logger.warning(f"Ошибка upstream: {metadata.isErrorUpstreamFault}")
                else:
                    logger.warning("Метаданные ошибки отсутствуют.")
            else:
                logger.warning("Метаданные ошибки недоступны.")

        except Exception as e:
            logger.error(f"Ошибка при попытке обработать ошибку ChatCompletion: {e}")

    def _clean_response(self, response):
        try:
            # Проверяем, что response является строкой
            if not isinstance(response, str):
                logger.warning(f"Ожидалась строка, но получен тип: {type(response)}")
                return response  # Возвращаем исходное значение, если это не строка

            # Убираем префиксы и суффиксы
            if response.startswith("```\n"):
                response = response.lstrip("```\n")
            if response.endswith("\n```\n"):
                response = response.removesuffix("\n```\n")
        except Exception as e:
            logger.error(f"Проблема с префиксами или постфиксами: {e}")
        return response

    def generate_request_gemini(self, combined_messages):
        params = self.get_params()

        data = {
            "contents": [
                {"role": "model" if msg["role"] == "assistant" else msg["role"], "parts": [{"text": msg["content"]}]}
                for msg in combined_messages
            ],
            "generationConfig": params
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        logger.info("Отправляю запрос к Gemini")
        save_combined_messages(data, "Gem2")
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
        data.update(params)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        logger.info("Отправляю запрос к RequestCommon")
        save_combined_messages(data, "RequestCommon")
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

    # Предполагаем, что у вас есть способ определить провайдера по имени модели
    def _get_provider_key(self, model_name):
        model_name = model_name.lower()
        if 'gpt' in model_name:
            return 'openai'
        elif bool(self.gui.settings.get("GEMINI_CASE", False)):
            return 'gemini'
        elif 'claude' in model_name:
            return 'anthropic'
        elif 'deepseek' in model_name:
            return 'deepseek'
        # Добавьте проверки для других провайдеров
        else:
            # Действие по умолчанию, если провайдер неизвестен (вызвать ошибку или использовать маппинг по умолчанию)
            print(f"Warning: Unknown model provider for model '{model_name}'. Defaulting to 'openai' rules.")
            return 'openai'  # Или можно вернуть None, чтобы добавить только общие параметры

    def get_params(self, model=None):
        current_model = model if model is not None else self.api_model
        provider_key = self._get_provider_key(current_model)

        params = {}

        # Температура часто называется одинаково
        if self.temperature is not None:
            params['temperature'] = self.temperature

        # Макс. токены - названия могут различаться
        if self.max_response_tokens is not None:
            if provider_key == 'openai' or provider_key == 'deepseek' or provider_key == 'anthropic':
                params['max_tokens'] = self.max_response_tokens
            elif provider_key == 'gemini':
                params['maxOutputTokens'] = self.max_response_tokens
            # Добавьте другие провайдеры

        # Штраф за присутствие - названия могут различаться, и параметр может отсутствовать у некоторых провайдеров
        if self.presence_penalty is not None and bool(self.gui.settings.get("USE_MODEL_PRESENCE_PENALTY")):
            if provider_key == 'openai' or provider_key == 'deepseek':
                params['presence_penalty'] = self.presence_penalty
            elif provider_key == 'gemini':
                params['presencePenalty'] = self.presence_penalty
            # Anthropic, например, не имеет прямого аналога этого параметра в том же виде.
            # Поэтому мы просто не добавляем его для Anthropic.

        # Добавьте другие параметры аналогично
        # if self.some_other_param is not None:
        #     if provider_key == 'openai': params['openai_name'] = self.some_other_param
        #     elif provider_key == 'gemini': params['gemini_name'] = self.some_other_param
        #     # и т.д.

        params = self.remove_unsupported_params(current_model,params)

        return params

    def get_final_params(self, model, messages):
        """Модель, сообщения и параметры"""
        final_params = {
            "model": model,
            "messages": messages,
        }
        final_params.update(self.get_params(model))

        return final_params

    def remove_unsupported_params(self,model,params):
        """Тут удаляем все лишние параметры"""
        if model in ("gemini-2.5-pro-exp-03-25","gemini-2.5-flash-preview-04-17"):
            params.pop("presencePenalty")
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

    def process_text_to_voice(self, text):
        # Проверяем, что текст является строкой (если это байты, декодируем)
        if isinstance(text, bytes):
            try:
                text = text.decode("utf-8")  # Декодируем в UTF-8
            except UnicodeDecodeError:
                # Если UTF-8 не подходит, пробуем определить кодировку
                import chardet
                encoding = chardet.detect(text)["encoding"]
                text = text.decode(encoding)

        # Удаляем все теги и их содержимое
        clean_text = re.sub(r"<[^>]+>.*?</[^>]+>", "", text)
        clean_text = re.sub(r"<.*?>", "", clean_text)
        clean_text = replace_numbers_with_words(clean_text)

        #clean_text = transliterate_english_to_russian(clean_text)

        # Если текст пустой, заменяем его на "Вот"
        if clean_text.strip() == "":
            clean_text = "Вот"

        return clean_text

    def reload_promts(self):
        logger.info("Перезагрузка промптов")

        self.current_character.init()
        self.current_character.process_response()

    def add_temporary_system_message(self, messages, content):
        """
        Добавляет одноразовое системное сообщение в список сообщений.

        :param messages: Список сообщений, в который добавляется системное сообщение.
        :param content: Текст системного сообщения.
        """
        system_message = {
            "role": "system",
            "content": content
        }
        messages.append(system_message)

    def add_temporary_system_info(self, content):
        """
        Добавляет одноразовое системное сообщение в список сообщений.

        :param messages: Список сообщений, в который добавляется системное сообщение.
        :param content: Текст системного сообщения.
        """
        system_info = {
            "role": "system",
            "content": content
        }
        self.infos.append(system_info)
        #self.current_character.add_message_to_history(system_info)

    #region TokensCounting
    def calculate_cost(self, user_input):
        # Загружаем историю
        history_data = self.load_history()

        # Получаем только сообщения
        messages = history_data.get('messages', [])

        # Добавляем новое сообщение от пользователя
        messages.append({"role": "user", "content": user_input})

        # Считаем токены
        token_count = self.count_tokens(messages)

        # Рассчитываем стоимость
        cost = (token_count / 1000) * self.cost_input_per_1000

        return token_count, cost

    def count_tokens(self, messages):
        return sum(len(self.tokenizer.encode(msg["content"])) for msg in messages if
                   isinstance(msg, dict) and "content" in msg)

    #endregion
    def GetOtherKey(self):
        """
        Получаем ключ на замену сломанному
        :return:
        """
        keys = [self.api_key] + self.gui.settings.get("NM_API_KEY_RES").split()
        count = len(keys)

        i = self.last_key + 1

        if i >= count:
            i = 0

        self.last_key = i

        return keys[i]
