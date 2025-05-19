import uuid
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
from utils.ffmpeg_installer import install_ffmpeg
from utils.ModelsDownloader import ModelsDownloader

import asyncio
import threading

import binascii

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

from utils import SH
import sys

import sounddevice as sd
from SpeechRecognition import SpeechRecognition

import requests
import importlib

from LocalVoice import LocalVoice
import time

from utils.PipInstaller import PipInstaller 


#gettext.bindtextdomain('NeuroMita', '/Translation')
#gettext.textdomain('NeuroMita')
#_ = gettext.gettext
#_ = str  # Временно пока чтобы не падало


def getTranslationVariant(ru_str, en_str=""):
    if en_str and SettingsManager.get("LANGUAGE") == "EN":
        return en_str

    return ru_str


_ = getTranslationVariant  # Временно, мб


LOCAL_VOICE_MODELS = [
    {
        "id": "low",
        "name": "Edge-TTS + RVC",
        "min_vram": 3,
        "rec_vram": 4,
        "gpu_vendor": ["NVIDIA", "AMD"],
        "size_gb": 3
    },
    {
        "id": "low+",
        "name": "Silero + RVC",
        "min_vram": 3,
        "rec_vram": 4,
        "gpu_vendor": ["NVIDIA", "AMD"],
        "size_gb": 3
    },
    {
        "id": "medium",
        "name": "Fish Speech",
        "min_vram": 4,
        "rec_vram": 6,
        "gpu_vendor":  ["NVIDIA"],
        "size_gb": 5
    },
    {
        "id": "medium+",
        "name": "Fish Speech+",
        "min_vram": 4,
        "rec_vram": 6,
        "gpu_vendor":  ["NVIDIA"],
        "size_gb": 10
    },
    {
        "id": "medium+low",
        "name": "Fish Speech+ + RVC",
        "min_vram": 6,
        "rec_vram": 8,
        "gpu_vendor": ["NVIDIA"],
        "size_gb": 15
    }
]

