# src/ui/settings/microphone_settings/ui.py
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QSizePolicy, QCheckBox
)
import qtawesome as qta

from ui.gui_templates import create_section_header
from utils import getTranslationVariant as _


def make_row(label_text: str, field_widget: QWidget, label_w: int) -> QWidget:
    """
    Унифицированная строка настроек: метка слева, виджет справа.
    """
    row = QWidget()
    hl = QHBoxLayout(row)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(6)

    lbl = QLabel(label_text)
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

    root = QWidget()
    root_lay = QVBoxLayout(root)
    root_lay.setContentsMargins(0, 0, 0, 0)
    root_lay.setSpacing(6)

    # 1) Кнопка в глоссарий
    self.asr_manage_button = QPushButton(_("Каталог ASR моделей", "ASR Model Catalogue"))
    self.asr_manage_button.setObjectName("SecondaryButton")
    self.asr_manage_button.setIcon(qta.icon("fa5s.list", color="#ffffff"))
    self.asr_manage_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    root_lay.addWidget(self.asr_manage_button, 0)

    # 2) Доступные (установленные) модели + refresh
    engine_field = QWidget()
    eng_h = QHBoxLayout(engine_field)
    eng_h.setContentsMargins(0, 0, 0, 0)
    eng_h.setSpacing(6)

    self.recognizer_combobox = QComboBox()
    self.recognizer_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.recognizer_combobox.setToolTip(_("Установленные модели распознавания", "Installed speech recognition models"))
    eng_h.addWidget(self.recognizer_combobox, 1)

    self.asr_refresh_button = QPushButton()
    self.asr_refresh_button.setObjectName("SecondaryButton")
    self.asr_refresh_button.setIcon(qta.icon("fa5s.sync", color="#ffffff"))
    self.asr_refresh_button.setToolTip(_("Обновить список моделей", "Refresh model list"))
    self.asr_refresh_button.setFixedSize(28, 26)
    eng_h.addWidget(self.asr_refresh_button, 0)

    root_lay.addWidget(make_row(_("Модель", "Model"), engine_field, label_w))

    # 3) Текущий микрофон + refresh
    mic_field = QWidget()
    mic_h = QHBoxLayout(mic_field)
    mic_h.setContentsMargins(0, 0, 0, 0)
    mic_h.setSpacing(6)

    self.mic_combobox = QComboBox()
    self.mic_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.mic_combobox.setMaximumWidth(200)
    self.mic_combobox.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)
    mic_h.addWidget(self.mic_combobox, 1)

    self.mic_refresh_button = QPushButton()
    self.mic_refresh_button.setObjectName("SecondaryButton")
    self.mic_refresh_button.setIcon(qta.icon("fa5s.sync", color="#ffffff"))
    self.mic_refresh_button.setToolTip(_("Обновить список микрофонов", "Refresh microphone list"))
    self.mic_refresh_button.setFixedSize(28, 26)
    mic_h.addWidget(self.mic_refresh_button, 0)

    root_lay.addWidget(make_row(_("Микрофон", "Microphone"), mic_field, label_w))

    # 4) Управление
    self.mic_active_checkbox = QCheckBox("")
    self.mic_active_checkbox.setChecked(bool(self.settings.get("MIC_ACTIVE")))
    self.mic_active_checkbox.setToolTip(_("Включить/выключить распознавание", "Enable/disable recognition"))
    root_lay.addWidget(make_row(_("Микрофон активен", "Microphone active"), self.mic_active_checkbox, label_w))

    self.mic_instant_checkbox = QCheckBox("")
    self.mic_instant_checkbox.setChecked(bool(self.settings.get("MIC_INSTANT_SENT")))
    self.mic_instant_checkbox.setToolTip(_("Мгновенная отправка распознанного текста", "Send recognized text immediately"))
    root_lay.addWidget(make_row(_("Мгновенная отправка", "Instant send"), self.mic_instant_checkbox, label_w))

    # 5) Статус (как раньше) — под кнопками
    self.asr_init_status = QLabel("—")
    root_lay.addWidget(make_row(_("Статус", "Status"), self.asr_init_status, label_w))

    parent_layout.addWidget(root)