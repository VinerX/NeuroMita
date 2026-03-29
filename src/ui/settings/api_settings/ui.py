from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, QStringListModel
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QToolButton, QComboBox, QSizePolicy, QCompleter, QTextEdit, QCheckBox, QLineEdit
)
import qtawesome as qta

from utils import _
from .widgets import (
    ProviderDelegate,
    LabeledLineEditRow,
    LabeledTextEditRow,
    LabeledComboRow,
)
from ui.gui_templates import create_section_header
from managers.settings_manager import CollapsibleSection


def build_api_settings_ui(self, parent_layout):
    main_container = QWidget()
    main_layout = QVBoxLayout(main_container)
    main_layout.setContentsMargins(0, 0, 0, 0)
    main_layout.setSpacing(8)

    create_section_header(main_layout, _("API пресеты", "API presets"))

    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setFrameShadow(QFrame.Shadow.Sunken)
    separator.setObjectName("SeparatorH")
    main_layout.addWidget(separator)

    # --- presets panel ---
    custom_presets_frame = QFrame()
    custom_presets_frame.setObjectName("PresetsPanel")
    custom_presets_frame.setFixedHeight(160)

    presets_layout = QHBoxLayout(custom_presets_frame)
    presets_layout.setContentsMargins(8, 8, 8, 8)
    presets_layout.setSpacing(10)

    self.custom_presets_list = QListWidget()
    self.custom_presets_list.setObjectName("PresetsList")
    self.custom_presets_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    presets_layout.addWidget(self.custom_presets_list, 1)

    buttons_layout = QVBoxLayout()
    buttons_layout.setContentsMargins(0, 0, 0, 0)
    buttons_layout.setSpacing(6)

    self.add_preset_btn = QPushButton()
    self.add_preset_btn.setObjectName("AddPresetButton")
    self.add_preset_btn.setIcon(qta.icon('fa5s.plus', color='#e6e6e6'))
    self.add_preset_btn.setToolTip(_("Добавить пресет", "Add preset"))
    self.add_preset_btn.setFixedSize(28, 28)
    self.add_preset_btn.setIconSize(QSize(14, 14))

    self.remove_preset_btn = QPushButton()
    self.remove_preset_btn.setObjectName("RemovePresetButton")
    self.remove_preset_btn.setIcon(qta.icon('fa5s.minus', color='#e6e6e6'))
    self.remove_preset_btn.setToolTip(_("Удалить пресет", "Remove preset"))
    self.remove_preset_btn.setEnabled(False)
    self.remove_preset_btn.setFixedSize(28, 28)
    self.remove_preset_btn.setIconSize(QSize(14, 14))

    self.move_up_btn = QPushButton()
    self.move_up_btn.setObjectName("MoveUpButton")
    self.move_up_btn.setIcon(qta.icon('fa5s.arrow-up', color='#e6e6e6'))
    self.move_up_btn.setToolTip(_("Переместить вверх", "Move up"))
    self.move_up_btn.setEnabled(False)
    self.move_up_btn.setFixedSize(28, 28)
    self.move_up_btn.setIconSize(QSize(14, 14))

    self.move_down_btn = QPushButton()
    self.move_down_btn.setObjectName("MoveDownButton")
    self.move_down_btn.setIcon(qta.icon('fa5s.arrow-down', color='#e6e6e6'))
    self.move_down_btn.setToolTip(_("Переместить вниз", "Move down"))
    self.move_down_btn.setEnabled(False)
    self.move_down_btn.setFixedSize(28, 28)
    self.move_down_btn.setIconSize(QSize(14, 14))

    buttons_layout.addWidget(self.add_preset_btn)
    buttons_layout.addWidget(self.remove_preset_btn)
    buttons_layout.addSpacing(6)
    buttons_layout.addWidget(self.move_up_btn)
    buttons_layout.addWidget(self.move_down_btn)
    buttons_layout.addStretch()
    presets_layout.addLayout(buttons_layout)

    main_layout.addWidget(custom_presets_frame)

    # --- editor container ---
    self.api_settings_container = QWidget()
    api_container_layout = QVBoxLayout(self.api_settings_container)
    api_container_layout.setContentsMargins(0, 10, 0, 0)
    api_container_layout.setSpacing(8)

    provider_info_layout = QHBoxLayout()
    self.provider_label = QLabel("")
    self.provider_label.setStyleSheet("font-weight: bold; font-size: 12px;")
    provider_info_layout.addWidget(self.provider_label)
    provider_info_layout.addStretch()
    api_container_layout.addLayout(provider_info_layout)

    # Template row
    template_layout = QHBoxLayout()
    template_label = QLabel(_("Шаблон:", "Template:"))
    self.template_combo = QComboBox()
    self.template_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.template_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    self.template_combo.setMinimumContentsLength(10)
    try:
        self.template_combo.view().setTextElideMode(Qt.TextElideMode.ElideRight)
    except Exception:
        pass

    template_layout.addWidget(template_label)
    template_layout.addWidget(self.template_combo, 1)
    api_container_layout.addLayout(template_layout)

    # Help links (under fields)
    self.url_help_label = QLabel()
    self.url_help_label.setOpenExternalLinks(True)
    self.url_help_label.setObjectName("LinkLabel")
    self.url_help_label.setVisible(False)

    self.model_help_label = QLabel()
    self.model_help_label.setOpenExternalLinks(True)
    self.model_help_label.setObjectName("LinkLabel")
    self.model_help_label.setVisible(False)

    self.key_help_label = QLabel()
    self.key_help_label.setOpenExternalLinks(True)
    self.key_help_label.setObjectName("LinkLabel")
    self.key_help_label.setVisible(False)

    api_container_layout.addWidget(self.url_help_label)
    self.api_url_row = LabeledLineEditRow(_('Ссылка API', 'API URL'))
    api_container_layout.addWidget(self.api_url_row)

    api_container_layout.addWidget(self.model_help_label)
    self.api_model_row = LabeledLineEditRow(_('Модель', 'Model'))
    api_container_layout.addWidget(self.api_model_row)

    api_container_layout.addWidget(self.key_help_label)
    self.api_key_row = LabeledLineEditRow(_('API Ключ', 'API Key'), password=True)
    api_container_layout.addWidget(self.api_key_row)

    self.key_visibility_button = QToolButton()
    self.key_visibility_button.setIcon(qta.icon('fa5s.eye'))
    self.key_visibility_button.setToolTip(_("Показать/скрыть ключ", "Show/hide key"))
    self.key_visibility_button.setFixedSize(28, 28)
    self.api_key_row.layout().addWidget(self.key_visibility_button, 0, Qt.AlignmentFlag.AlignRight)

    self.reserve_keys_row = LabeledTextEditRow(_('Резервные ключи', 'Reserve keys'))
    api_container_layout.addWidget(self.reserve_keys_row)

    # --- Collapsible protocol configuration section (UNDER inputs) ---
    self.protocol_section = CollapsibleSection(_("Конфигурация протокола", "Protocol configuration"), self, icon_name="fa5s.sliders-h")
    api_container_layout.addWidget(self.protocol_section)

    self.protocol_row = LabeledComboRow(_("Протокол", "Protocol"))
    self.protocol_section.add_widget(self.protocol_row)

    self.protocol_info_label = QLabel("")
    self.protocol_info_label.setWordWrap(True)
    self.protocol_info_label.setObjectName("ProtocolInfoLabel")
    self.protocol_info_label.setStyleSheet("color: #bfbfbf; font-size: 11px;")
    self.protocol_section.add_widget(self.protocol_info_label)

    self.protocol_transforms_view = QTextEdit()
    self.protocol_transforms_view.setReadOnly(True)
    self.protocol_transforms_view.setMinimumHeight(70)
    self.protocol_transforms_view.setMaximumHeight(110)
    self.protocol_section.add_widget(self.protocol_transforms_view)

    self.configure_pipeline_btn = QPushButton(_("Настроить pipeline", "Configure pipeline"))
    self.configure_pipeline_btn.setIcon(qta.icon('fa5s.sliders-h', color='#3498db'))
    self.protocol_section.add_widget(self.configure_pipeline_btn)

    # --- Collapsible generation overrides section ---
    self.gen_overrides_section = CollapsibleSection(
        _("Параметры генерации (переопределение)", "Generation overrides"), self, icon_name="fa5s.sliders-h"
    )
    api_container_layout.addWidget(self.gen_overrides_section)

    gen_note = QLabel(_("Переопределяют глобальные настройки только для этого пресета.",
                        "Override global generation settings for this preset only."))
    gen_note.setWordWrap(True)
    gen_note.setStyleSheet("color: #bfbfbf; font-size: 11px;")
    self.gen_overrides_section.add_widget(gen_note)

    # Numeric generation params: (key, display_label, default_value)
    _gen_params = [
        ("temperature",       _("Температура",       "Temperature"),       "1.0"),
        ("max_tokens",        _("Макс. токенов",      "Max tokens"),        "2500"),
        ("top_p",             "Top-P",                                      "1.0"),
        ("top_k",             "Top-K",                                      "0"),
        ("presence_penalty",  _("Штраф присутствия", "Presence penalty"),   "0.0"),
        ("frequency_penalty", _("Штраф частоты",     "Frequency penalty"),  "0.0"),
        ("thinking_budget",        _("Бюджет мышления",          "Thinking budget"),         "0.0"),
        ("gemini_thinking_budget", _("Бюджет мышления Gemini",   "Gemini thinking budget"),  "8192"),
    ]
    self.gen_override_widgets = {}
    for param_key, param_label, default_val in _gen_params:
        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 1, 0, 1)
        row_lay.setSpacing(6)
        chk = QCheckBox()
        chk.setFixedWidth(18)
        chk.setToolTip(_("Включить переопределение", "Enable override"))
        lbl = QLabel(param_label)
        lbl.setMinimumWidth(130)
        lbl.setMaximumWidth(130)
        val_edit = QLineEdit(default_val)
        val_edit.setEnabled(False)
        val_edit.setMaximumWidth(80)
        chk.toggled.connect(val_edit.setEnabled)
        row_lay.addWidget(chk)
        row_lay.addWidget(lbl)
        row_lay.addWidget(val_edit)
        row_lay.addStretch()
        self.gen_overrides_section.add_widget(row)
        self.gen_override_widgets[param_key] = (chk, val_edit)

    # enable_thinking override (boolean value)
    et_row = QWidget()
    et_lay = QHBoxLayout(et_row)
    et_lay.setContentsMargins(0, 1, 0, 1)
    et_lay.setSpacing(6)
    et_enable_chk = QCheckBox()
    et_enable_chk.setFixedWidth(18)
    et_enable_chk.setToolTip(_("Включить переопределение", "Enable override"))
    et_lbl = QLabel(_("Режим мышления", "Enable thinking"))
    et_lbl.setMinimumWidth(130)
    et_lbl.setMaximumWidth(130)
    et_val_chk = QCheckBox(_("Вкл", "On"))
    et_val_chk.setEnabled(False)
    et_enable_chk.toggled.connect(et_val_chk.setEnabled)
    et_lay.addWidget(et_enable_chk)
    et_lay.addWidget(et_lbl)
    et_lay.addWidget(et_val_chk)
    et_lay.addStretch()
    self.gen_overrides_section.add_widget(et_row)
    self.gen_override_widgets["enable_thinking"] = (et_enable_chk, et_val_chk)

    # buttons
    self.test_button = QPushButton(_("Тест подключения", "Test connection"))
    self.test_button.setIcon(qta.icon('fa5s.satellite', color='#3498db'))
    api_container_layout.addWidget(self.test_button)

    btns = QHBoxLayout()
    btns.setSpacing(10)

    self.cancel_button = QPushButton(_("Отменить", "Cancel"))
    self.cancel_button.setObjectName("CancelButton")
    self.cancel_button.setIcon(qta.icon('fa5s.undo', color='#ffffff'))
    self.cancel_button.setVisible(False)

    self.save_preset_button = QPushButton(_("Сохранить", "Save"))
    self.save_preset_button.setObjectName("SecondaryButton")
    self.save_preset_button.setIcon(qta.icon('fa5s.save', color='#ffffff'))
    self.save_preset_button.setEnabled(False)
    self.save_preset_button.setVisible(False)

    btns.addWidget(self.cancel_button, 1)
    btns.addWidget(self.save_preset_button, 1)
    api_container_layout.addLayout(btns)

    api_container_layout.addStretch(1)

    main_layout.addWidget(self.api_settings_container)
    self.api_settings_container.setVisible(False)

    parent_layout.addWidget(main_container)

    # --- model completer ---
    self.api_model_completer = QCompleter()
    self.api_model_list_model = QStringListModel()
    self.api_model_completer.setModel(self.api_model_list_model)
    self.api_model_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    self.api_model_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    self.api_model_completer.setFilterMode(Qt.MatchFlag.MatchContains)
    self.api_model_row.edit.setCompleter(self.api_model_completer)

    completer = self.api_model_completer

    def show_completer_on_click(event):
        from PyQt6.QtWidgets import QLineEdit
        QLineEdit.mousePressEvent(self.api_model_row.edit, event)
        if self.api_model_row.edit.text() == "":
            completer.setCompletionPrefix("")
            completer.complete()

    self.api_model_row.edit.mousePressEvent = show_completer_on_click

    # Delegate for pricing badges
    self.provider_delegate = ProviderDelegate(self.template_combo)
    self.template_combo.view().setItemDelegate(self.provider_delegate)