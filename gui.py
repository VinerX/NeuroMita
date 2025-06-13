import io
import uuid

import win32gui

import guiTemplates
from AudioHandler import AudioHandler
from Logger import logger
from SettingsManager import SettingsManager, CollapsibleSection
from chat_model import ChatModel
from server import ChatServer

from Silero import TelegramBotHandler

import gettext
from pathlib import Path
import os
import base64
import json
import glob
import sounddevice as sd
from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
from utils.ffmpeg_installer import install_ffmpeg
from utils.ModelsDownloader import ModelsDownloader

import asyncio
import threading

import binascii
import re  # Импортируем модуль регулярных выражений
import subprocess  # Импортируем модуль subprocess для открытия папок
from utils import _
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from PIL import Image, ImageTk

from utils import SH, process_text_to_voice
import sys

from ScreenCapture import ScreenCapture  # Импортируем ScreenCapture

import requests
import importlib

from LocalVoice import LocalVoice
import time

from SpeechRecognition import SpeechRecognition
from utils.PipInstaller import PipInstaller

from ui import chat_area, status_indicators, debug_area, news_area
from ui.settings import (
    api_settings, character_settings, chat_settings, common_settings,
    g4f_settings, gamemaster_settings, general_model_settings,
    language_settings, microphone_settings, screen_analysis_settings,
    token_settings, voiceover_settings, command_replacer_settings,history_compressor,
    prompt_catalogue_settings # Импортируем новый модуль
)


