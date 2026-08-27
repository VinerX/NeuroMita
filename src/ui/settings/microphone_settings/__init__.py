from .ui import build_microphone_settings_ui


def setup_microphone_controls(self, parent_layout, *, wire_microphone):
    build_microphone_settings_ui(self, parent_layout)
    wire_microphone(self)


def load_mic_settings(self, *, load_microphone):
    load_microphone(self)


__all__ = ["setup_microphone_controls", "load_mic_settings"]
