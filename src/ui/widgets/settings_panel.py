from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
from ui.widgets.settings_overlay_widget import SettingsOverlay
from ui.widgets.settings_icon_button import SettingsIconButton
from utils import _

_MODE_RANK = {"basic": 0, "advanced": 1, "full": 2}


def normalize_mode(v):
    m = (v or '').strip().lower()
    if m in ('advanced', 'продвинутый'):
        return 'advanced'
    if m in ('full', 'полный'):
        return 'full'
    return 'basic'


def apply_interface_mode(gui, mode_value):
    mode = normalize_mode(mode_value)
    cur_rank = _MODE_RANK[mode]
    for cat, btn in gui.settings_buttons.items():
        need = _MODE_RANK[gui._category_modes.get(cat, 'basic')]
        btn.setVisible(need <= cur_rank)
    # если активная категория стала скрытой — свернуть overlay
    active = getattr(gui, 'current_settings_category', None)
    if active:
        active_rank = _MODE_RANK[gui._category_modes.get(active, 'basic')]
        if active_rank > cur_rank:
            gui.show_settings_category(active)  # toggle = hide
    # обновить индикаторы захвата
    try:
        from ui.widgets.status_indicators_widget import apply_capture_visibility
        apply_capture_visibility(gui, mode)
    except Exception:
        pass


def setup_settings_panel(gui, main_layout):
    settings_panel = QWidget()
    settings_panel.setFixedWidth(50)
    gui.SETTINGS_SIDEBAR_WIDTH = 50
    settings_panel.setObjectName("SettingsSidebar")

    panel_layout = QVBoxLayout(settings_panel)
    panel_layout.setContentsMargins(5, 10, 5, 10)
    panel_layout.setSpacing(5)

    gui.settings_overlay = SettingsOverlay(gui)
    gui.settings_overlay.setMaximumWidth(0)
    gui.settings_overlay.hide()

    gui.settings_buttons = {}
    gui._category_modes = {}

    settings_categories = [
        ("fa6s.gear",       _("Общие",      "General"),     "general",    "basic"),
        ("fa6s.plug",       _("API",         "API"),         "api",        "basic"),
        ("fa6s.user",       _("Персонажи",   "Characters"),  "characters", "basic"),
        ("fa6s.volume-high",_("Озвучка",     "Voice"),       "voice",      "advanced"),
        ("fa6s.microphone", _("Микрофон",    "Microphone"),  "microphone", "advanced"),
        ("fa5s.gamepad",    _("Игра",        "Game"),        "game",       "advanced"),
        ("fa6s.robot",      _("Модели",      "Models"),      "models",     "full"),
        ("fa6s.display",    _("Экран",       "Screen"),      "screen",     "full"),
        ("fa6s.bug",        _("Отладка",     "Debug"),       "debug",      "full"),
        ("fa6s.newspaper",  _("Новости",     "News"),        "news",       "full"),
        ("fa5s.database",   _("Данные",      "Data"),        "data",       "full"),
    ]

    for icon_name, tooltip, category, min_mode in settings_categories:
        btn = SettingsIconButton(icon_name, tooltip)
        btn.clicked.connect(lambda checked, cat=category: gui.show_settings_category(cat))
        panel_layout.addWidget(btn)
        gui.settings_buttons[category] = btn
        gui._category_modes[category] = min_mode

    panel_layout.addStretch()

    main_layout.addWidget(gui.settings_overlay)
    main_layout.addWidget(settings_panel)
