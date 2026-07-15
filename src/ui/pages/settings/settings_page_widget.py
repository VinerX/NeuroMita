import qtawesome as qta

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.pages.settings.section_registry import (
    SettingsSectionSpec,
    get_settings_section_specs,
)
from ui.pages.settings.section_access import is_section_enabled
from ui.pages.settings.settings_presentation import (
    PrepareSettingsSection,
    SettingsSectionFailed,
    SettingsSectionReady,
)
from ui.widgets.flow_layout import FlowLayout as _FlowLayout
from ui.widgets.settings_icon_button import SettingsIconButton
from main_logger import logger
from utils import _
from localization.live import tr_set
from localization.live import register_if_tr

_MODE_RANK = {"basic": 0, "advanced": 1, "full": 2}
_MODE_ALIASES = {
    "basic": {"basic", "базовый", "standard", "стандартный"},
    "advanced": {"advanced", "продвинутый", "expanded", "расширенный"},
    "full": {"full", "полный", "maximum", "максимальный"},
}

_SECTION_FEATURES: dict[str, tuple[str, ...]] = {
    # Model metadata is supplied by LocalVoiceController; the voice catalog is
    # built only after that provider is ready. Both import and construction run
    # in the runtime-feature pool, never on the Qt thread.
    "voice": ("local_voice", "voice_models"),
    "microphone": ("speech",),
}

_SECTION_GUI_FEATURES: dict[str, str] = {
    "voice": "voice",
    "microphone": "speech",
}

