from PyQt6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from styles.main_styles import get_stylesheet
from ui.pages.home_page import build_home_page
from ui.pages.logs_page import build_logs_page
from ui.pages.main_page_registry import MAIN_PAGE_ORDER, get_main_page_factory
from ui.pages.news_page import build_news_page
from ui.pages.news_support import get_news_content as load_news_content
from ui.pages.news_support import get_news_releases as load_news_releases
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
            initial_page="sandbox",
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

        try:
            apply_section_visibility(self)
        except Exception:
            pass

        self._ensure_main_page("sandbox")
        self.switch_main_page("sandbox")
        self.resize(1560, 920)

    def _ensure_main_page(self, page_key):
        page = getattr(self, "page_map", {}).get(page_key)
        if page is not None:
            return page

        factory = get_main_page_factory(page_key)
        if factory is None or not hasattr(self, "page_stack"):
            return None

        page = factory(self)
        self.page_map[page_key] = page
        self.page_stack.addWidget(page)
        self._ensure_settings_animation()
        return page

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

    def switch_main_page(self, page_key):
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

        if hasattr(page, "on_activated"):
            page.on_activated()

    def open_release_page(self, release_id: str = ""):
        self.switch_main_page("news")
        page = getattr(self, "news_page", None)
        if page is not None and hasattr(page, "focus_release"):
            page.focus_release(release_id)

    def _build_home_page(self):
        return build_home_page(self)

    def _build_news_page(self):
        return build_news_page(self)

    def _build_logs_page(self):
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
        return load_news_content(self)

    def get_news_releases(self):
        return load_news_releases(self)

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
