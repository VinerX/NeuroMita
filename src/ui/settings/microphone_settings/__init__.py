from .ui import build_microphone_settings_ui


def setup_microphone_controls(self, parent_layout):
    build_microphone_settings_ui(self, parent_layout)
    self.presentation.settings_sections.wire_microphone(self)


def load_mic_settings(self):
    self.presentation.settings_sections.load_microphone(self)


__all__ = ["setup_microphone_controls", "load_mic_settings"]
