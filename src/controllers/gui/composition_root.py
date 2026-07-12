from __future__ import annotations

from typing import Any

from .app_shell_controller import AppShellController
from .main_window_coordinator import MainWindowCoordinator
from .presentation_hub import UiPresentationHub
from .window_composition_controller import WindowCompositionController


class GuiCompositionRoot:
    """Owns construction and lifetime of the complete GUI object graph."""

    def __init__(self, settings_controller: Any) -> None:
        from core.services import use
        from services.contracts import SettingsService
        from ui.settings.settings_binding import QtSettingsViewModel
        from ui.windows.main_window import MainWindow

        self.settings_controller = settings_controller
        self._closed = False
        self.presentation = UiPresentationHub()
        self.window = MainWindow(
            settings_controller.settings,
            presentation=self.presentation,
        )
        self.settings_binding = QtSettingsViewModel(use(SettingsService), self.window)
        self.window.attach_settings_binding(self.settings_binding)
        self.shell_controller = AppShellController(self.window, self.presentation)
        self.window.attach_shell_controller(self.shell_controller)
        self.window_controller = WindowCompositionController(self.window, self.presentation)
        self.window.attach_window_controller(self.window_controller)
        self.page_coordinator = MainWindowCoordinator(self.window, self.presentation)
        self.window.attach_page_coordinator(self.page_coordinator)
        self.window.initialize_pages()

    def attach_backend(self, controller: Any) -> None:
        if self._closed:
            raise RuntimeError("GUI composition root is already closed")
        self.shell_controller.attach_backend(controller)
        try:
            controller.update_view(self.window)
        except Exception as exc:
            self.shell_controller.backend_failed(exc)
            raise
        self.window.refresh_backend_state(
            backend_ready=bool(self.presentation.app.backend_ready),
            startup_error=self.presentation.app.startup_error,
        )

    def backend_failed(self, error: BaseException | str) -> None:
        if self._closed:
            return
        self.shell_controller.backend_failed(error)
        self.window.refresh_backend_state(
            backend_ready=bool(self.presentation.app.backend_ready),
            startup_error=self.presentation.app.startup_error,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.page_coordinator.close()
        finally:
            try:
                self.window_controller.close()
            finally:
                try:
                    self.shell_controller.close_application()
                finally:
                    self.settings_binding.close()
