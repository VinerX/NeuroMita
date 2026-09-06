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
        from startup.api_configuration import ensure_api_configuration
        from controllers.gui.telegram_auth_view_model import TelegramAuthViewModel
        from controllers.gui.window_action_adapters import (
            MainPageActionsAdapter,
            ShellActionsAdapter,
            WindowActionsAdapter,
        )
        from ui.settings.settings_binding import QtSettingsViewModel
        from ui.windows.main_window import MainWindow

        self.settings_controller = settings_controller
        self._closed = False
        # API preset configuration is part of the application shell, not the
        # optional voice/game runtime.  Keep it usable while that runtime is
        # still starting or has failed independently.
        self.api_configuration = ensure_api_configuration()
        self.presentation = UiPresentationHub()
        self.chat_message_actions = self.presentation.view_models.chat_message_actions(
            None,
            parent=None,
        )
        self.telegram_auth_actions = TelegramAuthViewModel(
            auth=self.presentation.telegram,
            parent=None,
        )
        self.shell_actions = ShellActionsAdapter()
        self.window_actions = WindowActionsAdapter()
        self.page_actions = MainPageActionsAdapter()
        self.settings_binding = QtSettingsViewModel(use(SettingsService), None)
        self.window = MainWindow(
            self.settings_binding,
            telegram_auth_actions=self.telegram_auth_actions,
            chat_message_actions=self.chat_message_actions,
            shell_actions=self.shell_actions,
            window_actions=self.window_actions,
            page_actions=self.page_actions,
            pending_restart_version=lambda: self.presentation.app.pending_restart_version,
        )
        self.chat_message_actions.setParent(self.window)
        self.telegram_auth_actions.setParent(self.window)
        self.settings_binding.setParent(self.window)
        self.window.attach_settings_binding(self.settings_binding)
        self.presentation.settings_sections.load_microphone(self.window)
        self.page_coordinator = MainWindowCoordinator(self.window, self.presentation)
        self.shell_controller = AppShellController(
            self.window,
            self.presentation,
            close_pages=self.page_coordinator.close,
        )
        self.shell_actions.bind(self.shell_controller)
        self.window_controller = WindowCompositionController(self.window, self.presentation)
        self.window_actions.bind(self.window_controller)
        self.page_actions.bind(self.page_coordinator)
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
                    try:
                        self.chat_message_actions.close()
                    finally:
                        try:
                            self.telegram_auth_actions.close()
                        finally:
                            try:
                                self.settings_binding.close()
                            finally:
                                self.api_configuration.close()
