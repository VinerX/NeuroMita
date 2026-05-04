from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.pages.settings.section_registry import get_settings_section_specs, iter_settings_button_specs
from ui.widgets.settings_icon_button import SettingsIconButton
from ui.widgets.settings_overlay_widget import SettingsOverlay
from utils import _

_MODE_RANK = {"basic": 0, "advanced": 1, "full": 2}
_MODE_ALIASES = {
    "basic": {"basic", "базовый", "standard", "стандартный", "Р‘Р°Р·РѕРІС‹Р№"},
    "advanced": {"advanced", "продвинутый", "expanded", "расширенный", "РџСЂРѕРґРІРёРЅСѓС‚С‹Р№"},
    "full": {"full", "полный", "maximum", "максимальный", "РџРѕР»РЅС‹Р№"},
}


def normalize_mode(value):
    text = (value or "").strip()
    if not text:
        return "basic"

    lowered = text.lower()
    for mode, aliases in _MODE_ALIASES.items():
        if lowered in aliases or text in aliases:
            return mode
    return "basic"


def get_mode_label(value) -> str:
    mode = normalize_mode(value)
    return {
        "basic": _("Базовый", "Basic"),
        "advanced": _("Продвинутый", "Advanced"),
        "full": _("Полный", "Full"),
    }[mode]


def _make_card(name: str) -> QFrame:
    card = QFrame()
    card.setObjectName(name)
    return card


