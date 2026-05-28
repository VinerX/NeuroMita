from pathlib import Path

import qtawesome as qta

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.pages.settings.section_registry import SettingsSectionSpec, get_settings_section_specs
from ui.widgets.settings_icon_button import SettingsIconButton
from utils import _

_MODE_RANK = {"basic": 0, "advanced": 1, "full": 2}
_MODE_ALIASES = {
    "basic": {"basic", "базовый", "standard", "стандартный"},
    "advanced": {"advanced", "продвинутый", "expanded", "расширенный"},
    "full": {"full", "полный", "maximum", "максимальный"},
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


class SettingsSectionPage(QFrame):
    def __init__(self, spec: SettingsSectionSpec, parent=None):
        super().__init__(parent)
        self.spec = spec

        self.setObjectName("SettingsSectionPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("SettingsSectionPageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content = QWidget()
        self.content.setObjectName("SettingsSectionPageContent")
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(2, 2, 6, 2)
        content_layout.setSpacing(14)

        self.header = QFrame()
        self.header.setObjectName("SettingsSectionPageHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(18, 18, 18, 18)
        header_layout.setSpacing(16)

        self.icon_box = QLabel()
        self.icon_box.setObjectName("SettingsSectionIcon")
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_box.setFixedSize(38, 38)
        self.icon_box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.icon_box.setPixmap(qta.icon(spec.icon_name, color="#ffd7eb").pixmap(18, 18))
        header_layout.addWidget(self.icon_box, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        self.title_label = QLabel(_(spec.title[0], spec.title[1]))
        self.title_label.setObjectName("SettingsSectionPageTitle")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_col.addWidget(self.title_label)

        self.subtitle_label = QLabel(_(spec.subtitle[0], spec.subtitle[1]))
        self.subtitle_label.setObjectName("SettingsSectionSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_col.addWidget(self.subtitle_label)

        header_layout.addLayout(text_col, 1)

        self.mode_badge = QLabel(get_mode_label(spec.min_mode))
        self.mode_badge.setObjectName("SettingsSectionBadge")
        self.mode_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.mode_badge.setVisible(False)

        self.body = QFrame()
        self.body.setObjectName("SettingsSectionPageBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)

        self.body_host = QFrame()
        self.body_host.setObjectName("SettingsSectionBodyHost")
        self.body_layout = QVBoxLayout(self.body_host)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)
        body_layout.addWidget(self.body_host)

        content_layout.addWidget(self.header)
        content_layout.addWidget(self.body)
        content_layout.addStretch(1)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll)

    def is_expanded(self) -> bool:
        return True

    def expand(self):
        self.body.setVisible(True)

    def collapse(self):
        self.body.setVisible(True)

    def scroll_to_top(self, *, smooth: bool = False, animate=None):
        bar = self.scroll.verticalScrollBar()
        if smooth and callable(animate):
            animate(bar, bar.value(), 0)
        else:
            bar.setValue(0)


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
        self._section_status_value = None
        self._current_mode = "basic"
        self._section_specs = {spec.key: spec for spec in get_settings_section_specs()}
        self._scroll_animation = None
        self._settings_stack = None
        self._page_indexes = {}

        self.SETTINGS_PANEL_WIDTH = max(920, int(getattr(gui, "SETTINGS_PANEL_WIDTH", 980) or 980))
        self.SETTINGS_SIDEBAR_WIDTH = 0
        self.settings_resize_handle = None
        self.settings_scroll = None

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

    def _section_enabled(self, category) -> bool:
        try:
            from ui.widgets.settings_panel import is_section_enabled

            return is_section_enabled(category)
        except Exception:
            return True

    def _first_available_category(self) -> str | None:
        for spec in get_settings_section_specs():
            if self._section_enabled(spec.key):
                return spec.key
        return None

    def _update_nav_state(self):
        active = self.current_settings_category
        for key, button in self.settings_buttons.items():
            button.set_active(key == active)

    def _update_section_status(self):
        if self._section_status_value is None:
            return
        total = len(self.settings_buttons)
        visible = sum(1 for cat in self.settings_buttons if self._section_enabled(cat))
        self._section_status_value.setText(f"{visible}/{total}")

    def apply_section_visibility(self):
        for category, button in self.settings_buttons.items():
            button.setVisible(self._section_enabled(category))

        active = self.current_settings_category
        if active is None or not self._section_enabled(active):
            fallback = self._first_available_category()
            if fallback is not None:
                self._activate_category(fallback, smooth_scroll=False)
            else:
                self._set_current_category(None)

        self._update_section_status()
        self._update_nav_state()

        try:
            from ui.widgets.status_indicators_widget import apply_capture_visibility

            apply_capture_visibility(self.gui)
        except Exception:
            pass

        sidebar = getattr(self.gui, "shell_sidebar", None)
        if sidebar is not None and hasattr(sidebar, "apply_section_visibility"):
            try:
                from ui.widgets.settings_panel import is_section_enabled

                sidebar.apply_section_visibility(is_section_enabled)
            except Exception:
                pass

    def apply_interface_mode(self, mode_value=None):
        # Back-compat: the interface mode dropdown was replaced by per-section
        # toggles. Ignore the legacy argument and apply the current map.
        self.apply_section_visibility()

    def on_activated(self):
        if self.current_settings_category is None:
            first_key = self._first_available_category() or "api"
            self._activate_category(first_key, smooth_scroll=False)

    def show_overview(self, *, scroll_to_top: bool = False):
        fallback = self._first_available_category()
        if fallback is not None:
            self._activate_category(fallback, smooth_scroll=False)
            if scroll_to_top:
                self._scroll_to_top(smooth=False)

    def show_category(self, category, *, smooth_scroll: bool = True):
        if category not in self.settings_containers:
            return
        if not self._section_enabled(category):
            fallback = self._first_available_category()
            if fallback is not None:
                category = fallback
            else:
                return

        was_on_settings_page = getattr(self.gui, "current_main_page", None) == "settings"
        if not was_on_settings_page:
            self.gui.switch_main_page("settings")
            QTimer.singleShot(0, lambda cat=category, smooth=smooth_scroll: self._activate_category(cat, smooth_scroll=smooth))
            return

        self._activate_category(category, smooth_scroll=smooth_scroll)

    def _activate_category(self, category: str, *, smooth_scroll: bool):
        page = self.settings_containers.get(category)
        if page is None:
            return

        if not self._section_enabled(category):
            fallback = self._first_available_category()
            if fallback is not None and fallback != category:
                self._activate_category(fallback, smooth_scroll=False)
            return

        self._set_current_category(category)
        if self._settings_stack is not None:
            self._settings_stack.setCurrentWidget(page)
        self.settings_scroll = getattr(page, "scroll", None)
        self._update_nav_state()
        if smooth_scroll:
            QTimer.singleShot(0, lambda key=category: self._scroll_to_category(key, smooth=True))

    def _scroll_to_category(self, category: str, *, smooth: bool):
        page = self.settings_containers.get(category)
        if page is None or not hasattr(page, "scroll_to_top"):
            return
        page.scroll_to_top(smooth=smooth, animate=self._animate_scroll)

    def _scroll_to_top(self, *, smooth: bool):
        active = self.current_settings_category
        page = self.settings_containers.get(active)
        if page is None or not hasattr(page, "scroll_to_top"):
            return
        page.scroll_to_top(smooth=smooth, animate=self._animate_scroll)

    def _animate_scroll(self, bar, start_value: int, end_value: int):
        if start_value == end_value:
            return
        if self._scroll_animation is not None:
            self._scroll_animation.stop()
        anim = QPropertyAnimation(bar, b"value", self)
        anim.setDuration(320)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.setStartValue(int(start_value))
        anim.setEndValue(int(end_value))
        self._scroll_animation = anim
        anim.start()

    def _build_ui(self):
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(14, 12, 14, 12)
        page_layout.setSpacing(0)

        workspace_shell = QFrame()
        workspace_shell.setObjectName("SettingsWorkspaceRootShell")
        shell_layout = QVBoxLayout(workspace_shell)
        shell_layout.setContentsMargins(14, 12, 14, 12)
        shell_layout.setSpacing(12)

        shell_layout.addWidget(self._build_settings_hero())

        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        self.settings_overlay = _make_card("SettingsWorkspacePanel")
        self.settings_overlay.setMinimumWidth(720)
        self.settings_overlay.setMaximumWidth(16777215)
        self.settings_overlay.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        overlay_layout = QVBoxLayout(self.settings_overlay)
        overlay_layout.setContentsMargins(14, 14, 14, 14)
        overlay_layout.setSpacing(14)
        overlay_layout.addWidget(self._build_tabs_row())

        self._settings_stack = QStackedWidget()
        self._settings_stack.setObjectName("SettingsWorkspaceStack")
        self._settings_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        overlay_layout.addWidget(self._settings_stack, 1)
        content_row.addWidget(self.settings_overlay, 5)

        rail = QWidget()
        rail.setObjectName("SettingsRail")
        rail.setMinimumWidth(308)
        rail.setMaximumWidth(420)
        rail.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(12)
        rail_layout.addWidget(self._build_system_card())
        rail_layout.addWidget(self._build_quick_actions())
        rail_layout.addStretch(1)
        content_row.addWidget(rail, 1)

        shell_layout.addLayout(content_row, 1)
        page_layout.addWidget(workspace_shell, 1)
        self.settings_overview_container = self._settings_stack

    def _build_tabs_row(self) -> QFrame:
        card = _make_card("SettingsTabsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        tabs_scroll = QScrollArea()
        tabs_scroll.setObjectName("SettingsTabsScroll")
        tabs_scroll.setWidgetResizable(False)
        tabs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tabs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tabs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tabs_scroll.setFixedHeight(50)

        tabs_host = QWidget()
        tabs_host.setObjectName("SettingsTabsHost")
        tabs_host.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        tabs_layout = QHBoxLayout(tabs_host)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(6)

        for spec in get_settings_section_specs():
            label = _(spec.nav_label[0], spec.nav_label[1])
            button = SettingsIconButton(spec.icon_name, label, category_key=spec.key)
            button.setMinimumWidth(92)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda checked=False, cat=spec.key: self.show_category(cat))
            tabs_layout.addWidget(button)
            self.settings_buttons[spec.key] = button
            self._category_modes[spec.key] = spec.min_mode

        tabs_layout.addStretch(1)
        tabs_scroll.setWidget(tabs_host)
        layout.addWidget(tabs_scroll)
        return card

    def _build_settings_hero(self) -> QFrame:
        card = QFrame()
        card.setObjectName("SettingsWorkspaceHeader")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(4, 2, 4, 10)
        layout.setSpacing(18)

        title_col = QVBoxLayout()
        title_col.setSpacing(5)

        headline_row = QHBoxLayout()
        headline_row.setSpacing(10)
        headline_row.setContentsMargins(0, 0, 0, 0)

        icon_label = QLabel()
        icon_label.setObjectName("SettingsHeroIcon")
        icon_label.setPixmap(qta.icon("fa6s.gear", color="#ff6db7").pixmap(22, 22))
        headline_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        title = QLabel(_("Настройки", "Settings"))
        title.setObjectName("SettingsHeroTitle")
        headline_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        headline_row.addStretch(1)
        title_col.addLayout(headline_row)

        subtitle = QLabel(
            _(
                "Центр конфигурации NeuroMita. Сохраняем логику, переводим интерфейс в компактный рабочий формат.",
                "NeuroMita configuration hub. Same logic, now presented as a compact workspace.",
            )
        )
        subtitle.setObjectName("SettingsHeroSubtitle")
        subtitle.setWordWrap(True)
        title_col.addWidget(subtitle)
        layout.addLayout(title_col, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        guide_button = QPushButton(_("Руководство", "Guide"))
        guide_button.setObjectName("SettingsHeaderButton")
        guide_button.clicked.connect(self.gui._show_guide)
        actions.addWidget(guide_button)

        home_button = QPushButton(_("На главную", "Home"))
        home_button.setObjectName("SettingsHeaderButton")
        home_button.clicked.connect(lambda: self.gui.switch_main_page("home"))
        actions.addWidget(home_button)

        updates_button = QPushButton(_("Открыть обновления", "Open updates"))
        updates_button.setObjectName("SettingsHeaderPrimaryButton")
        updates_button.clicked.connect(lambda: self.show_category("updates"))
        actions.addWidget(updates_button)

        layout.addLayout(actions)
        return card

    def _build_brand_panel(self) -> QFrame:
        card = _make_card("SettingsStatusRailCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

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

        brand_state = QLabel(_("Актуально", "Current"))
        brand_state.setObjectName("SettingsRailBrandState")
        brand_col.addWidget(brand_state)

        brand_row.addLayout(brand_col, 1)
        layout.addLayout(brand_row)

        build_meta = QLabel(
            _(
                "Сборка: launcher shell + модульные settings builders. Этот блок теперь служит правой стойкой статуса, а не отдельной страницей.",
                "Build: launcher shell + modular settings builders. This block now acts as a status rail rather than a separate page.",
            )
        )
        build_meta.setObjectName("SettingsRailBrandHint")
        build_meta.setWordWrap(True)
        layout.addWidget(build_meta)

        check_button = QPushButton(_("Проверить обновления", "Check updates"))
        check_button.setObjectName("SettingsQuickActionButton")
        check_button.clicked.connect(lambda: self.show_category("updates"))
        layout.addWidget(check_button)

        return card

    def _build_system_card(self) -> QFrame:
        card = _make_card("SettingsStatusRailCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(_("Статус конфигурации", "Configuration status"))
        title.setObjectName("SettingsRailTitle")
        layout.addWidget(title)

        items = [
            (
                "sections",
                _("Видимые разделы", "Visible sections"),
                "",
            ),
            ("language", _("Язык", "Language"), str(self.gui._get_setting("LANGUAGE", "ru")).upper()),
            (
                "memory",
                _("RAG", "RAG"),
                _("Включён", "Enabled") if self.gui._get_setting("RAG_ENABLED", False) else _("Выключен", "Disabled"),
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

            if key == "sections":
                self._section_status_value = value

        self._update_section_status()
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
            (_("Диагностика в песочнице", "Sandbox diagnostics"), self._open_sandbox_debug),
            (_("Песочница", "Sandbox"), lambda: self.gui.switch_main_page("sandbox")),
        ]
        for text, callback in buttons:
            button = QPushButton(text)
            button.setObjectName("SettingsQuickActionButton")
            button.clicked.connect(callback)
            layout.addWidget(button)

        return card

    def _build_note_card(self) -> QFrame:
        card = _make_card("SettingsNoteCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        quote = QLabel(
            _(
                "Настраивай систему как рабочий пульт: секции сверху дают быстрое переключение, а внутри остались те же проверенные builders.",
                "Treat the page like a control console: top chips switch context quickly while the proven builders stay intact underneath.",
            )
        )
        quote.setObjectName("SettingsNoteText")
        quote.setWordWrap(True)
        layout.addWidget(quote)
        return card

    def _open_db_viewer(self):
        try:
            from ui.settings.character_settings.logic import open_db_viewer

            open_db_viewer(self.gui)
        except Exception:
            self.gui.switch_main_page("settings")
            self.show_category("characters")

    def _open_sandbox_debug(self):
        self.gui.switch_main_page("sandbox")
        page = getattr(self.gui, "sandbox_page", None)
        if page is not None and hasattr(page, "show_debug_tab"):
            QTimer.singleShot(0, page.show_debug_tab)

    def _build_section_containers(self):
        self.settings_containers = {}
        self._page_indexes = {}
        if self._settings_stack is None:
            return

        for spec in get_settings_section_specs():
            page = SettingsSectionPage(spec, self._settings_stack)

            builder = spec.builder_ref
            if isinstance(builder, str):
                getattr(self.gui, builder)(page.body_layout)
            else:
                builder(self.gui, page.body_layout)

            self._prepare_settings_subsections(page)

            self.settings_containers[spec.key] = page
            index = self._settings_stack.addWidget(page)
            self._page_indexes[spec.key] = index

    def _prepare_settings_subsections(self, page: SettingsSectionPage):
        for section in page.findChildren(QWidget):
            if section.objectName() != "CollapsibleSection":
                continue
            if hasattr(section, "expand"):
                try:
                    section.expand()
                except Exception:
                    pass
            header = getattr(section, "header", None)
            if header is not None:
                header.setCursor(Qt.CursorShape.ArrowCursor)
                header.mousePressEvent = lambda event, h=header: QWidget.mousePressEvent(h, event)
            arrow = getattr(section, "arrow_label", None)
            if arrow is not None:
                arrow.hide()
