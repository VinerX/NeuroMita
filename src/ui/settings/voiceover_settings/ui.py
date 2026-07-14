import os
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QSizePolicy, QPushButton, QSlider
)
from ui.gui_templates import create_setting_widget, create_section_header, SettingsBodyWidget
from utils import getTranslationVariant as _
from localization.live import tr_set
from ui.settings.voiceover_settings.presentation import (
    OpenAIEngineSettings,
    OpenVoiceAIHub,
    RestartVoiceService,
    StartTelegramVoice,
)

try:
    import qtawesome as qta
except Exception:
    qta = None


def build_voiceover_settings_ui(self, parent_layout, *, actions):
    self._voiceover_settings_view_model = actions
    sidebar_w = getattr(self, "SETTINGS_SIDEBAR_WIDTH", 50)
    right_pad = max(8, min(14, int(sidebar_w * 0.22)))

    container = SettingsBodyWidget()
    container_lay = QVBoxLayout(container)
    container_lay.setContentsMargins(0, 0, right_pad, 0)
    container_lay.setSpacing(6)

    create_section_header(container_lay, _("Настройки озвучки", "Voiceover Settings"))

    self.voiceover_section = type('obj', (object,), {'content_frame': parent_layout.parent()})()

    main_config = [
        {'label': _('Использовать озвучку', 'Use speech'),
         'key': 'USE_VOICEOVER', 'type': 'checkbutton',
         'default_checkbutton': False, 'widget_name': 'use_voice_checkbox'},
        {'label': _("Вариант озвучки", "Voiceover Method"),
         'key': 'VOICEOVER_METHOD', 'type': 'combobox',
         'options': ["TG", "Local"], 'default': 'Local',
         'widget_name': 'method_combobox'},
    ]

    for cfg in main_config:
        widget = create_setting_widget(
            gui=self,
            parent=container,
            label=cfg.get('label'),
            setting_key=cfg.get('key', ''),
            widget_type=cfg.get('type', 'entry'),
            options=cfg.get('options'),
            default=cfg.get('default', ''),
            default_checkbutton=cfg.get('default_checkbutton', False),
            widget_name=cfg.get('widget_name')
        )
        if widget:
            container_lay.addWidget(widget)
            if cfg.get('widget_name') == 'method_combobox':
                self.method_frame = widget

    self.tg_settings_frame = SettingsBodyWidget()
    tg_layout = QVBoxLayout(self.tg_settings_frame)
    tg_layout.setContentsMargins(0, 0, 0, 0)
    tg_layout.setSpacing(4)

    tg_config = [
        {'label': _('Автоподключение Telegram', 'Telegram auto-connect'),
         'key': 'TG_AUTOCONNECT', 'type': 'checkbutton',
         'default_checkbutton': False},

        {'label': _('Подключиться к Telegram', 'Connect Telegram'),
         'type': 'button',
         'command': (lambda: actions.dispatch(StartTelegramVoice())),
         'widget_name': 'tg_connect_button'},

        {'label': _('Канал/Сервис', "Channel/Service"), 'key': 'AUDIO_BOT',
         'type': 'combobox', 'options': ["@silero_voice_bot", "@CrazyMitaAIbot"],
         'default': "@silero_voice_bot"},

        {'label': _('Макс. ожидание (сек)', 'Max wait (sec)'), 'key': 'SILERO_TIME',
         'type': 'entry', 'default': '12', 'validation': getattr(self, 'validate_number_0_60', None)},

        {'label': _('Мин. интервал запросов (сек)', 'Min request interval (sec)'),
         'key': 'TG_MIN_REQUEST_INTERVAL',
         'type': 'entry', 'default': '2', 'validation': getattr(self, 'validate_number_0_60', None)},

        {'label': _('Настройки Telegram API', 'Telegram API Settings'), 'type': 'text'},
        {'label': _('Будет скрыто после перезапуска', 'Will be hidden after restart'), 'type': 'text'},

        {'label': _('Telegram ID'), 'key': 'NM_TELEGRAM_API_ID', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('Telegram Hash'), 'key': 'NM_TELEGRAM_API_HASH', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('Telegram Phone'), 'key': 'NM_TELEGRAM_PHONE', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
    ]

    for cfg in tg_config:
        widget = create_setting_widget(
            gui=self,
            parent=self.tg_settings_frame,
            label=cfg['label'],
            setting_key=cfg.get('key', ''),
            widget_type=cfg.get('type', 'entry'),
            options=cfg.get('options'),
            default=cfg.get('default', ''),
            validation=cfg.get('validation'),
            hide=cfg.get('hide', False),
            default_checkbutton=cfg.get('default_checkbutton', False),
            command=cfg.get('command'),
            widget_name=cfg.get('widget_name'),
        )
        if widget:
            tg_layout.addWidget(widget)

    container_lay.addWidget(self.tg_settings_frame)

    self.local_settings_frame = SettingsBodyWidget()
    local_layout = QVBoxLayout(self.local_settings_frame)
    local_layout.setContentsMargins(0, 0, 0, 0)
    local_layout.setSpacing(4)

    local_model_row = SettingsBodyWidget()
    local_model_layout = QHBoxLayout(local_model_row)
    local_model_layout.setContentsMargins(0, 2, 0, 2)
    local_model_layout.setSpacing(10)

    label_part = QHBoxLayout()
    label_part.setContentsMargins(0, 0, 0, 0)
    label_part.setSpacing(2)

    local_model_label = tr_set(QLabel(), "Локальная модель", "Local Model")

    label_part.addWidget(local_model_label)

    label_container = SettingsBodyWidget()
    label_container.setLayout(label_part)
    label_container.setMinimumWidth(140)
    label_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    self.local_voice_combobox = QComboBox()
    self.local_voice_empty_status = tr_set(
        QLabel(),
        "Нет установленных моделей",
        "No installed models",
    )
    self.local_voice_empty_status.setObjectName("SeparatorLabel")
    self.local_voice_empty_status.setVisible(False)

    # Шестерёнка справа от модели → настройки конкретной модели (AI Hub, раздел TTS).
    self.local_model_settings_btn = QPushButton()
    self.local_model_settings_btn.setObjectName("VoiceModelSettingsButton")
    self.local_model_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.local_model_settings_btn.setFixedSize(30, 30)
    self.local_model_settings_btn.setToolTip(_("Настройки модели", "Model settings"))
    if qta is not None:
        try:
            self.local_model_settings_btn.setIcon(qta.icon("fa5s.cog", color="#cccccc"))
        except Exception:
            self.local_model_settings_btn.setText("⚙")
    else:
        self.local_model_settings_btn.setText("⚙")
    def _open_current_model_settings():
        # Открываем AI Hub на разделе TTS и сразу выделяем текущую модель.
        # component_id в реестре — "tts:<model_id>" (см. make_component_id).
        mid = None
        if self.local_voice_combobox is not None:
            mid = self.local_voice_combobox.currentData()
        if not mid:
            mid = self.settings.get("NM_CURRENT_VOICEOVER")
        mid = str(mid or "").strip()
        actions.dispatch(OpenVoiceAIHub(mid or None))

    self.local_model_settings_btn.clicked.connect(_open_current_model_settings)

    local_model_layout.addWidget(label_container)
    local_model_layout.addWidget(self.local_voice_combobox, 1)
    local_model_layout.addWidget(self.local_voice_empty_status, 1)
    local_model_layout.addWidget(self.local_model_settings_btn, 0)
    local_layout.addWidget(local_model_row)

    # Строка статуса локальной модели: цветной чип-состояние + адаптивная
    # кнопка действия («Установить» / «Инициализировать»). Состояния и подписи
    # выставляет VoiceoverGuiController._sync_local_model_status, действие кнопки
    # разруливает wire_voiceover_settings_logic по свойству "action".
    status_row = SettingsBodyWidget()
    status_layout = QHBoxLayout(status_row)
    status_layout.setContentsMargins(0, 0, 0, 2)
    status_layout.setSpacing(8)

    self.local_model_status_chip = QLabel()
    self.local_model_status_chip.setObjectName("VoiceModelStatusChip")
    self.local_model_status_chip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    self.local_model_action_btn = QPushButton()
    self.local_model_action_btn.setObjectName("VoiceModelActionButton")
    self.local_model_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.local_model_action_btn.setVisible(False)

    status_layout.addWidget(self.local_model_status_chip)
    status_layout.addStretch(1)
    status_layout.addWidget(self.local_model_action_btn)
    local_layout.addWidget(status_row)

    # Громкость воспроизведения в питоне (0..200%). Значения выше 100% усиливают
    # звук покадрово в AudioHandler, чтобы можно было сделать озвучку громче исходной.
    if self.settings.get("VOICEOVER_LOCAL_VOLUME") is None:
        self.settings.set("VOICEOVER_LOCAL_VOLUME", 100)
    try:
        _init_volume = int(self.settings.get("VOICEOVER_LOCAL_VOLUME", 100))
    except (TypeError, ValueError):
        _init_volume = 100
    _init_volume = max(0, min(200, _init_volume))

    volume_row = SettingsBodyWidget()
    volume_layout = QHBoxLayout(volume_row)
    volume_layout.setContentsMargins(0, 2, 0, 2)
    volume_layout.setSpacing(10)

    volume_label = tr_set(QLabel(), "Громкость озвучки", "Voiceover volume")
    volume_label.setMinimumWidth(140)
    volume_label.setMaximumWidth(140)
    volume_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    self.local_volume_slider = QSlider(Qt.Orientation.Horizontal)
    self.local_volume_slider.setMinimum(0)
    self.local_volume_slider.setMaximum(200)
    self.local_volume_slider.setSingleStep(5)
    self.local_volume_slider.setPageStep(10)
    self.local_volume_slider.setValue(_init_volume)

    self.local_volume_value_label = QLabel(f"{_init_volume}%")
    self.local_volume_value_label.setMinimumWidth(44)
    self.local_volume_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _on_volume_changed(value):
        self.local_volume_value_label.setText(f"{int(value)}%")
        # Во время перетаскивания не спамим сохранением — запишем на отпускании.
        if not self.local_volume_slider.isSliderDown():
            self._save_setting("VOICEOVER_LOCAL_VOLUME", int(value))

    def _on_volume_released():
        self._save_setting("VOICEOVER_LOCAL_VOLUME", int(self.local_volume_slider.value()))

    self.local_volume_slider.valueChanged.connect(_on_volume_changed)
    self.local_volume_slider.sliderReleased.connect(_on_volume_released)

    volume_layout.addWidget(volume_label)
    volume_layout.addWidget(self.local_volume_slider, 1)
    volume_layout.addWidget(self.local_volume_value_label, 0)
    local_layout.addWidget(volume_row)

    local_config = [
        {'label': _("Язык локальной озвучки", "Local Voice Language"),
         'key': "VOICE_LANGUAGE", 'type': 'combobox',
         'options': ["ru", "en"], 'default': "ru",
         'widget_name': 'voice_language_var'},

        {'label': _('Автозагрузка модели', 'Autoload model'),
         'key': 'LOCAL_VOICE_LOAD_LAST', 'type': 'checkbutton',
         'default_checkbutton': False},

        {'label': _('Озвучивать в чате', 'Voiceover in chat'),
         'key': 'VOICEOVER_LOCAL_CHAT', 'type': 'checkbutton',
         'default_checkbutton': True},

        {'label': _('Перезапустить нейро-ядро озвучки', 'Restart Voice AI Engine'),
         'type': 'button',
         'command': (lambda: actions.dispatch(RestartVoiceService()))},

        {'label': _('Перейти к настройкам AI Engine', 'Open AI Engine settings'),
         'type': 'button',
         'command': (lambda: actions.dispatch(OpenAIEngineSettings()))}
    ]
    if os.environ.get("ENABLE_VOICE_DELETE_CHECKBOX", "0") == "1":
        local_config.insert(2, {
            'label': _('Удалять аудио', 'Delete audio'),
            'key': 'LOCAL_VOICE_DELETE_AUDIO', 'type': 'checkbutton',
            'default_checkbutton': True
        })

    for cfg in local_config:
        widget = create_setting_widget(
            gui=self,
            parent=self.local_settings_frame,
            label=cfg.get('label'),
            setting_key=cfg.get('key', ''),
            widget_type=cfg.get('type', 'entry'),
            options=cfg.get('options'),
            default=cfg.get('default', ''),
            default_checkbutton=cfg.get('default_checkbutton', False),
            command=cfg.get('command'),
            widget_name=cfg.get('widget_name')
        )
        if widget:
            local_layout.addWidget(widget)

    container_lay.addWidget(self.local_settings_frame)

    parent_layout.addWidget(container)
