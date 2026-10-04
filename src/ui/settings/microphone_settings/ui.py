from ui.widgets.settings_section_header import create_settings_header
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QSizePolicy,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
)
import qtawesome as qta

from localization.live import tr_set, register
from localization import translate as _
from styles.theme import get_theme
from handlers.asr_input_gate import normalize_input_mode
from ui.settings.microphone_settings.widgets import (
    MicrophoneDeviceComboBox,
    MicrophoneLevelMeter,
    ResponsiveColumns,
    MicrophoneSwitch,
    MicrophoneCheckBox,
    RecognitionStatusBadge,
)
from controllers.gui.microphone_monitor_controller import MicrophoneMonitorController


def _label(ru, en, name="ASRDescription"):
    label = tr_set(QLabel(), ru, en)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _icon(name, size=22):
    label = QLabel()
    label.setObjectName("ASRIcon")
    label.setPixmap(qta.icon(name, color=get_theme()["accent"]).pixmap(size, size))
    label.setFixedSize(size + 16, size + 16)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _button(ru, en, icon=None):
    button = tr_set(QPushButton(), ru, en)
    button.setObjectName("ASRAction")
    if icon:
        button.setIcon(qta.icon(icon, color=get_theme()["text"]))
    return button


def _refresh(ru, en):
    button = _button("", "", "fa5s.sync-alt")
    button.setFixedSize(34, 34)
    tr_set(button, ru, en, "setToolTip")
    return button


