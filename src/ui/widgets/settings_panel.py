from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QFrame, QVBoxLayout, QWidget

from ui.widgets.settings_overlay_widget import SettingsOverlay, SettingsResizeHandle
from ui.widgets.settings_icon_button import SettingsIconButton
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


def _build_brand_card() -> QFrame:
    card = QFrame()
    card.setObjectName("LauncherBrandCard")

    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(8)

    icon_label = QLabel()
    icon_label.setObjectName("LauncherBrandIcon")
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_path = Path("Icon.png")
    if icon_path.exists():
        pixmap = QPixmap(str(icon_path)).scaled(
            52,
            52,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        icon_label.setPixmap(pixmap)
    layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignLeft)

    title = QLabel("NeuroMita")
    title.setObjectName("LauncherBrandTitle")
    layout.addWidget(title)

    subtitle = QLabel(_("Неоновый чат-лаунчер", "Neon chat launcher"))
    subtitle.setObjectName("LauncherBrandSubtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)

    return card


def _build_footer_card() -> QFrame:
    card = QFrame()
    card.setObjectName("LauncherFooterCard")

    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(6)

    status = QLabel(_("Система готова", "System ready"))
    status.setObjectName("LauncherFooterStatus")
    layout.addWidget(status)

    hint = QLabel(
        _(
            "Открой раздел настроек слева, чтобы менять API, память, игру, экран и голос.",
            "Open a section on the left to manage API, memory, game, screen and voice.",
        )
    )
    hint.setObjectName("LauncherFooterHint")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    return card


def setup_settings_panel(gui, main_layout):
    settings_panel = QWidget()
    settings_panel.setFixedWidth(248)
    gui.SETTINGS_SIDEBAR_WIDTH = 248
    settings_panel.setObjectName("SettingsSidebar")

    panel_layout = QVBoxLayout(settings_panel)
    panel_layout.setContentsMargins(16, 18, 16, 18)
    panel_layout.setSpacing(12)

    panel_layout.addWidget(_build_brand_card())

    nav_title = QLabel(_("Разделы", "Sections"))
    nav_title.setObjectName("SettingsSidebarTitle")
    panel_layout.addWidget(nav_title)

    gui.settings_overlay = SettingsOverlay(gui)
    gui.settings_overlay.setMaximumWidth(0)
    gui.settings_overlay.hide()

    gui.settings_resize_handle = SettingsResizeHandle(gui.settings_overlay, gui)
    gui.SETTINGS_RESIZE_HANDLE_WIDTH = gui.settings_resize_handle.width()
    gui.settings_resize_handle.hide()

    gui.settings_buttons = {}
    gui._category_modes = {}

    settings_categories = [
        ("fa6s.gear", _("Общие", "General"), "general", "basic"),
        ("fa6s.plug", _("API", "API"), "api", "basic"),
        ("fa6s.user", _("Персонажи", "Characters"), "characters", "basic"),
        ("fa6s.volume-high", _("Озвучка", "Voice"), "voice", "advanced"),
        ("fa6s.microphone", _("Микрофон", "Microphone"), "microphone", "advanced"),
        ("fa5s.gamepad", _("Игра", "Game"), "game", "advanced"),
        ("fa6s.robot", _("Модели", "Models"), "models", "full"),
        ("fa6s.display", _("Экран", "Screen"), "screen", "full"),
        ("fa6s.bug", _("Отладка", "Debug"), "debug", "full"),
        ("fa6s.newspaper", _("Новости", "News"), "news", "full"),
        ("fa5s.database", _("Данные", "Data"), "data", "full"),
        ("fa6s.rotate", _("Обновления", "Updates"), "updates", "advanced"),
    ]

    for icon_name, label, category, min_mode in settings_categories:
        btn = SettingsIconButton(icon_name, label, category_key=category)
        btn.clicked.connect(lambda checked=False, cat=category: gui.show_settings_category(cat))
        panel_layout.addWidget(btn)
        gui.settings_buttons[category] = btn
        gui._category_modes[category] = min_mode

    panel_layout.addStretch()
    panel_layout.addWidget(_build_footer_card())

    main_layout.addWidget(settings_panel)
    main_layout.addWidget(gui.settings_overlay)
    main_layout.addWidget(gui.settings_resize_handle)