_BACKEND_REQUIRED_SECTIONS = frozenset({"api", "characters", "models"})


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
        content_layout.setContentsMargins(2, 0, 6, 2)
        content_layout.setSpacing(8)

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
    def __init__(self, parent, view_model, page_actions, settings):
        super().__init__(parent)
        self._view_model = view_model
        self._page_actions = page_actions
        self._settings = settings
        self.setObjectName("SettingsPageRoot")

        self.settings_buttons = {}
        self._category_modes = {}
        self.settings_containers = {}
        self.settings_overview_container = None
        self.settings_overlay = None
        self.current_settings_category = None
        self._current_mode = "basic"
        self._section_specs = {spec.key: spec for spec in get_settings_section_specs()}
        self._scroll_animation = None
        self._settings_stack = None
        self._page_indexes = {}
        self._tabs_host = None
        self._loaded_sections = set()
        self._loading_sections = set()
        self._pending_section_scroll = {}

        width_getter = getattr(settings, "get", None)
        stored_width = width_getter("SETTINGS_PANEL_WIDTH", 980) if callable(width_getter) else 980
        self.SETTINGS_PANEL_WIDTH = max(920, int(stored_width or 980))
        self.SETTINGS_SIDEBAR_WIDTH = 0
        self.settings_resize_handle = None
        self.settings_scroll = None

        self._build_ui()
        self._build_section_containers()
        self._view_model.effect_emitted.connect(self._handle_effect)
        self.destroyed.connect(lambda *_args: self._view_model.close())
        # Сразу применяем карту видимости, иначе до первого клика в «Видимых
        # разделах» показываются все вкладки, включая отключённые.
        self.apply_section_visibility()

    def _set_current_category(self, category):
        self.current_settings_category = category

    @property
    def category_modes(self):
        return self._category_modes

    def _sync_mode_widgets(self, mode_value):
        self._page_actions.sync_settings_mode_widgets(mode_value)

    def _section_enabled(self, category) -> bool:
        try:
            return is_section_enabled(category, self._settings)
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

    def apply_section_visibility(self):
        for category, button in self.settings_buttons.items():
            button.setVisible(self._section_enabled(category))
        self._relayout_tabs()

        active = self.current_settings_category
        if active is None or not self._section_enabled(active):
            fallback = self._first_available_category()
            if fallback is not None and self._page_actions.is_current("settings"):
                self._activate_category(fallback, smooth_scroll=False)
            else:
                self._set_current_category(None)

        self._update_nav_state()

        self._page_actions.apply_settings_aux_visibility()

    def apply_interface_mode(self, mode_value=None):
        # Back-compat: the interface mode dropdown was replaced by per-section
        # toggles. Ignore the legacy argument and apply the current map.
        self.apply_section_visibility()

    def on_activated(self):
        if self.current_settings_category is None:
            first_key = self._first_available_category() or "api"
            self._activate_category(first_key, smooth_scroll=False)

        self._page_actions.refresh_tester_code()

    def show_overview(self, *, scroll_to_top: bool = False):
        fallback = self._first_available_category()
        if fallback is not None:
            self._activate_category(fallback, smooth_scroll=False)
            if scroll_to_top:
                self._scroll_to_top(smooth=False)

    def show_category(self, category, *, smooth_scroll: bool = True, force: bool = False, subsection=None):
        # force=True — пользователь явно перешёл в конкретный раздел (шестерёнка
        # подсистемы), показываем его даже если секция скрыта в «Видимых разделах»,
        # а не уводим в «Общие» (фидбэк #14: «пересылает вникуда»).
        # subsection — заголовок(и) вложенной CollapsibleSection (например «RAG»):
        # после перехода она разворачивается и подскролливается к началу, чтобы
        # сразу попасть в нужное поле, а не в начало длинной страницы (фидбэк Артёма).
        if category not in self.settings_containers:
            return
        if not force and not self._section_enabled(category):
            fallback = self._first_available_category()
            if fallback is not None:
                category = fallback
            else:
                return

        was_on_settings_page = self._page_actions.is_current("settings")
        if not was_on_settings_page:
            self._page_actions.switch_page("settings")
            QTimer.singleShot(0, lambda cat=category, smooth=smooth_scroll, f=force, sub=subsection: self._activate_category(cat, smooth_scroll=smooth, force=f, subsection=sub))
            return

        self._activate_category(category, smooth_scroll=smooth_scroll, force=force, subsection=subsection)

    def _activate_category(self, category: str, *, smooth_scroll: bool, force: bool = False, subsection=None):
        page = self.settings_containers.get(category)
        if page is None:
            return

        if not force and not self._section_enabled(category):
            fallback = self._first_available_category()
            if fallback is not None and fallback != category:
                self._activate_category(fallback, smooth_scroll=False)
            return

        self._set_current_category(category)
        if self._settings_stack is not None:
            self._settings_stack.setCurrentWidget(page)
        self.settings_scroll = getattr(page, "scroll", None)
        self._update_nav_state()
        if category == "updates":
            self._page_actions.refresh_tester_code()

        if category not in self._loaded_sections:
            self._ensure_section_loaded(category, subsection=subsection, smooth_scroll=smooth_scroll)
            return

        if subsection:
            # Разворачиваем целевую подсекцию и скроллим к ней (с задержкой —
            # дать layout пересобраться после expand).
            QTimer.singleShot(0, lambda p=page, sub=subsection, smooth=smooth_scroll: self._scroll_to_subsection(p, sub, smooth=smooth))
        elif smooth_scroll:
            QTimer.singleShot(0, lambda key=category: self._scroll_to_category(key, smooth=True))

    def _find_subsection(self, page, candidates):
        """Найти вложенную CollapsibleSection страницы по заголовку (без учёта
        регистра, точное совпадение или вхождение). candidates — строка или
        список вариантов заголовка на разных языках."""
        if isinstance(candidates, str):
            candidates = (candidates,)
        wanted = [str(c).strip().lower() for c in candidates if str(c).strip()]
        if not wanted:
            return None
        for section in page.findChildren(QWidget):
            if section.objectName() != "CollapsibleSection":
                continue
            title_label = getattr(section, "title_label", None)
            if title_label is None:
                continue
            title = title_label.text().strip().lower()
            if not title:
                continue
            if any(title == w or w in title for w in wanted):
                return section
        return None

    def _scroll_to_subsection(self, page, candidates, *, smooth: bool):
        section = self._find_subsection(page, candidates)
        scroll = getattr(page, "scroll", None)
        if section is None or scroll is None:
            # Не нашли подсекцию — хотя бы откроем начало страницы.
            if hasattr(page, "scroll_to_top"):
                page.scroll_to_top(smooth=smooth, animate=self._animate_scroll)
            return
        try:
            if getattr(section, "is_collapsed", False) and hasattr(section, "expand"):
                section.expand()
        except Exception:
            pass
        # После expand геометрия меняется — считаем целевую позицию в следующем тике.
        QTimer.singleShot(0, lambda s=section, sc=scroll, sm=smooth: self._do_scroll_to_widget(s, sc, smooth=sm))

    def _do_scroll_to_widget(self, widget, scroll, *, smooth: bool):
        content = scroll.widget()
        if content is None:
            return
        top_left = widget.mapTo(content, widget.rect().topLeft())
        bar = scroll.verticalScrollBar()
        target = max(0, min(bar.maximum(), top_left.y() - 12))
        if smooth:
            self._animate_scroll(bar, bar.value(), target)
        else:
            bar.setValue(target)

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
        content_row.addWidget(self.settings_overlay, 1)

        shell_layout.addLayout(content_row, 1)
        page_layout.addWidget(workspace_shell, 1)
        self.settings_overview_container = self._settings_stack

    def _build_tabs_row(self) -> QFrame:
        card = _make_card("SettingsTabsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs_host = QWidget()
        self._tabs_host.setObjectName("SettingsTabsHost")
        host_policy = self._tabs_host.sizePolicy()
        host_policy.setHeightForWidth(True)
        host_policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        self._tabs_host.setSizePolicy(host_policy)

        flow = _FlowLayout(self._tabs_host, margin=0, hspacing=10, vspacing=6, justify=False, center=True)

        tab_buttons = []
        for spec in get_settings_section_specs():
            label = _(spec.nav_label[0], spec.nav_label[1])
            button = SettingsIconButton(spec.icon_name, label, category_key=spec.key)
            register_if_tr(button, label, "setText")
            # Fixed horizontal policy so each tab keeps a uniform width (set
            # below) — no stretching, no empty gaps. The flow centers the row
            # as a group and wraps to a new line instead of scrolling.
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda checked=False, cat=spec.key: self.show_category(cat))
            flow.addWidget(button)
            self.settings_buttons[spec.key] = button
            self._category_modes[spec.key] = spec.min_mode
            tab_buttons.append(button)

        layout.addWidget(self._tabs_host)
        return card

    def _relayout_tabs(self):
        host = getattr(self, "_tabs_host", None)
        if host is None:
            return
        lay = host.layout()
        if lay is not None:
            lay.invalidate()
        host.updateGeometry()

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

        title = tr_set(QLabel(), "Настройки", "Settings")
        register_if_tr(title, _("Настройки", "Settings"))
        title.setObjectName("SettingsHeroTitle")
        headline_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        headline_row.addStretch(1)
        title_col.addLayout(headline_row)

        _subtitle_text = _(
            "Все параметры NeuroMita в одном месте: персонажи, голос, модели ИИ, память и обновления.",
            "Every NeuroMita setting in one place: characters, voice, AI models, memory and updates.",
        )
        subtitle = QLabel(_subtitle_text)
        register_if_tr(subtitle, _subtitle_text)
        subtitle.setObjectName("SettingsHeroSubtitle")
        subtitle.setWordWrap(True)
        title_col.addWidget(subtitle)
        layout.addLayout(title_col, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        guide_button = tr_set(QPushButton(), "Руководство", "Guide")
        register_if_tr(guide_button, _("Руководство", "Guide"))
        guide_button.setObjectName("SettingsHeaderButton")
        guide_button.clicked.connect(self._page_actions.show_guide)
        actions.addWidget(guide_button)

        wiki_button = tr_set(QPushButton(), "Вики", "Wiki")
        wiki_button.setObjectName("SettingsHeaderButton")
        wiki_button.clicked.connect(lambda: self._page_actions.switch_page("wiki"))
        actions.addWidget(wiki_button)

        home_button = tr_set(QPushButton(), "На главную", "Home")
        register_if_tr(home_button, _("На главную", "Home"))
        home_button.setObjectName("SettingsHeaderButton")
        home_button.clicked.connect(lambda: self._page_actions.switch_page("home"))
        actions.addWidget(home_button)

        updates_button = tr_set(QPushButton(), "Открыть обновления", "Open updates")
        register_if_tr(updates_button, _("Открыть обновления", "Open updates"))
        updates_button.setObjectName("SettingsHeaderPrimaryButton")
        updates_button.clicked.connect(lambda: self.show_category("updates"))
        actions.addWidget(updates_button)

        layout.addLayout(actions)
        return card

    def _build_section_containers(self):
        self.settings_containers = {}
        self._page_indexes = {}
        if self._settings_stack is None:
            return

        for spec in get_settings_section_specs():
            page = SettingsSectionPage(spec, self._settings_stack)
            self._set_section_placeholder(page, "idle")
            self.settings_containers[spec.key] = page
            index = self._settings_stack.addWidget(page)
            self._page_indexes[spec.key] = index

    def _set_section_placeholder(self, page: SettingsSectionPage, state: str, message: str | None = None):
        self._clear_layout(page.body_layout)
        box = QFrame()
        box.setObjectName("SettingsSectionLoading")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(24, 44, 24, 44)
        layout.setSpacing(10)

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            icon.setPixmap(qta.icon("fa6s.circle-notch", color="#ff6db7").pixmap(28, 28))
        except Exception:
            icon.setText("...")

        text = message
        if not text:
            if state == "loading":
                text = _("Loading section...", "Loading section...")
            else:
                text = _("Section is ready to load.", "Section is ready to load.")
        label = QLabel(text)
        label.setObjectName("Subtle")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(1)
        layout.addWidget(icon)
        layout.addWidget(label)
        layout.addStretch(1)
        page.body_layout.addWidget(box)

    def _ensure_section_loaded(self, category: str, *, subsection=None, smooth_scroll: bool = False, background: bool = False):
        if category in self._loaded_sections:
            if not background:
                self._apply_pending_scroll(category, subsection=subsection, smooth_scroll=smooth_scroll)
            return

        if category in self._loading_sections:
            if not background:
                self._pending_section_scroll[category] = (subsection, smooth_scroll)
            return

        page = self.settings_containers.get(category)
        if page is None:
            return

        self._loading_sections.add(category)
        if not background:
            self._pending_section_scroll[category] = (subsection, smooth_scroll)
        self._set_section_placeholder(page, "loading")
        required_features = _SECTION_FEATURES.get(category, ())
        self._view_model.dispatch(
            PrepareSettingsSection(
                category=category,
                feature_names=tuple(required_features),
                require_backend=category in _BACKEND_REQUIRED_SECTIONS,
                gui_feature=_SECTION_GUI_FEATURES.get(category),
            )
        )

    def _handle_effect(self, effect) -> None:
        if isinstance(effect, SettingsSectionReady):
            self._build_section_now(effect.category)
            return
        if isinstance(effect, SettingsSectionFailed):
            self._finish_section_feature_error(effect.category, RuntimeError(effect.message))

    def _finish_section_feature_error(self, category: str, error: BaseException) -> None:
        logger.error(
            "Settings section feature preparation failed for '%s': %s",
            category,
            error,
        )
        page = self.settings_containers.get(category)
        if page is not None:
            self._set_section_placeholder(
                page,
                "error",
                _("Компонент недоступен", "Component unavailable") + f": {error}",
            )
        self._loading_sections.discard(category)

    def _build_section_now(self, category: str):
        page = self.settings_containers.get(category)
        spec = self._section_specs.get(category)
        if page is None or spec is None:
            self._loading_sections.discard(category)
            return

        try:
            self._clear_layout(page.body_layout)
            self._page_actions.build_settings_section(category, page.body_layout)

            self._promote_first_subsection_header(page)
            self._prepare_settings_subsections(page)
            self._loaded_sections.add(category)
        except Exception as exc:
            logger.error(
                "Failed to build settings section '%s': %s",
                category,
                exc,
                exc_info=True,
            )
            self._set_section_placeholder(page, "error", f"Failed to load section: {exc}")
        finally:
            self._loading_sections.discard(category)

        subsection, smooth_scroll = self._pending_section_scroll.pop(category, (None, False))
        self._apply_pending_scroll(category, subsection=subsection, smooth_scroll=smooth_scroll)

    def _apply_pending_scroll(self, category: str, *, subsection=None, smooth_scroll: bool = False):
        page = self.settings_containers.get(category)
        if page is None:
            return
        if subsection:
            QTimer.singleShot(0, lambda p=page, sub=subsection, smooth=smooth_scroll: self._scroll_to_subsection(p, sub, smooth=smooth))
        elif smooth_scroll:
            QTimer.singleShot(0, lambda key=category: self._scroll_to_category(key, smooth=True))

    def _clear_layout(self, layout: QLayout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    _COLLAPSE_STATE_KEY = "SETTINGS_COLLAPSED_SECTIONS"

    def _promote_first_subsection_header(self, page: SettingsSectionPage):
        headers = page.findChildren(QWidget, "SettingsSubsectionHeader")
        if not headers:
            return

        header = headers[0]
        header.setProperty("hero", "true")

        layout = header.layout()
        if layout is not None:
            layout.setContentsMargins(0, 0, 0, 12)
            layout.setSpacing(5)

        title_label = header.findChild(QLabel, "SettingsSubsectionTitle")
        if title_label is not None:
            title_label.setWordWrap(True)

        if layout is None:
            return

        subtitle_text = _(page.spec.subtitle[0], page.spec.subtitle[1])
        subtitle = QLabel(subtitle_text)
        register_if_tr(subtitle, subtitle_text)
        subtitle.setObjectName("SettingsSubsectionSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        insert_at = 1
        layout.insertWidget(insert_at, subtitle)

        header.style().unpolish(header)
        header.style().polish(header)

    def _collapsed_state_map(self) -> dict:
        getter = getattr(self._settings, "get", None)
        value = getter(self._COLLAPSE_STATE_KEY, {}) if callable(getter) else {}
        return dict(value) if isinstance(value, dict) else {}

    def _persist_collapsed_state(self, section_id: str, collapsed: bool) -> None:
        state = self._collapsed_state_map()
        state[section_id] = bool(collapsed)
        setter = getattr(self._settings, "set", None)
        if callable(setter):
            setter(self._COLLAPSE_STATE_KEY, state)

    def _prepare_settings_subsections(self, page: SettingsSectionPage):
        """Keep the in-page subsections collapsible so long pages (e.g. Models)
        can be folded instead of forcing an endless scroll.

        Each section keeps the collapse state its builder chose as the default;
        a persisted per-section override (saved on user toggle) takes priority,
        so folding a group sticks across navigation."""
        page_key = getattr(getattr(page, "spec", None), "key", "")
        state_map = self._collapsed_state_map()
        seen: dict[str, int] = {}

        for section in page.findChildren(QWidget):
            if section.objectName() != "CollapsibleSection":
                continue
            if not (hasattr(section, "collapse") and hasattr(section, "expand")):
                continue

            title = ""
            title_label = getattr(section, "title_label", None)
            if title_label is not None:
                title = title_label.text()
            seen[title] = seen.get(title, 0) + 1
            section_id = f"{page_key}:{title}:{seen[title]}"

            # Default = whatever the builder set; persisted choice wins.
            want_collapsed = bool(state_map.get(section_id, getattr(section, "is_collapsed", True)))
            try:
                if want_collapsed:
                    section.collapse()
                else:
                    section.expand()
            except Exception:
                pass

            self._wire_section_persistence(section, section_id)

    def _wire_section_persistence(self, section, section_id: str) -> None:
        original_toggle = section.toggle

        def _toggle(event=None, _orig=original_toggle, _id=section_id, _sec=section):
            _orig()
            self._persist_collapsed_state(_id, bool(getattr(_sec, "is_collapsed", False)))

        # Shadow the bound method so collapse()/expand() (which call
        # self.toggle()) and the header click both go through persistence.
        section.toggle = _toggle
        header = getattr(section, "header", None)
        if header is not None:
            header.setCursor(Qt.CursorShape.PointingHandCursor)
            header.mousePressEvent = _toggle
