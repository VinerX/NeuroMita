# src/ui/settings/microphone_settings/ui.py
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QSizePolicy, QCheckBox, QSpinBox, QDoubleSpinBox,
    QAbstractSpinBox,
)
import qtawesome as qta

from ui.gui_templates import create_section_header, SettingsBodyWidget
from utils import getTranslationVariant as _
from localization.live import register_if_tr, tr_set


def make_row(label_text: str, field_widget: QWidget, label_w: int) -> QWidget:
    """
    Унифицированная строка настроек: метка слева, виджет справа.
    """
    row = SettingsBodyWidget()
    hl = QHBoxLayout(row)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(6)

    lbl = QLabel(label_text)
    register_if_tr(lbl, label_text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    lbl.setFixedWidth(label_w)
    hl.addWidget(lbl, 0)

    hl.addWidget(field_widget, 1)
    return row


def build_microphone_settings_ui(self, parent_layout):
    create_section_header(parent_layout, _("Настройки микрофона", "Microphone Settings"))

    overlay_w = getattr(self, "SETTINGS_PANEL_WIDTH", 400)
    label_w = max(90, min(120, int(overlay_w * 0.3)))
    self.mic_label_width = label_w

    root = SettingsBodyWidget()
    root_lay = QVBoxLayout(root)
    root_lay.setContentsMargins(0, 0, 0, 0)
    root_lay.setSpacing(6)

    # 0) Включение ASR — сразу под заголовком, чтобы было на виду
    self.mic_active_checkbox = QCheckBox("")
    self.mic_active_checkbox.setChecked(bool(self.settings.get("MIC_ACTIVE")))
    tr_set(self.mic_active_checkbox, "Включить/выключить распознавание", "Enable/disable recognition", "setToolTip")
    root_lay.addWidget(make_row(_("Микрофон активен", "Microphone active"), self.mic_active_checkbox, label_w))

    # 1) Кнопка в глоссарий
    self.asr_manage_button = tr_set(QPushButton(), "Перейти к настройкам AI Engine", "Open AI Engine settings")
    self.asr_manage_button.setObjectName("SecondaryButton")
    self.asr_manage_button.setIcon(qta.icon("fa6s.microchip", color="#ffffff"))
    self.asr_manage_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # 2) Доступные (установленные) модели + refresh
    engine_field = SettingsBodyWidget()
    eng_h = QHBoxLayout(engine_field)
    eng_h.setContentsMargins(0, 0, 0, 0)
    eng_h.setSpacing(6)

    self.recognizer_combobox = QComboBox()
    self.recognizer_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    tr_set(self.recognizer_combobox, "Установленные модели распознавания", "Installed speech recognition models", "setToolTip")
    eng_h.addWidget(self.recognizer_combobox, 1)

    self.asr_models_empty_status = tr_set(
        QLabel(),
        "Нет установленных моделей",
        "No installed models",
    )
    self.asr_models_empty_status.setObjectName("SeparatorLabel")
    self.asr_models_empty_status.setVisible(False)
    eng_h.addWidget(self.asr_models_empty_status, 1)

    self.asr_refresh_button = QPushButton()
    self.asr_refresh_button.setObjectName("SecondaryButton")
    self.asr_refresh_button.setIcon(qta.icon("fa5s.sync", color="#ffffff"))
    tr_set(self.asr_refresh_button, "Обновить список моделей", "Refresh model list", "setToolTip")
    self.asr_refresh_button.setFixedSize(28, 26)
    eng_h.addWidget(self.asr_refresh_button, 0)

    root_lay.addWidget(make_row(_("Модель", "Model"), engine_field, label_w))
    root_lay.addWidget(self.asr_manage_button, 0)

    # 3) Текущий микрофон + refresh
    mic_field = SettingsBodyWidget()
    mic_h = QHBoxLayout(mic_field)
    mic_h.setContentsMargins(0, 0, 0, 0)
    mic_h.setSpacing(6)

    self.mic_combobox = QComboBox()
    self.mic_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    mic_h.addWidget(self.mic_combobox, 1)

    self.mic_refresh_button = QPushButton()
    self.mic_refresh_button.setObjectName("SecondaryButton")
    self.mic_refresh_button.setIcon(qta.icon("fa5s.sync", color="#ffffff"))
    tr_set(self.mic_refresh_button, "Обновить список микрофонов", "Refresh microphone list", "setToolTip")
    self.mic_refresh_button.setFixedSize(28, 26)
    mic_h.addWidget(self.mic_refresh_button, 0)

    root_lay.addWidget(make_row(_("Микрофон", "Microphone"), mic_field, label_w))

    # 4) Управление
    self.mic_instant_checkbox = QCheckBox("")
    self.mic_instant_checkbox.setChecked(bool(self.settings.get("MIC_INSTANT_SENT")))
    tr_set(self.mic_instant_checkbox, "Мгновенная отправка распознанного текста", "Send recognized text immediately", "setToolTip")
    root_lay.addWidget(make_row(_("Мгновенная отправка", "Instant send"), self.mic_instant_checkbox, label_w))

    self.mic_instant_merge_input_checkbox = QCheckBox("")
    self.mic_instant_merge_input_checkbox.setChecked(bool(self.settings.get("MIC_INSTANT_MERGE_CHAT_INPUT", True)))
    tr_set(
        self.mic_instant_merge_input_checkbox,
        "При мгновенной отправке добавлять текст из поля ввода",
        "On instant send, include the typed chat input",
        "setToolTip",
    )
    root_lay.addWidget(
        make_row(
            _("Добавлять текст из чата", "Include chat text"),
            self.mic_instant_merge_input_checkbox,
            label_w,
        )
    )

    self.mic_mute_while_speaking_checkbox = QCheckBox("")
    self.mic_mute_while_speaking_checkbox.setChecked(bool(self.settings.get("MIC_MUTE_WHILE_SPEAKING", True)))
    self.mic_mute_while_speaking_checkbox.setToolTip(_(
        "Не засчитывать распознанное, пока Мита говорит (чтобы её голос из колонок не улетал в чат)",
        "Ignore recognized speech while Mita is talking (so her voice from the speakers isn't sent to chat)"
    ))
    root_lay.addWidget(make_row(_("Не слышать Миту", "Ignore Mita's voice"), self.mic_mute_while_speaking_checkbox, label_w))

    # 5) Статус (как раньше) — под кнопками
    self.asr_init_status = QLabel("—")
    root_lay.addWidget(make_row(_("Статус", "Status"), self.asr_init_status, label_w))

    # 6) VAD параметры
    create_section_header(root_lay, _("Параметры распознавания", "Recognition Parameters"))

    def _spinbox(min_val, max_val, default, step=1):
        sb = QSpinBox()
        sb.setRange(min_val, max_val)
        sb.setValue(default)
        sb.setSingleStep(step)
        sb.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return sb

    def _dspinbox(min_val, max_val, default, step, decimals=2):
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setValue(default)
        sb.setSingleStep(step)
        sb.setDecimals(decimals)
        sb.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return sb

    self.vad_sample_rate_spinbox = _spinbox(8000, 48000, 16000, 1000)
    tr_set(self.vad_sample_rate_spinbox, "Частота дискретизации (Гц)", "Sample rate (Hz)", "setToolTip")
    root_lay.addWidget(make_row(_("Sample rate", "Sample rate"), self.vad_sample_rate_spinbox, label_w))

    self.vad_chunk_size_spinbox = _spinbox(128, 4096, 512, 128)
    tr_set(self.vad_chunk_size_spinbox, "Размер чанка аудио", "Audio chunk size", "setToolTip")
    root_lay.addWidget(make_row(_("Chunk size", "Chunk size"), self.vad_chunk_size_spinbox, label_w))

    self.vad_threshold_spinbox = _dspinbox(0.0, 1.0, 0.5, 0.05)
    tr_set(self.vad_threshold_spinbox, "Порог VAD (0.0–1.0)", "VAD threshold (0.0–1.0)", "setToolTip")
    root_lay.addWidget(make_row(_("VAD threshold", "VAD threshold"), self.vad_threshold_spinbox, label_w))

    self.vad_silence_timeout_spinbox = _dspinbox(0.05, 10.0, 0.15, 0.05)
    tr_set(self.vad_silence_timeout_spinbox, "Таймаут тишины (сек)", "Silence timeout (sec)", "setToolTip")
    root_lay.addWidget(make_row(_("Тишина (сек)", "Silence (sec)"), self.vad_silence_timeout_spinbox, label_w))

    self.vad_pre_buffer_spinbox = _dspinbox(0.0, 5.0, 0.3, 0.05)
    tr_set(self.vad_pre_buffer_spinbox, "Предбуфер (сек)", "Pre-buffer (sec)", "setToolTip")
    root_lay.addWidget(make_row(_("Pre-buffer (сек)", "Pre-buffer (sec)"), self.vad_pre_buffer_spinbox, label_w))

    self.vad_max_speech_duration_spinbox = _dspinbox(1.0, 120.0, 30.0, 1.0, decimals=1)
    tr_set(self.vad_max_speech_duration_spinbox, "Макс. длительность речи (сек)", "Max speech duration (sec)", "setToolTip")
    root_lay.addWidget(make_row(_("Макс. речь (сек)", "Max speech (sec)"), self.vad_max_speech_duration_spinbox, label_w))

    # Кнопки «Применить» и «Сбросить» в одном ряду.
    buttons_row = SettingsBodyWidget()
    btn_h = QHBoxLayout(buttons_row)
    btn_h.setContentsMargins(0, 0, 0, 0)
    btn_h.setSpacing(6)

    self.vad_apply_button = tr_set(QPushButton(), "Применить", "Apply")
    self.vad_apply_button.setObjectName("SecondaryButton")
    self.vad_apply_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn_h.addWidget(self.vad_apply_button, 1)

    self.vad_reset_button = tr_set(QPushButton(), "Сбросить", "Reset")
    self.vad_reset_button.setObjectName("SecondaryButton")
    self.vad_reset_button.setIcon(qta.icon("fa5s.undo", color="#ffffff"))
    self.vad_reset_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    tr_set(self.vad_reset_button, "Сбросить параметры распознавания к значениям по умолчанию",
           "Reset recognition parameters to defaults", "setToolTip")
    btn_h.addWidget(self.vad_reset_button, 1)

    root_lay.addWidget(buttons_row)

    parent_layout.addWidget(root)
