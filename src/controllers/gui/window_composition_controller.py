from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout

from main_logger import logger
from ui.window_manager import WindowManager
from ui.windows.voice_action_windows import VoiceInstallationWindow
from utils import getTranslationVariant as _
from controllers.gui.ai_hub_view_model import AIHubViewModel


class WindowCompositionController:
    """Creates and coordinates top-level dialogs outside the passive shell view."""

    def __init__(self, view: Any, presentation: Any) -> None:
        self._view = view
        self._presentation = presentation
        self.window_manager = WindowManager(parent=view)
        self._ai_hub_view_model = AIHubViewModel(presentation)
        self._ai_hub_settings_view_model = presentation.view_models.ai_hub_settings(
            view,
            parent=view,
        )
        self._active_install_window = None
        self._closed = False
        self._register_dialogs()
        self._connect_signals()
        view.window_manager = self.window_manager

    def _register_dialogs(self) -> None:
        specs = {
            "ai_hub": (self._factory_ai_hub, True, True, False, self._on_ai_hub_ready),
            "voice_models": (self._factory_voice_models, True, True, False, None),
            "asr_glossary": (self._factory_asr_glossary, True, True, False, None),
            "vc_redist_dialog": (self._factory_vc_redist, False, False, True, None),
            "triton_deps_dialog": (self._factory_triton, False, False, True, None),
        }
        for window_id, (factory, singleton, hide_on_close, modal, on_ready) in specs.items():
            self.window_manager.register_dialog(
                window_id,
                factory=factory,
                singleton=singleton,
                hide_on_close=hide_on_close,
                modal=modal,
                on_ready=on_ready,
            )

    def _connect_signals(self) -> None:
        view = self._view
        view.create_dialog_signal.connect(self.open_voice_model_dialog)
        view.create_installation_window_signal.connect(
            self.create_installation_window,
            type=Qt.ConnectionType.QueuedConnection,
        )
        view.close_installation_window_signal.connect(
            self.close_installation_window,
            type=Qt.ConnectionType.QueuedConnection,
        )
        view.finalize_installation_window_signal.connect(
            self.finalize_installation_window,
            type=Qt.ConnectionType.QueuedConnection,
        )

    def _factory_voice_models(self, parent, _payload: dict):
        dialog = QDialog(parent)
        dialog.setWindowTitle(_("Управление локальными моделями", "Manage Local Models"))
        dialog.setModal(False)
        dialog.resize(875, 800)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return dialog

    def _factory_ai_hub(self, parent, _payload: dict):
        from ui.windows.ai_hub import AIHubDialog

        return AIHubDialog(
            self._ai_hub_view_model,
            self._ai_hub_settings_view_model,
            getattr(self._view, "settings_binding", None),
            parent,
        )

    @staticmethod
    def _on_ai_hub_ready(dialog, payload: dict) -> None:
        if hasattr(dialog, "apply_payload"):
            dialog.apply_payload(payload if isinstance(payload, dict) else {})

    def _factory_asr_glossary(self, parent, _payload: dict):
        dialog = QDialog(parent)
        dialog.setWindowTitle(_("ASR модели", "ASR Models"))
        dialog.setModal(False)
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return dialog

    def _factory_vc_redist(self, parent, _payload: dict):
        from ui.windows.voice_action_windows import VCRedistWarningDialog

        return VCRedistWarningDialog(
            self._presentation.voice.open_documentation,
            parent=parent,
        )

    def _factory_triton(self, parent, payload: dict):
        from ui.windows.voice_action_windows import TritonDependenciesDialog

        deps = payload.get("dependencies_status") or payload.get("deps") or {}
        return TritonDependenciesDialog(
            open_documentation=self._presentation.voice.open_documentation,
            refresh_status=lambda: self._presentation.voice.triton_status(refresh=True),
            parent=parent,
            dependencies_status=deps,
        )

    def open_voice_model_dialog(self, data: Any) -> None:
        payload = dict(data) if isinstance(data, dict) else {}
        payload.setdefault("category", "tts")
        self.window_manager.show_dialog("ai_hub", payload)

    def create_installation_window(self, title: str, initial_status: str, holder: dict) -> None:
        ready_event = holder.get("ready_event")
        try:
            style_variant = str(holder.get("style_variant") or "default")
            win = VoiceInstallationWindow(self._view, title, initial_status, style_variant=style_variant)
            self._active_install_window = win
            win.minimized.connect(lambda: self._set_install_logs_visible(True))
            win.window_closed.connect(lambda window=win: self._on_install_window_closed(window))
            self._set_install_logs_visible(True)
            win.show()
            holder["window"] = win
            holder["callbacks"] = (
                win.get_threadsafe_callbacks()
                if hasattr(win, "get_threadsafe_callbacks")
                else (win.update_progress, win.update_status, win.update_log)
            )
        except Exception as exc:
            holder["error"] = exc
            logger.error("Failed to create installation window: %s", exc, exc_info=True)
        finally:
            if ready_event is not None and hasattr(ready_event, "set"):
                ready_event.set()

    @staticmethod
    def close_installation_window(win_obj: object) -> None:
        if win_obj is None:
            return
        if hasattr(win_obj, "finalize"):
            win_obj.finalize()
        win_obj.close()

    @staticmethod
    def finalize_installation_window(win_obj: object, close_now: bool) -> None:
        if win_obj is None:
            return
        if hasattr(win_obj, "finalize"):
            win_obj.finalize()
        if close_now:
            win_obj.close()

    def _on_install_window_closed(self, win_obj: object) -> None:
        if win_obj is self._active_install_window:
            self._active_install_window = None
            self._set_install_logs_visible(False)

    def reopen_install_logs(self) -> None:
        win = self._active_install_window
        if win is None:
            self._set_install_logs_visible(False)
            return
        win.show()
        win.raise_()
        win.activateWindow()

    def _set_install_logs_visible(self, visible: bool) -> None:
        sidebar = getattr(self._view, "shell_sidebar", None)
        if sidebar is not None and hasattr(sidebar, "set_install_logs_visible"):
            sidebar.set_install_logs_visible(bool(visible))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._ai_hub_view_model.close()
        self._ai_hub_settings_view_model.close()
        self.window_manager.close_all(destroy=True)
        self._active_install_window = None
        if getattr(self._view, "window_manager", None) is self.window_manager:
            self._view.window_manager = None
