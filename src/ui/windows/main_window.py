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

    def __init__(self, settings, *, presentation):
        self.page_coordinator = None
        super().__init__(settings, presentation=presentation)

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

    def attach_page_coordinator(self, coordinator) -> None:
        self.page_coordinator = coordinator

    def initialize_pages(self) -> None:
        if self.page_coordinator is None:
            raise RuntimeError("Main page coordinator is not attached")
        self.page_coordinator.initialize()

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
        if self.page_coordinator is not None:
            self.page_coordinator.show_settings_category(
                category,
                force=force,
                subsection=subsection,
            )

    def switch_main_page(self, page_key, *, activate: bool = True):
        if self.page_coordinator is not None:
            self.page_coordinator.switch_page(page_key, activate=activate)

    def activate_current_main_page(self):
        if self.page_coordinator is None:
            return False
        return self.page_coordinator.activate_current_page()

    def open_release_page(self, release_id: str = ""):
        if self.page_coordinator is not None:
            self.page_coordinator.open_release_page(release_id)

    def _refresh_logs_view(self):
        if self.page_coordinator is not None:
            self.page_coordinator.refresh_logs()

    def _refresh_news_page(self):
        if self.page_coordinator is not None:
            self.page_coordinator.refresh_news()

    def get_news_content(self):
        return self.page_coordinator.news_content() if self.page_coordinator is not None else ""

    def get_news_releases(self):
        return self.page_coordinator.news_releases() if self.page_coordinator is not None else []

    def _refresh_home_primary_label(self):
        if self.page_coordinator is not None:
            self.page_coordinator.refresh_home_primary_label()

    def _set_home_progress(self, text: str, value: int, maximum: int, busy: bool = False):
        if self.page_coordinator is not None:
            self.page_coordinator.set_home_progress(
                text,
                value,
                maximum,
                busy=busy,
            )

    def _hide_home_progress(self):
        if self.page_coordinator is not None:
            self.page_coordinator.hide_home_progress()

    def _run_home_primary_action(self):
        if self.page_coordinator is not None:
            self.page_coordinator.run_home_primary_action()

    def _run_home_install_unity(self):
        if self.page_coordinator is not None:
            self.page_coordinator.run_home_install_unity()

    def _run_home_verify_action(self):
        if self.page_coordinator is not None:
            self.page_coordinator.run_home_verify_action()

    def _show_home_extra_menu(self, anchor_widget):
        if self.page_coordinator is not None:
            self.page_coordinator.show_home_extra_menu(anchor_widget)

    def _find_unity_executable(self):
        if self.page_coordinator is None:
            return None
        return self.page_coordinator.find_unity_executable()