class ChatGUI:
    def __init__(self):

        self.voice_language_var = None
        self.local_voice_combobox = None
        self.debug_window = None
        self.mic_combobox = None
        self.silero_connected = False
        self.game_connected_checkbox_var = False
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

        try:
            self.pip_installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_log=logger.info
            )
            logger.info("PipInstaller успешно инициализирован.")
        except Exception as e:
            logger.error(f"Не удалось инициализировать PipInstaller: {e}", exc_info=True)
            self.pip_installer = None  # Устанавливаем в None, чтобы ChatModel мог это проверить

        self._check_and_perform_pending_update()

        self.local_voice = LocalVoice(self)
        self.voiceover_method = self.settings.get("VOICEOVER_METHOD", "TG")
        self.current_local_voice_id = self.settings.get("NM_CURRENT_VOICEOVER", None)
        self.last_voice_model_selected = None
        if self.current_local_voice_id:
            for model_info in LOCAL_VOICE_MODELS:
                if model_info["id"] == self.current_local_voice_id:
                    self.last_voice_model_selected = model_info
                    break
        self.model_loading_cancelled = False

        self.model = ChatModel(self, self.api_key, self.api_key_res, self.api_url, self.api_model, self.makeRequest,
                               self.pip_installer)
        self.server = ChatServer(self, self.model)
        self.server_thread = None
        self.running = False
        self.start_server()

        self.textToTalk = ""
        self.textSpeaker = "/Speaker Mita"
        self.textSpeakerMiku = "/set_person CrazyMita"

        self.silero_turn_off_video = False

        self.dialog_active = False

        self.patch_to_sound_file = ""
        self.id_sound = -1
        self.instant_send = False
        self.waiting_answer = False

        # Параметры для ленивой загрузки
        self.lazy_load_batch_size = 50  # Количество сообщений для загрузки за раз
        self.total_messages_in_history = 0  # Общее количество сообщений в истории
        self.loaded_messages_offset = 0  # Смещение для загрузки сообщений
        self.loading_more_history = False  # Флаг, чтобы избежать повторной загрузки

        self.root = tk.Tk()
        self.root.wm_iconphoto(False, tk.PhotoImage(file='icon.png'))

        self.root.title(_("Чат с NeuroMita", "NeuroMita Chat"))

        self.ffmpeg_install_popup = None
        self.root.after(100, self.check_and_install_ffmpeg)

        self.delete_all_sound_files()
        self.setup_ui()

        self.load_chat_history()

        self.root.bind_class("Entry", "<Control-KeyPress>", lambda e: self.keypress(e))
        self.root.bind_class("Text", "<Control-KeyPress>", lambda e: self.keypress(e))

        try:
            microphone_settings.load_mic_settings(self)
        except Exception as e:
            logger.info("Не удалось удачно получить настройки микрофона", e)

        # Событие для синхронизации потоков
        self.loop_ready_event = threading.Event()

        self.loop = None  # Переменная для хранения ссылки на цикл событий
        self.asyncio_thread = threading.Thread(target=self.start_asyncio_loop, daemon=True)
        self.asyncio_thread.start()

        self.start_silero_async()

        # Загружаем настройки распознавания речи при запуске
        initial_recognizer_type = self.settings.get("RECOGNIZER_TYPE", "google")
        initial_vosk_model = self.settings.get("VOSK_MODEL", "vosk-model-ru-0.10")

        SpeechRecognition.set_recognizer_type(initial_recognizer_type)
        SpeechRecognition.vosk_model = initial_vosk_model

        # Запуск проверки переменной textToTalk через after
        self.root.after(150, self.check_text_to_talk_or_send)

        self.root.after(500, self.initialize_last_local_model_on_startup)

        self.screen_capture_instance = ScreenCapture()
        self.screen_capture_thread = None
        self.screen_capture_running = False
        self.last_captured_frame = None
        self.image_request_thread = None
        self.image_request_running = False
        self.last_image_request_time = time.time()
        self.image_request_timer_running = False

        # Добавляем автоматический запуск захвата экрана, если настройка включена
        if self.settings.get("ENABLE_SCREEN_ANALYSIS", False):
            logger.info("Настройка 'ENABLE_SCREEN_ANALYSIS' включена. Автоматический запуск захвата экрана.")
            self.start_screen_capture_thread()

        # Добавляем автоматический запуск захвата с камеры, если настройка включена
        if self.settings.get("ENABLE_CAMERA_CAPTURE", False):
            logger.info("Настройка 'ENABLE_CAMERA_CAPTURE' включена. Автоматический запуск захвата с камеры.")
            self.start_camera_capture_thread()

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
            self.loop.create_task(self.run_send_and_receive(self.textToTalk, self.get_speaker_text()))
        else:
            logger.info("Ошибка: Цикл событий asyncio не готов.")

    def get_speaker_text(self):
        if self.settings.get("AUDIO_BOT") == "@CrazyMitaAIbot":
            return self.textSpeakerMiku
        else:
            return self.textSpeaker

    async def run_send_and_receive(self, response, speaker_command, id=0):
        """Асинхронный метод для вызова send_and_receive."""
        logger.info("Попытка получить фразу")
        self.waiting_answer = True

        await self.bot_handler.send_and_receive(response, speaker_command, id)

        self.waiting_answer = False
        logger.info("Завершение получения фразы")

    # region Modified by Atm4x
    def check_text_to_talk_or_send(self):
        """Периодическая проверка переменной self.textToTalk."""

        # Если озвучка включена и есть текст
        if bool(self.settings.get("SILERO_USE")) and self.textToTalk:
            self.voice_text()

        # --- Логика периодической отправки изображений ---
        if self.image_request_timer_running:
            self.send_interval_image()

        # --- Остальная часть функции без изменений (обработка микрофона) ---
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
        self.root.after(100, self.check_text_to_talk_or_send)

    def send_interval_image(self):
        current_time = time.time()
        interval = float(self.settings.get("IMAGE_REQUEST_INTERVAL", 20.0))
        delta = current_time - self.last_image_request_time
        # Добавляем лог для отладки
        # logger.debug(f"Проверка периодической отправки: {delta}/{interval}")
        if delta >= interval:

            # Захватываем изображение
            image_data = []
            if self.settings.get("ENABLE_SCREEN_ANALYSIS", False):
                logger.info(
                    f"Отправка периодического запроса с изображением ({current_time - self.last_image_request_time:.2f}/{interval:.2f} сек).")
                history_limit = int(self.settings.get("SCREEN_CAPTURE_HISTORY_LIMIT", 1))
                frames = self.screen_capture_instance.get_recent_frames(history_limit)
                if frames:
                    image_data.extend(frames)
                    logger.info(f"Захвачено {len(frames)} кадров для периодической отправки.")
                else:
                    logger.info(
                        "Анализ экрана включен, но кадры не готовы или история пуста для периодической отправки.")

                if image_data:
                    # Отправляем запрос только с изображением (без текста)
                    if self.loop and self.loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self.async_send_message(user_input="", system_input="", image_data=image_data),
                            self.loop)
                        self.last_image_request_time = current_time
                    else:
                        logger.error("Ошибка: Цикл событий не готов для периодической отправки изображений.")
                else:
                    logger.warning("Нет изображений для периодической отправки.")

    def voice_text(self):
        logger.info(f"Есть текст для отправки: {self.textToTalk} id {self.id_sound}")
        if self.loop and self.loop.is_running():
            try:
                # Получаем основной метод озвучки из настроек
                self.voiceover_method = self.settings.get("VOICEOVER_METHOD", "TG")

                if self.voiceover_method == "TG":
                    logger.info("Используем Telegram (Silero/Miku) для озвучки")
                    # Используем существующую логику для TG/MikuTTS
                    asyncio.run_coroutine_threadsafe(
                        self.run_send_and_receive(self.textToTalk, self.get_speaker_text(), self.id_sound),
                        self.loop
                    )
                    self.textToTalk = ""  # Очищаем текст после отправки

                elif self.voiceover_method == "Local":
                    # Получаем ID выбранной локальной модели из настроек
                    selected_local_model_id = self.settings.get("NM_CURRENT_VOICEOVER", None)
                    if selected_local_model_id:  # Убедимся, что ID локальной модели выбран
                        logger.info(f"Используем {selected_local_model_id} для локальной озвучки")
                        # Проверяем, инициализирована ли модель
                        if self.local_voice.is_model_initialized(selected_local_model_id):
                            asyncio.run_coroutine_threadsafe(
                                self.run_local_voiceover(self.textToTalk),
                                self.loop
                            )
                            self.textToTalk = ""  # Очищаем текст после отправки
                        else:
                            logger.warning(
                                f"Модель {selected_local_model_id} выбрана, но не инициализирована. Озвучка не будет выполнена.")
                            self.textToTalk = ""  # Очищаем, чтобы не зациклиться
                    else:
                        logger.warning("Локальная озвучка выбрана, но конкретная модель не установлена/не выбрана.")
                        self.textToTalk = ""  # Очищаем, чтобы не зациклиться
                else:
                    logger.warning(f"Неизвестный метод озвучки: {self.voiceover_method}")
                    self.textToTalk = ""  # Очищаем, чтобы не зациклиться

                logger.info("Выполнено")
            except Exception as e:
                logger.error(f"Ошибка при отправке текста на озвучку: {e}")
                self.textToTalk = ""  # Очищаем текст в случае ошибки
        else:
            logger.error("Ошибка: Цикл событий не готов.")

    #endregion

    def send_instantly(self):
        """Мгновенная отправка распознанного текста"""
        try:
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

    def on_enter_pressed(self, event):
        """Обработчик нажатия клавиши Enter в поле ввода."""
        self.send_message()
        return 'break'  # Предотвращаем вставку новой строки

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
                logger.info(
                    f"[{time.strftime('%H:%M:%S')}] run_server_loop: Обнаружено needUpdate, вызываю load_chat_history.")
                self.load_chat_history()

    def setup_ui(self):
        self.root.config(bg="#1e1e1e")  # Установите темный цвет фона для всего окна
        self.root.geometry("1200x800")

        main_frame = tk.Frame(self.root, bg="#1e1e1e")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.setup_left_frame(main_frame)
        self.setup_right_frame(main_frame)

    def setup_left_frame(self, main_frame):
        # Первый столбец
        left_frame = tk.Frame(main_frame, bg="#1e1e1e")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        # Настройка grid для left_frame
        left_frame.grid_rowconfigure(0, weight=1)  # Чат получает всё свободное место
        left_frame.grid_rowconfigure(1, weight=0)  # Инпут остаётся фиксированным
        left_frame.grid_columnconfigure(0, weight=1)
        # Чат - верхняя часть (растягивается)
        # Фрейм для кнопок над чатом
        button_frame_above_chat = tk.Frame(left_frame, bg="#1e1e1e")
        button_frame_above_chat.grid(row=0, column=0, sticky="nw", padx=10, pady=(10, 0))  # Размещаем над чатом
        # Чат - верхняя часть (растягивается)
        self.chat_window = tk.Text(
            left_frame, height=30, width=40, state=tk.NORMAL,
            bg="#151515", fg="#ffffff", insertbackground="white", wrap=tk.WORD,
            font=("Arial", 12)
        )
        self.chat_window.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 0))  # Сдвигаем чат на вторую строку
        self.clear_chat_button = tk.Button(
            button_frame_above_chat, text=_("Очистить", "Clear"), command=self.clear_chat_display,
            bg="#8a2be2", fg="#ffffff", font=("Arial", 10), padx=2, pady=2  # Уменьшаем размер шрифта и отступы
        )
        self.clear_chat_button.pack(side=tk.LEFT, padx=(0, 5), pady=5)  # Размещаем слева
        self.load_history_button = tk.Button(
            button_frame_above_chat, text=_("Взять из истории", "Load from history"), command=self.load_chat_history,
            bg="#8a2be2", fg="#ffffff", font=("Arial", 10), padx=2, pady=2  # Уменьшаем размер шрифта и отступы
        )
        self.load_history_button.pack(side=tk.LEFT, padx=(0, 5), pady=5)  # Размещаем слева
        # Добавляем стили
        # Получаем начальный размер шрифта из настроек
        initial_font_size = int(self.settings.get("CHAT_FONT_SIZE", 12))

        self.setup_tags_configurations(initial_font_size)


        # Стили для цветов будут добавляться динамически
        # Инпут - нижняя часть (фиксированная высота)
        input_frame = tk.Frame(left_frame, bg="#2c2c2c")
        input_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=(20, 10))  # Сдвигаем инпут на третью строку
        # Метка для отображения количества токенов
        self.token_count_label = tk.Label(
            input_frame,
            text=_("Токены: 0/0 | Стоимость: 0.00 ₽", "Tokens: 0/0 | Cost: 0.00 ₽"),
            bg="#2c2c2c",
            fg="#ffffff",
            font=("Arial", 10)
        )
        self.token_count_label.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(0, 5))  # Размещаем сверху
        self.user_entry = tk.Text(
            input_frame, height=3, width=50, bg="#151515", fg="#ffffff",
            insertbackground="white", font=("Arial", 12)
        )
        self.user_entry.pack(side=tk.TOP, fill=tk.X, expand=True, padx=5, pady=(0, 5))
        self.user_entry.bind("<Return>", self.on_enter_pressed)  # Добавляем обработчик нажатия Enter
        self.send_button = tk.Button(
            input_frame, text=_("Отправить", "Send"), command=self.send_message,
            bg="#9370db", fg="#ffffff", font=("Arial", 12)
        )
        self.send_button.pack(side=tk.RIGHT, padx=5, pady=(0, 5))  # Размещаем справа от поля ввода
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_tags_configurations(self, initial_font_size):
        self.chat_window.tag_configure("default", font=("Arial", initial_font_size))  # Явно настраиваем тег "default"
        self.chat_window.tag_configure("Mita", foreground="hot pink", font=("Arial", initial_font_size, "bold"))
        self.chat_window.tag_configure("tag_green", foreground="#00FF00", font=("Arial", initial_font_size))
        self.chat_window.tag_configure("Player", foreground="gold", font=("Arial", initial_font_size, "bold"))
        self.chat_window.tag_configure("System", foreground="white", font=("Arial", initial_font_size, "bold"))
        self.chat_window.tag_configure("bold", font=("Arial", initial_font_size, "bold"))
        self.chat_window.tag_configure("italic", font=("Arial", initial_font_size, "italic"))
        self.chat_window.tag_configure("timestamp", foreground="#888888",
                                       font=("Arial", initial_font_size - 2, "italic"))  # Метка времени чуть меньше

    def setup_right_frame(self, main_frame):
        # Второй столбец
        right_frame = tk.Frame(main_frame, bg="#2c2c2c")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        # Создаем канвас и скроллбар для правой секции
        right_canvas = tk.Canvas(right_frame, bg="#1e1e1e", highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(right_frame, orient="vertical", command=right_canvas.yview)
        # Настраиваем скроллбар и канвас
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Создаем фрейм внутри канваса для размещения всех элементов
        settings_frame = tk.Frame(right_canvas, bg="#1e1e1e")
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
            # Это проверка на достигнутый конец прокрутки
            current_pos = right_canvas.yview()
            if (delta < 0 and current_pos[0] <= 0) or (delta > 0 and current_pos[1] >= 1):
                return

            right_canvas.yview_scroll(delta, "units")

        # Привязываем события прокрутки для разных платформ
        right_canvas.bind_all("<MouseWheel>", _on_mousewheel)  # Windows и macOS
        right_canvas.bind_all("<Button-4>", _on_mousewheel)  # Linux (прокрутка вверх)
        right_canvas.bind_all("<Button-5>", _on_mousewheel)  # Linux (прокрутка вниз)

        status_indicators.create_status_indicators(self, settings_frame)
        language_settings.create_language_section(self, settings_frame)
        api_settings.setup_api_controls(self, settings_frame)
        g4f_settings.setup_g4f_controls(self, settings_frame)
        general_model_settings.setup_general_settings_control(self, settings_frame)
        voiceover_settings.setup_voiceover_controls(self, settings_frame)
        microphone_settings.setup_microphone_controls(self, settings_frame)
        character_settings.setup_mita_controls(self, settings_frame)
        prompt_catalogue_settings.setup_prompt_catalogue_controls(self, settings_frame) # Добавляем вызов новой функции
        self.setup_debug_controls(settings_frame)
        self.setup_common_controls(settings_frame)
        gamemaster_settings.setup_game_master_controls(self, settings_frame)
        history_compressor.setup_history_compressor_controls(self, settings_frame)
        chat_settings.setup_chat_settings_controls(self, settings_frame)
        screen_analysis_settings.setup_screen_analysis_controls(self, settings_frame)
        token_settings.setup_token_settings_controls(self, settings_frame)
        command_replacer_settings.setup_command_replacer_controls(self, settings_frame)
        self.setup_news_control(settings_frame)

        # Сворачивание секций
        for widget in settings_frame.winfo_children():
            if isinstance(widget, CollapsibleSection):
                widget.collapse()

    def insert_message(self, role, content, insert_at_start=False, message_time=""):
        logger.info(f"insert_message вызван. Роль: {role}, Содержимое: {str(content)[:50]}...")
        # Создаем список для хранения ссылок на изображения, чтобы они не были удалены сборщиком мусора
        if not hasattr(self, '_images_in_chat'):
            self._images_in_chat = []

        processed_content_parts = []
        has_image_content = False

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        processed_content_parts.append(
                            {"type": "text", "content": item.get("text", ""), "tag": "default"})
                    elif item.get("type") == "image_url":
                        has_image_content = self.process_image_for_chat(has_image_content, item,
                                                                        processed_content_parts)

            if has_image_content and not any(
                    part["type"] == "text" and part["content"].strip() for part in processed_content_parts):
                # Если есть только изображения и нет текста, добавляем метку
                processed_content_parts.insert(0, {"type": "text",
                                                   "content": _("<Изображение экрана>", "<Screen Image>") + "\n",
                                                   "tag": "default"})

        elif isinstance(content, str):
            processed_content_parts.append({"type": "text", "content": content, "tag": "default"})
        else:
            return

            # Обработка тегов в текстовом содержимом
        processed_text_parts = []
        hide_tags = self.settings.get("HIDE_CHAT_TAGS", False)

        for part in processed_content_parts:
            if part["type"] == "text":
                text_content = part["content"]
                if hide_tags:
                    # Удаляем все теги и их содержимое
                    text_content = process_text_to_voice(text_content)
                    processed_text_parts.append({"type": "text", "content": text_content, "tag": "default"})
                else:
                    matches = list(
                        re.finditer(
                            r'(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)|(\[b\](.*?)\[\/b\])|(\[i\](.*?)\[\/i\])|(\[color=(.*?)\](.*?)\[\/color\])',
                            text_content))

                    last_end = 0
                    for match in matches:
                        start, end = match.span()
                        # Добавляем текст до совпадения без тега
                        if start > last_end:
                            processed_text_parts.append(
                                {"type": "text", "content": text_content[last_end:start], "tag": "default"})

                        # Обрабатываем совпадение
                        if match.group(1) is not None:  # Парные теги <любое_имя>...</любое_имя>
                            # match.group(1) = "<tag>"
                            # match.group(3) = "content"
                            # match.group(4) = "</tag>"
                            processed_text_parts.append(
                                {"type": "text", "content": match.group(1), "tag": "tag_green"})  # Открывающий тег
                            processed_text_parts.append(
                                {"type": "text", "content": match.group(3), "tag": "default"})  # Содержимое тега
                            processed_text_parts.append(
                                {"type": "text", "content": match.group(4), "tag": "tag_green"})  # Закрывающий тег
                        elif match.group(5) is not None:  # Одиночные открывающие теги <любое_имя>
                            # match.group(5) = "<tag>"
                            processed_text_parts.append({"type": "text", "content": match.group(5), "tag": "tag_green"})
                        elif match.group(7) is not None:  # Жирный текст [b]
                            processed_text_parts.append({"type": "text", "content": match.group(7), "tag": "bold"})
                        elif match.group(9) is not None:  # Курсивный текст [i]
                            processed_text_parts.append({"type": "text", "content": match.group(9), "tag": "italic"})
                        elif match.group(11) is not None and match.group(12) is not None:  # Цветной текст [color=...]
                            color = match.group(11)
                            colored_text = match.group(12)
                            tag_name = f"color_{color.replace('#', '').replace(' ', '_')}"
                            if tag_name not in self.chat_window.tag_names():
                                try:
                                    self.chat_window.tag_configure(tag_name, foreground=color)
                                except tk.TclError:
                                    logger.warning(f"Неверный формат цвета: {color}. Использование цвета по умолчанию.")
                                    tag_name = "Mita"
                            processed_text_parts.append(
                                {"type": "text", "content": f"[color={color}]{colored_text}[/color]", "tag": tag_name})

                        last_end = end

                    # Добавляем оставшийся текст после последнего совпадения без тега
                    if last_end < len(text_content):
                        processed_text_parts.append(
                            {"type": "text", "content": text_content[last_end:], "tag": "default"})
            else:
                processed_text_parts.append(part)

        # Вставка сообщений
        self.chat_window.config(state=tk.NORMAL)  # Включаем редактирование

        show_timestamps = self.settings.get("SHOW_CHAT_TIMESTAMPS", False)
        timestamp_str = "[???] "
        if show_timestamps:
            if message_time:
                timestamp_str = f"[{message_time}]"
            else:
                timestamp_str = time.strftime("[%H:%M:%S] ")

        if insert_at_start:
            # Собираем части сообщения в список в желаемом порядке отображения
            # (метка времени, имя, содержимое, перевод строки)
            parts_to_insert_in_order = []

            if show_timestamps:
                parts_to_insert_in_order.append({"type": "text", "content": timestamp_str, "tag": "timestamp"})

            if role == "user":
                parts_to_insert_in_order.append({"type": "text", "content": _("Вы: ", "You: "), "tag": "Player"})
            elif role == "assistant":
                parts_to_insert_in_order.append(
                    {"type": "text", "content": f"{self.model.current_character.name}: ", "tag": "Mita"})

            # Добавляем содержимое сообщения
            parts_to_insert_in_order.extend(processed_text_parts)

            # Добавляем переводы строк в конце
            if role == "user":
                parts_to_insert_in_order.append({"type": "text", "content": "\n"})
            elif role in {"assistant","system"}:
                parts_to_insert_in_order.append({"type": "text", "content": "\n\n"})

            # Вставляем все части в обратном порядке, чтобы они появились в правильном порядке в чате
            # (потому что insert(1.0, ...) вставляет в начало)
            for part in reversed(parts_to_insert_in_order):
                if part["type"] == "text":
                    self.chat_window.insert(1.0, part["content"], part.get("tag", "default"))
                elif part["type"] == "image":
                    self.chat_window.image_create(1.0, image=part["content"])
                    self.chat_window.insert(1.0, "\n")  # Добавляем перевод строки после изображения
        else:
            if role == "user":
                if show_timestamps:
                    self.chat_window.insert(tk.END, timestamp_str, "timestamp")
                self.chat_window.insert(tk.END, _("Вы: ", "You: "), "Player")  # Имя персонажа подсвечивается
                for part in processed_text_parts:
                    if part["type"] == "text":
                        self.chat_window.insert(tk.END, part["content"], part.get("tag", "default"))
                    elif part["type"] == "image":
                        self.chat_window.image_create(tk.END, image=part["content"])
                        self.chat_window.insert(tk.END, "\n")
                self.chat_window.insert(tk.END, "\n")
            elif role in {"assistant","system"}:
                if show_timestamps:
                    self.chat_window.insert(tk.END, timestamp_str, "timestamp")
                self.chat_window.insert(tk.END, f"{self.model.current_character.name}: ",
                                        "Mita")  # Имя персонажа подсвечивается
                for part in processed_text_parts:
                    if part["type"] == "text":
                        self.chat_window.insert(tk.END, part["content"], part.get("tag", "default"))
                    elif part["type"] == "image":
                        self.chat_window.image_create(tk.END, image=part["content"])
                        self.chat_window.insert(tk.END, "\n")
                self.chat_window.insert(tk.END, "\n\n")
        self.chat_window.config(state=tk.DISABLED)  # Выключаем редактирование

        # Автоматическая прокрутка вниз после вставки сообщения
        self.chat_window.see(tk.END)

    def process_image_for_chat(self, has_image_content, item, processed_content_parts):
        image_data_base64 = item.get("image_url", {}).get("url", "")
        if image_data_base64.startswith("data:image/jpeg;base64,"):
            image_data_base64 = image_data_base64.replace("data:image/jpeg;base64,", "")
        elif image_data_base64.startswith("data:image/png;base64,"):
            image_data_base64 = image_data_base64.replace("data:image/png;base64,", "")
        try:
            image_bytes = base64.b64decode(image_data_base64)
            image = Image.open(io.BytesIO(image_bytes))

            # Изменение размера изображения
            max_width = 400
            max_height = 300
            original_width, original_height = image.size

            if original_width > max_width or original_height > max_height:
                ratio = min(max_width / original_width, max_height / original_height)
                new_width = int(original_width * ratio)
                new_height = int(original_height * ratio)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            photo = ImageTk.PhotoImage(image)
            self._images_in_chat.append(photo)  # Сохраняем ссылку
            processed_content_parts.append({"type": "image", "content": photo})
            has_image_content = True
        except Exception as e:
            logger.error(f"Ошибка при декодировании или обработке изображения: {e}")
            processed_content_parts.append(
                {"type": "text", "content": _("<Ошибка загрузки изображения>", "<Image load error>")})
        return has_image_content

    # region секция g4f
    def _check_and_perform_pending_update(self):
        """Проверяет, запланировано ли обновление g4f, и выполняет его."""
        if not self.pip_installer:
            logger.warning("PipInstaller не инициализирован, проверка отложенного обновления пропущена.")
            return

        update_pending = self.settings.get("G4F_UPDATE_PENDING", False)
        target_version = self.settings.get("G4F_TARGET_VERSION", None)

        if update_pending and target_version:
            logger.info(f"Обнаружено запланированное обновление g4f до версии: {target_version}")
            package_spec = f"g4f=={target_version}" if target_version != "latest" else "g4f"
            description = f"Запланированное обновление g4f до {target_version}..."

            success = False
            try:
                success = self.pip_installer.install_package(
                    package_spec,
                    description=description,
                    extra_args=["--force-reinstall", "--upgrade"]
                )
                if success:
                    logger.info(f"Запланированное обновление g4f до {target_version} успешно завершено.")
                    try:
                        importlib.invalidate_caches()
                        logger.info("Кэш импорта очищен после запланированного обновления.")
                    except Exception as e_invalidate:
                        logger.error(f"Ошибка при очистке кэша импорта после обновления: {e_invalidate}")
                else:
                    logger.error(f"Запланированное обновление g4f до {target_version} не удалось (ошибка pip).")
            except Exception as e_install:
                logger.error(f"Исключение во время запланированного обновления g4f: {e_install}", exc_info=True)
                success = False  # Явно указываем на неудачу

            finally:
                # --- ВАЖНО: Сбрасываем флаги независимо от успеха ---
                logger.info("Сброс флагов запланированного обновления g4f.")
                self.settings.set("G4F_UPDATE_PENDING", False)
                self.settings.set("G4F_TARGET_VERSION", None)  # Или ""
                self.settings.save_settings()
        else:
            logger.info("Нет запланированных обновлений g4f.")

    def trigger_g4f_reinstall_schedule(self):
        """
        Считывает версию из поля ввода, сохраняет ее и флаг для обновления
        при следующем запуске. Информирует пользователя.
        """
        logger.info("Запрос на планирование обновления g4f...")

        target_version = None
        if hasattr(self, 'g4f_version_entry') and self.g4f_version_entry:
            target_version = self.g4f_version_entry.get().strip()
            if not target_version:
                messagebox.showerror(_("Ошибка", "Error"),
                                     _("Пожалуйста, введите версию g4f или 'latest'.",
                                       "Please enter a g4f version or 'latest'."),
                                     parent=self.root)
                return
        else:
            logger.error("Виджет entry для версии g4f не найден.")
            messagebox.showerror(_("Ошибка", "Error"),
                                 _("Не найден элемент интерфейса для ввода версии.",
                                   "UI element for version input not found."),
                                 parent=self.root)
            return

        try:
            # Сохраняем целевую версию и устанавливаем флаг
            self.settings.set("G4F_TARGET_VERSION", target_version)
            self.settings.set("G4F_UPDATE_PENDING", True)
            # Также обновим G4F_VERSION, чтобы в поле осталась введенная версия
            self.settings.set("G4F_VERSION", target_version)
            self.settings.save_settings()
            logger.info(f"Обновление g4f до версии '{target_version}' запланировано на следующий запуск.")

            # Информируем пользователя
            messagebox.showinfo(
                _("Запланировано", "Scheduled"),
                _("Версия g4f '{version}' будет установлена/обновлена при следующем запуске программы.",
                  "g4f version '{version}' will be installed/updated the next time the program starts.").format(
                    version=target_version),
                parent=self.root
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении настроек для запланированного обновления: {e}", exc_info=True)
            messagebox.showerror(
                _("Ошибка сохранения", "Save Error"),
                _("Не удалось сохранить настройки для обновления. Пожалуйста, проверьте логи.",
                  "Failed to save settings for the update. Please check the logs."),
                parent=self.root
            )

    # endregion

    def update_game_connection(self, is_connected):
        self.ConnectedToGame = is_connected
        self.game_connected_checkbox_var = tk.BooleanVar(value=is_connected)  # Статус подключения к игре

    def update_all(self):
        self.update_status_colors()
        self.update_debug_info()

    def update_status_colors(self):
        self.game_connected_checkbox_var = tk.BooleanVar(value=self.ConnectedToGame)  # Статус подключения к игре
        # Обновление цвета для подключения к игре
        game_color = "#00ff00" if self.ConnectedToGame else "#ffffff"
        self.game_status_checkbox.config(fg=game_color)

        # Обновление цвета для подключения к Silero
        silero_color = "#00ff00" if self.silero_connected.get() else "#ffffff"
        self.silero_status_checkbox.config(fg=silero_color)

    def load_chat_history(self):
        self.clear_chat_display()
        self.loaded_messages_offset = 0
        self.total_messages_in_history = 0
        self.loading_more_history = False

        chat_history = self.model.current_character.load_history()
        all_messages = chat_history["messages"]
        self.total_messages_in_history = len(all_messages)
        logger.info(f"[{time.strftime('%H:%M:%S')}] Всего сообщений в истории: {self.total_messages_in_history}")

        # Определяем максимальное количество сообщений для отображения
        max_display_messages = int(self.settings.get("MAX_CHAT_HISTORY_DISPLAY", 100))

        # Загружаем последние N сообщений
        start_index = max(0, self.total_messages_in_history - max_display_messages)
        messages_to_load = all_messages[start_index:]

        for entry in messages_to_load:
            role = entry["role"]
            content = entry["content"]
            message_time = entry.get("time", "???")
            self.insert_message(role, content, message_time=message_time)  # Вставляем в конец, как обычно

        self.loaded_messages_offset = len(messages_to_load)
        logger.info(f"[{time.strftime('%H:%M:%S')}] Загружено {self.loaded_messages_offset} последних сообщений.")

        # Привязываем событие прокрутки
        self.chat_window.bind("<MouseWheel>", self.on_chat_scroll)
        self.chat_window.bind("<Button-4>", self.on_chat_scroll)  # Linux
        self.chat_window.bind("<Button-5>", self.on_chat_scroll)  # Linux

        self.update_debug_info()
        self.update_token_count()
        # Автоматическая прокрутка вниз после загрузки истории
        self.chat_window.see(tk.END)

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

    def setup_model_controls(self, parent):
        # Основные настройки
        mita_config = [
            {'label': _('Использовать gpt4free', 'Use gpt4free'), 'key': 'gpt4free', 'type': 'checkbutton',
             'default_checkbutton': False},
            {'label': _('gpt4free | Модель gpt4free', 'gpt4free | model gpt4free'), 'key': 'gpt4free_model',
             'type': 'entry', 'default': "gemini-1.5-flash"},
            # gpt-4o-mini тоже подходит
        ]

        self.create_settings_section(parent, _("Настройки gpt4free модели", "Gpt4free settings"), mita_config)

    def setup_common_controls(self, parent):
        # Основные настройки
        common_config = [
            {'label': _('Скрывать (приватные) данные', 'Hide (private) data'), 'key': 'HIDE_PRIVATE',
             'type': 'checkbutton',
             'default_checkbutton': True},

        ]
        self.create_settings_section(parent, _("Общие настройки", "Common settings"), common_config)

    #endregion

    # region Validation
    def validate_number_0_60(self, new_value):
        if not new_value.isdigit():  # Проверяем, что это число
            return False
        return 0 <= int(new_value) <= 60  # Проверяем, что в пределах диапазона

    def validate_float_0_1(self, new_value):
        try:
            val = float(new_value)
            return 0.0 <= val <= 1.0
        except ValueError:
            return False

    def validate_float_positive(self, new_value):
        try:
            val = float(new_value)
            return val > 0.0
        except ValueError:
            return False

    def validate_float_positive_or_zero(self, new_value):
        if new_value == "": return True
        try:
            value = float(new_value)
            return value >= 0.0
        except ValueError:
            return False

    def validate_positive_integer(self, new_value):
        if new_value == "": return True  # Разрешаем пустое поле временно

        try:
            value = int(new_value)
            return value > 0
        except ValueError:
            return False

    def validate_positive_integer_or_zero(self, new_value):
        if new_value == "": return True
        try:
            value = int(new_value)
            return value >= 0
        except ValueError:
            return False

    def validate_float_0_to_1(self, new_value):
        if new_value == "": return True
        try:
            value = float(new_value)
            return 0.0 <= value <= 1.0
        except ValueError:
            return False

    def validate_float_0_to_2(self, new_value):
        if new_value == "": return True
        try:
            value = float(new_value)
            return 0.0 <= value <= 2.0
        except ValueError:
            return False

    def validate_float_minus2_to_2(self, new_value):
        if new_value == "": return True
        try:
            value = float(new_value)
            return -2.0 <= value <= 2.0
        except ValueError:
            return False

    # endregion

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

    def update_debug_info(self):
        """Обновить окно отладки с отображением актуальных данных."""
        self.debug_window.delete(1.0, tk.END)  # Очистить старые данные

        debug_info = (self.model.current_character.current_variables_string())

        self.debug_window.insert(tk.END, debug_info)

    def update_token_count(self, event=None):
        show_token_info = self.settings.get("SHOW_TOKEN_INFO", True)

        if show_token_info and self.model.hasTokenizer:
            # Получаем текущий контекст из модели
            current_context_tokens = self.model.get_current_context_token_count()

            # Получаем значения из настроек или используем значения по умолчанию
            token_cost_input = float(self.settings.get("TOKEN_COST_INPUT", 0.000001))
            token_cost_output = float(self.settings.get("TOKEN_COST_OUTPUT", 0.000002))
            max_model_tokens = int(self.settings.get("MAX_MODEL_TOKENS", 32000))

            # Обновляем атрибуты модели, если они еще не были обновлены через all_settings_actions
            self.model.token_cost_input = token_cost_input
            self.model.token_cost_output = token_cost_output
            self.model.max_model_tokens = max_model_tokens

            cost = self.model.calculate_cost_for_current_context()

            self.token_count_label.config(
                text=_("Токены: {}/{} (Макс. токены: {}) | Ориент. стоимость: {:.4f} ₽",
                       "Tokens: {}/{} (Max tokens: {}) | Approx. cost: {:.4f} ₽").format(
                    current_context_tokens, max_model_tokens, max_model_tokens, cost
                )
            )
            self.token_count_label.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(0, 5))  # Показываем метку
        else:
            self.token_count_label.pack_forget()  # Скрываем метку
            self.token_count_label.config(
                text=_("Токены: Токенизатор недоступен", "Tokens: Tokenizer not available")
            )
        self.update_debug_info()

    def insert_dialog(self, input_text="", response="", system_text=""):
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

    def clear_chat_display(self):
        """Очищает отображаемую историю чата в GUI."""
        self.chat_window.config(state=tk.NORMAL)
        self.chat_window.delete(1.0, tk.END)
        self.chat_window.config(state=tk.DISABLED)

    def send_message(self, system_input: str = "", image_data: list[bytes] = None):
        user_input = self.user_entry.get("1.0", "end-1c").strip()  # Убираем пробелы сразу
        # Если включен анализ экрана, пытаемся получить последние кадры
        current_image_data = []
        if self.settings.get("ENABLE_SCREEN_ANALYSIS", False):
            history_limit = int(self.settings.get("SCREEN_CAPTURE_HISTORY_LIMIT", 1))
            frames = self.screen_capture_instance.get_recent_frames(history_limit)
            if frames:
                current_image_data.extend(frames)
                #logger.info(f"Захвачено {len(frames)} кадров для отправки.")
            else:
                logger.info("Анализ экрана включен, но кадры не готовы или история пуста.")

        # Объединяем переданные изображения с текущими захваченными
        all_image_data = (image_data if image_data is not None else []) + current_image_data

        # Если включен захват с камеры, добавляем кадры с камеры
        if self.settings.get("ENABLE_CAMERA_CAPTURE", False):
            if hasattr(self, 'camera_capture') and self.camera_capture is not None and self.camera_capture.is_running():
                history_limit = int(self.settings.get("CAMERA_CAPTURE_HISTORY_LIMIT", 1))
                camera_frames = self.camera_capture.get_recent_frames(history_limit)
                if camera_frames:
                    all_image_data.extend(camera_frames)
                    logger.info(f"Добавлено {len(camera_frames)} кадров с камеры для отправки.")
                else:
                    logger.info("Захват с камеры включен, но кадры не готовы или история пуста.")

        # Отправляем сообщение, если есть пользовательский ввод ИЛИ системный ввод ИЛИ изображения
        if not user_input and not system_input:
            #logger.info("Нет текста или изображений для отправки.")
            return

        self.last_image_request_time = time.time()  # Сброс таймера захвата экрана при мгновенной отправке

        if user_input:  # Вставляем сообщение в чат только если есть пользовательский текст
            self.insert_message("user", user_input)
            self.user_entry.delete("1.0", "end")

        # Вставляем изображения в чат сразу, если они есть
        if all_image_data:
            # Создаем структуру, аналогичную той, что приходит из истории, для insert_message
            image_content_for_display = [{"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{base64.b64encode(img).decode('utf-8')}"}} for img in all_image_data]
            # Добавляем текстовую метку, если нет пользовательского ввода, но есть изображения
            if not user_input:
                image_content_for_display.insert(0, {"type": "text",
                                                     "content": _("<Изображение экрана>", "<Screen Image>") + "\n"})
            self.insert_message("user", image_content_for_display)

        # Запускаем асинхронную задачу для генерации ответа
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.async_send_message(user_input, system_input, all_image_data),
                                             self.loop)

    async def async_send_message(self, user_input: str, system_input: str = "", image_data: list[bytes] = None):
        try:
            # Ограничиваем выполнение задачи
            response = await asyncio.wait_for(
                self.loop.run_in_executor(None,
                                          lambda: self.model.generate_response(user_input, system_input, image_data)),
                timeout=60.0  # Тайм-аут в секундах
            )
            self.root.after(0, lambda: self.insert_message("assistant", response))
            self.root.after(0, self.update_all)
            self.root.after(0, self.update_token_count)  # Обновляем счетчик токенов после получения ответа
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

    def start_camera_capture_thread(self):
        if not hasattr(self, 'camera_capture') or self.camera_capture is None:
            from CameraCapture import CameraCapture
            self.camera_capture = CameraCapture()

        if not self.camera_capture.is_running():
            camera_index = int(self.settings.get("CAMERA_INDEX", 0))
            interval = float(self.settings.get("CAMERA_CAPTURE_INTERVAL", 5.0))
            quality = int(self.settings.get("CAMERA_CAPTURE_QUALITY", 25))
            fps = int(self.settings.get("CAMERA_CAPTURE_FPS", 1))
            max_history_frames = int(self.settings.get("CAMERA_CAPTURE_HISTORY_LIMIT", 3))
            max_frames_per_request = int(self.settings.get("CAMERA_CAPTURE_TRANSFER_LIMIT", 1))
            capture_width = int(self.settings.get("CAMERA_CAPTURE_WIDTH", 640))
            capture_height = int(self.settings.get("CAMERA_CAPTURE_HEIGHT", 480))
            self.camera_capture.start_capture(camera_index, quality, fps, max_history_frames,
                                                       max_frames_per_request, capture_width,
                                                       capture_height)
            logger.info(
                f"Поток захвата с камеры запущен с индексом {camera_index}, интервалом {interval}, качеством {quality}, {fps} FPS, историей {max_history_frames} кадров, разрешением {capture_width}x{capture_height}.")

    def stop_camera_capture_thread(self):
        if hasattr(self, 'camera_capture') and self.camera_capture is not None and self.camera_capture.is_running():
            self.camera_capture.stop_capture()
            logger.info("Поток захвата с камеры остановлен.")

    def start_screen_capture_thread(self):
        if not self.screen_capture_running:
            interval = float(self.settings.get("SCREEN_CAPTURE_INTERVAL", 5.0))
            quality = int(self.settings.get("SCREEN_CAPTURE_QUALITY", 25))
            fps = int(self.settings.get("SCREEN_CAPTURE_FPS", 1))
            max_history_frames = int(self.settings.get("SCREEN_CAPTURE_HISTORY_LIMIT", 3))
            max_frames_per_request = int(self.settings.get("SCREEN_CAPTURE_TRANSFER_LIMIT", 1))
            capture_width = int(self.settings.get("SCREEN_CAPTURE_WIDTH", 1024))
            capture_height = int(self.settings.get("SCREEN_CAPTURE_HEIGHT", 768))
            self.screen_capture_instance.start_capture(interval, quality, fps, max_history_frames,
                                                       max_frames_per_request, capture_width,
                                                       capture_height)
            self.screen_capture_running = True
            logger.info(
                f"Поток захвата экрана запущен с интервалом {interval}, качеством {quality}, {fps} FPS, историей {max_history_frames} кадров, разрешением {capture_width}x{capture_height}.")

            if self.settings.get("SEND_IMAGE_REQUESTS", 1):
                self.start_image_request_timer()

    def stop_screen_capture_thread(self):
        if self.screen_capture_running:
            self.screen_capture_instance.stop_capture()
            self.screen_capture_running = False
            logger.info("Поток захвата экрана остановлен.")

    def start_image_request_timer(self):
        if not self.image_request_timer_running:
            self.image_request_timer_running = True
            # Устанавливаем время последнего запроса так, чтобы следующий запрос произошел немедленно
            # interval = float(self.settings.get("IMAGE_REQUEST_INTERVAL", 20.0))
            self.last_image_request_time = time.time()  # - interval
            logger.info("Таймер периодической отправки изображений запущен.")

    def stop_image_request_timer(self):
        if self.image_request_timer_running:
            self.image_request_timer_running = False
            logger.info("Таймер периодической отправки изображений остановлен.")



    def on_chat_scroll(self, event):
        """Обработчик события прокрутки чата."""
        if self.loading_more_history:
            return

        # Проверяем, прокрутил ли пользователь к началу
        if self.chat_window.yview()[0] == 0:
            self.load_more_history()
        # Проверяем, прокрутил ли пользователь к концу и движется вниз
        elif self.chat_window.yview()[1] == 1.0 and (event.delta < 0 or (hasattr(event, 'num') and event.num == 5)):
            self.trim_chat_display()

    def trim_chat_display(self):
        """Удаляет сообщения из начала чата, оставляя только видимые + запас."""
        # Получаем общее количество строк в виджете Text
        total_lines = int(self.chat_window.index(tk.END).split('.')[0])

        # Получаем индекс первой видимой строки
        first_visible_line_index = int(self.chat_window.index("@0,0").split('.')[0])

        # Определяем буфер (количество строк, которые нужно оставить выше первой видимой)
        buffer_size = 20  # Например, 20 строк

        # Вычисляем количество строк для удаления
        # Удаляем все строки до первой видимой, оставляя буфер
        lines_to_delete = max(0, first_visible_line_index - buffer_size)

        if lines_to_delete > 0:
            self.chat_window.config(state=tk.NORMAL)
            # Удаляем строки с начала до (lines_to_delete + 1).0
            # +1.0 потому что delete удаляет до указанной позиции, не включая ее
            self.chat_window.delete("1.0", f"{lines_to_delete + 1}.0")
            self.chat_window.config(state=tk.DISABLED)
            # Уменьшаем смещение загруженных сообщений на количество удаленных строк
            self.loaded_messages_offset -= lines_to_delete
            logger.info(f"Удалено {lines_to_delete} сообщений из начала чата. Обновлено loaded_messages_offset: {self.loaded_messages_offset}")

    def load_more_history(self):
        """Загружает предыдущие сообщения в чат."""
        if self.loaded_messages_offset >= self.total_messages_in_history:
            return

        self.loading_more_history = True
        try:
            chat_history = self.model.current_character.load_history()
            all_messages = chat_history["messages"]

            # Определяем диапазон сообщений для загрузки
            end_index = self.total_messages_in_history - self.loaded_messages_offset
            start_index = max(0, end_index - self.lazy_load_batch_size)

            messages_to_prepend = all_messages[start_index:end_index]

            # Сохраняем текущую высоту содержимого чата перед вставкой
            old_content_height = self.chat_window.winfo_height()

            # Вставляем сообщения в обратном порядке, чтобы они появились в правильном порядке в чате
            for entry in reversed(messages_to_prepend):
                role = entry["role"]
                content = entry["content"]
                message_time = entry.get("time", "???")
                self.insert_message(role, content, insert_at_start=True, message_time=message_time)

            self.loaded_messages_offset += len(messages_to_prepend)
            logger.info(
                f"Загружено еще {len(messages_to_prepend)} сообщений. Всего загружено: {self.loaded_messages_offset}")

            # Обновляем виджет, чтобы он пересчитал свои размеры после вставки
            self.root.update_idletasks()

            # Получаем новую высоту содержимого чата
            new_content_height = self.chat_window.winfo_height()

            # Вычисляем разницу в высоте
            height_difference = new_content_height - old_content_height

            # Скорректировать прокрутку, переместив ее на height_difference пикселей вверх
            # Это компенсирует добавленный контент и сохраняет видимую область
            self.chat_window.yview_scroll(-height_difference, "pixels")

        finally:
            self.loading_more_history = False



    def _show_loading_popup(self, message):
        """Показать окно загрузки"""
        self.loading_popup = tk.Toplevel(self.root)
        self.loading_popup.title(" ")
        self.loading_popup.geometry("300x100")
        self.loading_popup.configure(bg="#2c2c2c")

        tk.Label(
            self.loading_popup,
            text=message,
            bg="#2c2c2c",
            fg="#ffffff",
            font=("Arial", 12)
        ).pack(pady=20)

        self.loading_popup.transient(self.root)
        self.loading_popup.grab_set()
        self.root.update()

    def _close_loading_popup(self):
        if self.loading_popup and self.loading_popup.winfo_exists():
            self.loading_popup.grab_release()
            self.loading_popup.destroy()

    #region SettingGUI - MODIFIED BUT NOT CHECKED
    def all_settings_actions(self, key, value):
        if key in ["SILERO_USE", "VOICEOVER_METHOD", "AUDIO_BOT"]:
            self.switch_voiceover_settings()

        if key == "SILERO_TIME":
            self.bot_handler.silero_time_limit = int(value)

        if key == "AUDIO_BOT":
            # Возвращаем старое сообщение
            if value.startswith("@CrazyMitaAIbot"):
                messagebox.showinfo("Информация",
                                    "VinerX: наши товарищи из CrazyMitaAIbot предоставляет озвучку бесплатно буквально со своих пк, будет время - загляните к ним в тг, скажите спасибо)",
                                    parent=self.root)

            if self.bot_handler:
                self.bot_handler.tg_bot = value

        elif key == "CHARACTER":
            self.model.current_character_to_change = value
            self.model.check_change_current_character()

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

        elif key == "MIC_ACTIVE":
            if bool(value):
                # Запускаем распознавание, если оно активировано
                SpeechRecognition.speach_recognition_start(self.device_id, self.loop)
            else:
                # Останавливаем распознавание, если оно деактивировано
                SpeechRecognition.speach_recognition_stop()

        elif key == "ENABLE_SCREEN_ANALYSIS":
            if bool(value):
                self.start_screen_capture_thread()
            else:
                self.stop_screen_capture_thread()
        elif key == "ENABLE_CAMERA_CAPTURE":
            if bool(value):
                self.start_camera_capture_thread()
            else:
                self.stop_camera_capture_thread()
        elif key in ["SCREEN_CAPTURE_INTERVAL", "SCREEN_CAPTURE_QUALITY", "SCREEN_CAPTURE_FPS",
                     "SCREEN_CAPTURE_HISTORY_LIMIT", "SCREEN_CAPTURE_TRANSFER_LIMIT", "SCREEN_CAPTURE_WIDTH",
                     "SCREEN_CAPTURE_HEIGHT"]:
            # Если поток захвата экрана запущен, перезапускаем его с новыми настройками
            if self.screen_capture_instance and self.screen_capture_instance.is_running():
                logger.info(f"Настройка захвата экрана '{key}' изменена на '{value}'. Перезапускаю поток захвата.")
                self.stop_screen_capture_thread()
                self.start_screen_capture_thread()
            else:
                logger.info(
                    f"Настройка захвата экрана '{key}' изменена на '{value}'. Поток захвата не активен, изменения будут применены при следующем запуске.")
        elif key == "SEND_IMAGE_REQUESTS":
            if bool(value):
                self.start_image_request_timer()
            else:
                self.stop_image_request_timer()
        elif key == "IMAGE_REQUEST_INTERVAL":
            if self.image_request_timer_running:
                logger.info(f"Настройка интервала запросов изображений изменена на '{value}'. Перезапускаю таймер.")
                self.stop_image_request_timer()
                self.start_image_request_timer()
            else:
                logger.info(
                    f"Настройка интервала запросов изображений изменена на '{value}'. Таймер не активен, изменения будут применены при следующем запуске.")
        elif key in ["EXCLUDE_GUI_WINDOW", "EXCLUDE_WINDOW_TITLE"]:
            # Получаем текущие значения настроек
            exclude_gui = self.settings.get("EXCLUDE_GUI_WINDOW", False)
            exclude_title = self.settings.get("EXCLUDE_WINDOW_TITLE", "")

            hwnd_to_pass = None
            if exclude_gui:
                # Если включено исключение GUI, получаем HWND текущего окна Tkinter
                hwnd_to_pass = self.root.winfo_id()
                logger.info(f"Получен HWND окна GUI для исключения: {hwnd_to_pass}")
            elif exclude_title:
                # Если указан заголовок, пытаемся найти HWND по заголовку
                try:
                    hwnd_to_pass = win32gui.FindWindow(None, exclude_title)
                    if hwnd_to_pass:
                        logger.info(f"Найден HWND для заголовка '{exclude_title}': {hwnd_to_pass}")
                    else:
                        logger.warning(f"Окно с заголовком '{exclude_title}' не найдено.")
                except Exception as e:
                    logger.error(f"Ошибка при поиске окна по заголовку '{exclude_title}': {e}")

            # Передаем параметры в ScreenCapture
            if self.screen_capture_instance:
                self.screen_capture_instance.set_exclusion_parameters(hwnd_to_pass, exclude_title,
                                                                      exclude_gui or bool(exclude_title))
                logger.info(
                    f"Параметры исключения окна переданы в ScreenCapture: exclude_gui={exclude_gui}, exclude_title='{exclude_title}'")

            # Если поток захвата экрана запущен, перезапускаем его с новыми настройками
            if self.screen_capture_instance and self.screen_capture_instance.is_running():
                logger.info(f"Настройка исключения окна '{key}' изменена на '{value}'. Перезапускаю поток захвата.")
                self.stop_screen_capture_thread()
                self.start_screen_capture_thread()
            else:
                logger.info(
                    f"Настройка исключения окна '{key}' изменена на '{value}'. Поток захвата не активен, изменения будут применены при следующем запуске.")
        elif key == "RECOGNIZER_TYPE":
            # Останавливаем текущее распознавание
            SpeechRecognition.active = False
            # Даем время на завершение текущего потока
            time.sleep(0.1)  # Небольшая задержка

            # Устанавливаем новый тип распознавателя
            SpeechRecognition.set_recognizer_type(value)

            # Перезапускаем распознавание с новым типом
            SpeechRecognition.active = True  # Активируем снова
            SpeechRecognition.speach_recognition_start(self.device_id, self.loop)
            microphone_settings.update_vosk_model_visibility(self,value)
        elif key == "VOSK_MODEL":
            SpeechRecognition.vosk_model = value
        elif key == "SILENCE_THRESHOLD":
            SpeechRecognition.SILENCE_THRESHOLD = float(value)
        elif key == "SILENCE_DURATION":
            SpeechRecognition.SILENCE_DURATION = float(value)
        elif key == "VOSK_PROCESS_INTERVAL":
            SpeechRecognition.VOSK_PROCESS_INTERVAL = float(value)
        elif key == "IMAGE_QUALITY_REDUCTION_ENABLED":
            self.model.image_quality_reduction_enabled = bool(value)

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




        # Handle chat specific settings keys
        if key == "CHAT_FONT_SIZE":
            try:
                font_size = int(value)
                # Обновляем размер шрифта для всех тегов, использующих "Arial"
                for tag_name in self.chat_window.tag_names():
                    current_font = self.chat_window.tag_cget(tag_name, "font")
                    if "Arial" in current_font:
                        # Разбираем текущий шрифт, чтобы сохранить стиль (bold, italic)
                        font_parts = current_font.split()
                        new_font_parts = ["Arial", str(font_size)]
                        if "bold" in font_parts:
                            new_font_parts.append("bold")
                        if "italic" in font_parts:
                            new_font_parts.append("italic")
                        self.chat_window.tag_configure(tag_name, font=(" ".join(new_font_parts)))
                logger.info(f"Размер шрифта чата изменен на: {font_size}")
            except ValueError:
                logger.warning(f"Неверное значение для размера шрифта чата: {value}")
            except Exception as e:
                logger.error(f"Ошибка при изменении размера шрифта чата: {e}")
        elif key == "SHOW_CHAT_TIMESTAMPS":
            # Перезагружаем историю чата, чтобы применить/убрать метки времени
            self.load_chat_history()
            logger.info(f"Настройка 'Показывать метки времени' изменена на: {value}. История чата перезагружена.")
        elif key == "MAX_CHAT_HISTORY_DISPLAY":
            # Перезагружаем историю чата, чтобы применить новое ограничение
            self.load_chat_history()
            logger.info(f"Настройка 'Макс. сообщений в истории' изменена на: {value}. История чата перезагружена.")
        elif key == "HIDE_CHAT_TAGS":
            # Перезагружаем историю чата, чтобы применить/убрать скрытие тегов
            self.load_chat_history()
            logger.info(f"Настройка 'Скрывать теги' изменена на: {value}. История чата перезагружена.")


        elif key == "SHOW_TOKEN_INFO":
            self.update_token_count()
        elif key == "TOKEN_COST_INPUT":
            self.model.token_cost_input = float(value)
            self.update_token_count()
        elif key == "TOKEN_COST_OUTPUT":
            self.model.token_cost_output = float(value)
            self.update_token_count()
        elif key == "MAX_MODEL_TOKENS":
            self.model.max_model_tokens = int(value)
            self.update_token_count()

        # logger.info(f"Настройки изменены: {key} = {value}")

    #endregion

    def create_settings_section(self, parent, title, settings_config):
        return guiTemplates.create_settings_section(self, parent, title, settings_config)

    def create_setting_widget(self, parent, label, setting_key, widget_type='entry',
                              options=None, default='', default_checkbutton=False, validation=None, tooltip=None,
                              width=None, height=None, command=None, hide=False):

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

        return guiTemplates.create_setting_widget(self, parent, label, setting_key, widget_type,
                                                  options, default, default_checkbutton, validation, tooltip,
                                                  width, height, command, hide)

    def create_tooltip(self, widget, text):
        guiTemplates.create_tooltip(self, widget, text)

    def _save_setting(self, key, value):
        self.settings.set(key, value)
        self.settings.save_settings()

        self.all_settings_actions(key, value)

    #endregion

    def get_news_content(self):
        """Получает содержимое новостей с GitHub"""
        try:
            response = requests.get('https://raw.githubusercontent.com/VinerX/NeuroMita/main/NEWS.md', timeout=500)
            #response = requests.get('https://raw.githubusercontent.com/VinerX/NeuroMita/refs/heads/main/NEWS.md', timeout=500)
            if response.status_code == 200:
                return response.text
            return _('Не удалось загрузить новости', 'Failed to load news')
        except Exception as e:
            logger.info(f"Ошибка при получении новостей: {e}")
            return _('Ошибка при загрузке новостей', 'Error loading news')

    def setup_news_control(self, parent):
        news_config = [
            #{'label': _('Новости и обновления', 'News and updates'), 'type': 'text'},
            {'label': self.get_news_content(), 'type': 'text'},
        ]

        self.create_settings_section(parent,
                                     _("Новости", "News"),
                                     news_config)

    #region HotKeys
    def keypress(self, e):
        # Получаем виджет, на котором произошло событие
        widget = e.widget

        # Обработчик комбинаций клавиш
        if e.keycode == 86 and e.state & 0x4:  # Ctrl+V
            self.cmd_paste(widget)
        elif e.keycode == 67 and e.state & 0x4:  # Ctrl+C
            self.cmd_copy(widget)
        elif e.keycode == 88 and e.state & 0x4:  # Ctrl+X
            self.cmd_cut(widget)

    def cmd_copy(self, widget):
        logger.info("123")
        # Обработчик команды копирования
        if isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
            widget.event_generate("<<Copy>>")

    def cmd_cut(self, widget):
        # Обработчик команды вырезания
        if isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
            widget.event_generate("<<Cut>>")

    def cmd_paste(self, widget):
        # Обработчик команды вставки
        if isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
            widget.event_generate("<<Paste>>")

    #endregion

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

        self.stop_screen_capture_thread()  # Останавливаем захват экрана при закрытии
        self.stop_camera_capture_thread() # Останавливаем захват с камеры при закрытии
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

    # region LocalVoice Functions
    async def run_local_voiceover(self, text):
        """Асинхронный метод для вызова локальной озвучки."""
        result_path = None  # Инициализируем переменную
        try:
            character = self.model.current_character if hasattr(self.model, "current_character") else None
            # Создаем уникальное имя файла
            output_file = f"MitaVoices/output_{uuid.uuid4()}.wav"
            absolute_audio_path = os.path.abspath(output_file)

            # Убедимся, что директория существует
            os.makedirs(os.path.dirname(absolute_audio_path), exist_ok=True)

            result_path = await self.local_voice.voiceover(
                text=text,
                output_file=absolute_audio_path,
                character=character
            )

            if result_path:
                logger.info(f"Локальная озвучка сохранена в: {result_path}")
                # Воспроизведение файла, если не подключены к игре И включена опция
                if not self.ConnectedToGame and self.settings.get("VOICEOVER_LOCAL_CHAT"):
                    await AudioHandler.handle_voice_file(result_path, self.settings.get("LOCAL_VOICE_DELETE_AUDIO",
                                                                                        True) if os.environ.get(
                        "ENABLE_VOICE_DELETE_CHECKBOX", "0") == "1" else True)
                elif self.ConnectedToGame:
                    self.patch_to_sound_file = result_path
                    logger.info(f"Путь к файлу для игры: {self.patch_to_sound_file}")
                else:
                    logger.info("Озвучка в локальном чате отключена.")
            else:
                logger.error("Локальная озвучка не удалась, файл не создан.")

        except Exception as e:
            logger.error(f"Ошибка при выполнении локальной озвучки: {e}")

    def on_local_voice_selected(self, event=None):
        """Обработчик выбора локальной модели озвучки"""
        if not hasattr(self, 'local_voice_combobox'):
            return

        selected_model_name = self.local_voice_combobox.get()
        if not selected_model_name:
            self.update_local_model_status_indicator()  # Обновляем на случай сброса
            return

        selected_model_id = None
        selected_model = None
        for model in LOCAL_VOICE_MODELS:
            if model["name"] == selected_model_name:
                selected_model = model
                selected_model_id = model["id"]
                break

        if not selected_model_id:
            messagebox.showerror(_("Ошибка", "Error"), _("Не удалось определить ID выбранной модели",
                                                         "Could not determine ID of selected model"))
            self.update_local_model_status_indicator()  # Обновляем статус
            return

        # Проверка перезапуска (без изменений)
        if selected_model_id in ["medium+", "medium+low"] and self.local_voice.first_compiled == False:
            to_open = messagebox.askyesno(
                _("Внимание", "Warning"),
                _("Невозможно перекомпилировать модель Fish Speech в Fish Speech+ - требуется перезапуск программы. \n\n Перезапустить?",
                  "Cannot recompile Fish Speech model to Fish Speech+ - program restart required. \n\n Restart?")
            )
            if not to_open:
                if self.last_voice_model_selected:
                    self.local_voice_combobox.set(self.last_voice_model_selected["name"])
                else:
                    self.local_voice_combobox.set('')
                    self.settings.set("NM_CURRENT_VOICEOVER", None)
                    self.settings.save_settings()
                self.update_local_model_status_indicator()  # Обновляем статус
                return
            else:
                import sys, subprocess
                python = sys.executable
                script = os.path.abspath(sys.argv[0])
                subprocess.Popen([python, script] + sys.argv[1:])
                self.root.destroy()
                return

        self.settings.set("NM_CURRENT_VOICEOVER", selected_model_id)
        self.settings.save_settings()
        self.current_local_voice_id = selected_model_id

        # Обновляем индикатор и решаем, нужна ли инициализация
        self.update_local_model_status_indicator()
        if not self.local_voice.is_model_initialized(selected_model_id):
            self.show_model_loading_window(selected_model)
        else:
            logger.info(f"Модель {selected_model_id} уже инициализирована.")
            self.last_voice_model_selected = selected_model
            self.local_voice.current_model = selected_model_id

    def show_model_loading_window(self, model):
        """Показывает окно загрузки модели с прогрессом"""
        model_id = model["id"]
        model_name = model["name"]

        downloader = ModelsDownloader(target_dir=".")
        logger.info(f"Проверка/загрузка файлов для '{model_name}'...")

        models_are_ready = downloader.download_models_if_needed(self.root)

        if not models_are_ready:
            logger.warning(f"Файлы моделей для '{model_name}' не готовы (загрузка не удалась или отменена).")
            messagebox.showerror(_("Ошибка", "Error"),
                                 _("Не удалось подготовить файлы моделей. Инициализация отменена.",
                                   "Failed to prepare model files. Initialization cancelled."),
                                 parent=self.root)
            return

        logger.info(f"Модели для '{model_name}' готовы. Запуск инициализации...")

        # Создаем новое окно
        loading_window = tk.Toplevel(self.root)
        loading_window.title(_("Загрузка модели", "Loading model") + f" {model_name}")
        loading_window.geometry("400x300")
        loading_window.configure(bg="#2c2c2c")
        loading_window.resizable(False, False)
        loading_window.transient(self.root)  # Делаем модальным относительно главного окна
        loading_window.grab_set()  # Захватываем фокус

        # Добавляем элементы интерфейса
        tk.Label(
            loading_window,
            text=_("Инициализация модели", "Initializing model") + f" {model_name}",
            font=("Arial", 12, "bold"),
            bg="#2c2c2c",
            fg="#ffffff"
        ).pack(pady=(20, 10))

        tk.Label(
            loading_window,
            text=_("Пожалуйста, подождите...", "Please wait..."),
            bg="#2c2c2c",
            fg="#ffffff"
        ).pack(pady=(0, 20))

        # Прогресс-бар (неопределенный)
        progress = ttk.Progressbar(
            loading_window,
            orient="horizontal",
            length=350,
            mode="indeterminate"
        )
        progress.pack(pady=10)
        progress.start(10)  # Запускаем анимацию прогресс-бара

        # Статус загрузки
        status_var = tk.StringVar(value=_("Инициализация...", "Initializing..."))
        status_label = tk.Label(
            loading_window,
            textvariable=status_var,
            bg="#2c2c2c",
            fg="#ffffff"
        )
        status_label.pack(pady=5)

        # Кнопка отмены
        cancel_button = tk.Button(
            loading_window,
            text=_("Отменить", "Cancel"),
            command=lambda: self.cancel_model_loading(loading_window),
            bg="#8a2be2",
            fg="#ffffff"
        )
        cancel_button.pack(pady=10)

        # Флаг отмены
        self.model_loading_cancelled = False

        # Запускаем инициализацию модели в отдельном потоке
        loading_thread = threading.Thread(
            target=self.init_model_thread,
            args=(model_id, loading_window, status_var, progress),  # Передаем progress
            daemon=True
        )
        loading_thread.start()

    def cancel_model_loading(self, loading_window):
        """Отменяет загрузку модели"""
        logger.info("Загрузка модели отменена пользователем.")
        self.model_loading_cancelled = True
        if loading_window.winfo_exists():
            loading_window.destroy()

        # Возвращаемся к предыдущей модели в комбобоксе, если она была
        restored_model_id = None
        if self.last_voice_model_selected:
            if hasattr(self, 'local_voice_combobox') and self.local_voice_combobox.winfo_exists():
                self.local_voice_combobox.set(self.last_voice_model_selected["name"])
            restored_model_id = self.last_voice_model_selected["id"]
            self.settings.set("NM_CURRENT_VOICEOVER", restored_model_id)
            self.current_local_voice_id = restored_model_id
        else:
            if hasattr(self, 'local_voice_combobox') and self.local_voice_combobox.winfo_exists():
                self.local_voice_combobox.set('')
            self.settings.set("NM_CURRENT_VOICEOVER", None)
            self.current_local_voice_id = None

        self.settings.save_settings()
        # Обновляем индикатор для восстановленной (или отсутствующей) модели
        self.update_local_model_status_indicator()

    def init_model_thread(self, model_id, loading_window, status_var, progress):
        """Поток инициализации модели"""
        try:
            # Обновляем статус (используем after для безопасности с Tkinter)
            self.root.after(0, lambda: status_var.set(_("Загрузка настроек...", "Loading settings...")))

            success = False
            # Защищаемся от отмены
            if not self.model_loading_cancelled:
                self.root.after(0, lambda: status_var.set(_("Инициализация модели...", "Initializing model...")))
                # Инициализируем модель
                success = self.local_voice.initialize_model(model_id, init=True)  # init=True для тестовой генерации

            # Проверяем окно перед обновлением UI
            if not loading_window.winfo_exists():
                logger.info("Окно загрузки было закрыто до завершения инициализации.")
                return

            # Если инициализация завершилась успешно и не была отменена
            if success and not self.model_loading_cancelled:
                self.root.after(0, lambda: self.finish_model_loading(model_id, loading_window))
            elif not self.model_loading_cancelled:
                # Если произошла ошибка во время инициализации
                error_message = _("Не удалось инициализировать модель. Проверьте логи.",
                                  "Failed to initialize model. Check logs.")
                self.root.after(0, lambda: [
                    status_var.set(_("Ошибка инициализации!", "Initialization Error!")),
                    progress.stop(),
                    messagebox.showerror(_("Ошибка инициализации", "Initialization Error"), error_message,
                                         parent=loading_window),
                    self.cancel_model_loading(loading_window)  # Используем cancel для сброса состояния
                ])
        except Exception as e:
            logger.error(f"Критическая ошибка в потоке инициализации модели {model_id}: {e}", exc_info=True)
            # Проверяем окно перед показом ошибки
            if loading_window.winfo_exists() and not self.model_loading_cancelled:
                error_message = _("Критическая ошибка при инициализации модели: ",
                                  "Critical error during model initialization: ") + str(e)
                self.root.after(0, lambda: [
                    status_var.set(_("Ошибка!", "Error!")),
                    progress.stop(),
                    messagebox.showerror(_("Ошибка", "Error"), error_message, parent=loading_window),
                    self.cancel_model_loading(loading_window)  # Используем cancel для сброса состояния
                ])

    def finish_model_loading(self, model_id, loading_window):
        """Завершает процесс загрузки модели"""
        logger.info(f"Модель {model_id} успешно инициализирована.")
        if loading_window.winfo_exists():
            loading_window.destroy()

        self.local_voice.current_model = model_id

        # Обновляем last_voice_model_selected ТОЛЬКО при успешной инициализации
        self.last_voice_model_selected = None
        for model in LOCAL_VOICE_MODELS:
            if model["id"] == model_id:
                self.last_voice_model_selected = model
                break

        # Сохраняем ID успешно загруженной модели как текущую
        self.settings.set("NM_CURRENT_VOICEOVER", model_id)
        self.settings.save_settings()
        self.current_local_voice_id = model_id  # Обновляем и внутреннюю переменную

        messagebox.showinfo(
            _("Успешно", "Success"),
            _("Модель {} успешно инициализирована!", "Model {} initialized successfully!").format(model_id),
            parent=self.root  # Указываем родителя для модальности
        )
        # Обновляем UI (комбобокс и индикатор)
        self.update_local_voice_combobox()

    def initialize_last_local_model_on_startup(self):
        """Проверяет настройку и инициализирует последнюю локальную модель при запуске."""
        if self.settings.get("LOCAL_VOICE_LOAD_LAST", False):
            logger.info("Проверка автозагрузки последней локальной модели...")
            last_model_id = self.settings.get("NM_CURRENT_VOICEOVER", None)

            if last_model_id:
                logger.info(f"Найдена последняя модель для автозагрузки: {last_model_id}")
                model_to_load = None
                for model in LOCAL_VOICE_MODELS:
                    if model["id"] == last_model_id:
                        model_to_load = model
                        break

                if model_to_load:
                    if self.local_voice.is_model_installed(last_model_id):
                        if not self.local_voice.is_model_initialized(last_model_id):
                            logger.info(
                                f"Модель {last_model_id} установлена, но не инициализирована. Запуск инициализации...")
                            # Используем существующее окно загрузки
                            self.show_model_loading_window(model_to_load)
                        else:
                            logger.info(f"Модель {last_model_id} уже инициализирована.")
                            # Убедимся, что last_voice_model_selected актуален
                            self.last_voice_model_selected = model_to_load
                            self.update_local_voice_combobox()  # Обновим UI на всякий случай
                    else:
                        logger.warning(f"Модель {last_model_id} выбрана для автозагрузки, но не установлена.")
                else:
                    logger.warning(f"Не найдена информация для модели с ID: {last_model_id}")
            else:
                logger.info("Нет сохраненной последней локальной модели для автозагрузки.")
        else:
            logger.info("Автозагрузка локальной модели отключена.")

    def update_local_model_status_indicator(self):
        if hasattr(self, 'local_model_status_label') and self.local_model_status_label.winfo_exists():
            show_combobox_indicator = False
            current_model_id_combo = self.settings.get("NM_CURRENT_VOICEOVER", None)

            if current_model_id_combo:
                model_installed_combo = self.local_voice.is_model_installed(current_model_id_combo)
                if model_installed_combo:
                    if not self.local_voice.is_model_initialized(current_model_id_combo):
                        show_combobox_indicator = True
                else:
                    show_combobox_indicator = True

            if show_combobox_indicator:
                if not self.local_model_status_label.winfo_manager():
                    self.local_model_status_label.pack(side=tk.LEFT, padx=(2, 5))
            else:
                if self.local_model_status_label.winfo_manager():
                    self.local_model_status_label.pack_forget()

        show_section_warning = False
        if (hasattr(self, 'voiceover_section_warning_label') and
                self.voiceover_section_warning_label.winfo_exists() and
                hasattr(self, 'voiceover_section') and
                self.voiceover_section.winfo_exists()):

            voiceover_method = self.settings.get("VOICEOVER_METHOD", "TG")
            current_model_id_section = self.settings.get("NM_CURRENT_VOICEOVER", None)

            if voiceover_method == "Local" and current_model_id_section:
                model_installed_section = self.local_voice.is_model_installed(current_model_id_section)
                if model_installed_section:
                    if not self.local_voice.is_model_initialized(current_model_id_section):
                        show_section_warning = True
                else:
                    show_section_warning = True

            # Используем правильные имена атрибутов
            title_widget = getattr(self.voiceover_section, 'title_label', None)
            header_widget = getattr(self.voiceover_section, 'header', None)  # Исправлено на 'header'

            if header_widget and header_widget.winfo_exists():
                if show_section_warning:
                    # Пакуем ПЕРЕД title_label, если он существует
                    if title_widget and title_widget.winfo_exists():
                        self.voiceover_section_warning_label.pack(
                            in_=header_widget,  # Указываем родителя
                            side=tk.LEFT,
                            before=title_widget,  # Помещаем перед текстом
                            padx=(0, 3)  # Отступ справа
                        )
                    else:
                        # Если title_label нет, пакуем после стрелки (arrow_label)
                        arrow_widget = getattr(self.voiceover_section, 'arrow_label', None)
                        if arrow_widget and arrow_widget.winfo_exists():
                            self.voiceover_section_warning_label.pack(
                                in_=header_widget,
                                side=tk.LEFT,
                                after=arrow_widget,  # Помещаем после стрелки
                                padx=(3, 3)  # Отступы с обеих сторон
                            )
                        else:
                            # Фоллбэк: просто пакуем слева
                            self.voiceover_section_warning_label.pack(
                                in_=header_widget,
                                side=tk.LEFT,
                                padx=(3, 3)
                            )
                else:
                    # Скрываем виджет, если он показан
                    if self.voiceover_section_warning_label.winfo_manager():
                        self.voiceover_section_warning_label.pack_forget()
            else:
                # Если header не найден, скрываем на всякий случай
                if self.voiceover_section_warning_label.winfo_manager():
                    self.voiceover_section_warning_label.pack_forget()

    def switch_voiceover_settings(self, selected_method=None):
        use_voice = self.settings.get("SILERO_USE", True)
        current_method = self.settings.get("VOICEOVER_METHOD", "TG")

        if not hasattr(self, 'voiceover_content_frame'):
            logger.error("Не найден родительский фрейм 'voiceover_content_frame' для настроек озвучки!")
            return

        # Сначала скрыть все специфичные фреймы (включая method_frame)
        if hasattr(self, 'method_frame') and self.method_frame.winfo_exists():
            if self.method_frame.winfo_manager():
                self.method_frame.pack_forget()
        if hasattr(self, 'tg_settings_frame') and self.tg_settings_frame.winfo_exists():
            if self.tg_settings_frame.winfo_manager():
                self.tg_settings_frame.pack_forget()
        if hasattr(self, 'local_settings_frame') and self.local_settings_frame.winfo_exists():
            if self.local_settings_frame.winfo_manager():
                self.local_settings_frame.pack_forget()

        # Если озвучка выключена, ничего больше не показываем
        if not use_voice:
            return

        # Показываем фрейм выбора метода озвучки
        if hasattr(self, 'method_frame'):
            self.method_frame.pack(fill=tk.X, padx=5, pady=0,
                                   in_=self.voiceover_content_frame)  # Пакуем в основной контент

        # Показываем фрейм для выбранного метода
        if current_method == "TG":
            if hasattr(self, 'tg_settings_frame'):
                self.tg_settings_frame.pack(fill=tk.X, padx=5, pady=0, in_=self.voiceover_content_frame)
        elif current_method == "Local":
            if hasattr(self, 'local_settings_frame'):
                self.local_settings_frame.pack(fill=tk.X, padx=5, pady=0, in_=self.voiceover_content_frame)
                self.update_local_voice_combobox()
                self.update_local_model_status_indicator()

        self.voiceover_method = current_method
        self.check_triton_dependencies()

    def update_tg_widgets_visibility(self):
        # if not hasattr(self, 'tg_widgets'):
        #     return

        # for key, data in self.tg_widgets.items():
        #     widget_frame = data['frame']
        #     config = data['config']
        #     show_widget = True

        #     if 'condition_key' in config:
        #         condition_value = self.settings.get(config['condition_key'])
        #         # Условие изменено: показываем API только если выбран @silero_voice_bot
        #         if 'condition_value' in config and condition_value != config['condition_value']:
        #              show_widget = False

        #     if widget_frame.winfo_exists():
        #         if show_widget:
        #             if not widget_frame.winfo_manager():
        #                 widget_frame.pack(fill=tk.X, pady=2)
        #         else:
        #             if widget_frame.winfo_manager():
        #                 widget_frame.pack_forget()
        pass

    def update_local_voice_combobox(self):
        """Обновляет комбобокс списком установленных локальных моделей и статус инициализации."""
        if not hasattr(self, 'local_voice_combobox') or not self.local_voice_combobox.winfo_exists():
            return

        installed_models_names = [model["name"] for model in LOCAL_VOICE_MODELS if
                                  self.local_voice.is_model_installed(model["id"])]
        current_values = list(self.local_voice_combobox['values'])

        if installed_models_names != current_values:
            self.local_voice_combobox['values'] = installed_models_names
            logger.info(f"Обновлен список локальных моделей: {installed_models_names}")

        current_model_id = self.settings.get("NM_CURRENT_VOICEOVER", None)
        current_model_name = ""
        if current_model_id:
            for model in LOCAL_VOICE_MODELS:
                if model["id"] == current_model_id:
                    current_model_name = model["name"]
                    break

        # Установка значения в комбобокс (логика без изменений)
        if current_model_name and current_model_name in installed_models_names:
            if self.local_voice_combobox.get() != current_model_name:
                self.local_voice_combobox.set(current_model_name)
        elif installed_models_names:
            if self.local_voice_combobox.get() != installed_models_names[0]:
                self.local_voice_combobox.set(installed_models_names[0])
                for model in LOCAL_VOICE_MODELS:
                    if model["name"] == installed_models_names[0]:
                        if self.settings.get("NM_CURRENT_VOICEOVER") != model["id"]:
                            self.settings.set("NM_CURRENT_VOICEOVER", model["id"])
                            self.settings.save_settings()
                            self.current_local_voice_id = model["id"]
                        break
        else:
            if self.local_voice_combobox.get() != '':
                self.local_voice_combobox.set('')
            if self.settings.get("NM_CURRENT_VOICEOVER") is not None:
                self.settings.set("NM_CURRENT_VOICEOVER", None)
                self.settings.save_settings()
                self.current_local_voice_id = None

        # Обновляем индикатор статуса после обновления комбобокса
        self.update_local_model_status_indicator()
        self.check_triton_dependencies()

    def check_triton_dependencies(self):
        """Проверяет зависимости Triton и отображает предупреждение, если нужно."""
        # Удаляем старое предупреждение, если оно есть
        if hasattr(self, 'triton_warning_label') and self.triton_warning_label.winfo_exists():
            self.triton_warning_label.destroy()
            delattr(self, 'triton_warning_label')

        # Проверяем только если выбрана локальная озвучка и фрейм существует
        if self.settings.get("VOICEOVER_METHOD") != "Local":
            return
        if not hasattr(self, 'local_settings_frame') or not self.local_settings_frame.winfo_exists():
            return

        triton_found = False
        try:
            # Пробуем просто импортировать triton
            import triton
            triton_found = True
            logger.debug("Зависимости Triton найдены (через import triton).")

        except ImportError as e:
            logger.warning(
                f"Зависимости Triton не найдены! Игнорируйте это предупреждение, если не используете \"Fish Speech+ / + RVC\" озвучку. Exception импорта: {e}")
        except Exception as e:  # Ловим другие возможные ошибки при импорте
            logger.error(
                f"Неожиданная ошибка при проверке Triton. Игнорируйте это предупреждение, если не используете \"Fish Speech+ / + RVC\" озвучку. Exception: {e}",
                exc_info=True)

        # if not triton_found:
        #     # Добавляем предупреждение в интерфейс локальных настроек
        #     self.triton_warning_label = tk.Label(
        #         self.local_settings_frame, # Добавляем в фрейм локальных настроек
        #         text=_("⚠️ Triton не найден! Модели medium+ и medium+low могут не работать.",
        #                "⚠️ Triton not found! Models medium+ and medium+low might not work."),
        #         bg="#400000", # Темно-красный фон
        #         fg="#ffffff",
        #         font=("Arial", 9, "bold"),
        #         wraplength=350 # Перенос текста
        #     )
        #     # Вставляем перед комбобоксом
        #     if hasattr(self, 'local_voice_combobox') and self.local_voice_combobox.winfo_exists():
        #          # Ищем фрейм, содержащий комбобокс
        #          combobox_parent = self.local_voice_combobox.master
        #          self.triton_warning_label.pack(in_=self.local_settings_frame, before=combobox_parent, pady=3, fill=tk.X)
        #     else: # Если комбобокса нет, просто пакуем в конец фрейма
        #          self.triton_warning_label.pack(in_=self.local_settings_frame, pady=3, fill=tk.X)

    def open_local_model_installation_window(self):
        """Открывает новое окно для управления установкой локальных моделей."""
        try:
            # Динамический импорт, чтобы избежать ошибки, если файла нет
            from voice_model_settings import VoiceModelSettingsWindow
            import os

            config_dir = "Settings"
            os.makedirs(config_dir, exist_ok=True)

            def on_save_callback(settings_data):
                """Обработчик события сохранения настроек из окна установки."""
                installed_models_ids = settings_data.get("installed_models", [])
                logger.info(f"Сохранены установленные модели (из окна установки): {installed_models_ids}")

                # Обновляем статус моделей в LocalVoice (перезагрузка модулей)
                self.refresh_local_voice_modules()

                # Обновляем UI главного окна
                self.update_local_voice_combobox()

                # Проверяем, осталась ли текущая выбранная модель установленной
                current_model_id = self.settings.get("NM_CURRENT_VOICEOVER", None)
                if current_model_id and current_model_id not in installed_models_ids:
                    logger.warning(f"Текущая модель {current_model_id} была удалена. Сбрасываем выбор.")
                    # Если есть другие установленные, выбираем первую, иначе сбрасываем
                    new_model_id = installed_models_ids[0] if installed_models_ids else None
                    self.settings.set("NM_CURRENT_VOICEOVER", new_model_id)
                    self.settings.save_settings()
                    self.current_local_voice_id = new_model_id
                    self.update_local_voice_combobox()  # Обновляем комбобокс еще раз

            # Создаем дочернее окно Toplevel БЕЗ grab_set и transient
            install_window = tk.Toplevel(self.root)
            # install_window.transient(self.root) # --- УБРАНО ---
            # install_window.grab_set() # --- УБРАНО ---
            install_window.title(_("Управление локальными моделями", "Manage Local Models"))  # Добавим заголовок

            # Инициализируем окно настроек моделей
            VoiceModelSettingsWindow(
                master=install_window,  # Передаем дочернее окно как родителя
                config_dir=config_dir,
                on_save_callback=on_save_callback,
                local_voice=self.local_voice,
                check_installed_func=self.check_module_installed,
            )
        except ImportError:
            logger.error("Не найден модуль voice_model_settings.py. Установка моделей недоступна.")
            messagebox.showerror(_("Ошибка", "Error"),
                                 _("Не найден файл voice_model_settings.py", "voice_model_settings.py not found."))
        except Exception as e:
            logger.error(f"Ошибка при открытии окна установки моделей: {e}", exc_info=True)
            messagebox.showerror(_("Ошибка", "Error"), _("Не удалось открыть окно установки моделей.",
                                                         "Failed to open model installation window."))

    def refresh_local_voice_modules(self):
        """Обновляет импорты модулей в LocalVoice без перезапуска программы."""
        import importlib
        import sys
        logger.info("Попытка обновления модулей локальной озвучки...")

        # Список модулей для перезагрузки/импорта
        modules_to_check = {
            "tts_with_rvc": "TTS_RVC",
            "fish_speech_lib.inference": "FishSpeech",
            "triton": None  # Просто проверяем наличие
        }
        # Пути, где могут лежать модули (добавляем Lib)
        lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Lib")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)  # Добавляем в начало, чтобы иметь приоритет

        for module_name, class_name in modules_to_check.items():
            try:
                if module_name in sys.modules:
                    logger.debug(f"Перезагрузка модуля: {module_name}")
                    importlib.reload(sys.modules[module_name])
                else:
                    logger.debug(f"Импорт модуля: {module_name}")
                    imported_module = importlib.import_module(module_name)

                # Обновляем ссылку в LocalVoice, если нужно
                if class_name:
                    actual_class = getattr(sys.modules[module_name], class_name)
                    if module_name == "tts_with_rvc":
                        self.local_voice.tts_rvc_module = actual_class
                    elif module_name == "fish_speech_lib.inference":
                        self.local_voice.fish_speech_module = actual_class

                logger.info(f"Модуль {module_name} успешно обработан.")
            except ImportError:
                logger.warning(f"Модуль {module_name} не найден или не установлен.")
                # Сбрасываем ссылку в LocalVoice, если модуль не найден
                if module_name == "tts_with_rvc":
                    self.local_voice.tts_rvc_module = None
                elif module_name == "fish_speech_lib.inference":
                    self.local_voice.fish_speech_module = None
            except Exception as e:
                logger.error(f"Ошибка при обработке модуля {module_name}: {e}", exc_info=True)

        # Обновляем проверку зависимостей Triton в UI
        self.check_triton_dependencies()

    def check_module_installed(self, module_name):
        """Проверяет, установлен ли модуль, фокусируясь на результате find_spec."""
        logger.info(f"Проверка установки модуля: {module_name}")
        spec = None
        try:
            spec = importlib.util.find_spec(module_name)

            if spec is None:
                logger.info(f"Модуль {module_name} НЕ найден через find_spec.")
                return False
            else:
                # Спецификация найдена, проверяем загрузчик
                if spec.loader is not None:
                    # Дополнительная проверка: попробуем получить __spec__ явно
                    try:
                        # Пытаемся импортировать модуль, чтобы проверить __spec__
                        # Это может быть медленно, но надежнее
                        module = importlib.import_module(module_name)
                        if hasattr(module, '__spec__') and module.__spec__ is not None:
                            logger.info(f"Модуль {module_name} найден (find_spec + loader + import).")
                            return True
                        else:
                            logger.warning(
                                f"Модуль {module_name} импортирован, но __spec__ is None или отсутствует. Считаем не установленным корректно.")
                            # Очищаем из sys.modules, если импорт был частичным
                            if module_name in sys.modules:
                                try:
                                    del sys.modules[module_name]
                                except KeyError:
                                    pass
                            return False
                    except ImportError as ie:
                        logger.warning(
                            f"Модуль {module_name} найден find_spec, но не импортируется: {ie}. Считаем не установленным.")
                        return False
                    except ValueError as ve:  # Ловим ValueError при импорте
                        logger.warning(
                            f"Модуль {module_name} найден find_spec, но ошибка ValueError при импорте: {ve}. Считаем не установленным.")
                        return False
                    except Exception as e_import:  # Ловим другие ошибки импорта
                        logger.error(f"Неожиданная ошибка при импорте {module_name} после find_spec: {e_import}")
                        return False
                else:
                    # Спецификация есть, но нет загрузчика
                    logger.warning(
                        f"Модуль {module_name} найден через find_spec, но loader is None. Считаем не установленным корректно.")
                    return False

        except ValueError as e:
            # Ловим ValueError именно от find_spec (хотя теперь это менее вероятно)
            logger.warning(
                f"Ошибка ValueError при find_spec для {module_name}: {e}. Считаем не установленным корректно.")
            return False
        except Exception as e:
            # Другие возможные ошибки при find_spec
            logger.error(f"Неожиданная ошибка при вызове find_spec для {module_name}: {e}")
            return False

    def check_available_vram(self):
        """Проверка доступной видеопамяти (заглушка)."""
        logger.warning("Проверка VRAM не реализована, возвращается фиктивное значение.")
        try:
            # Попытка получить информацию через nvidia-smi
            # import subprocess
            # result = subprocess.run(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True)
            # free_vram_mb = int(result.stdout.strip().split('\n')[0])
            # return free_vram_mb / 1024 
            return 100  # Возвращаем заглушку 100 GB
        except Exception as e:
            logger.error(f"Ошибка при попытке проверки VRAM: {e}")
            return 4  # Возвращаем минимальное значение в случае ошибки

    # endregion

    # region ffmpeg installations tools
    def _show_ffmpeg_installing_popup(self):
        """Показывает неблокирующее окно 'Установка FFmpeg...'."""
        if self.ffmpeg_install_popup and self.ffmpeg_install_popup.winfo_exists():
            return  # Окно уже открыто

        self.ffmpeg_install_popup = tk.Toplevel(self.root)
        self.ffmpeg_install_popup.title("FFmpeg")
        self.ffmpeg_install_popup.config(bg="#1e1e1e", padx=20, pady=15)
        self.ffmpeg_install_popup.resizable(False, False)
        # Убираем кнопки свернуть/развернуть (может не работать на всех ОС)
        self.ffmpeg_install_popup.attributes('-toolwindow', True)

        label = tk.Label(
            self.ffmpeg_install_popup,
            text="Идет установка FFmpeg...\nПожалуйста, подождите.",
            bg="#1e1e1e", fg="#ffffff", font=("Arial", 12)
        )
        label.pack()

        # Центрируем окно относительно главного
        self.ffmpeg_install_popup.update_idletasks()  # Обновляем размеры окна
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (self.ffmpeg_install_popup.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (self.ffmpeg_install_popup.winfo_height() // 2)
        self.ffmpeg_install_popup.geometry(f"+{x}+{y}")

        self.ffmpeg_install_popup.transient(self.root)  # Делаем зависимым от главного
        # self.ffmpeg_install_popup.grab_set() # НЕ делаем модальным

    def _close_ffmpeg_installing_popup(self):
        """Закрывает окно 'Установка FFmpeg...'."""
        if self.ffmpeg_install_popup and self.ffmpeg_install_popup.winfo_exists():
            self.ffmpeg_install_popup.destroy()
            self.ffmpeg_install_popup = None

    def _show_ffmpeg_error_popup(self):
        """Показывает МОДАЛЬНОЕ окно ошибки установки FFmpeg."""
        error_popup = tk.Toplevel(self.root)
        error_popup.title("Ошибка установки FFmpeg")
        error_popup.config(bg="#1e1e1e", padx=20, pady=15)
        error_popup.resizable(False, False)
        error_popup.attributes('-toolwindow', True)

        message = (
            "Не удалось автоматически установить FFmpeg.\n\n"
            "Он необходим для некоторых функций программы (например, обработки аудио).\n\n"
            "Пожалуйста, скачайте FFmpeg вручную с официального сайта:\n"
            f"{"https://ffmpeg.org/download.html"}\n\n"
            f"Распакуйте архив и поместите файл 'ffmpeg.exe' в папку программы:\n"
            f"{Path(".").resolve()}"
        )

        label = tk.Label(
            error_popup,
            text=message,
            bg="#1e1e1e", fg="#ffffff", font=("Arial", 11),
            justify=tk.LEFT  # Выравнивание текста по левому краю
        )
        label.pack(pady=(0, 10))

        ok_button = tk.Button(
            error_popup, text="OK", command=error_popup.destroy,
            bg="#9370db", fg="#ffffff", font=("Arial", 10), width=10
        )
        ok_button.pack()

        # Центрируем и делаем модальным
        error_popup.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (error_popup.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (error_popup.winfo_height() // 2)
        error_popup.geometry(f"+{x}+{y}")

        error_popup.transient(self.root)  # Зависимость от главного окна
        error_popup.grab_set()  # Перехват событий (делает модальным)
        self.root.wait_window(error_popup)  # Ожидание закрытия этого окна

    # --- ЛОГИКА ПРОВЕРКИ И УСТАНОВКИ В ОТДЕЛЬНОМ ПОТОКЕ ---

    def _ffmpeg_install_thread_target(self):
        """Функция, выполняемая в отдельном потоке для установки FFmpeg."""
        # Показываем окно "Установка..." (через mainloop)
        self.root.after(0, self._show_ffmpeg_installing_popup)

        logger.info("Starting FFmpeg installation attempt...")
        success = install_ffmpeg()
        logger.info(f"FFmpeg installation attempt finished. Success: {success}")

        # Закрываем окно "Установка..." (через mainloop)
        self.root.after(0, self._close_ffmpeg_installing_popup)

        # Если неудача, показываем окно ошибки (через mainloop)
        if not success:
            self.root.after(0, self._show_ffmpeg_error_popup)

    def check_and_install_ffmpeg(self):
        """Проверяет наличие ffmpeg.exe и запускает установку в потоке, если его нет."""
        ffmpeg_path = Path(".") / "ffmpeg.exe"
        logger.info(f"Checking for FFmpeg at: {ffmpeg_path}")

        if not ffmpeg_path.exists():
            logger.info("FFmpeg not found. Starting installation process in a separate thread.")
            # Запускаем установку в отдельном потоке, чтобы не блокировать UI
            install_thread = threading.Thread(target=self._ffmpeg_install_thread_target, daemon=True)
            # daemon=True позволяет программе завершиться, даже если этот поток еще работает
            install_thread.start()
        else:
            logger.info("FFmpeg found. No installation needed.")

    def on_voice_language_selected(self, event=None):
        """Обработчик выбора языка озвучки."""
        if not hasattr(self, 'voice_language_var'):
            logger.warning("Переменная voice_language_var не найдена.")
            return

        selected_language = self.voice_language_var.get()
        logger.info(f"Выбран язык озвучки: {selected_language}")

        self._save_setting("VOICE_LANGUAGE", selected_language)

        if hasattr(self.local_voice, 'change_voice_language'):
            try:
                self.local_voice.change_voice_language(selected_language)
                logger.info(f"Язык в LocalVoice успешно изменен на {selected_language}.")
                self.update_local_model_status_indicator()
            except Exception as e:
                logger.error(f"Ошибка при вызове local_voice.change_voice_language: {e}")
        else:
            logger.warning("Метод 'change_voice_language' отсутствует в объекте local_voice.")

    # endregion