class ChatGUI:
    def __init__(self):

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
            self.pip_installer = None # Устанавливаем в None, чтобы ChatModel мог это проверить

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


        self.model = ChatModel(self, self.api_key, self.api_key_res, self.api_url, self.api_model, self.makeRequest, self.pip_installer)
        self.server = ChatServer(self, self.model)
        self.server_thread = None
        self.running = False
        self.start_server()

        self.textToTalk = ""
        self.textSpeaker = "/Speaker Mita"
        self.textSpeakerMiku ="/set_person CrazyMita"

        self.silero_turn_off_video = False

        self.dialog_active = False

        self.patch_to_sound_file = ""
        self.id_sound = -1
        self.instant_send = False
        self.waiting_answer = False

        self.root = tk.Tk()
        self.root.wm_iconphoto(False, tk.PhotoImage(file = 'icon.png'))
        
        self.root.title(_("Чат с NeuroMita","NeuroMita Chat"))

        self.ffmpeg_install_popup = None 
        self.root.after(100, self.check_and_install_ffmpeg) 

        self.delete_all_sound_files()
        self.setup_ui()

        self.root.bind_class("Entry", "<Control-KeyPress>", lambda e: self.keypress(e))
        self.root.bind_class("Text", "<Control-KeyPress>", lambda e: self.keypress(e))

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

        self.root.after(500, self.initialize_last_local_model_on_startup)

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
            self.loop.create_task(self.run_send_and_receive(self.textToTalk, self.getSpeakerText()))
        else:
            logger.info("Ошибка: Цикл событий asyncio не готов.")

    def getSpeakerText(self):
        if self.settings.get("AUDIO_BOT") == "@CrazyMitaAIbot":
            return self.textSpeakerMiku
        else:
            return self.textSpeaker

    async def run_send_and_receive(self, response, speaker_command, id = 0):
        """Асинхронный метод для вызова send_and_receive."""
        logger.info("Попытка получить фразу")
        self.waiting_answer = True

        await self.bot_handler.send_and_receive(response, speaker_command, id)

        self.waiting_answer = False
        logger.info("Завершение получения фразы")

    # region Modified by Atm4x
    def check_text_to_talk_or_send(self):
        """Периодическая проверка переменной self.textToTalk."""

        # Проверяем, включена ли озвучка глобально
        # if not self.settings.get("SILERO_USE", True):
        #     if self.textToTalk:
        #         logger.debug("Озвучка выключена в настройках, очищаем текст.")
        #         self.textToTalk = "" # Очищаем, чтобы не пытаться отправить
        #     # Перезапуск проверки
        #     self.root.after(100, self.check_text_to_talk_or_send)
        #     return # Выходим, если озвучка выключена

        # Если озвучка включена и есть текст
        if bool(self.settings.get("SILERO_USE")) and self.textToTalk:
            logger.info(f"Есть текст для отправки: {self.textToTalk} id {self.id_sound}")
            if self.loop and self.loop.is_running():
                try:
                    # Получаем основной метод озвучки из настроек
                    self.voiceover_method = self.settings.get("VOICEOVER_METHOD", "TG")

                    if self.voiceover_method == "TG":
                        logger.info("Используем Telegram (Silero/Miku) для озвучки")
                        # Используем существующую логику для TG/MikuTTS
                        asyncio.run_coroutine_threadsafe(
                            self.run_send_and_receive(self.textToTalk, self.getSpeakerText(), self.id_sound),
                            self.loop
                        )
                        self.textToTalk = "" # Очищаем текст после отправки

                    elif self.voiceover_method == "Local":
                        # Получаем ID выбранной локальной модели из настроек
                        selected_local_model_id = self.settings.get("NM_CURRENT_VOICEOVER", None)
                        if selected_local_model_id: # Убедимся, что ID локальной модели выбран
                            logger.info(f"Используем {selected_local_model_id} для локальной озвучки")
                            # Проверяем, инициализирована ли модель
                            if self.local_voice.is_model_initialized(selected_local_model_id):
                                asyncio.run_coroutine_threadsafe(
                                    self.run_local_voiceover(self.textToTalk),
                                    self.loop
                                )
                                self.textToTalk = "" # Очищаем текст после отправки
                            else:
                                logger.warning(f"Модель {selected_local_model_id} выбрана, но не инициализирована. Озвучка не будет выполнена.")
                                self.textToTalk = "" # Очищаем, чтобы не зациклиться
                        else:
                            logger.warning("Локальная озвучка выбрана, но конкретная модель не установлена/не выбрана.")
                            self.textToTalk = "" # Очищаем, чтобы не зациклиться
                    else:
                         logger.warning(f"Неизвестный метод озвучки: {self.voiceover_method}")
                         self.textToTalk = "" # Очищаем, чтобы не зациклиться

                    logger.info("Выполнено")
                except Exception as e:
                    logger.error(f"Ошибка при отправке текста на озвучку: {e}")
                    self.textToTalk = "" # Очищаем текст в случае ошибки
            else:
                logger.error("Ошибка: Цикл событий не готов.")

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

    #endregion

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
        self.root.config(bg="#1e1e1e")  # Установите темный цвет фона для всего окна
        self.root.geometry("1200x800")

        main_frame = tk.Frame(self.root, bg="#1e1e1e")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Первый столбец
        left_frame = tk.Frame(main_frame, bg="#1e1e1e")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Настройка grid для left_frame
        left_frame.grid_rowconfigure(0, weight=1)  # Чат получает всё свободное место
        left_frame.grid_rowconfigure(1, weight=0)  # Инпут остаётся фиксированным
        left_frame.grid_columnconfigure(0, weight=1)

        # Чат - верхняя часть (растягивается)
        self.chat_window = tk.Text(
            left_frame, height=30, width=40, state=tk.NORMAL,
            bg="#151515", fg="#ffffff", insertbackground="white", wrap=tk.WORD,
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
            input_frame, height=3, width=50, bg="#151515", fg="#ffffff",
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
            #Это проверка на достигнутый конец прокрутки
            current_pos = right_canvas.yview()
            if (delta < 0 and current_pos[0] <= 0) or (delta > 0 and current_pos[1] >= 1):
                return
            
            right_canvas.yview_scroll(delta, "units")

        # Привязываем события прокрутки для разных платформ
        right_canvas.bind_all("<MouseWheel>", _on_mousewheel)  # Windows и macOS
        right_canvas.bind_all("<Button-4>", _on_mousewheel)  # Linux (прокрутка вверх)
        right_canvas.bind_all("<Button-5>", _on_mousewheel)  # Linux (прокрутка вниз)

        self.setup_status_indicators(settings_frame)
        self.setup_language_controls(settings_frame)
        self.setup_api_controls_new(settings_frame)

        #self.setup_model_controls(settings_frame)
        self.setup_g4f_controls(settings_frame)

        self.setup_general_settings_control(settings_frame)
        self.setup_voiceover_controls(settings_frame) # Бывший setup_tg_controls()
        self.setup_microphone_controls(settings_frame)

        self.setup_mita_controls(settings_frame)

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

        if os.environ.get("ENABLE_COMMAND_REPLACER_BY_DEFAULT", "0") == "1":
            self.setup_command_replacer_controls(settings_frame)

        self.setup_news_control(settings_frame)
        

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
                 success = False # Явно указываем на неудачу

            finally:
                # --- ВАЖНО: Сбрасываем флаги независимо от успеха ---
                logger.info("Сброс флагов запланированного обновления g4f.")
                self.settings.set("G4F_UPDATE_PENDING", False)
                self.settings.set("G4F_TARGET_VERSION", None) # Или ""
                self.settings.save_settings()
        else:
            logger.info("Нет запланированных обновлений g4f.")

    def setup_g4f_controls(self, parent):
        """Создает секцию настроек для управления версией g4f."""
        section = CollapsibleSection(parent, _("Настройки g4f", "g4f Settings"))
        section.pack(fill=tk.X, padx=5, pady=5, expand=True)


        use_g4f = self.create_setting_widget(
            parent=section.content_frame,
            label=_('Использовать gpt4free', 'Use gpt4free'),
            setting_key='gpt4free', # Этот ключ теперь просто хранит последнюю введенную/установленную версию
            widget_type='checkbutton',
            default_checkbutton=False,
            #tooltip=_('Укажите версию g4f (например, 0.4.7.7 или latest). Обновление произойдет при следующем запуске.',
            #          'Specify the g4f version (e.g., 0.4.7.7 or latest). The update will occur on the next launch.')
        )
        section.add_widget(use_g4f)

        model_g4f = self.create_setting_widget(
            parent=section.content_frame,
            label=_('Модель gpt4free', 'model gpt4free'),
            setting_key='gpt4free_model', # Этот ключ теперь просто хранит последнюю введенную/установленную версию
            widget_type='entry',
            default="gemini-1.5-flash",
        )
        section.add_widget(model_g4f)
       # {'label': , 'key': 'gpt4free', 'type': 'checkbutton',
       #      'default_checkbutton': False},
      #      {'label': _('gpt4free | Модель gpt4free', 'gpt4free | model gpt4free'), 'key': 'gpt4free_model',
      #       'type': 'entry', 'default': "gemini-1.5-flash"},


        version_frame = self.create_setting_widget(
            parent=section.content_frame,
            label=_('Версия gpt4free', 'gpt4free Version'),
            setting_key='G4F_VERSION', # Этот ключ теперь просто хранит последнюю введенную/установленную версию
            widget_type='entry',
            default='0.4.7.7',
            tooltip=_('Укажите версию g4f (например, 0.4.7.7 или latest). Обновление произойдет при следующем запуске.',
                      'Specify the g4f version (e.g., 0.4.7.7 or latest). The update will occur on the next launch.')
        )
        self.g4f_version_entry = None
        for widget in version_frame.winfo_children():
            if isinstance(widget, tk.Entry):
                self.g4f_version_entry = widget
                break
        if not self.g4f_version_entry:
             logger.error("Не удалось найти виджет Entry для версии g4f!")
        section.add_widget(version_frame)

        # Кнопка теперь вызывает trigger_g4f_reinstall_schedule
        button_frame = self.create_setting_widget(
            parent=section.content_frame,
            label=_('Запланировать обновление g4f', 'Schedule g4f Update'), # Текст кнопки изменен
            setting_key='',
            widget_type='button',
            command=self.trigger_g4f_reinstall_schedule # Привязываем к новой функции
        )
        section.add_widget(button_frame)

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
                                     _("Пожалуйста, введите версию g4f или 'latest'.", "Please enter a g4f version or 'latest'."),
                                     parent=self.root)
                return
        else:
            logger.error("Виджет entry для версии g4f не найден.")
            messagebox.showerror(_("Ошибка", "Error"),
                                 _("Не найден элемент интерфейса для ввода версии.", "UI element for version input not found."),
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
                  "g4f version '{version}' will be installed/updated the next time the program starts.").format(version=target_version),
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

    def setup_status_indicators(self, parent):
        # Создаем фрейм для индикаторов
        status_frame = tk.Frame(parent, bg="#2c2c2c")
        status_frame.pack(fill=tk.X, pady=3)

        # Переменные статуса
        self.game_connected_checkbox_var = tk.BooleanVar(value=False)  # Статус подключения к игре
        self.silero_connected = tk.BooleanVar(value=False)  # Статус подключения к Silero

        # Галки для подключения
        self.game_status_checkbox = tk.Checkbutton(
            status_frame,
            text=_("Подключение к игре", "Connection to game"),
            variable=self.game_connected_checkbox_var,
            state="disabled",
            bg="#2c2c2c",
            fg="#ffffff",
            selectcolor="#2c2c2c"
        )
        self.game_status_checkbox.pack(side=tk.LEFT, padx=5, pady=4)

        self.silero_status_checkbox = tk.Checkbutton(
            status_frame,
            text=_("Подключение Telegram", "Connection Telegram"),
            variable=self.silero_connected,
            state="disabled",
            bg="#2c2c2c",
            fg="#ffffff",
            selectcolor="#2c2c2c"
        )
        self.silero_status_checkbox.pack(side=tk.LEFT, padx=5, pady=4)

    def update_game_connection(self,is_connected):
        self.ConnectedToGame = is_connected
        self.game_connected_checkbox_var = tk.BooleanVar(value=is_connected)  # Статус подключения к игре


    def updateAll(self):
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
            history_frame, text=_("Очистить историю персонажа", "Clear character history"), command=self.clear_history,
            bg="#8a2be2", fg="#ffffff"
        )
        clear_button.pack(side=tk.LEFT, padx=5)

        clear_button = tk.Button(
            history_frame, text=_("Очистить все истории", "Clear all histories"), command=self.clear_history_all,
            bg="#8a2be2", fg="#ffffff"
        )
        clear_button.pack(side=tk.LEFT, padx=5)

        reload_prompts_button = tk.Button(
            history_frame, text=_("Перекачать промпты", "ReDownload prompts"), command=self.reload_prompts,
            bg="#8a2be2", fg="#ffffff"
        )
        reload_prompts_button.pack(side=tk.LEFT, padx=5)

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

    #region MODIFIED BUT NOT CHECKED BY Atm4x
    # Бывший setup_tg_controls()
    def setup_voiceover_controls(self, parent):
        voice_section = CollapsibleSection(parent, _("Настройка озвучки", "Voiceover Settings"))
        voice_section.pack(fill=tk.X, padx=5, pady=5, expand=True)
        self.voiceover_section = voice_section
        self.voiceover_content_frame = voice_section.content_frame

        try:
            header_bg = voice_section.header.cget("background") # ttk виджеты используют 'background'
        except Exception as e:
            logger.warning(f"Не удалось получить фон заголовка секции: {e}. Используется фоллбэк.")
            header_bg = "#333333" # Фоллбэк из стиля Header.TFrame

        self.voiceover_section_warning_label = ttk.Label( # Используем ttk.Label для консистентности
            voice_section.header,
            text="⚠️",
            background=header_bg, # Используем background
            foreground="orange", # Используем foreground
            font=("Arial", 10, "bold")
            # style="Header.TLabel" # Можно добавить стиль, если нужно
        )

        use_voice_frame = tk.Frame(self.voiceover_content_frame, bg="#2c2c2c")
        use_voice_frame.pack(fill=tk.X, pady=2)
        self.create_setting_widget(
            parent=use_voice_frame,
            label=_('Использовать озвучку', 'Use speech'),
            setting_key='SILERO_USE',
            widget_type='checkbutton',
            default_checkbutton=False,
            command=lambda v: self.switch_voiceover_settings()
        )

        method_frame = tk.Frame(self.voiceover_content_frame, bg="#2c2c2c")
        tk.Label(method_frame, text=_("Вариант озвучки:", "Voiceover Method:"), bg="#2c2c2c", fg="#ffffff", width=25, anchor='w').pack(side=tk.LEFT, padx=5)
        self.voiceover_method_var = tk.StringVar(value=self.settings.get("VOICEOVER_METHOD", "TG"))
        method_options = ["TG", "Local"] if os.environ.get("EXPERIMENTAL_FUNCTIONS", "0") == "1" else ["TG"] # Вернем локальную озвучку всем # Atm4x says: верну, ибо это вполне мог сделать гемини... хотя уже без разницы
        method_combobox = ttk.Combobox(
            method_frame,
            textvariable=self.voiceover_method_var,
            values=method_options,
            state="readonly",
            width=28
        )
        method_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        method_combobox.bind("<<ComboboxSelected>>",
                             lambda e: [self._save_setting("VOICEOVER_METHOD", self.voiceover_method_var.get()),
                                        self.switch_voiceover_settings()])
        self.method_frame = method_frame

        # === Настройки Telegram ===
        self.tg_settings_frame = tk.Frame(self.voiceover_content_frame, bg="#2c2c2c")
        tg_config = [
                {'label': _('Канал/Сервис', "Channel/Service"), 'key': 'AUDIO_BOT', 'type': 'combobox',
                 'options': ["@silero_voice_bot", "@CrazyMitaAIbot"], 'default': "@silero_voice_bot",
                 'tooltip': _("Выберите бота", "Select bot")},
                {'label': _('Макс. ожидание (сек)', 'Max wait (sec)'), 'key': 'SILERO_TIME', 'type': 'entry', 'default': 12, 'validation': self.validate_number},
                {'label': _('Настройки Telegram API', 'Telegram API Settings'), 'type': 'text'},
                 {'label': _('Будет скрыто после перезапуска','Will be hidden after restart')},
                {'label': _('Telegram ID'), 'key': 'NM_TELEGRAM_API_ID', 'type': 'entry', 'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
                {'label': _('Telegram Hash'), 'key': 'NM_TELEGRAM_API_HASH', 'type': 'entry', 'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
                {'label': _('Telegram Phone'), 'key': 'NM_TELEGRAM_PHONE', 'type': 'entry', 'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        ]
        self.tg_widgets = {}
        for config in tg_config:
            widget_frame = self.create_setting_widget(
                parent=self.tg_settings_frame,
                label=config['label'],
                setting_key=config.get('key', ''),
                widget_type=config.get('type', 'entry'),
                options=config.get('options', None),
                default=config.get('default', ''),
                default_checkbutton=config.get('default_checkbutton', False),
                validation=config.get('validation', None),
                tooltip=config.get('tooltip', ""),
                hide=config.get('hide', False),
                command=config.get('command', None)
            )
            widget_key = config.get('key', config['label'])
            self.tg_widgets[widget_key] = {'frame': widget_frame, 'config': config}

        # === Настройки локальной озвучки ===
        self.local_settings_frame = tk.Frame(self.voiceover_content_frame, bg="#2c2c2c")
        # --- Выбор модели ---
        local_model_frame = tk.Frame(self.local_settings_frame, bg="#2c2c2c")
        local_model_frame.pack(fill=tk.X, pady=2)
        tk.Label(local_model_frame, text=_("Локальная модель:", "Local Model:"), bg="#2c2c2c", fg="#ffffff", width=25, anchor='w').pack(side=tk.LEFT, padx=5)
        self.local_model_status_label = tk.Label(local_model_frame, text="⚠️", bg="#2c2c2c", fg="orange", font=("Arial", 12, "bold"))
        self.create_tooltip(self.local_model_status_label, _("Модель не инициализирована.\nВыберите модель для начала инициализации.", "Model not initialized.\nSelect the model to start initialization."))
        installed_models = [model["name"] for model in LOCAL_VOICE_MODELS if self.local_voice.is_model_installed(model["id"])]
        current_model_id = self.settings.get("NM_CURRENT_VOICEOVER", None)
        current_model_name = ""
        if current_model_id:
            for m in LOCAL_VOICE_MODELS:
                if m["id"] == current_model_id:
                    current_model_name = m["name"]
                    break
        self.local_voice_combobox = ttk.Combobox(
            local_model_frame,
            values=installed_models,
            state="readonly",
            width=26
        )
        if current_model_name and current_model_name in installed_models:
            self.local_voice_combobox.set(current_model_name)
        elif installed_models:
                self.local_voice_combobox.set(installed_models[0])
                for m in LOCAL_VOICE_MODELS:
                    if m["name"] == installed_models[0]:
                        self.settings.set("NM_CURRENT_VOICEOVER", m["id"])
                        self.settings.save_settings()
                        self.current_local_voice_id = m["id"]
                        break
        else:
                self.local_voice_combobox.set("")
        self.local_voice_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        self.local_voice_combobox.bind("<<ComboboxSelected>>", self.on_local_voice_selected)
        self.local_model_status_label.pack(side=tk.LEFT, padx=(2, 5))

        voice_lang_frame = tk.Frame(self.local_settings_frame, bg="#2c2c2c")
        voice_lang_frame.pack(fill=tk.X, pady=2)
        tk.Label(voice_lang_frame, text=_("Язык локальной озвучки:", "Local Voice Language:"), bg="#2c2c2c", fg="#ffffff", width=25, anchor='w').pack(side=tk.LEFT, padx=5)
        self.voice_language_var = tk.StringVar(value=self.settings.get("VOICE_LANGUAGE", "ru"))
        voice_lang_options = ["ru", "en"] 
        voice_lang_combobox = ttk.Combobox(
            voice_lang_frame,
            textvariable=self.voice_language_var,
            values=voice_lang_options,
            state="readonly",
            width=28
        )
        voice_lang_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        voice_lang_combobox.bind("<<ComboboxSelected>>", self.on_voice_language_selected)

        load_last_model_frame = tk.Frame(self.local_settings_frame, bg="#2c2c2c")
        load_last_model_frame.pack(fill=tk.X, pady=2)
        self.create_setting_widget(
            parent=load_last_model_frame,
            label=_('Автозагрузка модели', 'Autoload model'),
            setting_key='LOCAL_VOICE_LOAD_LAST',
            widget_type='checkbutton',
            default_checkbutton=False,
            tooltip=_('Загружает последнюю выбранную локальную модель при старте программы.',
                      'Loads the last selected local model when the program starts.')
        )

        if os.environ.get("ENABLE_VOICE_DELETE_CHECKBOX", "0") == "1":
            delete_audio_frame = tk.Frame(self.local_settings_frame, bg="#2c2c2c")
            delete_audio_frame.pack(fill=tk.X, pady=2)
            self.create_setting_widget(
                parent=delete_audio_frame,
                label=_('Удалять аудио', 'Delete audio'),
                setting_key='LOCAL_VOICE_DELETE_AUDIO',
                widget_type='checkbutton',
                default_checkbutton=True,
                tooltip=_('Удалять аудиофайл локальной озвучки после его воспроизведения или отправки.',
                        'Delete the local voiceover audio file after it has been played or sent.')
            )

        local_chat_voice_frame = tk.Frame(self.local_settings_frame, bg="#2c2c2c")
        local_chat_voice_frame.pack(fill=tk.X, pady=2)
        self.create_setting_widget(
            parent=local_chat_voice_frame,
            label=_('Озвучивать в локальном чате', 'Voiceover in local chat'),
            setting_key='VOICEOVER_LOCAL_CHAT',
            widget_type='checkbutton',
            default_checkbutton=True
        )

        # --- Кнопка управления моделями ---
        install_button_frame = tk.Frame(self.local_settings_frame, bg="#2c2c2c")
        install_button_frame.pack(fill=tk.X, pady=5)
        install_button = tk.Button(
            install_button_frame,
            text=_("Управление локальными моделями", "Manage Local Models"),
            command=self.open_local_model_installation_window,
            bg="#8a2be2",
            fg="#ffffff"
        )
        install_button.pack(pady=5)

        # --- Переключаем видимость настроек ---
        self.switch_voiceover_settings()
        self.check_triton_dependencies()
    
    #endregion

    def setup_mita_controls(self, parent):
        # Основные настройки
        mita_config = [
            {'label': _('Персонаж', 'Character'), 'key': 'CHARACTER', 'type': 'combobox',
             'options': self.model.get_all_mitas(),
             'default': "Crazy"},

            {'label': _('Экспериментальные функции', 'Experimental features'), 'type': 'text'},
            {'label': _('Меню выбора Мит', 'Mita selection menu'), 'key': 'MITAS_MENU', 'type': 'checkbutton',
             'default_checkbutton': False},
            {'label': _('Меню эмоций Мит', 'Emotion menu'), 'key': 'EMOTION_MENU', 'type': 'checkbutton',
             'default_checkbutton': False},
          #  {'label': _('Миты в работе', 'Mitas in work'), 'key': 'TEST_MITAS', 'type': 'checkbutton',
          #   'default_checkbutton': False,'tooltip':_("Позволяет выбирать нестабильные версии Мит", "Allow to choose ustable Mita versions")}
        ]

        self.create_settings_section(parent, _("Выбор персонажа", "Character selection"), mita_config)

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

    def setup_game_master_controls(self, parent):
        # Основные настройки
        common_config = [
            {'label': _('Лимит речей нпс %', 'Limit NPC convesationg'), 'key': 'CC_Limit_mod', 'type': 'entry',
             'default': 100, 'tooltip': _('Сколько от кол-ва персонажей может отклоняться повтор речей нпс',
                                          'How long NPC can talk ignoring player')},
            {'label': _('ГеймМастер - экспериментальная функция', 'GameMaster is experimental feature'), 'type': 'text'},
            {'label': _('ГеймМастер включен', 'GameMaster is on'), 'key': 'GM_ON', 'type': 'checkbutton',
             'default_checkbutton': False, 'tooltip': 'Помогает вести диалоги, в теории устраняя проблемы'},
            #{'label': _('ГеймМастер зачитывается', 'GameMaster write in game'), 'key': 'GM_READ', 'type': 'checkbutton',
            # 'default_checkbutton': False},
            #{'label': _('ГеймМастер озвучивает', 'GameMaster is voiced'), 'key': 'GM_VOICE', 'type': 'checkbutton',
           #  'default_checkbutton': False},
            {'label': _('Задача ГМу', 'GM task'), 'key': 'GM_SMALL_PROMPT', 'type': 'text', 'default': ""},
            {'label': _('ГеймМастер встревает каждые', 'GameMaster intervene each'), 'key': 'GM_REPEAT',
             'type': 'entry',
             'default': 2,
             'tooltip': _('Пример: 3 Означает, что через каждые две фразы ГМ напишет свое сообщение', 'Example: 3 means that after 2 phreses GM will write his message')},

        ]
        self.create_settings_section(parent,
                                     _("Настройки Мастера игры и Диалогов", "GameMaster and Dialogues settings"),
                                     common_config)
        
    def setup_command_replacer_controls(self, parent):
        """Создает секцию настроек для Command Replacer."""
        command_replacer_config = [
            {'label': _('Использовать Command Replacer', 'Use Command Replacer'), 'key': 'USE_COMMAND_REPLACER', 'type': 'checkbutton',
            'default_checkbutton': False, 'tooltip': _('Включает замену команд в ответе модели на основе схожести.', 'Enables replacing commands in the model response based on similarity.')},
            {'label': _('Мин. порог схожести', 'Min Similarity Threshold'), 'key': 'MIN_SIMILARITY_THRESHOLD', 'type': 'entry',
            'default': 0.40, 'tooltip': _('Минимальный порог схожести для замены команды (0.0-1.0).', 'Minimum similarity threshold for command replacement (0.0-1.0).')},
            {'label': _('Порог смены категории', 'Category Switch Threshold'), 'key': 'CATEGORY_SWITCH_THRESHOLD', 'type': 'entry',
            'default': 0.18, 'tooltip': _('Дополнительный порог для переключения на другую категорию команд (0.0-1.0).', 'Additional threshold for switching to a different command category (0.0-1.0).')},
            {'label': _('Пропускать параметры с запятой', 'Skip Comma Parameters'), 'key': 'SKIP_COMMA_PARAMETERS', 'type': 'checkbutton',
            'default_checkbutton': True, 'tooltip': _('Пропускать параметры, содержащие запятую, при замене.', 'Skip parameters containing commas during replacement.')},
        ]

        self.create_settings_section(parent,
                                    _("Настройки Command Replacer (БЕТА)", "Command Replacer Settings (BETA)"),
                                    command_replacer_config)

    def setup_api_controls_new(self, parent):
        # Основные настройки
        common_config = [
            {'label': _('Ссылка', 'URL'), 'key': 'NM_API_URL', 'type': 'entry'},
            {'label': _('Модель', 'Model'), 'key': 'NM_API_MODEL', 'type': 'entry'},
            {'label': _('Ключ', 'Key'), 'key': 'NM_API_KEY', 'type': 'entry', 'default': ""},
            {'label': _('Резервные ключи', 'Reserve keys'), 'key': 'NM_API_KEY_RES', 'type': 'text',
             'hide': bool(self.settings.get("HIDE_PRIVATE")), 'default': ""},
            {'label': _('Через Request', 'Using Request'), 'key': 'NM_API_REQ', 'type': 'checkbutton'},
            {'label': _('Гемини для ProxiAPI', 'Gemini for ProxiAPI'), 'key': 'GEMINI_CASE', 'type': 'checkbutton',
             'default_checkbutton': False}
        ]
        self.create_settings_section(parent,
                                     _("Настройки API", "API settings"),
                                     common_config)

    #endregion
    def setup_general_settings_control(self, parent):
        general_config = [
            # здесь настройки из setup_model_controls
            {'label': _('Настройки сообщений', 'Message settings'), 'type': 'text'},
            {'label': _('Лимит сообщений', 'Message limit'), 'key': 'MODEL_MESSAGE_LIMIT',
             'type': 'entry', 'default': 40,
             'tooltip': _('Сколько сообщений будет помнить мита', 'How much messages Mita will remember')},
            {'label': _('Кол-во попыток', 'Attempt count'), 'key': 'MODEL_MESSAGE_ATTEMPTS_COUNT',
             'type': 'entry', 'default': 3},
            {'label': _('Время между попытками', 'time between attempts'),
             'key': 'MODEL_MESSAGE_ATTEMPTS_TIME', 'type': 'entry', 'default': 0.20},
            {'label': _('Использовать gpt4free последней попыткой ', 'Use gpt4free as last attempt'),
             'key': 'GPT4FREE_LAST_ATTEMPT', 'type': 'checkbutton', 'default_checkbutton': False},

            {'label': _('Настройки ожидания', 'Waiting settings'), 'type': 'text'},
            {'label': _('Время ожидания текста (сек)', 'Text waiting time (sec)'),
             'key': 'TEXT_WAIT_TIME', 'type': 'entry', 'default': 40,
             'tooltip': _('время ожидания ответа', 'response waiting time')},
            {'label': _('Время ожидания звука (сек)', 'Voice waiting time (sec)'),
             'key': 'VOICE_WAIT_TIME', 'type': 'entry', 'default': 40,
             'tooltip': _('время ожидания озвучки', 'voice generation waiting time')},

            {'label': _('Настройки генерации текста', 'Text Generation Settings'), 'type': 'text'},
            {'label': _('Макс. токенов в ответе', 'Max response tokens'), 'key': 'MODEL_MAX_RESPONSE_TOKENS',
             'type': 'entry', 'default': 2500, 'validation': self.validate_positive_integer,
             'tooltip': _('Максимальное количество токенов в ответе модели',
                          'Maximum number of tokens in the model response')},
            {'label': _('Температура', 'Temperature'), 'key': 'MODEL_TEMPERATURE',
             'type': 'entry', 'default': 0.5, 'validation': self.validate_float_0_to_2,
             'tooltip': _('Креативность ответа (0.0 = строго, 2.0 = очень творчески)',
                          'Creativity of response (0.0 = strict, 2.0 = very creative)')},

            {'label': _('Штраф присутствия', 'Use Presence penalty'),
             'key': 'USE_MODEL_PRESENCE_PENALTY',
             'type': 'checkbutton',
             'default_checkbutton': True,
             'tooltip': _('Использовать параметр Штраф присутствия', 'Use the Presence penalty parameter')},
            {'label': _('Штраф присутствия', 'Presence penalty'), 'key': 'MODEL_PRESENCE_PENALTY',
             'type': 'entry', 'default': 0.0, 'validation': self.validate_float_minus2_to_2,
             'tooltip': _('Штраф за использование новых токенов (-2.0 = поощрять новые, 2.0 = сильно штрафовать)',
                          'Penalty for using new tokens (-2.0 = encourage new, 2.0 = strongly penalize)')},

        ]

        self.create_settings_section(parent,
                                     _("Общие настройки моделей", "General settings for models"),
                                     general_config)
    # region Validation
    def validate_number(self, new_value):
        if not new_value.isdigit():  # Проверяем, что это число
            return False
        return 0 <= int(new_value) <= 60  # Проверяем, что в пределах диапазона

    # Добавьте функции валидации в ChatGUI
    def validate_positive_integer(self, new_value):
        if new_value == "": return True  # Разрешаем пустое поле временно
        try:
            value = int(new_value)
            return value > 0
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
    # endrigion

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

    def insertDialog(self, input_text="", response="", system_text=""):
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
            # Ограничиваем выполнение задачи
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

    def reload_prompts(self):
        """Скачивает свежие промпты с GitHub и перезагружает их для текущего персонажа."""
        # Запускаем асинхронную задачу через event loop
        #тут делаем запрос подверждение
        confirm = messagebox.askokcancel(
            _("Подтверждение", "Confirmation"),
            _("Это удалит текущие промпты! Продолжить?", "This will delete the current prompts! Continue?"),
            icon='warning', parent=self.root
        )
        if not confirm:
            return
        if confirm:
            # Показать индикатор загрузки
            self._show_loading_popup(_("Загрузка промптов...", "Downloading prompts..."))      
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.async_reload_prompts(), self.loop)
            else:
                logger.error("Цикл событий asyncio не запущен. Невозможно выполнить асинхронную загрузку промптов.")
                messagebox.showerror(
                    _("Ошибка", "Error"), 
                    _("Не удалось запустить асинхронную загрузку промптов.", 
                      "Failed to start asynchronous prompt download.")
                )

    async def async_reload_prompts(self):
        try:
            from utils.prompt_downloader import PromptDownloader
            downloader = PromptDownloader()
            
            success = await self.loop.run_in_executor(None, downloader.download_and_replace_prompts)
            
            if success:
                character = self.model.characters.get(self.model.current_character_to_change)
                if character:
                    await self.loop.run_in_executor(None, character.reload_prompts)
                else:
                    logger.error("Персонаж для перезагрузки не найден")

                self._close_loading_popup()
                messagebox.showinfo(
                    _("Успешно", "Success"), 
                    _("Промпты успешно скачаны и перезагружены.", "Prompts successfully downloaded and reloaded.")
                )
            else:
                messagebox.showerror(
                    _("Ошибка", "Error"), 
                    _("Не удалось скачать промпты с GitHub. Проверьте подключение к интернету.", 
                      "Failed to download prompts from GitHub. Check your internet connection.")
                )
        except Exception as e:
            logger.error(f"Ошибка при обновлении промптов: {e}")
            messagebox.showerror(
                _("Ошибка", "Error"), 
                _("Не удалось обновить промпты.", "Failed to update prompts.")
            )
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
            try:
                self.model.max_response_tokens = int(value)
            except ValueError:
                pass  # Игнорировать, если не число
        elif key == "MODEL_TEMPERATURE":
            try:
                self.model.temperature = float(value)
            except ValueError:
                pass  # Игнорировать, если не число
        elif key == "MODEL_PRESENCE_PENALTY":
            try:
                self.model.presence_penalty = float(value)
            except ValueError:
                pass  # Игнорировать, если не число


        elif key == "MODEL_MESSAGE_LIMIT":
            self.model.memory_limit = int(value)
        elif key == "MODEL_MESSAGE_ATTEMPTS_COUNT":
            self.model.max_request_attempts = int(value)
        elif key == "MODEL_MESSAGE_ATTEMPTS_TIME":
            self.model.request_delay = float(value)

        elif key == "MIC_ACTIVE":
            SpeechRecognition.active = bool(value)

        # logger.info(f"Настройки изменены: {key} = {value}")
    #endregion

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
                hide=config.get('hide', False),
                command=config.get('command', None)
            )
            section.add_widget(widget)

        return section

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

            # Явная привязка горячих клавиш для Entry
            # entry.bind("<Control-v>", lambda e: self.cmd_paste(e.widget))
            # entry.bind("<Control-c>", lambda e: self.cmd_copy(e.widget))
            # entry.bind("<Control-x>", lambda e: self.cmd_cut(e.widget))
            
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
        result_path = None # Инициализируем переменную
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
                    await AudioHandler.handle_voice_file(result_path, self.settings.get("LOCAL_VOICE_DELETE_AUDIO", True) if os.environ.get("ENABLE_VOICE_DELETE_CHECKBOX", "0") == "1" else True)
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
            self.update_local_model_status_indicator() # Обновляем на случай сброса
            return

        selected_model_id = None
        selected_model = None
        for model in LOCAL_VOICE_MODELS:
            if model["name"] == selected_model_name:
                selected_model = model
                selected_model_id = model["id"]
                break

        if not selected_model_id:
            messagebox.showerror(_("Ошибка", "Error"), _("Не удалось определить ID выбранной модели", "Could not determine ID of selected model"))
            self.update_local_model_status_indicator() # Обновляем статус
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
                self.update_local_model_status_indicator() # Обновляем статус
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
        loading_window.transient(self.root) # Делаем модальным относительно главного окна
        loading_window.grab_set() # Захватываем фокус

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
        progress.start(10) # Запускаем анимацию прогресс-бара

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
            args=(model_id, loading_window, status_var, progress), # Передаем progress
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
                success = self.local_voice.initialize_model(model_id, init=True) # init=True для тестовой генерации

            # Проверяем окно перед обновлением UI
            if not loading_window.winfo_exists():
                logger.info("Окно загрузки было закрыто до завершения инициализации.")
                return

            # Если инициализация завершилась успешно и не была отменена
            if success and not self.model_loading_cancelled:
                self.root.after(0, lambda: self.finish_model_loading(model_id, loading_window))
            elif not self.model_loading_cancelled:
                # Если произошла ошибка во время инициализации
                error_message = _("Не удалось инициализировать модель. Проверьте логи.", "Failed to initialize model. Check logs.")
                self.root.after(0, lambda: [
                    status_var.set(_("Ошибка инициализации!", "Initialization Error!")),
                    progress.stop(),
                    messagebox.showerror(_("Ошибка инициализации", "Initialization Error"), error_message, parent=loading_window),
                    self.cancel_model_loading(loading_window) # Используем cancel для сброса состояния
                ])
        except Exception as e:
            logger.error(f"Критическая ошибка в потоке инициализации модели {model_id}: {e}", exc_info=True)
            # Проверяем окно перед показом ошибки
            if loading_window.winfo_exists() and not self.model_loading_cancelled:
                error_message = _("Критическая ошибка при инициализации модели: ", "Critical error during model initialization: ") + str(e)
                self.root.after(0, lambda: [
                    status_var.set(_("Ошибка!", "Error!")),
                    progress.stop(),
                    messagebox.showerror(_("Ошибка", "Error"), error_message, parent=loading_window),
                    self.cancel_model_loading(loading_window) # Используем cancel для сброса состояния
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
        self.current_local_voice_id = model_id # Обновляем и внутреннюю переменную

        messagebox.showinfo(
            _("Успешно", "Success"),
            _("Модель {} успешно инициализирована!", "Model {} initialized successfully!").format(model_id),
            parent=self.root # Указываем родителя для модальности
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
                            logger.info(f"Модель {last_model_id} установлена, но не инициализирована. Запуск инициализации...")
                            # Используем существующее окно загрузки
                            self.show_model_loading_window(model_to_load)
                        else:
                            logger.info(f"Модель {last_model_id} уже инициализирована.")
                            # Убедимся, что last_voice_model_selected актуален
                            self.last_voice_model_selected = model_to_load
                            self.update_local_voice_combobox() # Обновим UI на всякий случай
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
            header_widget = getattr(self.voiceover_section, 'header', None) # Исправлено на 'header'

            if header_widget and header_widget.winfo_exists():
                if show_section_warning:
                    # Пакуем ПЕРЕД title_label, если он существует
                    if title_widget and title_widget.winfo_exists():
                        self.voiceover_section_warning_label.pack(
                            in_=header_widget, # Указываем родителя
                            side=tk.LEFT,
                            before=title_widget, # Помещаем перед текстом
                            padx=(0, 3) # Отступ справа
                        )
                    else:
                        # Если title_label нет, пакуем после стрелки (arrow_label)
                        arrow_widget = getattr(self.voiceover_section, 'arrow_label', None)
                        if arrow_widget and arrow_widget.winfo_exists():
                             self.voiceover_section_warning_label.pack(
                                in_=header_widget,
                                side=tk.LEFT,
                                after=arrow_widget, # Помещаем после стрелки
                                padx=(3, 3) # Отступы с обеих сторон
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
             self.method_frame.pack(fill=tk.X, padx=5, pady=0, in_=self.voiceover_content_frame) # Пакуем в основной контент

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

        installed_models_names = [model["name"] for model in LOCAL_VOICE_MODELS if self.local_voice.is_model_installed(model["id"])]
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
            logger.warning(f"Зависимости Triton не найдены! Игнорируйте это предупреждение, если не используете \"Fish Speech+ / + RVC\" озвучку. Exception импорта: {e}")
        except Exception as e: # Ловим другие возможные ошибки при импорте
            logger.error(f"Неожиданная ошибка при проверке Triton. Игнорируйте это предупреждение, если не используете \"Fish Speech+ / + RVC\" озвучку. Exception: {e}", exc_info=True)


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
                    self.update_local_voice_combobox() # Обновляем комбобокс еще раз

            # Создаем дочернее окно Toplevel БЕЗ grab_set и transient
            install_window = tk.Toplevel(self.root)
            # install_window.transient(self.root) # --- УБРАНО ---
            # install_window.grab_set() # --- УБРАНО ---
            install_window.title(_("Управление локальными моделями", "Manage Local Models")) # Добавим заголовок

            # Инициализируем окно настроек моделей
            VoiceModelSettingsWindow(
                master=install_window, # Передаем дочернее окно как родителя
                config_dir=config_dir,
                on_save_callback=on_save_callback,
                local_voice=self.local_voice,
                check_installed_func=self.check_module_installed,
            )
        except ImportError:
             logger.error("Не найден модуль voice_model_settings.py. Установка моделей недоступна.")
             messagebox.showerror(_("Ошибка", "Error"), _("Не найден файл voice_model_settings.py", "voice_model_settings.py not found."))
        except Exception as e:
            logger.error(f"Ошибка при открытии окна установки моделей: {e}", exc_info=True)
            messagebox.showerror(_("Ошибка", "Error"), _("Не удалось открыть окно установки моделей.", "Failed to open model installation window."))


    def refresh_local_voice_modules(self):
        """Обновляет импорты модулей в LocalVoice без перезапуска программы."""
        import importlib
        import sys
        logger.info("Попытка обновления модулей локальной озвучки...")

        # Список модулей для перезагрузки/импорта
        modules_to_check = {
            "tts_with_rvc": "TTS_RVC",
            "fish_speech_lib.inference": "FishSpeech",
            "triton": None # Просто проверяем наличие
        }
        # Пути, где могут лежать модули (добавляем Lib)
        lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Lib")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path) # Добавляем в начало, чтобы иметь приоритет

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
                            logger.warning(f"Модуль {module_name} импортирован, но __spec__ is None или отсутствует. Считаем не установленным корректно.")
                            # Очищаем из sys.modules, если импорт был частичным
                            if module_name in sys.modules:
                                try: del sys.modules[module_name]
                                except KeyError: pass
                            return False
                    except ImportError as ie:
                         logger.warning(f"Модуль {module_name} найден find_spec, но не импортируется: {ie}. Считаем не установленным.")
                         return False
                    except ValueError as ve: # Ловим ValueError при импорте
                         logger.warning(f"Модуль {module_name} найден find_spec, но ошибка ValueError при импорте: {ve}. Считаем не установленным.")
                         return False
                    except Exception as e_import: # Ловим другие ошибки импорта
                         logger.error(f"Неожиданная ошибка при импорте {module_name} после find_spec: {e_import}")
                         return False
                else:
                    # Спецификация есть, но нет загрузчика
                    logger.warning(f"Модуль {module_name} найден через find_spec, но loader is None. Считаем не установленным корректно.")
                    return False

        except ValueError as e:
            # Ловим ValueError именно от find_spec (хотя теперь это менее вероятно)
            logger.warning(f"Ошибка ValueError при find_spec для {module_name}: {e}. Считаем не установленным корректно.")
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
            return 100 # Возвращаем заглушку 100 GB
        except Exception as e:
            logger.error(f"Ошибка при попытке проверки VRAM: {e}")
            return 4 # Возвращаем минимальное значение в случае ошибки

    # endregion

    # region ffmpeg installations tools
    def _show_ffmpeg_installing_popup(self):
        """Показывает неблокирующее окно 'Установка FFmpeg...'."""
        if self.ffmpeg_install_popup and self.ffmpeg_install_popup.winfo_exists():
            return # Окно уже открыто

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
        self.ffmpeg_install_popup.update_idletasks() # Обновляем размеры окна
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (self.ffmpeg_install_popup.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (self.ffmpeg_install_popup.winfo_height() // 2)
        self.ffmpeg_install_popup.geometry(f"+{x}+{y}")

        self.ffmpeg_install_popup.transient(self.root) # Делаем зависимым от главного
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
            justify=tk.LEFT # Выравнивание текста по левому краю
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

        error_popup.transient(self.root) # Зависимость от главного окна
        error_popup.grab_set()          # Перехват событий (делает модальным)
        self.root.wait_window(error_popup) # Ожидание закрытия этого окна

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

