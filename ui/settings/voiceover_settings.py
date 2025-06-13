import os
import tkinter as tk
from tkinter import ttk
from Logger import logger
from SettingsManager import CollapsibleSection
from utils import getTranslationVariant as _


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
        "gpu_vendor": ["NVIDIA"],
        "size_gb": 5
    },
    {
        "id": "medium+",
        "name": "Fish Speech+",
        "min_vram": 4,
        "rec_vram": 6,
        "gpu_vendor": ["NVIDIA"],
        "size_gb": 10
    },
    {
        "id": "medium+low",
        "name": "Fish Speech+ + RVC",
        "min_vram": 6,
        "rec_vram": 8,
        "gpu_vendor": ["NVIDIA"],
        "size_gb": 15
    },
    {
        "id": "f5_tts",
        "name": "F5-TTS",
        "min_vram": 6,
        "rec_vram": 8,
        "gpu_vendor": ["NVIDIA", "AMD"],
        "size_gb": 4
    }
]



def setup_voiceover_controls(self, parent):
    voice_section = CollapsibleSection(parent, _("Настройка озвучки", "Voiceover Settings"))
    voice_section.pack(fill=tk.X, padx=5, pady=5, expand=True)
    self.voiceover_section = voice_section
    self.voiceover_content_frame = voice_section.content_frame

    try:
        header_bg = voice_section.header.cget("background")  # ttk виджеты используют 'background'
    except Exception as e:
        logger.warning(f"Не удалось получить фон заголовка секции: {e}. Используется фоллбэк.")
        header_bg = "#333333"  # Фоллбэк из стиля Header.TFrame

    self.voiceover_section_warning_label = ttk.Label(  # Используем ttk.Label для консистентности
        voice_section.header,
        text="⚠️",
        background=header_bg,  # Используем background
        foreground="orange",  # Используем foreground
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
    tk.Label(method_frame, text=_("Вариант озвучки:", "Voiceover Method:"), bg="#2c2c2c", fg="#ffffff", width=25,
             anchor='w').pack(side=tk.LEFT, padx=5)
    self.voiceover_method_var = tk.StringVar(value=self.settings.get("VOICEOVER_METHOD", "TG"))
    method_options = ["TG", "Local"] if os.environ.get("EXPERIMENTAL_FUNCTIONS", "0") == "1" else [
        "TG"]  # Вернем локальную озвучку всем # Atm4x says: верну, ибо это вполне мог сделать гемини... хотя уже без разницы
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
        {'label': _('Макс. ожидание (сек)', 'Max wait (sec)'), 'key': 'SILERO_TIME', 'type': 'entry', 'default': 12,
         'validation': self.validate_number_0_60},
        {'label': _('Настройки Telegram API', 'Telegram API Settings'), 'type': 'text'},
        {'label': _('Будет скрыто после перезапуска', 'Will be hidden after restart')},
        {'label': _('Telegram ID'), 'key': 'NM_TELEGRAM_API_ID', 'type': 'entry', 'default': "",
         'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('Telegram Hash'), 'key': 'NM_TELEGRAM_API_HASH', 'type': 'entry', 'default': "",
         'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('Telegram Phone'), 'key': 'NM_TELEGRAM_PHONE', 'type': 'entry', 'default': "",
         'hide': bool(self.settings.get("HIDE_PRIVATE"))},
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
    tk.Label(local_model_frame, text=_("Локальная модель:", "Local Model:"), bg="#2c2c2c", fg="#ffffff", width=25,
             anchor='w').pack(side=tk.LEFT, padx=5)
    self.local_model_status_label = tk.Label(local_model_frame, text="⚠️", bg="#2c2c2c", fg="orange",
                                             font=("Arial", 12, "bold"))
    self.create_tooltip(self.local_model_status_label,
                        _("Модель не инициализирована.\nВыберите модель для начала инициализации.",
                          "Model not initialized.\nSelect the model to start initialization."))
    installed_models = [model["name"] for model in LOCAL_VOICE_MODELS if
                        self.local_voice.is_model_installed(model["id"])]
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
    tk.Label(voice_lang_frame, text=_("Язык локальной озвучки:", "Local Voice Language:"), bg="#2c2c2c",
             fg="#ffffff", width=25, anchor='w').pack(side=tk.LEFT, padx=5)
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