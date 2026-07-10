from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from styles.main_styles import get_stylesheet
from ui.pages.main_page_registry import MAIN_PAGE_ORDER, get_main_page_factory
from ui.widgets.launcher_shell_sidebar import LauncherSidebarWidget
from ui.widgets.settings_panel import apply_section_visibility
from ui.windows.app_window_base import AppWindowBase


class MainWindow(AppWindowBase):
    def setup_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("LauncherRoot")
        self.setCentralWidget(central_widget)
        self.setStyleSheet(get_stylesheet())

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.shell_sidebar = LauncherSidebarWidget(
            initial_page="home",
            on_page_requested=self.switch_main_page,
        )
        self.shell_sidebar.social_requested.connect(self._on_shell_social_requested)
        self.shell_sidebar.utility_requested.connect(self._on_shell_utility_requested)
        self.shell_sidebar.install_logs_requested.connect(self._on_reopen_install_logs)
        try:
            current_lang = str(self.settings.get("LANGUAGE", "RU") or "RU").lower()
        except Exception:
            current_lang = "ru"
        self.shell_sidebar.set_active_language(current_lang)
        main_layout.addWidget(self.shell_sidebar)

        content_host = QFrame()
        content_host.setObjectName("LauncherContentHost")
        content_layout = QVBoxLayout(content_host)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("MainPageStack")
        content_layout.addWidget(self.page_stack)
        main_layout.addWidget(content_host, 1)

        self.page_map = {}
        self._deferred_main_pages = {
            "sandbox",
            "news",
            "developer",
            "wiki",
            "logs",
        }
        self._page_building = set()
        self._page_placeholders = {}
        self._pending_page_actions = {}

        try:
            apply_section_visibility(self)
        except Exception:
            pass

        self._ensure_main_page("home", eager=True)
        self.switch_main_page("home", activate=False)
        self._apply_initial_geometry(1560, 920)
        # Settings construction is intentionally opt-in. Building hundreds of
        # widgets shortly after show stalls the GUI thread and corrupts startup
        # latency; the page remains lazy unless the user explicitly enables it.
        try:
            prebuild_settings = bool(self.settings.get("PREBUILD_SETTINGS_PAGE_ON_STARTUP", False))
        except Exception:
            prebuild_settings = False
        if prebuild_settings:
            QTimer.singleShot(450, self._prebuild_settings_page)

    def _prefetch_release_feed(self):
        """Прогреть ленту релизов в фоне сразу на старте (#8).

        Раньше страницы Home/Releases создавались лениво (по клику), поэтому
        лента релизов с GitHub тянулась только когда пользователь открывал их —
        Артём это и заметил («грузятся только по клику»). Тянем её отдельным
        фоновым потоком на старте: `load_news_releases_async` коалесцирует
        запросы и кладёт результат в кэш, так что к моменту открытия Home/News
        данные уже готовы. Колбэк-заглушка ничего не трогает в GUI.
        """
        try:
            from ui.pages.news_support import load_news_releases_async

            load_news_releases_async(self, lambda _releases: None)
        except Exception:
            pass

    def _prebuild_settings_page(self):
        """Собрать страницу настроек заранее, в фоне после старта.

        Сборка идёт через тот же `_ensure_main_page`, что и по клику, поэтому
        результат кэшируется в `page_map` и повторная сборка не выполняется —
        клик по «Настройкам» становится мгновенным. Ошибки глотаем: если что-то
        ещё не готово, страница соберётся штатно по первому клику.
        """
        try:
            if not getattr(self, "page_map", {}).get("settings"):
                self._ensure_main_page("settings")
        except Exception:
            pass

    def _apply_initial_geometry(self, design_w: int, design_h: int) -> None:
        """Стартовый размер окна, но не больше доступной области экрана.

        Раньше стоял жёсткий resize(1560, 920) — на RDP / небольших мониторах
        окно вылезало за пределы экрана (фидбэк Артёма). Ужимаем до ~92% рабочей
        области и центрируем.
        """
        try:
            screen = self.screen()
            if screen is None:
                from PyQt6.QtWidgets import QApplication
                screen = QApplication.primaryScreen()
            avail = screen.availableGeometry()
            w = min(design_w, int(avail.width() * 0.92))
            h = min(design_h, int(avail.height() * 0.92))
            self.resize(w, h)
            frame = self.frameGeometry()
            frame.moveCenter(avail.center())
            self.move(frame.topLeft())
        except Exception:
            self.resize(design_w, design_h)

    def _ensure_main_page(self, page_key, *, eager: bool = False):
        page = getattr(self, "page_map", {}).get(page_key)
        if page is not None:
            return page

        factory = get_main_page_factory(page_key)
        if factory is None or not hasattr(self, "page_stack"):
            return None

        if not eager and page_key in getattr(self, "_deferred_main_pages", set()):
            page = self._create_main_page_placeholder(page_key)
            self.page_map[page_key] = page
            self._page_placeholders[page_key] = page
            self.page_stack.addWidget(page)
            self._schedule_main_page_build(page_key)
            return page

        page = factory(self)
        self.page_map[page_key] = page
        self.page_stack.addWidget(page)
        self._ensure_settings_animation()
        return page

    def _create_main_page_placeholder(self, page_key: str) -> QWidget:
        frame = QFrame()
        frame.setObjectName("MainPageDeferredPlaceholder")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(10)

        title = QLabel(f"Loading {page_key}...")
        title.setObjectName("Subtle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)

        layout.addStretch(1)
        layout.addWidget(title)
        layout.addStretch(1)
        return frame

    def _schedule_main_page_build(self, page_key: str):
        if page_key in self._page_building:
            return
        self._page_building.add(page_key)
        QTimer.singleShot(35, lambda key=page_key: self._build_main_page_now(key))

    def _build_main_page_now(self, page_key: str):
        factory = get_main_page_factory(page_key)
        placeholder = self._page_placeholders.get(page_key)
        if factory is None or placeholder is None or not hasattr(self, "page_stack"):
            self._page_building.discard(page_key)
            return

        was_current = (
            getattr(self, "current_main_page", None) == page_key
            and self.page_stack.currentWidget() is placeholder
        )

        try:
            page = factory(self)
        except Exception as exc:
            self._page_building.discard(page_key)
            label = placeholder.findChild(QLabel)
            if label is not None:
                label.setText(f"Failed to load {page_key}: {exc}")
            return

        idx = self.page_stack.indexOf(placeholder)
        if idx >= 0:
            self.page_stack.insertWidget(idx, page)
            self.page_stack.removeWidget(placeholder)
            placeholder.deleteLater()
        else:
            self.page_stack.addWidget(page)

        self.page_map[page_key] = page
        self._page_placeholders.pop(page_key, None)
        self._page_building.discard(page_key)
        self._ensure_settings_animation()

        if was_current:
            self.page_stack.setCurrentWidget(page)
            if hasattr(page, "on_activated"):
                page.on_activated()

        for action in self._pending_page_actions.pop(page_key, []):
            try:
                action(page)
            except Exception:
                pass

    def _run_when_main_page_ready(self, page_key: str, action):
        page = getattr(self, "page_map", {}).get(page_key)
        if page is not None and self._page_placeholders.get(page_key) is not page:
            try:
                action(page)
            except Exception:
                pass
            return
        self._pending_page_actions.setdefault(page_key, []).append(action)
        self._ensure_main_page(page_key)

    def _init_settings_containers(self):
        page = getattr(self, "settings_page", None)
        if page is None:
            return {}
        return page.settings_containers

    def _on_hide_animation_finished(self):
        page = getattr(self, "settings_page", None)
        if page is not None:
            page.show_overview()
        try:
            if self.settings_animation is not None:
                self.settings_animation.finished.disconnect(self._on_hide_animation_finished)
        except TypeError:
            pass

    def show_settings_category(self, category, *, force: bool = False, subsection=None):
        page = self._ensure_main_page("settings")
        if page is not None:
            page.show_category(category, force=force, subsection=subsection)

    def switch_main_page(self, page_key, *, activate: bool = True):
        if page_key not in MAIN_PAGE_ORDER or not hasattr(self, "page_stack"):
            return
        page = self._ensure_main_page(page_key)
        if page is None:
            return
        current_page = self.page_stack.currentWidget()

        if current_page is not None and current_page is not page and hasattr(current_page, "on_deactivated"):
            current_page.on_deactivated()

        self.page_stack.setCurrentWidget(page)
        self.current_main_page = page_key

        if hasattr(self, "shell_sidebar"):
            self.shell_sidebar.set_active_page(page_key)

        is_placeholder = self._page_placeholders.get(page_key) is page
        if activate and not is_placeholder and hasattr(page, "on_activated"):
            page.on_activated()

    def activate_current_main_page(self):
        page_key = getattr(self, "current_main_page", "")
        page = getattr(self, "page_map", {}).get(page_key)
        if page is None or self._page_placeholders.get(page_key) is page:
            return False
        if hasattr(page, "on_activated"):
            page.on_activated()
        return True

    def open_release_page(self, release_id: str = ""):
        self.switch_main_page("news")
        self._run_when_main_page_ready(
            "news",
            lambda page: page.focus_release(release_id) if hasattr(page, "focus_release") else None,
        )

    def _build_home_page(self):
        from ui.pages.home_page import build_home_page

        return build_home_page(self)

    def _build_news_page(self):
        from ui.pages.news_page import build_news_page

        return build_news_page(self)

    def _build_logs_page(self):
        from ui.pages.logs_page import build_logs_page

        return build_logs_page(self)

    def _refresh_logs_view(self):
        page = getattr(self, "logs_page", None)
        if page is not None:
            page.refresh_logs()

    def _refresh_news_page(self):
        page = getattr(self, "news_page", None)
        if page is not None:
            page.refresh_content()

    def get_news_content(self):
        from ui.pages.news_support import get_news_content

        return get_news_content(self)

    def get_news_releases(self):
        from ui.pages.news_support import get_news_releases

        return get_news_releases(self)

    def _refresh_home_primary_label(self):
        page = getattr(self, "home_page", None)
        if page is not None:
            page.refresh_primary_label()

    def _set_home_progress(self, text: str, value: int, maximum: int, busy: bool = False):
        page = getattr(self, "home_page", None)
        if page is not None:
            page.set_progress(text, value, maximum, busy=busy)

    def _hide_home_progress(self):
        page = getattr(self, "home_page", None)
        if page is not None:
            page.hide_progress()

    def _run_home_primary_action(self):
        page = getattr(self, "home_page", None)
        if page is not None:
            page.run_primary_action()

    def _run_home_install_unity(self):
        page = getattr(self, "home_page", None)
        if page is not None:
            page.run_install_unity()

    def _run_home_verify_action(self):
        page = getattr(self, "home_page", None)
        if page is not None:
            page.run_verify_action()

    def _show_home_extra_menu(self, anchor_widget):
        page = getattr(self, "home_page", None)
        if page is not None:
            page.show_extra_menu(anchor_widget)

    def _find_unity_executable(self):
        page = getattr(self, "home_page", None)
        if page is not None:
            return page.find_unity_executable()
        return None