class SettingsPage(QWidget):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("SettingsPageRoot")

        self.settings_buttons = {}
        self._category_modes = {}
        self.settings_containers = {}
        self.settings_overview_container = None
        self.settings_overlay = None
        self.current_settings_category = None
        self._mode_status_value = None

        self.SETTINGS_PANEL_WIDTH = 920
        self.SETTINGS_SIDEBAR_WIDTH = 0
        self.settings_resize_handle = None

        self._build_ui()
        self._build_section_containers()
        self._sync_host_exports()

    def _sync_host_exports(self):
        self.gui.settings_page = self
        self.gui.settings_buttons = self.settings_buttons
        self.gui._category_modes = self._category_modes
        self.gui.settings_containers = self.settings_containers
        self.gui.settings_overview_container = self.settings_overview_container
        self.gui.settings_overlay = self.settings_overlay
        self.gui.current_settings_category = self.current_settings_category
        self.gui.SETTINGS_PANEL_WIDTH = self.SETTINGS_PANEL_WIDTH
        self.gui.SETTINGS_SIDEBAR_WIDTH = self.SETTINGS_SIDEBAR_WIDTH
        self.gui.settings_resize_handle = self.settings_resize_handle

    def _set_current_category(self, category):
        self.current_settings_category = category
        self.gui.current_settings_category = category

    def _sync_mode_widgets(self, mode_value):
        clean_label = get_mode_label(mode_value)

        for attr_name in ("INTERFACE_MODE", "chat_mode_combobox"):
            widget = getattr(self.gui, attr_name, None)
            if widget is None or not hasattr(widget, "findText"):
                continue

            index = widget.findText(clean_label, Qt.MatchFlag.MatchFixedString)
            if index < 0 or widget.currentIndex() == index:
                continue

            widget.blockSignals(True)
            try:
                widget.setCurrentIndex(index)
            finally:
                widget.blockSignals(False)

    def apply_interface_mode(self, mode_value):
        mode = normalize_mode(mode_value)
        cur_rank = _MODE_RANK[mode]

        for category, button in self.settings_buttons.items():
            need = _MODE_RANK[self._category_modes.get(category, "basic")]
            button.setVisible(need <= cur_rank)

        active = self.current_settings_category
        if active:
            active_rank = _MODE_RANK[self._category_modes.get(active, "basic")]
            if active_rank > cur_rank:
                self.show_overview()

        if self._mode_status_value is not None:
            self._mode_status_value.setText(get_mode_label(mode))

        self._sync_mode_widgets(mode)

        try:
            from ui.widgets.status_indicators_widget import apply_capture_visibility

            apply_capture_visibility(self.gui, mode)
        except Exception:
            pass

    def on_activated(self):
        if self.current_settings_category is None:
            self.show_overview()

    def show_overview(self):
        for button in self.settings_buttons.values():
            button.set_active(False)
        self._set_current_category(None)
        if self.settings_overview_container is not None:
            self.settings_overlay.show_category(self.settings_overview_container)

    def show_category(self, category):
        container = self.settings_containers.get(category)
        if container is None:
            return

        was_on_settings_page = getattr(self.gui, "current_main_page", None) == "settings"
        if not was_on_settings_page:
            self.gui.switch_main_page("settings")

        is_hiding = was_on_settings_page and self.current_settings_category == category
        for cat, button in self.settings_buttons.items():
            button.set_active(cat == category and not is_hiding)

        if is_hiding:
            self.show_overview()
            return

        self._set_current_category(category)
        self.settings_overlay.show_category(container)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        outer.addWidget(self._build_settings_hero())

        tabs_card = _make_card("SettingsTabsCard")
        tabs_layout = QGridLayout(tabs_card)
        tabs_layout.setContentsMargins(14, 14, 14, 14)
        tabs_layout.setHorizontalSpacing(10)
        tabs_layout.setVerticalSpacing(10)
        outer.addWidget(tabs_card)

        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        self.settings_overlay = SettingsOverlay(self)
        self.settings_overlay.setObjectName("SettingsPageOverlay")
        self.settings_overlay.setMinimumWidth(640)
        self.settings_overlay.setMaximumWidth(1400)
        content_row.addWidget(self.settings_overlay, 1)

        rail = QWidget()
        rail.setObjectName("SettingsRail")
        rail.setFixedWidth(300)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(12)
        rail_layout.addWidget(self._build_brand_panel())
        rail_layout.addWidget(self._build_system_card())
        rail_layout.addWidget(self._build_quick_actions())
        rail_layout.addStretch(1)
        content_row.addWidget(rail)

        outer.addLayout(content_row, 1)

        for index, (icon_name, label, category, min_mode) in enumerate(iter_settings_button_specs()):
            button = SettingsIconButton(icon_name, label, category_key=category)
            button.clicked.connect(lambda checked=False, cat=category: self.show_category(cat))
            tabs_layout.addWidget(button, index // 4, index % 4)
            self.settings_buttons[category] = button
            self._category_modes[category] = min_mode

        self.settings_overview_container = self._build_overview_card()
        self.settings_overlay.add_container(self.settings_overview_container)
        self.settings_overlay.show_category(self.settings_overview_container)

    def _build_settings_hero(self) -> QFrame:
        card = _make_card("SettingsHeroCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title = QLabel(_("Настройки", "Settings"))
        title.setObjectName("SettingsHeroTitle")
        title_col.addWidget(title)

        subtitle = QLabel(
            _(
                "Центр конфигурации NeuroMita. Сохраняем функционал, меняем форму подачи.",
                "NeuroMita configuration hub. Same functionality, new presentation layer.",
            )
        )
        subtitle.setObjectName("SettingsHeroSubtitle")
        subtitle.setWordWrap(True)
        title_col.addWidget(subtitle)
        top_row.addLayout(title_col, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        guide_button = QPushButton(_("Руководство", "Guide"))
        guide_button.setObjectName("SecondaryButton")
        guide_button.clicked.connect(self.gui._show_guide)
        actions.addWidget(guide_button)

        updates_button = QPushButton(_("Обновления", "Updates"))
        updates_button.setObjectName("SecondaryButton")
        updates_button.clicked.connect(lambda: self.show_category("updates"))
        actions.addWidget(updates_button)

        home_button = QPushButton(_("На главную", "Home"))
        home_button.setObjectName("SecondaryButton")
        home_button.clicked.connect(lambda: self.gui.switch_main_page("home"))
        actions.addWidget(home_button)

        top_row.addLayout(actions)
        layout.addLayout(top_row)
        return card

    def _build_brand_panel(self) -> QFrame:
        card = _make_card("SettingsStatusRailCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)

        icon = QLabel()
        icon.setObjectName("SettingsRailBrandIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_path = Path("assets/launcher_ui/icon.png")
        if icon_path.exists():
            icon.setPixmap(
                QPixmap(str(icon_path)).scaled(
                    56,
                    56,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        brand_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        brand_title = QLabel("NeuroMita Launcher")
        brand_title.setObjectName("SettingsRailBrandTitle")
        brand_col.addWidget(brand_title)
        brand_ver = QLabel("v2.0.0")
        brand_ver.setObjectName("SettingsRailBrandMeta")
        brand_col.addWidget(brand_ver)
        brand_state = QLabel(_("АКТИВНО", "ACTIVE"))
        brand_state.setObjectName("SettingsRailBrandState")
        brand_col.addWidget(brand_state)
        brand_row.addLayout(brand_col, 1)
        layout.addLayout(brand_row)

        note = QLabel(
            _(
                "Стиль этой страницы строится от launcher shell и не завязан на фиксированную палитру.",
                "This page inherits the launcher shell language and stays palette-replaceable.",
            )
        )
        note.setObjectName("SettingsRailBrandHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        return card

    def _build_system_card(self) -> QFrame:
        card = _make_card("SettingsStatusRailCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(_("Состояние конфигурации", "Configuration status"))
        title.setObjectName("SettingsRailTitle")
        layout.addWidget(title)

        items = [
            (
                "interface_mode",
                _("Режим интерфейса", "Interface mode"),
                get_mode_label(self.gui._get_setting("INTERFACE_MODE", _("Базовый", "Basic"))),
            ),
            ("language", _("Язык", "Language"), str(self.gui._get_setting("LANGUAGE", "ru")).upper()),
            (
                "memory",
                _("Память", "Memory"),
                _("Включена", "Enabled") if self.gui._get_setting("RAG_ENABLED", False) else _("Выключена", "Disabled"),
            ),
            (
                "voice",
                _("Озвучка", "Voice"),
                _("Локально", "Local") if str(self.gui._get_setting("VOICEOVER_METHOD", "TG")).lower() == "local" else "Telegram",
            ),
        ]
        for key, label_text, value_text in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            label.setObjectName("SettingsRailLabel")
            row.addWidget(label)
            row.addStretch()
            value = QLabel(value_text)
            value.setObjectName("SettingsRailValue")
            row.addWidget(value)
            layout.addLayout(row)

            if key == "interface_mode":
                self._mode_status_value = value

        return card

    def _build_quick_actions(self) -> QFrame:
        card = _make_card("SettingsQuickActionsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(_("Быстрые действия", "Quick actions"))
        title.setObjectName("SettingsRailTitle")
        layout.addWidget(title)

        buttons = [
            (_("API и пресеты", "API and presets"), lambda: self.show_category("api")),
            (_("История персонажа", "Character history"), self._open_db_viewer),
            (_("Экспорт данных", "Export data"), lambda: self.show_category("data")),
            (_("Песочница", "Sandbox"), lambda: self.gui.switch_main_page("sandbox")),
        ]
        for text, callback in buttons:
            button = QPushButton(text)
            button.setObjectName("SettingsQuickActionButton")
            button.clicked.connect(callback)
            layout.addWidget(button)

        return card

    def _open_db_viewer(self):
        try:
            from ui.settings.character_settings.logic import open_db_viewer

            open_db_viewer(self.gui)
        except Exception:
            self.gui.switch_main_page("settings")
            self.show_category("characters")

    def _build_overview_card(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("SettingsOverviewPage")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        hero = _make_card("SettingsOverviewCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 18, 18, 18)
        hero_layout.setSpacing(8)

        heading = QLabel(_("Выбери раздел для тонкой настройки", "Pick a section to fine-tune"))
        heading.setObjectName("SettingsOverviewTitle")
        hero_layout.addWidget(heading)

        text = QLabel(
            _(
                "Секции ниже сохраняют всю текущую логику: API, память, экран, голос, RAG, данные и обслуживание.",
                "The sections below preserve the existing logic: API, memory, screen, voice, RAG, data and maintenance.",
            )
        )
        text.setWordWrap(True)
        text.setObjectName("SettingsOverviewText")
        hero_layout.addWidget(text)
        layout.addWidget(hero)

        shortcuts = QGridLayout()
        shortcuts.setHorizontalSpacing(10)
        shortcuts.setVerticalSpacing(10)
        featured = [
            ("api", _("API и ключи", "API and keys")),
            ("models", _("Модели и память", "Models and memory")),
            ("voice", _("Озвучка", "Voice")),
            ("screen", _("Экран и камера", "Screen and camera")),
        ]
        for index, (key, label_text) in enumerate(featured):
            button = QPushButton(label_text)
            button.setObjectName("SettingsOverviewShortcut")
            button.clicked.connect(lambda checked=False, cat=key: self.show_category(cat))
            shortcuts.addWidget(button, index // 2, index % 2)
        layout.addLayout(shortcuts)
        layout.addStretch(1)
        return wrapper

    def _build_section_containers(self):
        self.settings_containers = {}

        for spec in get_settings_section_specs():
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            scroll_area.setObjectName(f"ScrollArea_{spec.key}")
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

            content_widget = QFrame()
            content_widget.setObjectName(f"ContentWidget_{spec.key}")
            content_layout = QVBoxLayout(content_widget)
            content_layout.setContentsMargins(10, 10, 10, 10)
            content_layout.setSpacing(12)

            header_card = QFrame()
            header_card.setObjectName("SettingsHeroCard")
            header_layout = QVBoxLayout(header_card)
            header_layout.setContentsMargins(18, 18, 18, 18)
            header_layout.setSpacing(6)

            title_label = QLabel(_(spec.title[0], spec.title[1]))
            title_label.setObjectName("SettingsHeroTitle")
            header_layout.addWidget(title_label)

            subtitle_label = QLabel(_(spec.subtitle[0], spec.subtitle[1]))
            subtitle_label.setObjectName("SettingsHeroSubtitle")
            subtitle_label.setWordWrap(True)
            header_layout.addWidget(subtitle_label)

            content_layout.addWidget(header_card)

            builder = spec.builder_ref
            if isinstance(builder, str):
                getattr(self.gui, builder)(content_layout)
            else:
                builder(self.gui, content_layout)

            content_layout.addStretch()
            scroll_area.setWidget(content_widget)
            self.settings_containers[spec.key] = scroll_area
            self.settings_overlay.add_container(scroll_area)
