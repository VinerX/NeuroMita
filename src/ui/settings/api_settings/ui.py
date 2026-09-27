from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, QStringListModel, QTimer, QRect, QRectF
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QToolButton, QComboBox, QSizePolicy, QCompleter, QTextEdit, QCheckBox,
    QLineEdit, QScrollArea, QSplitter, QTabWidget,
)
from PyQt6.QtGui import QPainter, QPainterPath, QPalette, QColor
import qtawesome as qta

from utils import _
from localization.live import tr_set, register_if_tr, register
from styles.theme import THEME
from .model_settings_form import ModelSettingsForm
from .widgets import (
    ProviderDelegate, PresetsListWidget, LabeledLineEditRow, LabeledComboRow,
    FallbackChainEditor, ReserveKeysEditor,
)
from ui.provider_icons import provider_icon
from ui.widgets.tr_combobox import TRQComboBox
from ui.widgets.settings_sections import CollapsibleSection


class ApiWorkspaceSplitter(QSplitter):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setObjectName("ApiWorkspaceSplitter")
        self.setChildrenCollapsible(False)
        self.setHandleWidth(9)
        self._initialised = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initialised:
            self._initialised = True
            QTimer.singleShot(0, self._set_initial_sizes)

    def _set_initial_sizes(self):
        width = max(1, self.width() - self.handleWidth())
        self.setSizes([width // 3, width - width // 3])
        self.setStretchFactor(0, 1)
        self.setStretchFactor(1, 1)


class ApiTemplateCombo(TRQComboBox):
    def add_provider_item(self, text, *, value, provider):
        self.add_data_item(text, value=value)
        self.setItemIcon(self.count() - 1, provider_icon(provider))


class ApiEditorTabs(QTabWidget):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.currentChanged.connect(self.updateGeometry)

    def minimumSizeHint(self):
        return QSize(0, 110)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(QRect(0, 0, self.width(), self.tabBar().height()))
        header = QPainterPath()
        header.addRoundedRect(QRectF(0, 0, self.width(), self.tabBar().height() + 11), 11, 11)
        painter.fillPath(header, QColor(THEME["bg_root"]))
        painter.end()


class ApiField(QWidget):
    def __init__(self, title, *, password=False):
        super().__init__()
        self._base_label = str(title)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.heading = QHBoxLayout()
        self.label = QLabel(title)
        register_if_tr(self.label, title)
        self.heading.addWidget(self.label)
        self.heading.addStretch(1)
        layout.addLayout(self.heading)
        self.input_layout = QHBoxLayout()
        self.input_layout.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setMinimumHeight(40)
        if password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_layout.addWidget(self.edit, 1)
        layout.addLayout(self.input_layout)

    def set_text(self, value):
        self.edit.setText(str(value or ""))

    def text(self):
        return self.edit.text()

    def set_enabled(self, enabled):
        self.edit.setEnabled(enabled)

    def set_dirty(self, dirty):
        self.label.setProperty("dirty", bool(dirty))
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)


def _link_label():
    label = QLabel()
    label.setObjectName("LinkLabel")
    label.setOpenExternalLinks(True)
    label.hide()
    return label


def _button(ru, en, icon, name=""):
    button = tr_set(QPushButton(), ru, en)
    button.setIcon(qta.icon(icon, color=THEME["text"]))
    button.setObjectName(name)
    button.setFixedHeight(40)
    button.setMinimumWidth(110)
    button.setIconSize(QSize(14, 14))
    return button


def build_api_settings_ui(self, parent_layout):
    root = QWidget()
    root.setObjectName("ApiSettingsWorkspace")
    root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    heading = QHBoxLayout()
    titles = QVBoxLayout()
    titles.setSpacing(4)
    title = tr_set(QLabel(), "API пресеты", "API presets")
    title.setObjectName("ApiSettingsTitle")
    titles.addWidget(title)
    subtitle = tr_set(QLabel(), "Управление подключениями к провайдерам и настройками моделей.",
                      "Manage provider connections and model settings.")
    subtitle.setObjectName("ApiSettingsSubtitle")
    subtitle.setWordWrap(True)
    titles.addWidget(subtitle)
    heading.addLayout(titles, 1)
    self.add_preset_btn = _button("Добавить пресет", "Add preset", "fa5s.plus", "ApiAddPresetButton")

    layout.addLayout(heading)

    workspace = QFrame()
    workspace.setObjectName("ApiWorkspacePanel")
    workspace_layout = QVBoxLayout(workspace)
    workspace_layout.setContentsMargins(1, 1, 1, 1)
    self.api_workspace_splitter = ApiWorkspaceSplitter()
    workspace_layout.addWidget(self.api_workspace_splitter)
    layout.addWidget(workspace, 1)

    sidebar = QFrame()
    sidebar.setObjectName("ApiPresetSidebar")
    sidebar.setMinimumWidth(310)
    sidebar_layout = QVBoxLayout(sidebar)
    sidebar_layout.setContentsMargins(10, 14, 10, 10)
    sidebar_layout.setSpacing(10)
    preset_tools = QHBoxLayout()
    preset_tools.setSpacing(10)
    self.preset_search = QLineEdit()
    self.preset_search.setObjectName("ApiPresetSearch")
    self.preset_search.setFixedHeight(40)
    tr_set(self.preset_search, "Поиск пресетов...", "Search presets...", "setPlaceholderText")
    self.preset_search.addAction(qta.icon("fa5s.search", color=THEME["muted"]), QLineEdit.ActionPosition.LeadingPosition)
    preset_tools.addWidget(self.preset_search, 1)
    preset_tools.addWidget(self.add_preset_btn)
    sidebar_layout.addLayout(preset_tools)
    self.custom_presets_list = PresetsListWidget()
    self.custom_presets_list.setObjectName("ApiPresetCards")
    self.custom_presets_list.setFrameShape(QFrame.Shape.NoFrame)
    self.custom_presets_list.setStyleSheet("QListWidget {background: transparent; border: none; padding: 0;} QListWidget::item {padding: 0; border: none;}")
    self.custom_presets_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    sidebar_layout.addWidget(self.custom_presets_list, 1)
    self.preset_search.textChanged.connect(lambda text: _filter_presets(self.custom_presets_list, text))
    self.api_workspace_splitter.addWidget(sidebar)

    editor_panel = QFrame()
    editor_panel.setObjectName("ApiEditorPanel")
    editor_panel.setMinimumWidth(0)
    editor_layout = QVBoxLayout(editor_panel)
    editor_layout.setContentsMargins(4, 0, 0, 0)
    editor_layout.setSpacing(14)
    editor_header = QFrame()
    editor_header.setObjectName("ApiEditorHeader")
    toolbar = QHBoxLayout(editor_header)
    toolbar.setContentsMargins(18, 12, 18, 12)
    toolbar.setSpacing(12)
    self.preset_provider_icon = QLabel()
    self.preset_provider_icon.setFixedSize(42, 42)
    self.preset_provider_icon.setPixmap(provider_icon("").pixmap(38, 38))
    toolbar.addWidget(self.preset_provider_icon)
    caption = QVBoxLayout()
    caption.setContentsMargins(0, 0, 0, 0)
    caption.setSpacing(2)
    caption.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    self.provider_label = tr_set(QLabel(), "Настройки пресета", "Preset settings")
    self.provider_label.setObjectName("ApiPresetName")
    self.provider_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    self.api_type_label = QLabel()
    self.api_type_label.setObjectName("ApiSettingsSubtitle")
    self.api_type_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    name_heading = QHBoxLayout()
    name_heading.setContentsMargins(0, 0, 0, 0)
    name_heading.setSpacing(6)
    name_heading.addWidget(self.provider_label)
    self.preset_active_tag = tr_set(QLabel(), "Активен", "Active")
    self.preset_active_tag.setObjectName("ApiActiveTag")
    self.preset_active_tag.setFixedHeight(24)
    self.preset_active_tag.hide()
    name_heading.addWidget(self.preset_active_tag)
    name_heading.addStretch(1)
    caption.addLayout(name_heading)
    caption.addWidget(self.api_type_label)
    toolbar.addLayout(caption, 1)
    self.test_button = _button("Проверить", "Check", "fa5s.link", "ApiCheckButton")
    register(self.test_button, lambda button: button.setText(
        str(_("Проверка…", "Checking…") if button.property("apiTesting") else _("Проверить", "Check"))
    ))
    self.save_preset_button = _button("Сохранить", "Save", "fa5s.save", "ApiSaveButton")
    self.save_preset_button.setEnabled(False)
    self.cancel_button = _button("Отменить", "Cancel", "fa5s.undo")
    self.cancel_button.hide()
    for button in (self.test_button, self.cancel_button, self.save_preset_button):
        toolbar.addWidget(button)
    editor_layout.addWidget(editor_header)

    scroll = QScrollArea()
    scroll.setObjectName("ApiEditorScroll")
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self.api_settings_container = ApiEditorTabs()
    self.api_settings_container.setObjectName("ApiEditorTabs")
    self.api_settings_container.setDocumentMode(False)
    self.api_settings_container.tabBar().setDrawBase(False)
    connection_body = QWidget()
    connection_body.setObjectName("ApiEditorContent")
    content = QVBoxLayout(connection_body)
    content.setContentsMargins(20, 20, 20, 20)
    content.setSpacing(16)

    self.preset_name_row = ApiField(_("Название пресета", "Preset name"))
    identity = QGridLayout()
    identity.setHorizontalSpacing(16)
    identity.setColumnStretch(0, 1)
    identity.setColumnStretch(1, 1)
    identity.addWidget(self.preset_name_row, 0, 0)
    template_field = QWidget()
    template_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    template_layout = QVBoxLayout(template_field)
    template_layout.setContentsMargins(0, 0, 0, 0)
    template_layout.setSpacing(6)
    template_heading = QHBoxLayout()
    template_heading.addWidget(tr_set(QLabel(), "Шаблон / провайдер", "Template / provider"))
    template_heading.addStretch(1)
    self.url_help_label = _link_label()
    template_heading.addWidget(self.url_help_label)
    template_layout.addLayout(template_heading)
    self.template_combo = ApiTemplateCombo()
    self.template_combo.setObjectName("ApiArrowCombo")
    self.template_combo.setMinimumHeight(40)
    self.template_combo.setIconSize(QSize(18, 18))
    self.template_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    self.template_combo.setMinimumContentsLength(10)
    template_layout.addWidget(self.template_combo)
    identity.addWidget(template_field, 0, 1)
    content.addLayout(identity)

    self.api_url_row = ApiField(_("Ссылка API", "API URL"))
    content.addWidget(self.api_url_row)
    credentials = QGridLayout()
    credentials.setHorizontalSpacing(16)
    credentials.setColumnStretch(0, 1)
    credentials.setColumnStretch(1, 1)
    self.api_model_row = ApiField(_("Модель", "Model"))
    self.api_key_row = ApiField(_("API ключ", "API key"), password=True)
    self.model_help_label = _link_label()
    self.key_help_label = _link_label()
    self.api_model_row.heading.addWidget(self.model_help_label)
    self.api_key_row.heading.addWidget(self.key_help_label)
    self.key_visibility_button = QToolButton()
    self.key_visibility_button.setIcon(qta.icon("fa5s.eye", color=THEME["muted"]))
    self.key_visibility_button.setFixedSize(30, 40)
    tr_set(self.key_visibility_button, "Показать/скрыть ключ", "Show/hide key", "setToolTip")
    self.api_key_row.input_layout.addWidget(self.key_visibility_button)
    credentials.addWidget(self.api_model_row, 0, 0)
    credentials.addWidget(self.api_key_row, 0, 1)
    content.addLayout(credentials)

    configuration_scroll = QScrollArea()
    configuration_scroll.setObjectName("ApiConfigurationScroll")
    configuration_scroll.setFrameShape(QFrame.Shape.NoFrame)
    configuration_scroll.setWidgetResizable(True)
    configuration_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    configuration_body = QWidget()
    configuration_body.setObjectName("ApiEditorContent")
    configuration_layout = QVBoxLayout(configuration_body)
    configuration_layout.setContentsMargins(16, 14, 16, 16)
    configuration_layout.setSpacing(14)
    _build_generation(self, configuration_layout)
    configuration_layout.addStretch(1)
    configuration_scroll.setWidget(configuration_body)
    _build_protocol(self, content)
    _build_routing(self, content)
    _build_fallbacks(self, content)
    content.addStretch(1)
    _build_retained_state(self, root)
    scroll.setWidget(connection_body)
    self.api_settings_container.addTab(scroll, qta.icon("fa5s.link", color=THEME["muted"]), str(_("Подключение", "Connection")))
    self.api_settings_container.addTab(configuration_scroll, qta.icon("fa5s.sliders-h", color=THEME["muted"]), str(_("Параметры генерации", "Generation parameters")))
    register(self.api_settings_container, lambda tabs: (
        tabs.setTabText(0, str(_("Подключение", "Connection"))),
        tabs.setTabText(1, str(_("Параметры генерации", "Generation parameters"))),
    ))
    connection_card = QFrame()
    connection_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    connection_card.setObjectName("ApiConnectionCard")
    connection_card_layout = QVBoxLayout(connection_card)
    connection_card_layout.setContentsMargins(1, 1, 1, 1)
    connection_card_layout.addWidget(self.api_settings_container)
    editor_layout.addWidget(connection_card, 1)
    self.api_workspace_splitter.addWidget(editor_panel)
    self.api_settings_container.hide()
    parent_layout.addWidget(root, 1)
    _build_completer(self)
    self.provider_delegate = ProviderDelegate(self.template_combo)
    self.template_combo.view().setItemDelegate(self.provider_delegate)


def _build_generation(self, layout):
    self.model_settings_form = ModelSettingsForm()
    layout.addWidget(self.model_settings_form)


def _build_protocol(self, layout):
    title = _("Резервные ключи", "Reserve keys")
    self.reserve_keys_section = CollapsibleSection(title, icon_name="fa5s.key", subtitle=_("Используются при недоступности основного ключа", "Used when the primary key is unavailable"))
    self.reserve_keys_section.icon_label.setFixedSize(38, 38)
    self.reserve_keys_section.icon_label.setPixmap(qta.icon("fa5s.key", color=THEME["muted"]).pixmap(20, 20))
    self.reserve_keys_row = ReserveKeysEditor()
    self.reserve_keys_row.attach_section(self.reserve_keys_section, title)
    self.reserve_keys_count = QLabel()
    self.reserve_keys_count.setObjectName("ApiReserveCount")
    register(self.reserve_keys_count, lambda label: label.setText(
        str(label.property("keyCount") or 0) + str(_(" ключей", " keys"))
    ))
    header_layout = self.reserve_keys_section.header.layout()
    header_layout.insertWidget(header_layout.count() - 1, self.reserve_keys_count)
    self.reserve_keys_row.count_label = self.reserve_keys_count
    self.reserve_keys_row.changed.connect(lambda: _update_reserve_count(self.reserve_keys_row))
    _update_reserve_count(self.reserve_keys_row)
    self.reserve_keys_section.add_widget(self.reserve_keys_row)
    layout.addWidget(self.reserve_keys_section)
    self.protocol_section = CollapsibleSection(_("Расширенные настройки подключения", "Advanced connection settings"))
    self.protocol_row = LabeledComboRow(_("Формат запроса", "Request format"))
    self.protocol_section.add_widget(self.protocol_row)
    self.protocol_info_label = QLabel()
    self.protocol_info_label.setWordWrap(True)
    self.protocol_section.add_widget(self.protocol_info_label)
    self.protocol_transforms_view = QTextEdit()
    self.protocol_transforms_view.setReadOnly(True)
    self.protocol_transforms_view.setFixedHeight(90)
    self.protocol_section.add_widget(self.protocol_transforms_view)
    self.configure_pipeline_btn = _button("Настроить pipeline", "Configure pipeline", "fa5s.sliders-h")
    self.protocol_section.add_widget(self.configure_pipeline_btn)
    layout.addWidget(self.protocol_section)


def _build_retained_state(self, parent):
    for name in ("remove_preset_btn", "rename_preset_btn", "copy_preset_btn", "move_up_btn", "move_down_btn"):
        button = QPushButton(parent)
        button.hide()
        button.setEnabled(False)
        setattr(self, name, button)


def _build_fallbacks(self, layout):
    self.fallback_providers_section = CollapsibleSection(
        _("Резервные провайдеры", "Fallback providers"),
        icon_name="fa5s.random",
        subtitle=_(
            "Используются по очереди, если основной провайдер не ответил",
            "Used in order when the primary provider does not respond",
        ),
    )
    self.fallback_editor = FallbackChainEditor(self.fallback_providers_section)
    self.fallback_providers_section.add_widget(self.fallback_editor)
    layout.addWidget(self.fallback_providers_section)


def _build_completer(self):
    self.api_model_completer = QCompleter()
    self.api_model_list_model = QStringListModel()
    self.api_model_completer.setModel(self.api_model_list_model)
    self.api_model_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    self.api_model_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    self.api_model_completer.setFilterMode(Qt.MatchFlag.MatchContains)
    self.api_model_row.edit.setCompleter(self.api_model_completer)

    def show_completer(event):
        QLineEdit.mousePressEvent(self.api_model_row.edit, event)
        if not self.api_model_row.edit.text():
            self.api_model_completer.setCompletionPrefix("")
            self.api_model_completer.complete()

    self.api_model_row.edit.mousePressEvent = show_completer


def _build_routing(self, layout):
    self.openrouter_routing_section = CollapsibleSection(
        _("OpenRouter routing", "OpenRouter routing"), self, icon_name="fa5s.sliders-h"
    )
    layout.addWidget(self.openrouter_routing_section)

    or_note = tr_set(
        QLabel(),
        "Управляет выбором upstream-провайдеров только для OpenRouter.",
        "Controls upstream provider selection for OpenRouter only.",
    )
    or_note.setWordWrap(True)
    or_note.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px;")
    self.openrouter_routing_section.add_widget(or_note)

    self.or_enable_cb = tr_set(QCheckBox(), "Включить provider routing", "Enable provider routing")
    self.openrouter_routing_section.add_widget(self.or_enable_cb)

    self.or_tail_system_to_user_cb = tr_set(QCheckBox(), "Хвостовой system → user", "Trailing system → user")
    self.or_tail_system_to_user_cb.setChecked(True)
    tr_set(self.or_tail_system_to_user_cb,
           "Если последнее сообщение запроса имеет роль system, для OpenRouter оно будет отправлено как user с префиксом [SYSTEM INFO].",
           "If the last request message has system role, OpenRouter will send it as user with a [SYSTEM INFO] prefix.",
           "setToolTip")
    self.openrouter_routing_section.add_widget(self.or_tail_system_to_user_cb)

    self.or_order_row = LabeledLineEditRow(_("Приоритет провайдеров", "Provider order"))
    self.or_order_row.edit.setPlaceholderText("together, fireworks, groq")
    self.openrouter_routing_section.add_widget(self.or_order_row)

    self.or_only_row = LabeledLineEditRow(_("Только эти провайдеры", "Only providers"))
    self.or_only_row.edit.setPlaceholderText("together, groq")
    self.openrouter_routing_section.add_widget(self.or_only_row)

    self.or_ignore_row = LabeledLineEditRow(_("Игнорировать провайдеров", "Ignore providers"))
    self.or_ignore_row.edit.setPlaceholderText("azure")
    self.openrouter_routing_section.add_widget(self.or_ignore_row)

    self.or_quantizations_row = LabeledLineEditRow(_("Квантизации", "Quantizations"))
    self.or_quantizations_row.edit.setPlaceholderText("fp8, int8")
    self.openrouter_routing_section.add_widget(self.or_quantizations_row)

    self.or_sort_row = LabeledComboRow(_("Сортировка", "Sort by"))
    self.or_sort_row.set_items(
        [
            (_("По умолчанию", "Default"), ""),
            (_("Цена", "Price"), "price"),
            (_("Латентность", "Latency"), "latency"),
            (_("Пропускная способность", "Throughput"), "throughput"),
        ]
    )
    self.openrouter_routing_section.add_widget(self.or_sort_row)

    self.or_data_collection_row = LabeledComboRow(_("Сбор данных", "Data collection"))
    self.or_data_collection_row.set_items(
        [
            (_("По умолчанию", "Default"), ""),
            (_("Разрешить", "Allow"), "allow"),
            (_("Запретить", "Deny"), "deny"),
        ]
    )
    self.openrouter_routing_section.add_widget(self.or_data_collection_row)

    or_flags_row = QWidget()
    or_flags_layout = QHBoxLayout(or_flags_row)
    or_flags_layout.setContentsMargins(0, 2, 0, 2)
    or_flags_layout.setSpacing(12)
    self.or_allow_fallbacks_cb = tr_set(QCheckBox(), "Разрешить fallback", "Allow fallbacks")
    self.or_require_parameters_cb = tr_set(QCheckBox(), "Требовать параметры", "Require parameters")
    self.or_zdr_cb = tr_set(QCheckBox(), "Только ZDR", "ZDR only")
    or_flags_layout.addWidget(self.or_allow_fallbacks_cb)
    or_flags_layout.addWidget(self.or_require_parameters_cb)
    or_flags_layout.addWidget(self.or_zdr_cb)
    or_flags_layout.addStretch(1)
    self.openrouter_routing_section.add_widget(or_flags_row)

    or_max_price_label = tr_set(QLabel(), "Max price ($)", "Max price ($)")
    or_max_price_label.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px;")
    self.openrouter_routing_section.add_widget(or_max_price_label)

    or_max_price_row = QWidget()
    or_max_price_layout = QHBoxLayout(or_max_price_row)
    or_max_price_layout.setContentsMargins(0, 2, 0, 2)
    or_max_price_layout.setSpacing(8)
    self.or_max_price_prompt = QLineEdit()
    self.or_max_price_prompt.setPlaceholderText("prompt")
    self.or_max_price_prompt.setMaximumWidth(90)
    self.or_max_price_completion = QLineEdit()
    self.or_max_price_completion.setPlaceholderText("completion")
    self.or_max_price_completion.setMaximumWidth(90)
    self.or_max_price_request = QLineEdit()
    self.or_max_price_request.setPlaceholderText("request")
    self.or_max_price_request.setMaximumWidth(90)
    self.or_max_price_image = QLineEdit()
    self.or_max_price_image.setPlaceholderText("image")
    self.or_max_price_image.setMaximumWidth(90)
    for _w in (
        self.or_max_price_prompt,
        self.or_max_price_completion,
        self.or_max_price_request,
        self.or_max_price_image,
    ):
        or_max_price_layout.addWidget(_w)
    or_max_price_layout.addStretch(1)
    self.openrouter_routing_section.add_widget(or_max_price_row)

    self.openrouter_routing_widgets = {
        "enabled": self.or_enable_cb,
        "tail_system_to_user": self.or_tail_system_to_user_cb,
        "order": self.or_order_row.edit,
        "only": self.or_only_row.edit,
        "ignore": self.or_ignore_row.edit,
        "quantizations": self.or_quantizations_row.edit,
        "sort": self.or_sort_row.combo,
        "data_collection": self.or_data_collection_row.combo,
        "allow_fallbacks": self.or_allow_fallbacks_cb,
        "require_parameters": self.or_require_parameters_cb,
        "zdr": self.or_zdr_cb,
        "max_price_prompt": self.or_max_price_prompt,
        "max_price_completion": self.or_max_price_completion,
        "max_price_request": self.or_max_price_request,
        "max_price_image": self.or_max_price_image,
    }
    self.openrouter_routing_section.setVisible(False)



def _filter_presets(widget, text):
    query = text.strip().casefold()
    for index in range(widget.count()):
        item = widget.item(index)
        item.setHidden(query not in f"{item.base_name} {item.model} {getattr(item, 'provider_label', '')}".casefold())



def _update_reserve_count(editor):
    editor.count_label.setProperty("keyCount", len(editor.get_keys()))
    editor.count_label.setText(str(len(editor.get_keys())) + str(_(" ключей", " keys")))
