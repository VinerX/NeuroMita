from .ui import build_voiceover_settings_ui


def setup_voiceover_controls(self, parent_layout, *, actions, wire_voiceover):
    build_voiceover_settings_ui(self, parent_layout, actions=actions)
    wire_voiceover(self)


__all__ = ["setup_voiceover_controls"]
