import uuid
from AudioHandler import AudioHandler
from Logger import logger
from SettingsManager import SettingsManager, CollapsibleSection
from chat_model import ChatModel
from web.client import MikuTTSClient
from server import ChatServer

from Silero import TelegramBotHandler

import gettext

import os
import base64
import json
import glob

import asyncio
import threading

import binascii

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

from utils import SH

import sounddevice as sd
from SpeechRecognition import SpeechRecognition


#gettext.bindtextdomain('NeuroMita', '/Translation')
#gettext.textdomain('NeuroMita')
#_ = gettext.gettext
#_ = str  # Временно пока чтобы не падало


def getTranslationVariant(ru_str, en_str=""):
    if en_str and SettingsManager.get("LANGUAGE") == "EN":
        return en_str

    return ru_str


_ = getTranslationVariant  # Временно, мб


class ChatGUI:
    def __init__(self):

        self.silero_connected = False
        self.game_connected = False
        self.ConnectedToGame = False

        self.chat_window = None
        self.token_count_label = None

        self.bot_handler = None
        self.bot_handler_ready = False

        self.selected_microphone = ""
        self.device_id = 0
        self.user_entry = None
        self.user_input = ""

        self.api_key = ""
        self.api_key_res = ""
        self.api_url = ""
        self.api_model = ""

        self.makeRequest = False
        self.api_hash = ""
        self.api_id = ""
        self.phone = ""

        try:
            target_folder = "Settings"
            os.makedirs(target_folder, exist_ok=True)
            self.config_path = os.path.join(target_folder, "settings.json")

            self.load_api_settings(False)  # Загружаем настройки при инициализации
            self.settings = SettingsManager(self.config_path)
        except Exception as e:
            logger.info("Не удалось удачно получить из системных переменных все данные", e)
            self.settings = SettingsManager("Settings/settings.json")

        self.model = ChatModel(self, self.api_key, self.api_key_res, self.api_url, self.api_model,
                               self.settings.get("gpt4free_model"),
                               self.makeRequest)
        self.server = ChatServer(self, self.model)
        self.server_thread = None
        self.running = False
        self.start_server()

        self.textToTalk = ""
        self.textSpeaker = "/Speaker Mita"
        self.silero_turn_off_video = False

        self.dialog_active = False

        self.patch_to_sound_file = ""
        self.id_sound = -1
        self.instant_send = False
        self.waiting_answer = False

        self.root = tk.Tk()
        self.root.title("Чат с NeuroMita")

        self.last_price = ""

        self.delete_all_sound_files()
        self.setup_ui()

        try:
            self.load_mic_settings()
        except Exception as e:
            logger.info("Не удалось удачно получить настройки микрофона", e)

        # Событие для синхронизации потоков
        self.loop_ready_event = threading.Event()

        self.loop = None  # Переменная для хранения ссылки на цикл событий
        self.asyncio_thread = threading.Thread(target=self.start_asyncio_loop, daemon=True)
        self.asyncio_thread.start()

        self.start_silero_async()

        SpeechRecognition.speach_recognition_start(self.device_id, self.loop)

        # Запуск проверки переменной textToTalk через after
        self.root.after(150, self.check_text_to_talk_or_send)

    def start_asyncio_loop(self):
        """Запускает цикл событий asyncio в отдельном потоке."""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            logger.info("Цикл событий asyncio успешно запущен.")
            self.loop_ready_event.set()  # Сигнализируем, что цикл событий готов
            try:
                self.loop.run_forever()
            except Exception as e:
                logger.info(f"Ошибка в цикле событий asyncio: {e}")
            finally:
                self.loop.close()
        except Exception as e:
            logger.info(f"Ошибка при запуске цикла событий asyncio: {e}")
            self.loop_ready_event.set()  # Сигнализируем даже в случае ошибки

    def start_silero_async(self):
        """Отправляет задачу для запуска Silero в цикл событий."""
        logger.info("Ожидание готовности цикла событий...")
        self.loop_ready_event.wait()  # Ждем, пока цикл событий будет готов
        if self.loop and self.loop.is_running():
            logger.info("Запускаем Silero через цикл событий.")
            asyncio.run_coroutine_threadsafe(self.startSilero(), self.loop)
        else:
            logger.info("Ошибка: Цикл событий asyncio не запущен.")

    async def startSilero(self):
        """Асинхронный запуск обработчика Telegram Bot."""
        logger.info("Telegram Bot запускается!")
        try:
            if not self.api_id or not self.api_hash or not self.phone:
                logger.info("Ошибка: отсутствуют необходимые данные для Telegram бота")
                self.silero_connected.set(False)
                return

            logger.info(f"Передаю в тг {SH(self.api_id)},{SH(self.api_hash)},{SH(self.phone)} (Должно быть не пусто)")

            self.bot_handler = TelegramBotHandler(self, self.api_id, self.api_hash, self.phone,
                                                  self.settings.get("AUDIO_BOT", "@silero_voice_bot"))

            try:
                await self.bot_handler.start()
                self.bot_handler_ready = True
                if hasattr(self, 'silero_connected') and self.silero_connected:
                    logger.info("ТГ успешно подключен")
                else:
                    logger.info("ТГ не подключен")
            except Exception as e:
                logger.info(f"Ошибка при запуске Telegram бота: {e}")
                self.bot_handler_ready = False
                self.silero_connected.set(False)

        except Exception as e:
            logger.info(f"Критическая ошибка при инициализации Telegram Bot: {e}")
            self.silero_connected.set(False)
            self.bot_handler_ready = False

    def run_in_thread(self, response):
        """Запуск асинхронной задачи в отдельном потоке."""
        # Убедимся, что цикл событий готов и запускаем задачу в том же цикле
        self.loop_ready_event.wait()  # Ждем, пока цикл событий будет готов
        if self.loop and self.loop.is_running():
            logger.info("Запускаем асинхронную задачу в цикле событий...")
            # Здесь мы вызываем асинхронную задачу через главный цикл
            self.loop.create_task(self.run_send_and_receive(self.textToTalk, self.textSpeaker))
        else:
            logger.info("Ошибка: Цикл событий asyncio не готов.")

    async def run_send_and_receive(self, response, speaker_command, id):
        """Асинхронный метод для вызова send_and_receive."""
        logger.info("Попытка получить фразу")
        self.waiting_answer = True
        text_to_talk = response

        if self.settings.get("AUDIO_BOT") == "@CrazyMitaAIbot (Без тг)":
            rate = self.settings.get("MIKUTTS_VOICE_RATE")
            engine = self.settings.get("MIKUTTS_ENGINE")
            pitch = int(self.settings.get("MIKUTTS_VOICE_PITCH"))

            params = {'text': text_to_talk,
                      'person': self.model.current_character.miku_tts_name}
            data = None
            if engine == "Edge":
                method = "GET"
                endpoint = "get_edge"
                port = 2020
                params['rate'] = rate
                params['pitch'] = pitch
            elif engine == "Vosk":
                method = "GET"
                endpoint = "get_item"
                port = 2040
                params['ids'] = self.settings.get("MIKUTTS_VOSK_IDS", 1)
                params['pith'] = pitch
            elif engine == "Silero":
                method = "POST"
                endpoint = "get_silero"
                port = 2060
                data = {
                    "text": text_to_talk,
                    "person": self.model.current_character.miku_tts_name,
                    "model_id": "v4_ru",
                    "language": "ru",
                    "pitch": pitch,
                    "provider": self.settings.get("MIKUTTS_SILERO_PROVIDER", "Aidar")
                }
                params = None

            max_retries = 3
            retry_delay = 1

            for attempt in range(max_retries):
                try:
                    response, time_taken = await MikuTTSClient.send_request(method=method, data=data, port=port,
                                                                            endpoint=endpoint, timeout=int(
                            self.settings.get("SILERO_TIME")), params=params)
                    if response:
                        break
                except Exception as e:
                    logger.info(f"Попытка {attempt + 1} из {max_retries} не удалась. {e}")
                    await asyncio.sleep(retry_delay)

            logger.info(
                f"Успешно сгенерирована озвучка, {time_taken} секунд, Движок: {self.settings.get("MIKUTTS_ENGINE")}, Текст: {text_to_talk}")

            voice_path = f"MitaVoices/{uuid.uuid4()}.{"wav" if self.ConnectedToGame else "mp3"}"
            absolute_audio_path = os.path.abspath(voice_path)

            logger.info(f"После uuid {voice_path} \n{absolute_audio_path}")

            try:
                # Создаем директорию в отдельном потоке
                await asyncio.to_thread(os.makedirs, os.path.dirname(absolute_audio_path), exist_ok=True)

                # Записываем файл в отдельном потоке
                await asyncio.to_thread(
                    lambda: open(absolute_audio_path, "wb").write(response.content)
                )

                logger.info("Запись завершена")
            except Exception as e:
                logger.info(f"Ошибка при записи файла: {e}")

            # end_time = time.time()
            # logger.info(f"Время генерации озвучки {self.settings.get("AUDIO_BOT")}: {end_time - start_time}")

            if self.ConnectedToGame:
                self.patch_to_sound_file = absolute_audio_path
                logger.info(f"Файл wav загружен: {absolute_audio_path}")
            else:
                logger.info(f"Отправлен воспроизводится: {absolute_audio_path}")
                await AudioHandler.handle_voice_file(absolute_audio_path)
        else:
            await self.bot_handler.send_and_receive(response, speaker_command, id)
        self.waiting_answer = False
        logger.info("Завершение получения фразы")

    def check_text_to_talk_or_send(self):
        """Периодическая проверка переменной self.textToTalk."""
        if self.textToTalk:  #and not self.ConnectedToGame:
            logger.info(f"Есть текст для отправки: {self.textToTalk} id {self.id_sound}")
            # Вызываем метод для отправки текста, если переменная не пуста
            if self.loop and self.loop.is_running():
                try:
                    if bool(self.settings.get("SILERO_USE")):
                        logger.info("Цикл событий готов. Отправка текста.")
                        asyncio.run_coroutine_threadsafe(
                            self.run_send_and_receive(self.textToTalk, self.textSpeaker, self.id_sound),
                            self.loop
                        )
                    self.textToTalk = ""  # Очищаем текст после отправки
                    logger.info("Выполнено")
                except Exception as e:
                    logger.info(f"Ошибка при отправке текста: {e}")
                    self.textToTalk = ""  # Очищаем текст в случае ошибки
            else:
                logger.info("Ошибка: Цикл событий не готов.")

        if bool(self.settings.get("MIC_INSTANT_SENT")):

            if not self.waiting_answer:
                text_from_recognition = SpeechRecognition.receive_text()
                user_input = self.user_entry.get("1.0", "end-1c")
                user_input += text_from_recognition
                self.user_entry.insert(tk.END, text_from_recognition)
                self.user_input = self.user_entry.get("1.0", "end-1c").strip()
                if not self.dialog_active:
                    self.send_instantly()

        elif bool(self.settings.get("MIC_ACTIVE")) and self.user_entry:
            text_from_recognition = SpeechRecognition.receive_text()
            self.user_entry.insert(tk.END, text_from_recognition)
            self.user_input = self.user_entry.get("1.0", "end-1c").strip()

        # Перезапуск проверки через 100 миллисекунд
        self.root.after(100, self.check_text_to_talk_or_send)  # Это обеспечит постоянную проверку

    def send_instantly(self):
        """Мгновенная отправка распознанного текста"""
        try:
            #if text:
            #logger.info(f"Получен текст: {text}")

            #self.user_entry.delete("1.0", tk.END)
            #self.user_entry.insert(tk.END, text)
            if self.ConnectedToGame:
                self.instant_send = True
            else:
                self.send_message()

            SpeechRecognition._text_buffer.clear()
            SpeechRecognition._current_text = ""

        except Exception as e:
            logger.info(f"Ошибка обработки текста: {str(e)}")

    def clear_user_input(self):
        self.user_input = ""
        self.user_entry.delete(1.0, 'end')

    def start_server(self):
        """Запускает сервер в отдельном потоке."""
        if not self.running:
            self.running = True
            self.server.start()  # Инициализация сокета
            self.server_thread = threading.Thread(target=self.run_server_loop, daemon=True)
            self.server_thread.start()
            logger.info("Сервер запущен.")

    def stop_server(self):
        """Останавливает сервер."""
        if self.running:
            self.running = False
            self.server.stop()
            logger.info("Сервер остановлен.")

    def run_server_loop(self):
        """Цикл обработки подключений сервера."""
        while self.running:
            needUpdate = self.server.handle_connection()
            if needUpdate:
                self.load_chat_history()

    def setup_ui(self):
        self.root.config(bg="#2c2c2c")  # Установите темный цвет фона для всего окна
        self.root.geometry("1200x800")

        main_frame = tk.Frame(self.root, bg="#2c2c2c")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Первый столбец
        left_frame = tk.Frame(main_frame, bg="#2c2c2c")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Настройка grid для left_frame
        left_frame.grid_rowconfigure(0, weight=1)  # Чат получает всё свободное место
        left_frame.grid_rowconfigure(1, weight=0)  # Инпут остаётся фиксированным
        left_frame.grid_columnconfigure(0, weight=1)

        # Чат - верхняя часть (растягивается)
        self.chat_window = tk.Text(
            left_frame, height=30, width=40, state=tk.NORMAL,
            bg="#1e1e1e", fg="#ffffff", insertbackground="white", wrap=tk.WORD,
            font=("Arial", 12)
        )
        self.chat_window.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))

        # Добавляем стили
        self.chat_window.tag_configure("Mita", foreground="hot pink", font=("Arial", 12, "bold"))
        self.chat_window.tag_configure("Player", foreground="gold", font=("Arial", 12, "bold"))
        self.chat_window.tag_configure("System", foreground="white", font=("Arial", 12, "bold"))

        # Инпут - нижняя часть (фиксированная высота)
        input_frame = tk.Frame(left_frame, bg="#2c2c2c")
        input_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(20, 10))  # pady=(20, 10) — отступ сверху 20px

        self.user_entry = tk.Text(
            input_frame, height=3, width=50, bg="#1e1e1e", fg="#ffffff",
            insertbackground="white", font=("Arial", 12)
        )
        self.user_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.send_button = tk.Button(
            input_frame, text=_("Отправить", "Send"), command=self.send_message,
            bg="#9370db", fg="#ffffff", font=("Arial", 12)
        )
        self.send_button.pack(side=tk.RIGHT, padx=5)


        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Второй столбец
        right_frame = tk.Frame(main_frame, bg="#2c2c2c")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Создаем канвас и скроллбар для правой секции
        right_canvas = tk.Canvas(right_frame, bg="#2c2c2c", highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(right_frame, orient="vertical", command=right_canvas.yview)

        # Настраиваем скроллбар и канвас
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Создаем фрейм внутри канваса для размещения всех элементов
        settings_frame = tk.Frame(right_canvas, bg="#2c2c2c")
        settings_frame_window = right_canvas.create_window((0, 0), window=settings_frame, anchor="nw",
                                                           tags="settings_frame")

        # Настраиваем изменение размера канваса при изменении размера фрейма
        def configure_scroll_region(event):
            right_canvas.configure(scrollregion=right_canvas.bbox("all"))

        settings_frame.bind("<Configure>", configure_scroll_region)

        # Настраиваем изменение ширины фрейма при изменении ширины канваса
        def configure_frame_width(event):
            right_canvas.itemconfig(settings_frame_window, width=event.width)

        right_canvas.bind("<Configure>", configure_frame_width)

        # Настраиваем прокрутку колесиком мыши
        def _on_mousewheel(event):
            # Определяем направление прокрутки в зависимости от платформы
            if hasattr(event, 'num') and event.num in (4, 5):
                # Linux
                delta = -1 if event.num == 4 else 1
            elif hasattr(event, 'delta'):
                # Windows и macOS
                # На macOS delta обычно больше, поэтому нормализуем
                if event.delta > 100 or event.delta < -100:
                    # macOS, где delta может быть большим числом
                    delta = -1 if event.delta > 0 else 1
                else:
                    # Windows, где delta обычно кратна 120
                    delta = -1 if event.delta > 0 else 1
            else:
                return

            right_canvas.yview_scroll(delta, "units")

        # Привязываем события прокрутки для разных платформ
        right_canvas.bind_all("<MouseWheel>", _on_mousewheel)  # Windows и macOS
        right_canvas.bind_all("<Button-4>", _on_mousewheel)  # Linux (прокрутка вверх)
        right_canvas.bind_all("<Button-5>", _on_mousewheel)  # Linux (прокрутка вниз)

        self.setup_status_indicators(settings_frame)
        self.setup_language_controls(settings_frame)
        self.setup_api_controls_new(settings_frame)
        self.setup_model_controls(settings_frame)
        self.setup_tg_controls(settings_frame)
        self.setup_microphone_controls(settings_frame)

        self.setup_mita_controls(settings_frame)

        self.setup_general_settings_control(settings_frame)

        # Передаем settings_frame как родителя

        # Настройка элементов управления
        # Создаем контейнер для всех элементов управления
        #self.controls_frame = tk.Frame(settings_frame, bg="#2c2c2c")
        #self.controls_frame.pack(fill=tk.X, pady=3)

        # Настройка элементов управления
        #self.setup_control("Отношение к игроку", "attitude", self.model.attitude)
        #self.setup_control("Скука", "boredom", self.model.boredom)
        #self.setup_control("Стресс", "stress", self.model.stress)
        #self.setup_secret_control()

        self.setup_history_controls(settings_frame)
        self.setup_debug_controls(settings_frame)

        self.setup_common_controls(settings_frame)
        self.setup_game_master_controls(settings_frame)


        #self.setup_advanced_controls(right_frame)

        #Сворачивание секций
        for widget in settings_frame.winfo_children():
            if isinstance(widget, CollapsibleSection):
                widget.collapse()

        self.load_chat_history()

    def insert_message(self, role, content):
        if role == "user":
            # Вставляем имя пользователя с зеленым цветом, а текст — обычным
            self.chat_window.insert(tk.END, _("Вы: ", "You: "), "Player")
            self.chat_window.insert(tk.END, f"{content}\n")
        elif role == "assistant":
            # Вставляем имя Миты с синим цветом, а текст — обычным
            self.chat_window.insert(tk.END, f"{self.model.current_character.name}: ", "Mita")
            self.chat_window.insert(tk.END, f"{content}\n\n")

    def setup_status_indicators(self, parent):
        # Создаем фрейм для индикаторов
        status_frame = tk.Frame(parent, bg="#2c2c2c")
        status_frame.pack(fill=tk.X, pady=3)

        # Переменные статуса
        self.game_connected = tk.BooleanVar(value=False)  # Статус подключения к игре
        self.silero_connected = tk.BooleanVar(value=False)  # Статус подключения к Silero

        # Галки для подключения
        self.game_status_checkbox = tk.Checkbutton(
            status_frame,
            text=_("Подключение к игре","Connection to game"),
            variable=self.game_connected,
            state="disabled",
            bg="#2c2c2c",
            fg="#ffffff",
            selectcolor="#2c2c2c"
        )
        self.game_status_checkbox.pack(side=tk.LEFT, padx=5, pady=4)

        self.silero_status_checkbox = tk.Checkbutton(
            status_frame,
            text=_("Подключение Telegram","Connection Telegram"),
            variable=self.silero_connected,
            state="disabled",
            bg="#2c2c2c",
            fg="#ffffff",
            selectcolor="#2c2c2c"
        )
        self.silero_status_checkbox.pack(side=tk.LEFT, padx=5, pady=4)

    def updateAll(self):
        self.update_status_colors()
        self.update_debug_info()

    def update_status_colors(self):
        self.game_connected = tk.BooleanVar(value=self.ConnectedToGame)  # Статус подключения к игре
        # Обновление цвета для подключения к игре
        game_color = "#00ff00" if self.ConnectedToGame else "#ffffff"
        self.game_status_checkbox.config(fg=game_color)

        # Обновление цвета для подключения к Silero
        silero_color = "#00ff00" if self.silero_connected.get() else "#ffffff"
        self.silero_status_checkbox.config(fg=silero_color)

    def setup_control(self, label_text, attribute_name, initial_value):
        """
        Создает элементы управления для настроения, скуки и стресса.
        :param label_text: Текст метки (например, "Настроение").
        :param attribute_name: Имя атрибута модели (например, "attitude").
        :param initial_value: Начальное значение атрибута.
        """
        frame = tk.Frame(self.controls_frame, bg="#2c2c2c")
        frame.pack(fill=tk.X, pady=5)

        # Метка для отображения текущего значения
        label = tk.Label(frame, text=f"{label_text}: {initial_value}", bg="#2c2c2c", fg="#ffffff")
        label.pack(side=tk.LEFT, padx=5)

        # Кнопки для увеличения и уменьшения значения
        up_button = tk.Button(
            frame, text="+", command=lambda: self.adjust_value(attribute_name, 15, label),
            bg="#8a2be2", fg="#ffffff"
        )
        up_button.pack(side=tk.RIGHT, padx=5)

        down_button = tk.Button(
            frame, text="-", command=lambda: self.adjust_value(attribute_name, -15, label),
            bg="#8a2be2", fg="#ffffff"
        )
        down_button.pack(side=tk.RIGHT, padx=5)

        # Сохраняем ссылку на метку для обновления
        setattr(self, f"{attribute_name}_label", label)

    def setup_secret_control(self):
        """
        Создает чекбокс для управления состоянием "Секрет раскрыт".
        """
        frame = tk.Frame(self.controls_frame, bg="#2c2c2c")
        frame.pack(fill=tk.X, pady=5)

        self.secret_var = tk.BooleanVar(value=self.model.secretExposed)

        secret_checkbox = tk.Checkbutton(
            frame, text="Секрет раскрыт", variable=self.secret_var,
            bg="#2c2c2c", fg="#ffffff", command=self.adjust_secret
        )
        secret_checkbox.pack(side=tk.LEFT, padx=5)

    def adjust_value(self, attribute_name, delta, label):
        """
        Обновляет значение атрибута модели и метки.
        :param attribute_name: Имя атрибута модели (например, "attitude").
        :param delta: Изменение значения (например, +15 или -15).
        :param label: Метка, которую нужно обновить.
        """
        current_value = getattr(self.model, attribute_name)
        new_value = current_value + delta
        setattr(self.model, attribute_name, new_value)

        # Обновляем текст метки
        label.config(text=f"{label.cget('text').split(':')[0]}: {new_value}")

    def adjust_secret(self):
        """
        Обновляет состояние "Секрет раскрыт" в модели.
        """
        self.model.secretExposed = self.secret_var.get()

    def setup_history_controls(self, parent):
        history_frame = tk.Frame(parent, bg="#2c2c2c")
        history_frame.pack(fill=tk.X, pady=4)

        clear_button = tk.Button(
            history_frame, text=_("Очистить историю персонажа","Clear character history"), command=self.clear_history,
            bg="#8a2be2", fg="#ffffff"
        )
        clear_button.pack(side=tk.LEFT, padx=5)

        clear_button = tk.Button(
            history_frame, text=_("Очистить все истории","Clear all histories"), command=self.clear_history_all,
            bg="#8a2be2", fg="#ffffff"
        )
        clear_button.pack(side=tk.LEFT, padx=5)

        # TODO Вернуть
        # save_history_button = tk.Button(
        #     history_frame, text="Сохранить историю", command=self.model.save_chat_history,
        #     bg="#8a2be2", fg="#ffffff"
        # )
        # save_history_button.pack(side=tk.LEFT, padx=10)

    def load_chat_history(self):

        chat_history = self.model.current_character.load_history()
        for entry in chat_history["messages"]:
            role = entry["role"]
            content = entry["content"]
            self.insert_message(role, content)
        # Прокручиваем вниз
        self.chat_window.see(tk.END)

        self.update_debug_info()


    #region SetupControls

    def setup_debug_controls(self, parent):
        debug_frame = tk.Frame(parent, bg="#2c2c2c")
        debug_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.debug_window = tk.Text(
            debug_frame, height=5, width=50, bg="#1e1e1e", fg="#ffffff",
            state=tk.NORMAL, wrap=tk.WORD, insertbackground="white"
        )
        self.debug_window.pack(fill=tk.BOTH, expand=True)

        self.update_debug_info()  # Отобразить изначальное состояние переменных

    def setup_api_controls(self, parent):
        api_frame = tk.Frame(parent, bg="#2c2c2c")
        api_frame.pack(fill=tk.X, pady=3)

        self.show_api_var = tk.BooleanVar(value=False)

        api_toggle = tk.Checkbutton(
            api_frame, text=_("Показать настройки API","Show API settings"), variable=self.show_api_var,
            command=lambda: self.pack_unpack(self.show_api_var, self.api_settings_frame), bg="#2c2c2c", fg="#ffffff"
        )
        api_toggle.pack(side=tk.LEFT, padx=4)

        self.api_settings_frame = tk.Frame(parent, bg="#2c2c2c")

        # Элементы в одном столбце
        tk.Label(
            self.api_settings_frame, text=_("API-ключ:","API-key:"), bg="#2c2c2c", fg="#ffffff"
        ).grid(row=0, column=0, padx=4, pady=4, sticky=tk.W)

        self.api_key_entry = tk.Entry(self.api_settings_frame, width=50, bg="#1e1e1e", fg="#ffffff",
                                      insertbackground="white")
        self.api_key_entry.grid(row=0, column=1, padx=4, pady=4, sticky=tk.W)

        tk.Label(
            self.api_settings_frame, text=_("резервный API-ключ:","reserve API-key:"), bg="#2c2c2c", fg="#ffffff"
        ).grid(row=1, column=0, padx=4, pady=4, sticky=tk.W)

        self.api_key_res_entry = tk.Entry(self.api_settings_frame, width=50, bg="#1e1e1e", fg="#ffffff",
                                          insertbackground="white")
        self.api_key_res_entry.grid(row=1, column=1, padx=4, pady=4, sticky=tk.W)

        tk.Label(
            self.api_settings_frame, text=_("Ссылка:","URL"), bg="#2c2c2c", fg="#ffffff"
        ).grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)

        self.api_url_entry = tk.Entry(self.api_settings_frame, width=50, bg="#1e1e1e", fg="#ffffff",
                                      insertbackground="white")
        self.api_url_entry.grid(row=2, column=1, padx=4, pady=5, sticky=tk.W)

        tk.Label(
            self.api_settings_frame, text=_("Модель:","Model:"), bg="#2c2c2c", fg="#ffffff"
        ).grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)

        self.api_model_entry = tk.Entry(self.api_settings_frame, width=50, bg="#1e1e1e", fg="#ffffff",
                                        insertbackground="white")
        self.api_model_entry.grid(row=3, column=1, padx=4, pady=4, sticky=tk.W)

        tk.Label(
            self.api_settings_frame, text="Telegram API ID:", bg="#2c2c2c", fg="#ffffff"
        ).grid(row=4, column=0, padx=5, pady=5, sticky=tk.W)

        self.api_id_entry = tk.Entry(self.api_settings_frame, width=50, bg="#1e1e1e", fg="#ffffff",
                                     insertbackground="white")
        self.api_id_entry.grid(row=4, column=1, padx=4, pady=4, sticky=tk.W)

        tk.Label(
            self.api_settings_frame, text="Telegram API Hash:", bg="#2c2c2c", fg="#ffffff"
        ).grid(row=5, column=0, padx=5, pady=5, sticky=tk.W)

        self.api_hash_entry = tk.Entry(self.api_settings_frame, width=50, bg="#1e1e1e", fg="#ffffff",
                                       insertbackground="white")
        self.api_hash_entry.grid(row=5, column=1, padx=4, pady=4, sticky=tk.W)

        tk.Label(
            self.api_settings_frame, text="Telegram Phone:", bg="#2c2c2c", fg="#ffffff"
        ).grid(row=6, column=0, padx=5, pady=5, sticky=tk.W)

        self.phone_entry = tk.Entry(self.api_settings_frame, width=50, bg="#1e1e1e", fg="#ffffff",
                                    insertbackground="white")
        self.phone_entry.grid(row=6, column=1, padx=4, pady=4, sticky=tk.W)

        # Переменная для тумблера
        self.makeRequest_entry = tk.Checkbutton(
            self.api_settings_frame, text="openapi or req", variable=self.show_api_var,
            command=self.toggle_makeRequest, bg="#2c2c2c", fg="#ffffff"
        )
        self.makeRequest_entry.grid(row=7, column=0, padx=15, pady=0, sticky=tk.W)
        self.toggle_makeRequest(False)

        save_button = tk.Button(
            self.api_settings_frame, text=_("Сохранить","Save"), command=self.save_api_settings,
            bg="#8a2be2", fg="#ffffff"
        )
        save_button.grid(row=8, column=0, padx=5, sticky=tk.E)

        # Обновляем поля ввода
        self.api_url_entry.insert(0, self.api_url)
        self.api_model_entry.insert(0, self.api_model)

        if not bool(self.settings.get(
                "HIDE_PRIVATE")):  # Для безопасности стримеров т.п. это надо будет сделать переключаемым по настройке
            self.api_key_entry.insert(0, self.api_key)
            self.api_key_res_entry.insert(0, self.api_key_res)
            self.api_id_entry.insert(0, self.api_id)
            self.api_hash_entry.insert(0, self.api_hash)
            self.phone_entry.insert(0, self.phone)

    def setup_tg_controls(self, parent):
        # Основные настройки
        mita_voice_config = [
            {'label': _('Использовать озвучку', 'Use speech'), 'key': 'SILERO_USE', 'type': 'checkbutton',
             'default': True},
            {'label': _('Вариант озвучки', "Speech option"), 'key': 'LOCAL_OR_NET', 'type': 'combobox',
             'options': ["TG", "Local"], 'default': "TG"},
            {'label': _('Канал телеграмм',"Telegram channel"), 'key': 'AUDIO_BOT', 'type': 'combobox',
             'options': ["@silero_voice_bot","@CrazyMitaAIbot"],'default': "@silero_voice_bot"},
            {'label': _('Максимальное ожидание','Max awaiting time'), 'key': 'SILERO_TIME', 'type': 'entry', 'default': 12,
             'validation': self.validate_number},
        ]
        if False:
            mita_voice_config.extend([
            {'label': _('Без тг | Движок',"No TG | engine"), 'key': 'MIKUTTS_ENGINE', 'type': 'combobox',
             'options': ["Edge", "Vosk", "Silero"], 'default': "Edge"},
            {'label': _('Без тг | Скорость голоса','No TG | Voice speed'), 'key': 'MIKUTTS_VOICE_RATE', 'type': 'entry', 'default': "+10%"},
            {'label': _('Без тг | Высота голоса','No TG | Voice pitch'), 'key': 'MIKUTTS_VOICE_PITCH', 'type': 'entry', 'default': 8},
            {'label': _("Без тг | VOSK | IDs",'No TG | VOSK | IDs'), 'key': 'MIKUTTS_VOSK_IDS', 'type': 'combobox', 'options': [0, 1, 2, 3, 4],
             'default': 0},
            {'label': _("Без тг | SILERO | Провайдер",'No TG | SILERO | Provider'), 'key': 'MIKUTTS_SILERO_PROVIDER', 'type': 'combobox',
             'options': ["aidar", "baya", "kseniya", "xenia", "eugene"], 'default': "aidar"},
            ])

        # ТГ
        mita_voice_config.extend([
                {'label': _('Настройки ТГ будут скрыты после перезапуска!','TG Settings will be hidden after restart!'),'type': 'text'},
                {'label': _('Telegram id'), 'key': 'NM_TELEGRAM_API_ID', 'type': 'entry','default':"",'hide': bool(self.settings.get("HIDE_PRIVATE"))},
                {'label': _('Telegram hash'), 'key': 'NM_TELEGRAM_API_HASH', 'type': 'entry','default':"",'hide':bool(self.settings.get("HIDE_PRIVATE"))},
                {'label': _('Telegram number'), 'key': 'NM_TELEGRAM_PHONE', 'type': 'entry','default':"",'hide':bool(self.settings.get("HIDE_PRIVATE"))},
        ])
        self.create_settings_section(parent, _("Настройка озвучки","Speech settings"), mita_voice_config)

    def setup_mita_controls(self, parent):
        # Основные настройки
        mita_config = [
            {'label': _('Персонаж','Character'), 'key': 'CHARACTER', 'type': 'combobox', 'options': self.model.get_all_mitas(),
             'default': "Crazy"}
        ]

        self.create_settings_section(parent, _("Выбор персонажа","Character selection"), mita_config)

    def setup_model_controls(self, parent):
        # Основные настройки
        mita_config = [
            {'label': _('Использовать gpt4free','Use gpt4free'), 'key': 'gpt4free', 'type': 'checkbutton', 
             'default_checkbutton': False},
            {'label': _('gpt4free | Модель gpt4free','gpt4free | model gpt4free'), 'key': 'gpt4free_model', 
             'type': 'entry', 'default': "gemini-1.5-flash"}
        ]

        self.create_settings_section(parent, _("Настройки модели","Model settings"), mita_config)

    def setup_common_controls(self, parent):
        # Основные настройки
        common_config = [
            {'label': _('Скрывать (приватные) данные','Hide (private) data'), 'key': 'HIDE_PRIVATE', 'type': 'checkbutton',
             'default_checkbutton': True},

        ]
        self.create_settings_section(parent, _("Общие настройки", "Common settings"), common_config)

    def setup_game_master_controls(self, parent):
        # Основные настройки
        common_config = [
            {'label': _('ГеймМастер включен','GameMaster is on'), 'key': 'GM_ON', 'type': 'checkbutton',
             'default_checkbutton': False, 'tooltip': 'Помогает вести диалоги, в теории устраняя проблемы'},
            {'label': _('ГеймМастер зачитывается','GameMaster write in game'), 'key': 'GM_READ', 'type': 'checkbutton',
             'default_checkbutton': False},
            {'label': _('ГеймМастер озвучивает','GameMaster is voiced'), 'key': 'GM_VOICE', 'type': 'checkbutton',
             'default_checkbutton': False},
            {'label': _('Встревать через','Intervene after'), 'key': 'GM_REPEAT', 'type': 'entry',
             'default': 2, 'tooltip': _('Через сколько фраз гейммастер вмешивается','How much phares GM need to intervene')},
            {'label': _('Лимит речей нпс %','Limit NPC convesationg'), 'key': 'CC_Limit_mod', 'type': 'entry',
             'default': 100, 'tooltip': _('Сколько от кол-ва персонажей может отклоняться повтор речей нпс','How long NPC can talk ignoring player')}
        ]
        self.create_settings_section(parent, _("Настройки Мастера игры и Диалогов","GameMaster and Dialogues settings"), common_config)

    def setup_new_game_master_controls(self, parent):
        # Основные настройки для новой секции
        new_common_config = [
            {'label': 'Новая настройка 1', 'key': 'NEW_SETTING_1', 'type': 'checkbutton',
             'default_checkbutton': False, 'tooltip': 'Описание новой настройки 1'},
            {'label': 'Новая настройка 2', 'key': 'NEW_SETTING_2', 'type': 'entry',
             'default': 5, 'tooltip': 'Описание новой настройки 2'}
        ]
        self.create_settings_section(parent, "Новая секция", new_common_config)

    def setup_api_controls_new(self, parent):
        # Основные настройки
        common_config = [
            {'label': _('Ссылка', 'URL'), 'key': 'NM_API_URL', 'type': 'entry'},
            {'label': _('Модель', 'Model'), 'key': 'NM_API_MODEL', 'type': 'entry'},
            {'label': _('Ключ', 'Key'), 'key': 'NM_API_KEY', 'type': 'entry'},
            {'label': _('Резервные ключи', 'Reserve keys'), 'key': 'NM_API_KEY_RES', 'type': 'text', 'hide':  bool(self.settings.get("HIDE_PRIVATE")) },
            {'label': _('Через Request', 'Using Request'), 'key': 'NM_API_REQ', 'type': 'checkbutton'},
            {'label': _('Спец Структура Гемини', 'Special Gemini Case'), 'key': 'GEMINI_CASE', 'type': 'checkbutton','default_checkbutton':False}
        ]
        self.create_settings_section(parent,
                                     _("Настройки API", "API settings"),
                                     common_config)

    def setup_general_settings_control(self, parent):
        general_config = [
            # здесь настройки из setup_model_controls
            {'label': _('Настройки сообщений', 'Message settings'), 'type': 'text'},
            {'label': _('Лимит сообщений','Message limit'), 'key': 'MODEL_MESSAGE_LIMIT', 
             'type': 'entry', 'default': 40,
             'tooltip':_('Сколько сообщений будет помнить мита','How much messages Mita will remember')},
            {'label': _('Кол-во попыток','Attempt count'), 'key': 'MODEL_MESSAGE_ATTEMPTS_COUNT', 
             'type': 'entry', 'default': 3},
            {'label': _('Время между попытками','time between attempts'), 
             'key': 'MODEL_MESSAGE_ATTEMPTS_TIME', 'type': 'entry', 'default': 0.20}
        ]

        self.create_settings_section(parent,
                                   _("Общие настройки моделей", "General settings for models"), 
                                   general_config)

    #endregion

    def validate_number(self, new_value):
        if not new_value.isdigit():  # Проверяем, что это число
            return False
        return 0 <= int(new_value) <= 60  # Проверяем, что в пределах диапазона

    def pack_unpack(self, var, frame):
        """
        Показывает или скрывает фрейм в зависимости от состояния var.
        """
        if var.get():
            frame.pack(fill=tk.X, padx=10, pady=10)
        else:
            frame.pack_forget()

    def toggle_makeRequest(self, change_to_opposite=True):
        if change_to_opposite:
            self.makeRequest = not self.makeRequest

        if self.makeRequest:
            self.makeRequest_entry.config(text="Сейчас режим прокси Gemini")
        else:
            self.makeRequest_entry.config(text="Сейчас обычный режим")

    def save_api_settings(self):
        """Собирает данные из полей ввода и сохраняет только непустые значения, не перезаписывая существующие."""
        try:
            settings = {}  # По умолчанию пустые настройки
            # Загружаем текущие настройки, если файл существует
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "rb") as f:
                        encoded = f.read()
                    try:
                        decoded = base64.b64decode(encoded)
                    except binascii.Error:
                        logger.info("Ошибка: Файл настроек поврежден (невалидный Base64).")
                        decoded = "{}".encode("utf-8")  # Пустой JSON в виде строки

                    try:
                        settings = json.loads(decoded.decode("utf-8"))
                    except json.JSONDecodeError:
                        logger.info("Ошибка: Файл настроек содержит некорректный JSON.")
                        settings = {}

                except (OSError, IOError) as e:
                    decoded = base64.b64decode(encoded)
                    settings = json.loads(decoded.decode("utf-8"))

            # Обновляем настройки новыми значениями, если они не пустые
            if api_key := self.api_key_entry.get().strip():
                logger.info("Сохранение апи ключа")
                settings["NM_API_KEY"] = api_key
            if api_key_res := self.api_key_res_entry.get().strip():
                logger.info("Сохранение резервного апи ключа")
                settings["NM_API_KEY_RES"] = api_key_res
            if api_url := self.api_url_entry.get().strip():
                logger.info("Сохранение апи ссылки")
                settings["NM_API_URL"] = api_url
            else:
                logger.info("Сохранение ссылку по умолчанию, тк она пуста")
                settings["NM_API_URL"] = "https://openrouter.ai/api/v1"
            if api_model := self.api_model_entry.get().strip():
                logger.info("Сохранение апи модели")
                settings["NM_API_MODEL"] = api_model
            else:
                logger.info("Сохранение модель по умолчанию, тк настройка пуста")
                settings["NM_API_MODEL"] = "google/gemini-2.0-pro-exp-02-05:free"

            if api_id := self.api_id_entry.get().strip():
                logger.info("Сохранение тг айди")
                settings["NM_TELEGRAM_API_ID"] = api_id
            if api_hash := self.api_hash_entry.get().strip():
                logger.info("Сохранение тг хеш")
                settings["NM_TELEGRAM_API_HASH"] = api_hash
            if phone := self.phone_entry.get().strip():
                logger.info("Сохранение тг телефона")
                settings["NM_TELEGRAM_PHONE"] = phone

            # Булево значение сохраняем всегда
            settings["NM_API_REQ"] = self.makeRequest

            # Сериализация и кодирование
            json_data = json.dumps(settings, ensure_ascii=False)
            encoded = base64.b64encode(json_data.encode("utf-8"))

            # Сохраняем в файл
            with open(self.config_path, "wb") as f:
                f.write(encoded)
            logger.info("Настройки успешно сохранены в файл")

        except Exception as e:
            logger.info(f"Ошибка сохранения: {e}")

        # Сразу же их загружаем
        self.load_api_settings(update_model=True)

        if not self.silero_connected.get():
            logger.info("Попытка запустить силеро заново")
            self.start_silero_async()

    def load_api_settings(self, update_model):
        """Загружает настройки из файла"""
        logger.info("Начинаю загрузку настроек")

        if not os.path.exists(self.config_path):
            logger.info("Не найден файл настроек")
            #self.save_api_settings(False)
            return

        try:
            # Читаем закодированные данные из файла
            with open(self.config_path, "rb") as f:
                encoded = f.read()
            # Декодируем из base64
            decoded = base64.b64decode(encoded)
            # Десериализуем JSON
            settings = json.loads(decoded.decode("utf-8"))

            # Устанавливаем значения
            self.api_key = settings.get("NM_API_KEY", "")
            self.api_key_res = settings.get("NM_API_KEY_RES", "")
            self.api_url = settings.get("NM_API_URL", "")
            self.api_model = settings.get("NM_API_MODEL", "")
            self.makeRequest = settings.get("NM_API_REQ", False)

            # ТГ
            self.api_id = settings.get("NM_TELEGRAM_API_ID", "")
            self.api_hash = settings.get("NM_TELEGRAM_API_HASH", "")
            self.phone = settings.get("NM_TELEGRAM_PHONE", "")

            logger.info(
                f"Итого загружено {SH(self.api_key)},{SH(self.api_key_res)},{self.api_url},{self.api_model},{self.makeRequest} (Должно быть не пусто)")
            logger.info(f"По тг {SH(self.api_id)},{SH(self.api_hash)},{SH(self.phone)} (Должно быть не пусто если тг)")
            if update_model:
                if self.api_key:
                    self.model.api_key = self.api_key
                if self.api_url:
                    self.model.api_url = self.api_url
                if self.api_model:
                    self.model.api_model = self.api_model

                self.model.makeRequest = self.makeRequest
                self.model.update_openai_client()

            logger.info("Настройки загружены из файла")
        except Exception as e:
            logger.info(f"Ошибка загрузки: {e}")

    def paste_from_clipboard(self, event=None):
        try:
            clipboard_content = self.root.clipboard_get()
            self.user_entry.insert(tk.INSERT, clipboard_content)
        except tk.TclError:
            pass  # Если буфер обмена пуст, ничего не делаем

    def copy_to_clipboard(self, event=None):
        try:
            # Получение выделенного текста из поля ввода
            selected_text = self.user_entry.selection_get()
            # Копирование текста в буфер обмена
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_text)
            self.root.update()  # Обновление буфера обмена
        except tk.TclError:
            # Если текст не выделен, ничего не делать
            pass

    def toggle_api_settings(self):
        if self.show_api_var.get():
            self.api_settings_frame.pack(fill=tk.X, padx=10, pady=10)
        else:
            self.api_settings_frame.pack_forget()

    def update_debug_info(self):
        """Обновить окно отладки с отображением актуальных данных."""
        self.debug_window.delete(1.0, tk.END)  # Очистить старые данные

        debug_info = (self.model.current_character.current_variables_string())

        self.debug_window.insert(tk.END, debug_info)

    def update_token_count(self, event=None):
        if False and self.model.hasTokenizer:
            user_input = self.user_entry.get("1.0", "end-1c")
            token_count, cost = self.model.calculate_cost(user_input)
            self.token_count_label.config(
                text=f"ВЫКЛЮЧЕНО!! Токенов: {token_count}/{self.model.max_input_tokens} | Ориент. стоимость: {cost:.4f} ₽"
            )
            self.update_debug_info()

    def insertDialog(self, input_text="", response="",system_text=""):
        MitaName = self.model.current_character.name

        if input_text != "":
            self.chat_window.insert(tk.END, "Вы: ", "Player")
            self.chat_window.insert(tk.END, f"{input_text}\n")
        if system_text != "":
            self.chat_window.insert(tk.END, f"System to {MitaName}: ", "System")
            self.chat_window.insert(tk.END, f"{system_text}\n\n")
        if response != "":
            self.chat_window.insert(tk.END, f"{MitaName}: ", "Mita")
            self.chat_window.insert(tk.END, f"{response}\n\n")


    def send_message(self, system_input=""):
        user_input = self.user_entry.get("1.0", "end-1c")
        if not user_input.strip() and system_input == "":
            return

        if user_input != "":
            self.insert_message("user", user_input)
            self.user_entry.delete("1.0", "end")

        # Запускаем асинхронную задачу для генерации ответа
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.async_send_message(user_input, system_input), self.loop)

    async def async_send_message(self, user_input, system_input=""):
        try:
            # Ограничиваем выполнение задачи 10 секундами
            response = await asyncio.wait_for(
                self.loop.run_in_executor(None, lambda: self.model.generate_response(user_input, system_input)),
                timeout=25.0  # Тайм-аут в секундах
            )
            self.insert_message("assistant", response)
            self.updateAll()
            if self.server:
                try:
                    if self.server.client_socket:
                        self.server.send_message_to_server(response)
                        logger.info("Сообщение отправлено на сервер (связь с игрой есть)")
                    else:
                        logger.info("Нет активного подключения к клиенту игры")
                except Exception as e:
                    logger.info(f"Ошибка при отправке сообщения на сервер: {e}")
        except asyncio.TimeoutError:
            # Обработка тайм-аута
            logger.info("Тайм-аут: генерация ответа заняла слишком много времени.")
            #self.insert_message("assistant", "Превышен лимит времени ожидания ответа от нейросети.")

    def clear_history(self):
        self.model.current_character.clear_history()
        self.chat_window.delete(1.0, tk.END)
        self.update_debug_info()

    def clear_history_all(self):
        for character in self.model.characters.values():
            character.clear_history()
        self.chat_window.delete(1.0, tk.END)
        self.update_debug_info()

    # region Microphone

    """Спасибо Nelxi (distrane25)"""

    def setup_microphone_controls(self, parent):
        # Конфигурация настроек микрофона
        mic_settings = [
            {
                'label': _("Микрофон", "Microphone"),
                'type': 'combobox',
                'key': 'MIC_DEVICE',
                'options': self.get_microphone_list(),
                'default': '',
                'command': self.on_mic_selected,
                'widget_attrs': {
                    'width': 30
                }
            },
            {
                'label': _("Распознавание", "Recognition"),
                'type': 'checkbutton',
                'key': 'MIC_ACTIVE',
                'default_checkbutton': False,
                'tooltip': _("Включить/выключить распознавание голоса", "Toggle voice recognition")
            },
            {
                'label': _("Мгновенная отправка", "Immediate sending"),
                'type': 'checkbutton',
                'key': 'MIC_INSTANT_SENT',
                'default_checkbutton': False,
                'tooltip': _("Отправлять сообщение сразу после распознавания",
                             "Send message immediately after recognition")
            },
            {
                'label': _("Обновить список", "Refresh list"),
                'type': 'button',
                'command': self.update_mic_list
            }
        ]

        # Создаем секцию
        self.mic_section = self.create_settings_section(
            parent,
            _("Настройки микрофона", "Microphone Settings"),
            mic_settings
        )

        # Сохраняем ссылки на важные виджеты
        for widget in self.mic_section.content_frame.winfo_children():
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Combobox):
                        self.mic_combobox = child
                    elif isinstance(child, tk.Checkbutton):
                        if 'MIC_ACTIVE' in str(widget):
                            self.mic_active_check = child
    def get_microphone_list(self):
        try:
            devices = sd.query_devices()
            input_devices = [
                f"{d['name']} ({i})"
                for i, d in enumerate(devices)
                if d['max_input_channels'] > 0
            ]
            return input_devices
        except Exception as e:
            logger.info(f"Ошибка получения списка микрофонов: {e}")
            return []

    def update_mic_list(self):
        self.mic_combobox['values'] = self.get_microphone_list()

    def on_mic_selected(self, event):
        selection = self.mic_combobox.get()
        if selection:
            self.selected_microphone = selection.split(" (")[0]
            device_id = int(selection.split(" (")[-1].replace(")", ""))
            self.device_id = device_id
            logger.info(f"Выбран микрофон: {self.selected_microphone} (ID: {device_id})")
            self.save_mic_settings(device_id)

    def save_mic_settings(self, device_id):
        try:
            with open(self.config_path, "rb") as f:
                encoded = f.read()
            decoded = base64.b64decode(encoded)
            settings = json.loads(decoded.decode("utf-8"))
        except FileNotFoundError:
            settings = {}

        settings["NM_MICROPHONE_ID"] = device_id
        settings["NM_MICROPHONE_NAME"] = self.selected_microphone

        json_data = json.dumps(settings, ensure_ascii=False)
        encoded = base64.b64encode(json_data.encode("utf-8"))
        with open(self.config_path, "wb") as f:
            f.write(encoded)

    def load_mic_settings(self):
        try:
            with open(self.config_path, "rb") as f:
                encoded = f.read()
            decoded = base64.b64decode(encoded)
            settings = json.loads(decoded.decode("utf-8"))

            device_id = settings.get("NM_MICROPHONE_ID", 0)
            device_name = settings.get("NM_MICROPHONE_NAME", "")

            devices = sd.query_devices()
            if device_id < len(devices):
                self.selected_microphone = device_name
                self.device_id = device_id
                self.mic_combobox.set(f"{device_name} ({device_id})")
                logger.info(f"Загружен микрофон: {device_name} (ID: {device_id})")

        except Exception as e:
            logger.info(f"Ошибка загрузки настроек микрофона: {e}")

    # endregion

    #region SettingGUI

    def all_settings_actions(self, key, value):
        ...
        if key == "SILERO_TIME":
            self.bot_handler.silero_time_limit = int(value)
        if key == "AUDIO_BOT":
            if value.startswith("@CrazyMitaAIbot"):
                messagebox.showinfo("Информация",
                                    "HАШ Слава Богу 🙏❤️СЛАВА @CrazyMitaAIbot🙏❤️АНГЕЛА ХРАНИТЕЛЯ КАЖДОМУ ИЗ ВАС 🙏❤️БОЖЕ ХРАНИ @CrazyMitaAIbot🙏❤️СПАСИБО ВАМ НАШИ МАЛЬЧИКИ ИЗ @CrazyMitaAIbot🙏🏼❤️",
                                    parent=self.root)
            if self.bot_handler:
                self.bot_handler.tg_bot = value
        #if key == "TG_BOT":
        #   self.bot_handler.tg_bot_channel = value
        elif key == "CHARACTER":
            self.model.current_character_to_change = value


        elif key == "NM_API_MODEL":
            self.model.api_model = value.strip()
        elif key == "NM_API_KEY":
            self.model.api_key = value.strip()
        elif key == "NM_API_URL":
            self.model.api_url = value.strip()
        elif key == "NM_API_REQ":
            self.model.makeRequest = bool(value)
        elif key == "gpt4free_model":
            self.model.gpt4free_model = value.strip()



        elif key == "MODEL_MESSAGE_LIMIT":
            self.model.memory_limit = int(value)
        elif key == "MODEL_MESSAGE_ATTEMPTS_COUNT":
            self.model.max_request_attempts = int(value)
        elif key == "MODEL_MESSAGE_ATTEMPTS_TIME":
            self.model.request_delay = float(value)



        elif key == "MIC_ACTIVE":
            SpeechRecognition.active = bool(value)
        logger.info(f"Настройки изменены: {key} = {value}")

    def create_settings_section(self, parent, title, settings_config):
        section = CollapsibleSection(parent, title)
        section.pack(fill=tk.X, padx=5, pady=5, expand=True)

        for config in settings_config:
            widget = self.create_setting_widget(
                parent=section.content_frame,
                label=config['label'],
                setting_key=config.get('key', ''),
                widget_type=config.get('type', 'entry'),
                options=config.get('options', None),
                default=config.get('default', ''),
                default_checkbutton=config.get('default_checkbutton', False),
                validation=config.get('validation', None),
                tooltip=config.get('tooltip', ""),
                hide = config.get('hide', False),
                command = config.get('command', None)
            )
            section.add_widget(widget)

        return section

    def create_setting_widget(self, parent, label, setting_key, widget_type='entry',
                              options=None, default='', default_checkbutton=False, validation=None, tooltip=None,
                              width=None, height=None, command=None,hide=False):

        """
        Создает виджет настройки с различными параметрами.

        Параметры:
            parent: Родительский контейнер
            label: Текст метки
            setting_key: Ключ настройки
            widget_type: Тип виджета ('entry', 'combobox', 'checkbutton', 'button', 'scale', 'text')
            options: Опции для combobox
            default: Значение по умолчанию
            validation: Функция валидации
            tooltip: Текст подсказки
            width: Ширина виджета
            height: Высота виджета (для текстовых полей)
            command: Функция, вызываемая при изменении значения
            hide: не выводит при перезагрузке скрытые поля
        """
        # Применяем default при первом запуске
        if not self.settings.get(setting_key):
            self.settings.set(setting_key, default_checkbutton if widget_type == 'checkbutton' else default)

        frame = tk.Frame(parent, bg="#2c2c2c")
        frame.pack(fill=tk.X, pady=2)

        # Label
        lbl = tk.Label(frame, text=label, bg="#2c2c2c", fg="#ffffff", width=25, anchor='w')
        lbl.pack(side=tk.LEFT, padx=5)

        # Widgets
        if widget_type == 'entry':
            entry = tk.Entry(frame, bg="#1e1e1e", fg="#ffffff", insertbackground="white")
            if width:
                entry.config(width=width)

            if not hide:
                entry.insert(0, self.settings.get(setting_key, default))
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

            def save_entry():
                self._save_setting(setting_key, entry.get())
                if command:
                    command(entry.get())

            entry.bind("<FocusOut>", lambda e: save_entry())
            entry.bind("<Return>", lambda e: save_entry())

            if validation:
                entry.config(validate="key", validatecommand=(parent.register(validation), '%P'))

        elif widget_type == 'combobox':
            var = tk.StringVar(value=self.settings.get(setting_key, default))
            cb = ttk.Combobox(frame, textvariable=var, values=options, state="readonly")
            if width:
                cb.config(width=width)
            cb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

            def save_combobox():
                self._save_setting(setting_key, var.get())
                if command:
                    command(var.get())

            cb.bind("<<ComboboxSelected>>", lambda e: save_combobox())

        elif widget_type == 'checkbutton':
            var = tk.BooleanVar(value=self.settings.get(setting_key, default_checkbutton))
            cb = tk.Checkbutton(frame, variable=var, bg="#2c2c2c",
                                command=lambda: [self._save_setting(setting_key, var.get()),
                                                 command(var.get()) if command else None])
            cb.pack(side=tk.LEFT, padx=5)

        elif widget_type == 'button':

            btn = tk.Button(
                frame,
                text=label,
                bg="#8a2be2",
                fg="#ffffff",
                activebackground="#6a1bcb",
                activeforeground="#ffffff",
                relief=tk.RAISED,
                bd=2,
                command=command
            )

            if width:
                btn.config(width=width)

            btn.pack(side=tk.LEFT, padx=5, ipadx=5, ipady=2)

            # Сохраняем ссылку на кнопку, если нужно
            if setting_key:
                self._save_setting(setting_key, False)

        elif widget_type == 'scale':
            var = tk.DoubleVar(value=self.settings.get(setting_key, default))
            scale = tk.Scale(frame, from_=options[0], to=options[1], orient=tk.HORIZONTAL,
                             variable=var, bg="#2c2c2c", fg="#ffffff", highlightbackground="#2c2c2c",
                             length=200 if not width else width)
            scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

            def save_scale(value):
                self._save_setting(setting_key, float(value))
                if command:
                    command(float(value))

            scale.config(command=save_scale)

        elif widget_type == 'text':



            if setting_key != "":
                def save_text():
                    self._save_setting(setting_key, text.get('1.0', 'end-1c'))
                    if command:
                        command(text.get('1.0', 'end-1c'))

                text = tk.Text(frame, bg="#1e1e1e", fg="#ffffff", insertbackground="white",
                               height=height if height else 5, width=width if width else 50)
                text.insert('1.0', self.settings.get(setting_key, default))
                text.bind("<FocusOut>", lambda e: save_text())
                text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)


            else:
                lbl.config(width=100)





        # Добавляем tooltip если указан
        if tooltip:
            self.create_tooltip(frame, tooltip)

        return frame

    def create_tooltip(self, widget, text):
        """Создает всплывающую подсказку для виджета"""
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry("+0+0")
        tooltip.withdraw()

        label = tk.Label(tooltip, text=text, bg="#ffffe0", relief='solid', borderwidth=1)
        label.pack()

        def enter(event):
            x = widget.winfo_rootx() + widget.winfo_width() + 5
            y = widget.winfo_rooty()
            tooltip.wm_geometry(f"+{x}+{y}")
            tooltip.deiconify()

        def leave(event):
            tooltip.withdraw()

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _save_setting(self, key, value):
        self.settings.set(key, value)
        self.settings.save_settings()

        self.all_settings_actions(key, value)

    #endregion

    # region Language

    def setup_language_controls(self, settings_frame):
        config = [
            {'label': 'Язык / Language', 'key': 'LANGUAGE', 'type': 'combobox',
             'options': ["RU", "EN"], 'default': "RU"},
            {'label': 'Перезапусти программу после смены! / Restart program after change!', 'type': 'text'},

        ]

        self.create_settings_section(settings_frame, "Язык / Language", config)

        pass

    # endregion
    def run(self):
        self.root.mainloop()

    def on_closing(self):
        # Отвязываем события прокрутки перед закрытием
        try:
            self.root.unbind_all("<MouseWheel>")
            self.root.unbind_all("<Button-4>")
            self.root.unbind_all("<Button-5>")
        except:
            pass

        self.delete_all_sound_files()
        self.stop_server()
        logger.info("Закрываемся")
        self.root.destroy()

    def close_app(self):
        """Закрытие приложения корректным образом."""
        logger.info("Завершение программы...")
        self.root.destroy()  # Закрывает GUI

    @staticmethod
    def delete_all_sound_files():
        # Получаем список всех .wav файлов в корневой директории
        files = glob.glob("*.wav")

        # Проходим по каждому файлу и удаляем его
        for file in files:
            try:
                os.remove(file)
                logger.info(f"Удален файл: {file}")
            except Exception as e:
                logger.info(f"Ошибка при удалении файла {file}: {e}")

        # Получаем список всех .wav файлов в корневой директории
        files = glob.glob("*.mp3")

        # Проходим по каждому файлу и удаляем его
        for file in files:
            try:
                os.remove(file)
                logger.info(f"Удален файл: {file}")
            except Exception as e:
                logger.info(f"Ошибка при удалении файла {file}: {e}")
