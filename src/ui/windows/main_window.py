from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from styles.main_styles import get_stylesheet
from ui.widgets.launcher_shell_sidebar import LauncherSidebarWidget
from ui.windows.app_window_base import AppWindowBase


class MainWindow(AppWindowBase):
    """Passive launcher shell.

    Page construction and navigation live in ``MainWindowCoordinator``. The
    window only exposes stable rendering/navigation ports used by child views.
    """

    def __init__(
        self,
        settings,
        *,
        telegram_auth_actions,
        chat_message_actions,
        shell_actions,
        window_actions,
        page_actions,
        pending_restart_version,
    ):
        self._page_actions = page_actions
        self._pending_restart_version = pending_restart_version
        super().__init__(
            settings,
            telegram_auth_actions=telegram_auth_actions,
            chat_message_actions=chat_message_actions,
            shell_actions=shell_actions,
            window_actions=window_actions,
        )

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
            version_provider=self._pending_restart_version,
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

    def initialize_pages(self) -> None:
        self._page_actions.initialize()

    def apply_initial_geometry(self, design_w: int, design_h: int) -> None:
        try:
            screen = self.screen()
            if screen is None:
                from PyQt6.QtWidgets import QApplication

                screen = QApplication.primaryScreen()
            available = screen.availableGeometry()
            width = min(design_w, int(available.width() * 0.92))
            height = min(design_h, int(available.height() * 0.92))
            self.resize(width, height)
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())
        except Exception:
            self.resize(design_w, design_h)

    def show_settings_category(self, category, *, force: bool = False, subsection=None):
        self._page_actions.show_settings_category(
            category,
            force=force,
            subsection=subsection,
        )

    def switch_main_page(self, page_key, *, activate: bool = True):
        self._page_actions.switch_page(page_key, activate=activate)

    def activate_current_main_page(self):
        return self._page_actions.activate_current_page()

    def open_release_page(self, release_id: str = ""):
        self._page_actions.open_release_page(release_id)

    def _refresh_logs_view(self):
        self._page_actions.refresh_logs()

    def _refresh_news_page(self):
        self._page_actions.refresh_news()

    def get_news_content(self):
        return self._page_actions.news_content()

    def get_news_releases(self):
        return self._page_actions.news_releases()

    def _refresh_home_primary_label(self):
        self._page_actions.refresh_home_primary_label()

    def _set_home_progress(self, text: str, value: int, maximum: int, busy: bool = False):
        self._page_actions.set_home_progress(
            text,
            value,
            maximum,
            busy=busy,
        )

    def _hide_home_progress(self):
        self._page_actions.hide_home_progress()

    def _run_home_primary_action(self):
        self._page_actions.run_home_primary_action()

    def _run_home_install_unity(self):
        self._page_actions.run_home_install_unity()

    def _run_home_verify_action(self):
        self._page_actions.run_home_verify_action()

    def _show_home_extra_menu(self, anchor_widget):
        self._page_actions.show_home_extra_menu(anchor_widget)

    def _find_unity_executable(self):
        return self._page_actions.find_unity_executable()
