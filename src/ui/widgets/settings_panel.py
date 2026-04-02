from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
from ui.widgets.settings_overlay_widget import SettingsOverlay
from ui.widgets.settings_icon_button import SettingsIconButton
from utils import _


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

    settings_categories = [
        ("fa6s.gear", _("Общие", "General"), "general"),
        ("fa6s.plug", _("API", "API"), "api"),
        ("fa6s.robot", _("Модели", "Models"), "models"),
        ("fa6s.volume-high", _("Озвучка", "Voice"), "voice"),
        ("fa6s.microphone", _("Микрофон", "Microphone"), "microphone"),
        ("fa6s.user", _("Персонажи", "Characters"), "characters"),
        ("fa6s.display", _("Экран", "Screen"), "screen"),
        ("fa5s.gamepad", _("Игра", "Game"), "game"),
        ("fa6s.bug", _("Отладка", "Debug"), "debug"),
        ("fa6s.newspaper", _("Новости", "News"), "news"),
        ("fa5s.database", _("Данные", "Data"), "data"),
    ]

    for icon_name, tooltip, category in settings_categories:
        btn = SettingsIconButton(icon_name, tooltip)
        btn.clicked.connect(lambda checked, cat=category: gui.show_settings_category(cat))
        panel_layout.addWidget(btn)
        gui.settings_buttons[category] = btn

    panel_layout.addStretch()

    main_layout.addWidget(gui.settings_overlay)
    main_layout.addWidget(settings_panel)