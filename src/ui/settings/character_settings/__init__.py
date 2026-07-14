from .ui import build_character_settings_ui


def setup_mita_controls(self, parent_layout, *, wire_characters):
    build_character_settings_ui(self, parent_layout)
    wire_characters(self)


__all__ = ["setup_mita_controls"]
