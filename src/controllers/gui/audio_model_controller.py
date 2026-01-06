from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController

from PyQt6.QtCore import QTimer


class AudioModelController(BaseController):

    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.CHECK_TRITON_DEPENDENCIES, self._on_check_triton_dependencies, weak=False)
        self.event_bus.subscribe(Events.Audio.UPDATE_MODEL_LOADING_STATUS, self._on_update_model_loading_status, weak=False)
        self.event_bus.subscribe(Events.Audio.FINISH_MODEL_LOADING, self._on_finish_model_loading, weak=False)
        self.event_bus.subscribe(Events.Audio.CANCEL_MODEL_LOADING, self._on_cancel_model_loading, weak=False)

        self.event_bus.subscribe(Events.Audio.OPEN_VOICE_MODEL_SETTINGS_DIALOG, self._on_open_voice_model_settings_dialog, weak=False)

    def _on_open_voice_model_settings_dialog(self, event: Event):
        self.event_bus.emit(Events.GUI.SHOW_WINDOW, {"window_id": "voice_models", "payload": {}})

    def _on_check_triton_dependencies(self, event: Event):
        if self.view and hasattr(self.view, "check_triton_dependencies_signal") and self.view.check_triton_dependencies_signal:
            self.view.check_triton_dependencies_signal.emit()
        elif self.view and hasattr(self.view, "check_triton_dependencies"):
            self.view.check_triton_dependencies()

        if self.view and hasattr(self.view, "update_local_voice_combobox"):
            QTimer.singleShot(0, self.view.update_local_voice_combobox)

    def _on_update_model_loading_status(self, event: Event):
        status = event.data.get("status", "")
        if self.view and hasattr(self.view, "update_model_loading_status_signal") and self.view.update_model_loading_status_signal:
            self.view.update_model_loading_status_signal.emit(status)
        elif self.view and hasattr(self.view, "loading_status_label"):
            QTimer.singleShot(0, lambda: self.view.loading_status_label.setText(status))

    def _on_finish_model_loading(self, event: Event):
        model_id = event.data.get("model_id")
        if self.view and hasattr(self.view, "finish_model_loading_signal") and self.view.finish_model_loading_signal:
            self.view.finish_model_loading_signal.emit({"model_id": model_id})

    def _on_cancel_model_loading(self, event: Event):
        if self.view and hasattr(self.view, "cancel_model_loading_signal") and self.view.cancel_model_loading_signal:
            self.view.cancel_model_loading_signal.emit()
        elif self.view and hasattr(self.view, "cancel_model_loading") and hasattr(self.view, "loading_dialog"):
            QTimer.singleShot(0, lambda: self.view.cancel_model_loading(self.view.loading_dialog))