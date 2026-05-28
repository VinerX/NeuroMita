from pathlib import Path

import qtawesome as qta

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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


class SettingsCategoryCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, spec: SettingsSectionSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._expanded = False

        self.setObjectName("SettingsSectionCard")
        self.setProperty("expanded", False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("SettingsSectionHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(18, 19, 18, 14)
        header_layout.setSpacing(14)

        self.icon_box = QLabel()
        self.icon_box.setObjectName("SettingsSectionIcon")
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_box.setFixedSize(38, 38)
        self.icon_box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.icon_box.setPixmap(qta.icon(spec.icon_name, color="#ffd7eb").pixmap(18, 18))
        header_layout.addWidget(self.icon_box, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        self.title_label = QLabel(_(spec.nav_label[0], spec.nav_label[1]))
        self.title_label.setObjectName("SettingsSectionTitle")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_col.addWidget(self.title_label)

        self.subtitle_label = QLabel(_(spec.subtitle[0], spec.subtitle[1]))
        self.subtitle_label.setObjectName("SettingsSectionSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_col.addWidget(self.subtitle_label)

        header_layout.addLayout(text_col, 1)

        meta_col = QVBoxLayout()
        meta_col.setSpacing(6)
        meta_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.mode_badge = QLabel(get_mode_label(spec.min_mode))
        self.mode_badge.setObjectName("SettingsSectionBadge")
        self.mode_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Interface modes were replaced by per-section toggles; the badge is
        # kept for layout/QSS compatibility but no longer shown.
        self.mode_badge.setVisible(False)
        meta_col.addWidget(self.mode_badge, 0, Qt.AlignmentFlag.AlignRight)

        self.chevron_label = QLabel()
        self.chevron_label.setObjectName("SettingsSectionChevron")
        self.chevron_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        meta_col.addWidget(self.chevron_label, 0, Qt.AlignmentFlag.AlignRight)

        header_layout.addLayout(meta_col)

        self.body = QFrame()
        self.body.setObjectName("SettingsSectionBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(18, 0, 18, 18)
        body_layout.setSpacing(12)

        self.body_host = QFrame()
        self.body_host.setObjectName("SettingsSectionBodyHost")
        self.body_layout = QVBoxLayout(self.body_host)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)
        body_layout.addWidget(self.body_host)

        root.addWidget(self.header)
        root.addWidget(self.body)

        self.header.mousePressEvent = self._handle_header_press
        self.body.setVisible(False)
        self.body.setMaximumHeight(0)
        self.set_expanded(False)

    def _handle_header_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        QFrame.mousePressEvent(self.header, event)

    def set_expanded(self, expanded: bool):
        target_state = bool(expanded)
        if self._expanded == target_state and ((target_state and self.body.isVisible()) or (not target_state and not self.body.isVisible())):
            return

        self._expanded = target_state
        self.setProperty("expanded", self._expanded)
        self.header.setProperty("expanded", self._expanded)
        chevron = "fa6s.angle-up" if self._expanded else "fa6s.angle-down"
        self.chevron_label.setPixmap(qta.icon(chevron, color="#f6d7ea").pixmap(16, 16))
        self._repolish()
        self._apply_body_state()

    def is_expanded(self) -> bool:
        return self._expanded

    def expand(self):
        self.set_expanded(True)

    def collapse(self):
        self.set_expanded(False)

    def _repolish(self):
        for widget in (self, self.header):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _apply_body_state(self):
        if self._expanded:
            self.body.setVisible(True)
            self.body.setMaximumHeight(16777215)
        else:
            self.body.setMaximumHeight(0)
            self.body.setVisible(False)


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
        self._forced_visible_categories = set()
        self._section_specs = {spec.key: spec for spec in get_settings_section_specs()}
        self._scroll_animation = None

        self.SETTINGS_PANEL_WIDTH = max(920, int(getattr(gui, "SETTINGS_PANEL_WIDTH", 980) or 980))
        self.SETTINGS_SIDEBAR_WIDTH = 0
        self.settings_resize_handle = None
        self.settings_scroll = None
        self._workspace_content = None

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

        for category, card in self.settings_containers.items():
            card.setVisible(self._section_enabled(category) or category in self._forced_visible_categories)

        active = self.current_settings_category
        if active and not self._section_enabled(active) and active not in self._forced_visible_categories:
            fallback = self._first_available_category()
            if fallback is not None:
                self._activate_category(fallback, toggle_if_active=False, smooth_scroll=False)
            else:
                self.show_overview()

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
            self._activate_category(first_key, toggle_if_active=False, smooth_scroll=False)

    def show_overview(self, *, scroll_to_top: bool = False):
        self._set_current_category(None)
        self._batch_toggle_cards(None)
        self._update_nav_state()
        if scroll_to_top:
            self._scroll_to_top(smooth=False)

    def show_category(self, category, *, smooth_scroll: bool = True):
        if category not in self.settings_containers:
            return

        was_on_settings_page = getattr(self.gui, "current_main_page", None) == "settings"
        if not was_on_settings_page:
            self.gui.switch_main_page("settings")
            QTimer.singleShot(0, lambda cat=category, smooth=smooth_scroll: self._activate_category(cat, toggle_if_active=False, smooth_scroll=smooth))
            return

        self._activate_category(category, toggle_if_active=self.current_settings_category == category, smooth_scroll=smooth_scroll)

    def _toggle_category_from_card(self, category: str):
        self._activate_category(category, toggle_if_active=True, smooth_scroll=False)

    def _activate_category(self, category: str, *, toggle_if_active: bool, smooth_scroll: bool):
        card = self.settings_containers.get(category)
        if card is None:
            return

        if not card.isVisible():
            self._forced_visible_categories.add(category)
            card.setVisible(True)

        if toggle_if_active and card.is_expanded():
            self.show_overview(scroll_to_top=False)
            return

        self._batch_toggle_cards(category)

        self._set_current_category(category)
        self._update_nav_state()
        if smooth_scroll:
            QTimer.singleShot(0, lambda key=category: self._scroll_to_category(key, smooth=True))

    def _batch_toggle_cards(self, expanded_key: str | None):
        widgets = []
        if self._workspace_content is not None:
            widgets.append(self._workspace_content)
        if self.settings_scroll is not None:
            widgets.append(self.settings_scroll)
            viewport = self.settings_scroll.viewport()
            if viewport is not None:
                widgets.append(viewport)

        for widget in widgets:
            widget.setUpdatesEnabled(False)
        try:
            for key, other_card in self.settings_containers.items():
                if key == expanded_key:
                    other_card.expand()
                else:
                    other_card.collapse()
        finally:
            for widget in reversed(widgets):
                widget.setUpdatesEnabled(True)
                widget.update()

    def _scroll_to_category(self, category: str, *, smooth: bool):
        if self.settings_scroll is None or self._workspace_content is None:
            return

        card = self.settings_containers.get(category)
        if card is None:
            return

        bar = self.settings_scroll.verticalScrollBar()
        target = max(0, card.y() - 10)
        if not smooth:
            bar.setValue(target)
            return
        self._animate_scroll(bar.value(), target)

    def _scroll_to_top(self, *, smooth: bool):
        if self.settings_scroll is None:
            return
        bar = self.settings_scroll.verticalScrollBar()
        if smooth:
            self._animate_scroll(bar.value(), 0)
        else:
            bar.setValue(0)

    def _animate_scroll(self, start_value: int, end_value: int):
        if self.settings_scroll is None:
            return
        bar = self.settings_scroll.verticalScrollBar()
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

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("SettingsWorkspaceScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._workspace_content = QWidget()
        self._workspace_content.setObjectName("SettingsWorkspaceContent")
        self._workspace_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        workspace_layout = QVBoxLayout(self._workspace_content)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(12)
        self.settings_scroll.setWidget(self._workspace_content)

        overlay_layout.addWidget(self.settings_scroll, 1)
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
        self.settings_overview_container = self._workspace_content

    def _build_tabs_row(self) -> QFrame:
        card = _make_card("SettingsTabsCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(4)

        for spec in get_settings_section_specs():
            label = _(spec.nav_label[0], spec.nav_label[1])
            button = SettingsIconButton(spec.icon_name, label, category_key=spec.key)
            button.clicked.connect(lambda checked=False, cat=spec.key: self.show_category(cat))
            layout.addWidget(button)
            self.settings_buttons[spec.key] = button
            self._category_modes[spec.key] = spec.min_mode

        layout.addStretch(1)
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
        if self._workspace_content is None or self._workspace_content.layout() is None:
            return

        workspace_layout = self._workspace_content.layout()

        for spec in get_settings_section_specs():
            card = SettingsCategoryCard(spec, self._workspace_content)
            card.clicked.connect(lambda key=spec.key: self._toggle_category_from_card(key))

            builder = spec.builder_ref
            if isinstance(builder, str):
                getattr(self.gui, builder)(card.body_layout)
            else:
                builder(self.gui, card.body_layout)

            self.settings_containers[spec.key] = card
            workspace_layout.addWidget(card)

        workspace_layout.addStretch(1)
