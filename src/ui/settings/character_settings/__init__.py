from .ui import build_character_settings_ui


def setup_mita_controls(self, parent_layout):
    build_character_settings_ui(self, parent_layout)
    self.presentation.settings_sections.wire_characters(self)


__all__ = ["setup_mita_controls"]