def _card(title=None, english=None, icon=None):
    card = QFrame()
    card.setObjectName("ASRCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(9)
    if title:
        header = QHBoxLayout()
        header.setSpacing(8)
        if icon:
            header.addWidget(_icon(icon, 18))
        header.addWidget(_label(title, english, "ASRCardTitle"), 1)
        layout.addLayout(header)
    return card, layout


def _row(ru, en, hint_ru, hint_en, field, icon):
    row = QFrame()
    row.setObjectName("ASRSettingRow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(10)
    layout.addWidget(_icon(icon, 18))
    copy = QVBoxLayout()
    copy.setSpacing(3)
    copy.addWidget(_label(ru, en, "ASRSettingTitle"))
    copy.addWidget(_label(hint_ru, hint_en))
    layout.addLayout(copy, 1)
    layout.addWidget(field)
    return row


def _top_field(ru, en, field):
    widget = QWidget()
    widget.setObjectName("ASRTransparent")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(7)
    layout.addWidget(_label(ru, en))
    layout.addWidget(field)
    return widget


def build_microphone_settings_ui(self, parent_layout):
    root = QWidget()
    root.setObjectName("MicrophoneSettingsWorkspace")
    self.microphone_workspace = root
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)
    create_settings_header(layout, "microphone")

    strip, strip_layout = _card()
    self.mic_active_checkbox = MicrophoneSwitch()
    self.mic_active_checkbox.setChecked(bool(self.settings.get("MIC_ACTIVE", False)))
    tr_set(
        self.mic_active_checkbox,
        "Включить/выключить распознавание",
        "Enable/disable recognition",
        "setToolTip",
    )
    tr_set(
        self.mic_active_checkbox,
        "Микрофон активен",
        "Microphone active",
        "setAccessibleName",
    )
    active = QWidget()
    active.setObjectName("ASRTransparent")
    active_layout = QHBoxLayout(active)
    active_layout.setContentsMargins(0, 0, 0, 0)
    active_layout.setSpacing(12)
    active_layout.addWidget(self.mic_active_checkbox)
    active_copy = QVBoxLayout()
    active_copy.setSpacing(3)
    active_copy.addWidget(
        _label("Микрофон активен", "Microphone active", "ASRSettingTitle")
    )
    active_hint = QLabel()
    active_hint.setObjectName("ASRDescription")
    active_copy.addWidget(active_hint)
    active_layout.addLayout(active_copy)

    def refresh_active_hint():
        active_hint.setProperty("micEnabled", self.mic_active_checkbox.isChecked())
        active_hint.setText(
            _("Распознавание включено", "Recognition enabled")
            if self.mic_active_checkbox.isChecked()
            else _("Распознавание выключено", "Recognition disabled")
        )

    self.mic_active_checkbox.toggled.connect(lambda _checked: refresh_active_hint())
    register(
        active_hint,
        lambda label: label.setText(
            _("Распознавание включено", "Recognition enabled")
            if label.property("micEnabled")
            else _("Распознавание выключено", "Recognition disabled")
        ),
    )
    refresh_active_hint()

    self.recognizer_combobox = QComboBox()
    self.recognizer_combobox.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    self.recognizer_combobox.setMinimumContentsLength(8)
    self.asr_refresh_button = _refresh("Обновить список моделей", "Refresh model list")
    engine = QWidget()
    eng = QHBoxLayout(engine)
    eng.setContentsMargins(0, 0, 0, 0)
    eng.addWidget(self.recognizer_combobox, 1)
    eng.addWidget(self.asr_refresh_button)
    self.asr_models_empty_status = _label(
        "Нет установленных моделей", "No installed models"
    )
    self.asr_models_empty_status.hide()
    eng.addWidget(self.asr_models_empty_status, 1)

    self.mic_combobox = MicrophoneDeviceComboBox()
    self.mic_refresh_button = _refresh(
        "Обновить список микрофонов", "Refresh microphone list"
    )
    mic = QWidget()
    mh = QHBoxLayout(mic)
    mh.setContentsMargins(0, 0, 0, 0)
    mh.addWidget(self.mic_combobox, 1)
    mh.addWidget(self.mic_refresh_button)

    self.asr_status_badge = RecognitionStatusBadge()
    self.asr_init_status = self.asr_status_badge.label
    self.asr_restart_button = _button("Перезапустить", "Restart", "fa5s.redo-alt")
    self.asr_restart_button.setObjectName("ASRRestart")
    self.asr_restart_button.setFixedHeight(38)
    tr_set(
        self.asr_restart_button,
        "Перезапустить распознавание",
        "Restart speech recognition",
        "setToolTip",
    )
    self.asr_restart_button.setEnabled(bool(self.settings.get("MIC_ACTIVE", False)))
    status = QWidget()
    sh = QHBoxLayout(status)
    sh.setContentsMargins(0, 0, 0, 0)
    sh.addWidget(self.asr_status_badge)
    self.asr_manage_button = _button("Каталог моделей", "Model catalog", "fa5s.cubes")
    self.asr_manage_button.setFixedHeight(38)
    self.asr_manage_button.setObjectName("ASRModelCatalog")
    eng.insertWidget(2, self.asr_manage_button)
    status_caption = _label("Статус", "Status")
    sh.insertWidget(0, status_caption)
    sh.setSpacing(9)
    actions = QWidget()
    actions.setObjectName("ASRTransparent")
    toolbar = QHBoxLayout(actions)
    toolbar.setContentsMargins(0, 0, 0, 0)
    toolbar.setSpacing(20)
    toolbar.addStretch(1)
    toolbar.addWidget(status)
    toolbar.addWidget(self.asr_restart_button)
    strip_layout.addWidget(
        ResponsiveColumns([active, actions], breakpoint=760, weights=[1, 2])
    )
    separator = QFrame()
    separator.setObjectName("ASRToolbarSeparator")
    separator.setFixedHeight(1)
    strip_layout.addWidget(separator)
    self.recognizer_combobox.setObjectName("ASRToolbarInput")
    self.mic_combobox.setObjectName("ASRToolbarInput")
    self.asr_refresh_button.setObjectName("ASRToolbarRefresh")
    self.mic_refresh_button.setObjectName("ASRToolbarRefresh")
    self.recognizer_combobox.setFixedHeight(38)
    self.mic_combobox.setFixedHeight(38)
    self.asr_refresh_button.setFixedSize(38, 38)
    self.mic_refresh_button.setFixedSize(38, 38)
    eng.setSpacing(8)
    mh.setSpacing(8)
    strip_layout.addWidget(
        ResponsiveColumns(
            [
                _top_field("Модель распознавания", "Recognition model", engine),
                _top_field("Устройство ввода", "Input device", mic),
            ],
            breakpoint=760,
            weights=[3, 4],
        )
    )
    layout.addWidget(strip)

    behavior, behavior_layout = _card(
        "Поведение и отправка", "Behavior and sending", "fa5s.sliders-h"
    )
    switches = [
        (
            "mic_instant_checkbox",
            "MIC_INSTANT_SENT",
            False,
            "Мгновенная отправка",
            "Instant send",
            "Отправлять распознанный текст сразу.",
            "Send recognized text immediately.",
            "fa5s.bolt",
        ),
        (
            "mic_instant_delay_checkbox",
            "MIC_INSTANT_SEND_DELAY_ENABLED",
            False,
            "Отправлять с паузой",
            "Send after pause",
            "Новая речь или печать перезапускает отсчёт.",
            "New speech or typing restarts the countdown.",
            "fa5s.clock",
        ),
        (
            "mic_instant_merge_input_checkbox",
            "MIC_INSTANT_MERGE_CHAT_INPUT",
            True,
            "Добавлять текст из чата",
            "Include chat text",
            "Объединять речь с текстом в поле ввода.",
            "Combine speech with the typed chat input.",
            "fa5s.comment-dots",
        ),
        (
            "mic_mute_while_speaking_checkbox",
            "MIC_MUTE_WHILE_SPEAKING",
            True,
            "Приостанавливать распознавание, пока Мита говорит",
            "Pause recognition while Mita speaks",
            "Не распознавать речь во время ответа Миты.",
            "Ignore speech while Mita is replying.",
            "fa5s.pause",
        ),
    ]
    for attr, key, default, ru, en, hint_ru, hint_en, icon in switches:
        checkbox = MicrophoneCheckBox()
        checkbox.setChecked(bool(self.settings.get(key, default)))
        tr_set(checkbox, ru, en, "setAccessibleName")
        tr_set(checkbox, hint_ru, hint_en, "setToolTip")
        setattr(self, attr, checkbox)
        behavior_layout.addWidget(_row(ru, en, hint_ru, hint_en, checkbox, icon))
        if key == "MIC_INSTANT_SEND_DELAY_ENABLED":
            self.mic_instant_delay_spin = QDoubleSpinBox()
            self.mic_instant_delay_spin.setRange(0.5, 30)
            self.mic_instant_delay_spin.setValue(
                float(self.settings.get("MIC_INSTANT_SEND_DELAY_SEC", 3.0) or 3.0)
            )
            self.mic_instant_delay_spin.setDecimals(1)
            self.mic_instant_delay_spin.setSingleStep(0.5)
            self.mic_instant_delay_spin.setFixedWidth(110)
            self.mic_instant_delay_row = _row(
                "Пауза до отправки",
                "Pause before send",
                "В секундах",
                "In seconds",
                self.mic_instant_delay_spin,
                "fa5s.hourglass-half",
            )
            self.mic_instant_delay_row.setVisible(checkbox.isChecked())
            checkbox.toggled.connect(self.mic_instant_delay_row.setVisible)
            behavior_layout.addWidget(self.mic_instant_delay_row)

    self.asr_input_mode_combobox = QComboBox()
    self.asr_input_mode_combobox.addItem(
        _("Рация — включать кнопкой", "Radio — start with a button"), "radio"
    )
    self.asr_input_mode_combobox.addItem(_("Слушать постоянно", "Always listen"), "vad")
    self.asr_input_mode_combobox.addItem("Push-to-talk", "ptt")
    self.asr_input_mode_combobox.setCurrentIndex(
        self.asr_input_mode_combobox.findData(
            normalize_input_mode(self.settings.get("ASR_INPUT_MODE", "radio"))
        )
    )
    register(
        self.asr_input_mode_combobox,
        lambda w: (
            w.setItemText(
                0, _("Рация — включать кнопкой", "Radio — start with a button")
            ),
            w.setItemText(1, _("Слушать постоянно", "Always listen")),
        ),
    )
    behavior_layout.addWidget(
        _row(
            "Режим ввода",
            "Input mode",
            "Способ активации распознавания речи.",
            "How speech recognition is activated.",
            self.asr_input_mode_combobox,
            "fa5s.keyboard",
        )
    )
    behavior_layout.addStretch(1)

    recognition, recognition_layout = _card(
        "Параметры распознавания", "Recognition parameters", "fa5s.wave-square"
    )
    params = [
        (
            "vad_sample_rate_spinbox",
            "VOSK_SAMPLE_RATE",
            16000,
            16000,
            16000,
            1000,
            0,
            "Sample rate",
            "Sample rate",
            "Фиксированная частота: 16000 Гц.",
            "Fixed sample rate: 16000 Hz.",
            "fa5s.wave-square",
        ),
        (
            "vad_chunk_size_spinbox",
            "CHUNK_SIZE",
            128,
            4096,
            512,
            128,
            0,
            "Chunk size",
            "Chunk size",
            "Размер аудиоблока в сэмплах.",
            "Audio block size in samples.",
            "fa5s.database",
        ),
        (
            "vad_threshold_spinbox",
            "VAD_THRESHOLD",
            0,
            1,
            0.5,
            0.05,
            2,
            "VAD threshold",
            "VAD threshold",
            "Порог голосовой активности.",
            "Voice activity threshold.",
            "fa5s.wave-square",
        ),
        (
            "vad_silence_timeout_spinbox",
            "VAD_SILENCE_TIMEOUT_SEC",
            0.05,
            10,
            0.6,
            0.05,
            2,
            "Тишина (сек)",
            "Silence (sec)",
            "Пауза для окончания фразы. Менее 0,4 с может обрезать речь.",
            "Pause ending a phrase. Below 0.4 s may cut speech short.",
            "fa5s.clock",
        ),
        (
            "vad_pre_buffer_spinbox",
            "VAD_PRE_BUFFER_DURATION_SEC",
            0,
            5,
            0.4,
            0.05,
            2,
            "Pre-buffer (сек)",
            "Pre-buffer (sec)",
            "Аудио до начала речи.",
            "Audio before speech begins.",
            "fa5s.backward",
        ),
        (
            "vad_max_speech_duration_spinbox",
            "MAX_SPEECH_DURATION_SEC",
            1,
            120,
            30,
            1,
            1,
            "Макс. речь (сек)",
            "Max speech (sec)",
            "Максимальная длительность одной фразы.",
            "Maximum duration of one phrase.",
            "fa5s.hourglass-end",
        ),
        (
            "vad_min_speech_duration_spinbox",
            "MIN_SPEECH_DURATION_SEC",
            0,
            3,
            0.35,
            0.05,
            2,
            "Мин. речь (сек)",
            "Min speech (sec)",
            "Отсеивать щелчки и короткие звуки. 0 — отключить.",
            "Filter clicks and short sounds. 0 disables the filter.",
            "fa5s.filter",
        ),
    ]
    for (
        attr,
        key,
        minimum,
        maximum,
        default,
        step,
        decimals,
        ru,
        en,
        hint_ru,
        hint_en,
        icon,
    ) in params:
        field = QDoubleSpinBox() if decimals else QSpinBox()
        field.setRange(minimum, maximum)
        field.setValue(default)
        field.setSingleStep(step)
        if decimals:
            field.setDecimals(decimals)
        field.setFixedWidth(110)
        field.setEnabled(minimum != maximum)
        tr_set(field, hint_ru, hint_en, "setToolTip")
        setattr(self, attr, field)
        recognition_layout.addWidget(_row(ru, en, hint_ru, hint_en, field, icon))
    buttons = QHBoxLayout()
    self.vad_apply_button = _button("Применить", "Apply", "fa5s.check")
    self.vad_reset_button = _button("Сбросить", "Reset", "fa5s.undo")
    buttons.addWidget(self.vad_apply_button, 1)
    buttons.addWidget(self.vad_reset_button, 1)
    recognition_layout.addLayout(buttons)
    layout.addWidget(ResponsiveColumns([behavior, recognition], breakpoint=850))

    monitor, monitor_layout = _card()
    monitor_header = QHBoxLayout()
    monitor_header.addWidget(_icon("fa5s.microphone", 22))
    copy = QVBoxLayout()
    copy.addWidget(_label("Уровень микрофона", "Microphone level", "ASRCardTitle"))
    copy.addWidget(
        _label(
            "Во время теста вы слышите себя. Распознавание временно приостановлено.",
            "During the test you hear yourself. Recognition is temporarily paused.",
        )
    )
    monitor_header.addLayout(copy, 1)
    self.mic_test_button = _button(
        "Проверить микрофон", "Test microphone", "fa5s.headphones"
    )
    self.mic_test_button.setCheckable(True)
    monitor_header.addWidget(self.mic_test_button)
    monitor_layout.addLayout(monitor_header)
    self.mic_level_meter = MicrophoneLevelMeter()
    monitor_layout.addWidget(self.mic_level_meter)
    self.mic_test_device_label = QLabel()
    self.mic_test_device_label.setObjectName("ASRDescription")
    self.mic_test_device_label.setWordWrap(True)
    monitor_layout.addWidget(self.mic_test_device_label)
    layout.addWidget(monitor)
    self.mic_monitor_controller = MicrophoneMonitorController(
        root,
        self.mic_combobox,
        self.mic_test_button,
        self.mic_test_device_label,
        self.mic_level_meter,
    )
    parent_layout.addWidget(root)
