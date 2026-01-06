from core.events import get_event_bus, Events


def wire_voiceover_settings_logic(self):
    eb = get_event_bus()

    if hasattr(self, 'local_voice_combobox') and self.local_voice_combobox is not None:
        def _on_local_model_changed(_idx: int):
            mid = self.local_voice_combobox.currentData()
            eb.emit(Events.GUI.VOICEOVER_MODEL_SELECTED, {"model_id": mid})
        self.local_voice_combobox.activated.connect(_on_local_model_changed)

    if hasattr(self, 'method_combobox') and self.method_combobox is not None:
        self.method_combobox.currentTextChanged.connect(lambda _t: eb.emit(Events.GUI.VOICEOVER_REFRESH))

    if hasattr(self, 'use_voice_checkbox') and self.use_voice_checkbox is not None:
        self.use_voice_checkbox.stateChanged.connect(lambda _s: eb.emit(Events.GUI.VOICEOVER_REFRESH))

    eb.emit(Events.GUI.VOICEOVER_REFRESH)