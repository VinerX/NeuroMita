from PyQt6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from styles.main_styles import get_stylesheet
from ui.pages.home_page import build_home_page
from ui.pages.logs_page import build_logs_page
from ui.pages.main_page_registry import MAIN_PAGE_ORDER, build_main_pages
from ui.pages.news_page import build_news_page
from ui.pages.settings.section_registry import build_settings_containers
from ui.widgets.launcher_shell_sidebar import LauncherSidebarWidget
from ui.widgets.settings_panel import apply_interface_mode
from ui.windows.main_view import ChatGUI as LegacyChatGUI
from utils import _


class MainWindow(LegacyChatGUI):
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
        try:
            current_lang = str(self.settings.get("LANGUAGE", "RU") or "RU").lower()
        except Exception:
            current_lang = "ru"
        self.shell_sidebar.set_active_language(current_lang)
        main_layout.addWidget(self.shell_sidebar)

        content_host = QFrame()
        content_host.setObjectName("LauncherContentHost")
        content_layout = QVBoxLayout(content_host)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(0)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("MainPageStack")
        content_layout.addWidget(self.page_stack)
        main_layout.addWidget(content_host, 1)

        self.page_map = build_main_pages(self)
        for key in MAIN_PAGE_ORDER:
            self.page_stack.addWidget(self.page_map[key])

        try:
            apply_interface_mode(self, self.settings.get("INTERFACE_MODE") or _("Базовый", "Basic"))
        except Exception:
            pass

        self.switch_main_page("sandbox")
        self.resize(1560, 920)

    def _init_settings_containers(self):
        return build_settings_containers(self)

    def _build_home_page(self):
        return build_home_page(self)

    def _build_news_page(self):
        return build_news_page(self)

    def _build_logs_page(self):
        return build_logs_page(self)
