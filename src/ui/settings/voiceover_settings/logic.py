from PyQt6.QtCore import QTimer
from core.events import get_event_bus, Events


def wire_voiceover_settings_logic(self):
    eb = get_event_bus()

    def request_refresh():
        if bool(getattr(self, "_voiceover_refresh_pending", False)):
            return
        self._voiceover_refresh_pending = True

        def fire():
            self._voiceover_refresh_pending = False
            eb.emit(Events.GUI.VOICEOVER_REFRESH)

        QTimer.singleShot(0, fire)

    # --- Local model combobox ---
    if hasattr(self, "local_voice_combobox") and self.local_voice_combobox is not None:
        try:
            if hasattr(self, "_on_local_model_changed"):
                self.local_voice_combobox.activated.disconnect(self._on_local_model_changed)
        except Exception:
            pass

        def _on_local_model_changed(_idx: int):
            mid = self.local_voice_combobox.currentData()
            eb.emit(Events.GUI.VOICEOVER_MODEL_SELECTED, {"model_id": mid})

        self._on_local_model_changed = _on_local_model_changed
        self.local_voice_combobox.activated.connect(self._on_local_model_changed)

    # --- Method combobox ---
    if hasattr(self, "method_combobox") and self.method_combobox is not None:
        try:
            if hasattr(self, "_on_voiceover_method_changed"):
                self.method_combobox.currentTextChanged.disconnect(self._on_voiceover_method_changed)
        except Exception:
            pass

        def _on_voiceover_method_changed(_t: str):
            request_refresh()

        self._on_voiceover_method_changed = _on_voiceover_method_changed
        self.method_combobox.currentTextChanged.connect(self._on_voiceover_method_changed)

    # --- Use voice checkbox ---
    if hasattr(self, "use_voice_checkbox") and self.use_voice_checkbox is not None:
        try:
            if hasattr(self, "_on_use_voice_changed"):
                self.use_voice_checkbox.stateChanged.disconnect(self._on_use_voice_changed)
        except Exception:
            pass

        def _on_use_voice_changed(_s: int):
            request_refresh()

        self._on_use_voice_changed = _on_use_voice_changed
        self.use_voice_checkbox.stateChanged.connect(self._on_use_voice_changed)

    request_refresh()