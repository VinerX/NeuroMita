from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.settings_icon_button import SettingsIconButton
from ui.widgets.settings_overlay_widget import SettingsOverlay
from utils import _

_MODE_RANK = {"basic": 0, "advanced": 1, "full": 2}


def normalize_mode(v):
    m = (v or "").strip().lower()
    if m in ("advanced", "продвинутый"):
        return "advanced"
    if m in ("full", "полный"):
        return "full"
    return "basic"


def apply_interface_mode(gui, mode_value):
    mode = normalize_mode(mode_value)
    cur_rank = _MODE_RANK[mode]
    for cat, btn in gui.settings_buttons.items():
        need = _MODE_RANK[gui._category_modes.get(cat, "basic")]
        btn.setVisible(need <= cur_rank)

    active = getattr(gui, "current_settings_category", None)
    if active:
        active_rank = _MODE_RANK[gui._category_modes.get(active, "basic")]
        if active_rank > cur_rank:
            gui.show_settings_category(active)

    try:
        from ui.widgets.status_indicators_widget import apply_capture_visibility

        apply_capture_visibility(gui, mode)
    except Exception:
        pass


def _make_card(name: str) -> QFrame:
    card = QFrame()
    card.setObjectName(name)
    return card


def _build_settings_hero(gui) -> QFrame:
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
    guide_button.clicked.connect(gui._show_guide)
    actions.addWidget(guide_button)

    updates_button = QPushButton(_("Обновления", "Updates"))
    updates_button.setObjectName("SecondaryButton")
    updates_button.clicked.connect(lambda: gui.show_settings_category("updates"))
    actions.addWidget(updates_button)

    home_button = QPushButton(_("На главную", "Home"))
    home_button.setObjectName("SecondaryButton")
    home_button.clicked.connect(lambda: gui.switch_main_page("home"))
    actions.addWidget(home_button)

    top_row.addLayout(actions)
    layout.addLayout(top_row)

    return card


def _build_brand_panel() -> QFrame:
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


def _build_system_card(gui) -> QFrame:
    card = _make_card("SettingsStatusRailCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    title = QLabel(_("Состояние конфигурации", "Configuration status"))
    title.setObjectName("SettingsRailTitle")
    layout.addWidget(title)

    items = [
        (_("Режим интерфейса", "Interface mode"), str(gui._get_setting("INTERFACE_MODE", _("Базовый", "Basic")))),
        (_("Язык", "Language"), str(gui._get_setting("LANGUAGE", "ru")).upper()),
        (_("Память", "Memory"), _("Включена", "Enabled") if gui._get_setting("RAG_ENABLED", False) else _("Выключена", "Disabled")),
        (_("Озвучка", "Voice"), _("Локально", "Local") if str(gui._get_setting("VOICEOVER_METHOD", "TG")).lower() == "local" else "Telegram"),
    ]
    for label_text, value_text in items:
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

    return card


def _build_quick_actions(gui) -> QFrame:
    card = _make_card("SettingsQuickActionsCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    title = QLabel(_("Быстрые действия", "Quick actions"))
    title.setObjectName("SettingsRailTitle")
    layout.addWidget(title)

    buttons = [
        (_("API и пресеты", "API and presets"), lambda: gui.show_settings_category("api")),
        (_("История персонажа", "Character history"), lambda: _open_db_viewer(gui)),
        (_("Экспорт данных", "Export data"), lambda: gui.show_settings_category("data")),
        (_("Песочница", "Sandbox"), lambda: gui.switch_main_page("sandbox")),
    ]
    for text, callback in buttons:
        button = QPushButton(text)
        button.setObjectName("SettingsQuickActionButton")
        button.clicked.connect(callback)
        layout.addWidget(button)

    return card


def _open_db_viewer(gui):
    try:
        from ui.settings.character_settings.logic import open_db_viewer

        open_db_viewer(gui)
    except Exception:
        gui.switch_main_page("settings")
        gui.show_settings_category("characters")


def _build_overview_card(gui) -> QWidget:
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
        button.clicked.connect(lambda checked=False, cat=key: gui.show_settings_category(cat))
        shortcuts.addWidget(button, index // 2, index % 2)
    layout.addLayout(shortcuts)
    layout.addStretch(1)

    return wrapper


def create_settings_page(gui) -> QWidget:
    page = QWidget()
    page.setObjectName("SettingsPageRoot")

    outer = QVBoxLayout(page)
    outer.setContentsMargins(22, 18, 22, 18)
    outer.setSpacing(14)

    outer.addWidget(_build_settings_hero(gui))

    tabs_card = _make_card("SettingsTabsCard")
    tabs_layout = QGridLayout(tabs_card)
    tabs_layout.setContentsMargins(14, 14, 14, 14)
    tabs_layout.setHorizontalSpacing(10)
    tabs_layout.setVerticalSpacing(10)
    outer.addWidget(tabs_card)

    content_row = QHBoxLayout()
    content_row.setSpacing(14)

    gui.settings_overlay = SettingsOverlay(gui)
    gui.settings_overlay.setObjectName("SettingsPageOverlay")
    gui.settings_overlay.setMinimumWidth(640)
    gui.settings_overlay.setMaximumWidth(1400)
    gui.SETTINGS_PANEL_WIDTH = 920
    gui.SETTINGS_SIDEBAR_WIDTH = 0
    gui.settings_resize_handle = None
    content_row.addWidget(gui.settings_overlay, 1)

    rail = QWidget()
    rail.setObjectName("SettingsRail")
    rail.setFixedWidth(300)
    rail_layout = QVBoxLayout(rail)
    rail_layout.setContentsMargins(0, 0, 0, 0)
    rail_layout.setSpacing(12)
    rail_layout.addWidget(_build_brand_panel())
    rail_layout.addWidget(_build_system_card(gui))
    rail_layout.addWidget(_build_quick_actions(gui))
    rail_layout.addStretch(1)
    content_row.addWidget(rail)

    outer.addLayout(content_row, 1)

    gui.settings_buttons = {}
    gui._category_modes = {}

    settings_categories = [
        ("fa6s.gear", _("General", "General"), "general", "basic"),
        ("fa6s.plug", _("API", "API"), "api", "basic"),
        ("fa6s.user", _("Characters", "Characters"), "characters", "basic"),
        ("fa6s.volume-high", _("Voice", "Voice"), "voice", "advanced"),
        ("fa6s.microphone", _("ASR", "ASR"), "microphone", "advanced"),
        ("fa5s.gamepad", _("Game", "Game"), "game", "advanced"),
        ("fa6s.robot", _("Models", "Models"), "models", "full"),
        ("fa6s.display", _("Screen", "Screen"), "screen", "full"),
        ("fa6s.bug", _("Debug", "Debug"), "debug", "full"),
        ("fa6s.newspaper", _("News", "News"), "news", "full"),
        ("fa5s.database", _("Data", "Data"), "data", "full"),
        ("fa6s.rotate", _("Updates", "Updates"), "updates", "advanced"),
    ]

    for index, (icon_name, label, category, min_mode) in enumerate(settings_categories):
        btn = SettingsIconButton(icon_name, label, category_key=category)
        btn.clicked.connect(lambda checked=False, cat=category: gui.show_settings_category(cat))
        tabs_layout.addWidget(btn, index // 4, index % 4)
        gui.settings_buttons[category] = btn
        gui._category_modes[category] = min_mode

    gui.settings_overview_container = _build_overview_card(gui)
    gui.settings_overlay.add_container(gui.settings_overview_container)
    gui.settings_overlay.show_category(gui.settings_overview_container)

    return page
