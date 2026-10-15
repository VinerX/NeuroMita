from ui.widgets.tr_combobox import TRQComboBox
from ui.widgets.settings_section_header import create_settings_header
import os
from PyQt6.QtCore import Qt, QSignalBlocker, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from styles.theme import get_theme
from core.telegram_credentials import (
    telegram_credentials_complete,
    TELEGRAM_CREDENTIAL_KEYS,
)
from ui.widgets.toggle_switch import ToggleSwitch, SettingsSwitch
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QSizePolicy,
    QPushButton,
    QSlider,
    QToolButton,
    QLineEdit,
    QWidget,
)
from ui.gui_templates import (
    create_setting_widget,
    SettingsBodyWidget,
)
from utils import getTranslationVariant as _
from localization.live import tr_set, register
from ui.settings.settings_access import get_setting, set_setting
from ui.settings.voiceover_settings.widgets import (
    VoiceCard,
    VoiceColumns,
    VoiceMethodSelector,
    VoiceStatus,
    voice_label,
)
from ui.settings.voiceover_settings.presentation import (
    OpenAIEngineSettings,
    OpenVoiceAIHub,
    RestartVoiceService,
    StartTelegramVoice,
)

import qtawesome as qta


def build_voiceover_settings_ui(self, parent_layout, *, actions):
    self._voiceover_settings_view_model = actions
    sidebar_w = getattr(self, "SETTINGS_SIDEBAR_WIDTH", 50)
    right_pad = max(8, min(14, int(sidebar_w * 0.22)))

    container = SettingsBodyWidget()
    container.setObjectName("VoiceoverSettingsWorkspace")
    container_lay = QVBoxLayout(container)
    container_lay.setContentsMargins(0, 0, right_pad, 0)
    container_lay.setSpacing(16)
    create_settings_header(container_lay, "voice")
    self.voiceover_status = VoiceStatus()
    self.voiceover_status.setMinimumWidth(300)
    self.voiceover_status.setMaximumWidth(380)
    toolbar = VoiceCard()
    toolbar_row = QHBoxLayout()
    toolbar.body.setContentsMargins(16, 10, 16, 10)
    toolbar_row.setSpacing(20)
    toolbar.body.addLayout(toolbar_row)
    container_lay.addWidget(toolbar)
    columns = VoiceColumns()
    container_lay.addWidget(columns)

    self.voiceover_section = type(
        "obj", (object,), {"content_frame": parent_layout.parent()}
    )()

    use_row = QWidget()
    use_layout = QHBoxLayout(use_row)
    use_layout.setContentsMargins(0, 0, 0, 0)
    use_layout.setSpacing(12)
    self.use_voice_checkbox = SettingsSwitch()
    tr_set(
        self.use_voice_checkbox,
        "Использовать озвучку",
        "Use speech",
        "setAccessibleName",
    )
    if get_setting(self, "USE_VOICEOVER") is None:
        set_setting(self, "USE_VOICEOVER", False)
    self.use_voice_checkbox.setChecked(bool(get_setting(self, "USE_VOICEOVER", False)))
    use_layout.addWidget(self.use_voice_checkbox)
    use_copy = QVBoxLayout()
    use_copy.setSpacing(3)
    use_title = voice_label("Использовать озвучку", "Use speech", "VoiceSettingTitle")
    use_title.setWordWrap(False)
    use_title.setBuddy(self.use_voice_checkbox)
    use_copy.addWidget(use_title)
    self.voice_enabled_hint = QLabel()
    self.voice_enabled_hint.setObjectName("VoiceDescription")
    use_copy.addWidget(self.voice_enabled_hint)
    use_layout.addLayout(use_copy)

    def refresh_voice_hint():
        self.voice_enabled_hint.setText(
            _("Озвучка включена", "Voiceover enabled")
            if self.use_voice_checkbox.isChecked()
            else _("Озвучка выключена", "Voiceover disabled")
        )

    def apply_voice_enabled(value):
        blocker = QSignalBlocker(self.use_voice_checkbox)
        self.use_voice_checkbox.setChecked(bool(value))
        del blocker
        refresh_voice_hint()

    binding = getattr(self, "settings_binding", None)
    if binding is not None:
        binding.bind_two_way(
            "USE_VOICEOVER",
            self.use_voice_checkbox,
            self.use_voice_checkbox.toggled,
            self.use_voice_checkbox.isChecked,
            apply_voice_enabled,
            default=False,
        )
    else:
        self.use_voice_checkbox.toggled.connect(
            lambda enabled: self._save_setting("USE_VOICEOVER", enabled)
        )
    self.use_voice_checkbox.toggled.connect(lambda _enabled: refresh_voice_hint())
    register(self.voice_enabled_hint, lambda _label: refresh_voice_hint())
    refresh_voice_hint()
    toolbar_row.addWidget(use_row)
    self.method_combobox = VoiceMethodSelector(
        get_setting(self, "VOICEOVER_METHOD", "Local")
    )
    self.voice_method_selector = self.method_combobox
    toolbar_row.addWidget(self.method_combobox, 0, Qt.AlignmentFlag.AlignVCenter)
    toolbar_row.addStretch(1)
    toolbar_row.addWidget(self.voiceover_status, 0, Qt.AlignmentFlag.AlignVCenter)
    self.method_combobox.currentTextChanged.connect(
        lambda value: self._save_setting("VOICEOVER_METHOD", value)
    )

    self.tg_settings_frame = VoiceCard(
        "Подключение Telegram",
        "Telegram connection",
        "fa5b.telegram-plane",
        "Синтез через выбранного Telegram-бота.",
        "Synthesis through the selected Telegram bot.",
    )
    tg_layout = self.tg_settings_frame.body

    tg_config = [
        {
            "label": _("Автоподключение Telegram", "Telegram auto-connect"),
            "key": "TG_AUTOCONNECT",
            "type": "checkbutton",
            "default_checkbutton": False,
        },
        {
            "label": _("Подключиться к Telegram", "Connect Telegram"),
            "type": "button",
            "command": (lambda: actions.dispatch(StartTelegramVoice())),
            "widget_name": "tg_connect_button",
        },
        {
            "label": _("Канал/Сервис", "Channel/Service"),
            "key": "AUDIO_BOT",
            "type": "combobox",
            "options": ["@silero_voice_bot", "@CrazyMitaAIbot"],
            "default": "@silero_voice_bot",
        },
        {
            "label": _("Макс. ожидание (сек)", "Max wait (sec)"),
            "key": "SILERO_TIME",
            "type": "entry",
            "default": "12",
            "validation": getattr(self, "validate_number_0_60", None),
        },
        {
            "label": _("Мин. интервал запросов (сек)", "Min request interval (sec)"),
            "key": "TG_MIN_REQUEST_INTERVAL",
            "type": "entry",
            "default": "2",
            "validation": getattr(self, "validate_number_0_60", None),
        },
        {"label": _("Настройки Telegram API", "Telegram API Settings"), "type": "text"},
        {
            "label": _("API ID", "API ID"),
            "widget_name": "tg_api_id",
            "key": "NM_TELEGRAM_API_ID",
            "type": "entry",
            "default": "",
            "hide": bool(self.settings.get("HIDE_PRIVATE")),
        },
        {
            "label": _("API Hash", "API Hash"),
            "widget_name": "tg_api_hash",
            "key": "NM_TELEGRAM_API_HASH",
            "type": "entry",
            "default": "",
            "hide": bool(self.settings.get("HIDE_PRIVATE")),
        },
        {
            "label": _("Номер телефона", "Phone number"),
            "widget_name": "tg_phone",
            "key": "NM_TELEGRAM_PHONE",
            "type": "entry",
            "default": "",
            "hide": bool(self.settings.get("HIDE_PRIVATE")),
        },
    ]

    def connect_telegram():
        values = dict(
            zip(
                TELEGRAM_CREDENTIAL_KEYS,
                (self.tg_api_id.text(), self.tg_api_hash.text(), self.tg_phone.text()),
            )
        )
        if not telegram_credentials_complete(values):
            return
        for key, value in values.items():
            self._save_setting(key, value.strip())
        actions.dispatch(StartTelegramVoice())

    for cfg in tg_config:
        if cfg.get("type") == "button":
            self.tg_connect_button = tr_set(
                QPushButton(), "Подключиться к Telegram", "Connect Telegram"
            )
            self.tg_connect_button.setObjectName("VoicePrimaryAction")
            self.tg_connect_button.setIcon(
                qta.icon("fa5b.telegram-plane", color=get_theme()["text"])
            )
            self.tg_connect_button.clicked.connect(connect_telegram)
            tg_layout.addWidget(self.tg_connect_button)
            continue
        if cfg.get("key") == "NM_TELEGRAM_API_HASH":
            cfg["hide"] = True
        widget = create_setting_widget(
            gui=self,
            parent=self.tg_settings_frame,
            label=cfg["label"],
            setting_key=cfg.get("key", ""),
            widget_type=cfg.get("type", "entry"),
            options=cfg.get("options"),
            default=cfg.get("default", ""),
            validation=cfg.get("validation"),
            hide=cfg.get("hide", False),
            default_checkbutton=cfg.get("default_checkbutton", False),
            command=cfg.get("command"),
            widget_name=cfg.get("widget_name"),
        )
        if widget:
            tg_layout.addWidget(widget)

    tr_set(
        self.tg_api_id,
        "api_id из my.telegram.org",
        "api_id from my.telegram.org",
        "setPlaceholderText",
    )
    tr_set(
        self.tg_api_hash,
        "api_hash из my.telegram.org",
        "api_hash from my.telegram.org",
        "setPlaceholderText",
    )
    tr_set(self.tg_phone, "+79991234567", "+79991234567", "setPlaceholderText")
    self.tg_credentials_hint = voice_label(
        "Для подключения заполните API ID, API Hash и номер вашего Telegram-аккаунта в международном формате.",
        "To connect, enter API ID, API Hash and your Telegram account phone number in international format.",
    )
    tg_layout.addWidget(self.tg_credentials_hint)
    docs = QHBoxLayout()
    for ru, en, url in (
        (
            "Получить API ID и Hash",
            "Get API ID and Hash",
            "https://my.telegram.org/apps",
        ),
        (
            "Инструкция Telegram",
            "Telegram instructions",
            "https://core.telegram.org/api/obtaining_api_id",
        ),
    ):
        button = tr_set(QPushButton(), ru, en)
        button.setIcon(qta.icon("fa5s.external-link-alt", color=get_theme()["muted"]))
        button.clicked.connect(
            lambda _checked, target=url: QDesktopServices.openUrl(QUrl(target))
        )
        docs.addWidget(button)
    tg_layout.addLayout(docs)

    def sync_telegram_credentials():
        complete = telegram_credentials_complete(
            {
                "NM_TELEGRAM_API_ID": self.tg_api_id.text(),
                "NM_TELEGRAM_API_HASH": self.tg_api_hash.text(),
                "NM_TELEGRAM_PHONE": self.tg_phone.text(),
            }
        )
        self.tg_credentials_hint.setVisible(not complete)
        self.tg_connect_button.setEnabled(
            complete
            and self.use_voice_checkbox.isChecked()
            and self.method_combobox.currentText() == "TG"
            and not self.tg_connect_button.property("connectionLocked")
        )

    def clear_empty_credential(key, field):
        if not field.text().strip():
            self._save_setting(key, "")

    for key, field in zip(
        TELEGRAM_CREDENTIAL_KEYS, (self.tg_api_id, self.tg_api_hash, self.tg_phone)
    ):
        field.textChanged.connect(lambda _text: sync_telegram_credentials())
        field.editingFinished.connect(
            lambda setting_key=key, edit=field: clear_empty_credential(
                setting_key, edit
            )
        )
    self.use_voice_checkbox.toggled.connect(
        lambda _checked: sync_telegram_credentials()
    )
    self.method_combobox.currentTextChanged.connect(
        lambda _method: sync_telegram_credentials()
    )
    sync_telegram_credentials()

    columns.left_layout.addWidget(self.tg_settings_frame)

    self.local_settings_frame = VoiceCard(
        "Локальный движок озвучки",
        "Local voice engine",
        "fa5s.microchip",
        "Выберите установленную модель и способ её загрузки.",
        "Choose an installed model and when to load it.",
    )
    self.local_settings_frame.setProperty("requiresLocalVoice", True)
    local_layout = self.local_settings_frame.body

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
    label_container.setSizePolicy(
        QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
    )

    self.local_voice_combobox = TRQComboBox()
    self.local_voice_empty_status = QLabel(
        _(
            'Нет установленных моделей. <a href="install">Установить</a>',
            'No installed models. <a href="install">Install</a>',
        )
    )
    self.local_voice_empty_status.setObjectName("SeparatorLabel")
    self.local_voice_empty_status.setTextFormat(Qt.TextFormat.RichText)
    self.local_voice_empty_status.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextBrowserInteraction
    )
    self.local_voice_empty_status.setOpenExternalLinks(False)
    self.local_voice_empty_status.linkActivated.connect(
        lambda _href: actions.dispatch(OpenVoiceAIHub())
    )
    self.local_voice_empty_status.setVisible(False)

    self.local_model_settings_btn = QPushButton()
    self.local_model_settings_btn.setObjectName("VoiceModelSettingsButton")
    self.local_model_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.local_model_settings_btn.setFixedSize(38, 38)
    self.local_model_settings_btn.setToolTip(_("Настройки модели", "Model settings"))
    if qta is not None:
        try:
            self.local_model_settings_btn.setIcon(qta.icon("fa5s.cog", color="#cccccc"))
        except Exception:
            self.local_model_settings_btn.setText("")
    else:
        self.local_model_settings_btn.setText("")

    def _open_current_model_settings():
        mid = None
        if self.local_voice_combobox is not None:
            mid = self.local_voice_combobox.currentData()
        if not mid:
            mid = self.settings.get("NM_CURRENT_VOICEOVER")
        mid = str(mid or "").strip()
        actions.dispatch(OpenVoiceAIHub(mid or None))

    self.local_model_settings_btn.clicked.connect(_open_current_model_settings)

    self.local_model_action_btn = QPushButton()
    self.local_model_action_btn.setObjectName("VoicePrimaryAction")
    self.local_model_action_btn.setIcon(
        qta.icon("fa5s.play", color=get_theme()["text"])
    )
    self.local_model_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.local_model_action_btn.setVisible(False)

    local_model_layout.addWidget(label_container)
    local_model_layout.addWidget(self.local_voice_combobox, 1)
    local_model_layout.addWidget(self.local_voice_empty_status, 1)
    local_model_layout.addWidget(self.local_model_settings_btn, 0)
    local_layout.addWidget(local_model_row)

    status_row = SettingsBodyWidget()
    status_layout = QHBoxLayout(status_row)
    status_layout.setContentsMargins(0, 0, 0, 0)
    status_layout.setSpacing(8)

    self.local_model_status_chip = QLabel()
    self.local_model_status_chip.setObjectName("VoiceModelStatusChip")
    self.local_model_status_chip.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
    )

    status_layout.addWidget(self.local_model_status_chip)
    status_layout.addStretch(1)
    self.local_status_frame = VoiceCard(
        "Состояние модели",
        "Model state",
        "fa5s.check-circle",
        "Готовность выбранной модели к синтезу.",
        "Readiness of the selected model for synthesis.",
    )
    self.local_status_frame.setProperty("requiresLocalVoice", True)
    self.local_status_frame.body.addWidget(status_row)
    self.local_status_frame.body.addWidget(self.local_model_action_btn)
    self.local_status_frame.body.addWidget(
        voice_label(
            "Параметры синтеза и голоса — в настройках выбранной модели.",
            "Synthesis and voice options are in the selected model settings.",
        )
    )
    columns.right_layout.addWidget(self.local_status_frame)
    self.telegram_status_frame = VoiceCard(
        "Состояние подключения", "Connection state", "fa5b.telegram-plane"
    )
    self.telegram_status = VoiceStatus()
    self.telegram_status_frame.body.addWidget(self.telegram_status)
    self.telegram_status_frame.body.addWidget(
        voice_label(
            "При первом подключении Telegram запросит код входа.",
            "Telegram will request a login code on the first connection.",
        )
    )
    columns.right_layout.addWidget(self.telegram_status_frame)

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
    self.local_volume_value_label.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )

    def _on_volume_changed(value):
        self.local_volume_value_label.setText(f"{int(value)}%")
        if not self.local_volume_slider.isSliderDown():
            self._save_setting("VOICEOVER_LOCAL_VOLUME", int(value))

    def _on_volume_released():
        self._save_setting(
            "VOICEOVER_LOCAL_VOLUME", int(self.local_volume_slider.value())
        )

    self.local_volume_slider.valueChanged.connect(_on_volume_changed)
    self.local_volume_slider.sliderReleased.connect(_on_volume_released)

    volume_layout.addWidget(volume_label)
    volume_layout.addWidget(self.local_volume_slider, 1)
    volume_layout.addWidget(self.local_volume_value_label, 0)
    self.playback_settings_frame = VoiceCard(
        "Вывод и громкость", "Playback and volume", "fa5s.volume-up"
    )
    playback_layout = self.playback_settings_frame.body
    playback_layout.addWidget(volume_row)
    playback_layout.addWidget(
        create_setting_widget(
            gui=self,
            parent=self.playback_settings_frame,
            label=_("Озвучивать в чате", "Voiceover in chat"),
            setting_key="VOICEOVER_LOCAL_CHAT",
            widget_type="checkbutton",
            default_checkbutton=True,
        )
    )

    local_config = [
        {
            "label": _("Язык локальной озвучки", "Local Voice Language"),
            "key": "VOICE_LANGUAGE",
            "type": "combobox",
            "options": ["ru", "en"],
            "default": "ru",
            "widget_name": "voice_language_var",
        },
        {
            "label": _("Автозагрузка модели", "Autoload model"),
            "key": "LOCAL_VOICE_LOAD_LAST",
            "type": "checkbutton",
            "default_checkbutton": False,
        },
        {
            "label": _(
                "Инициализировать модель при запросе", "Initialize model on request"
            ),
            "key": "LOCAL_VOICE_INIT_ON_REQUEST",
            "type": "checkbutton",
            "default_checkbutton": False,
        },
        {
            "label": _("Перезапустить озвучку", "Restart voice service"),
            "action": "restart",
            "type": "button",
            "command": (lambda: actions.dispatch(RestartVoiceService())),
        },
        {
            "label": _("Перейти к настройкам ИИ-движка", "Open AI Engine settings"),
            "type": "button",
            "command": (lambda: actions.dispatch(OpenAIEngineSettings())),
        },
    ]
    if os.environ.get("ENABLE_VOICE_DELETE_CHECKBOX", "0") == "1":
        local_config.insert(
            2,
            {
                "label": _("Удалять аудио", "Delete audio"),
                "key": "LOCAL_VOICE_DELETE_AUDIO",
                "type": "checkbutton",
                "default_checkbutton": True,
            },
        )

    for cfg in local_config:
        if cfg.get("type") == "button":
            restart = cfg.get("action") == "restart"
            button = tr_set(
                QPushButton(),
                "Перезапустить озвучку" if restart else "Настройки ИИ-движка",
                "Restart voice service" if restart else "AI engine settings",
            )
            button.setIcon(
                qta.icon(
                    "fa5s.sync-alt" if restart else "fa5s.microchip",
                    color=get_theme()["text"],
                )
            )
            button.clicked.connect(cfg["command"])
            local_layout.addWidget(button)
            continue
        widget = create_setting_widget(
            gui=self,
            parent=self.local_settings_frame,
            label=cfg.get("label"),
            setting_key=cfg.get("key", ""),
            widget_type=cfg.get("type", "entry"),
            options=cfg.get("options"),
            default=cfg.get("default", ""),
            default_checkbutton=cfg.get("default_checkbutton", False),
            command=cfg.get("command"),
            widget_name=cfg.get("widget_name"),
        )
        if widget:
            local_layout.addWidget(widget)

    columns.left_layout.addWidget(self.local_settings_frame)

    from ui.settings.voiceover_settings.remote_api import RemoteVoiceSettingsWidget

    self.api_settings_frame = VoiceCard(
        "Профиль API озвучки",
        "Voice API profile",
        "fa5s.cloud",
        "Подключение к провайдеру и голоса персонажей.",
        "Provider connection and character voices.",
    )
    remote_widget = RemoteVoiceSettingsWidget(actions.remote, detached_preview=True)
    self.api_settings_frame.body.addWidget(remote_widget)
    self.api_preview_frame = remote_widget.preview_panel
    columns.left_layout.addWidget(self.api_settings_frame)
    columns.right_layout.addWidget(self.api_preview_frame)
    columns.right_layout.addWidget(self.playback_settings_frame)

    def sync_mode(method):
        self.tg_settings_frame.setVisible(method == "TG")
        self.local_settings_frame.setVisible(method == "Local")
        self.local_status_frame.setVisible(method == "Local")
        self.telegram_status_frame.setVisible(method == "TG")
        self.api_settings_frame.setVisible(method == "API")
        self.api_preview_frame.setVisible(method == "API")
        self.playback_settings_frame.setVisible(method in {"Local", "API"})

    binding = getattr(self, "settings_binding", None)
    if binding is not None:

        def apply_method(value):
            blocker = QSignalBlocker(self.method_combobox)
            self.method_combobox.setCurrentText(str(value or "Local"))
            del blocker
            sync_mode(self.method_combobox.currentText())

        binding.bind("VOICEOVER_METHOD", self.method_combobox, apply_method)
    self.method_combobox.currentTextChanged.connect(sync_mode)
    sync_mode(self.method_combobox.currentText())
    container_lay.addStretch(1)
    for reveal in container.findChildren(QToolButton):
        if reveal.isCheckable() and reveal.parentWidget().findChild(QLineEdit):
            reveal.setText("")
            reveal.setIcon(qta.icon("fa5s.eye", color=get_theme()["muted"]))
            reveal.toggled.connect(
                lambda checked, button=reveal: button.setIcon(
                    qta.icon(
                        "fa5s.eye-slash" if checked else "fa5s.eye",
                        color=get_theme()["muted"],
                    )
                )
            )
    for switch in container.findChildren(ToggleSwitch):
        switch._ON_TRACK = QColor(get_theme()["accent"])
        switch.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        row = switch.parentWidget()
        label = row.findChild(QLabel) if row else None
        if label is not None:
            switch.setAccessibleName(label.text())
            label.setBuddy(switch)
    parent_layout.addWidget(container)
