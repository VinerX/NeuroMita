from .ui import build_voiceover_settings_ui


def setup_voiceover_controls(self, parent_layout):
    build_voiceover_settings_ui(self, parent_layout)
    self.presentation.settings_sections.wire_voiceover(self)


__all__ = ["setup_voiceover_controls"]
