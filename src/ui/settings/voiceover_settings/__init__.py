from .ui import build_voiceover_settings_ui
from .logic import wire_voiceover_settings_logic

# Совместимость: константа доступна по прежнему импорту
from presets.local_voice_models import LOCAL_VOICE_MODELS

def setup_voiceover_controls(self, parent_layout):
    """
    Собирает UI и подключает логику озвучки.
    self — это ваш MainView (или аналог).
    parent_layout — QVBoxLayout контейнера настройки вкладки Озвучка.
    """
    build_voiceover_settings_ui(self, parent_layout)
    wire_voiceover_settings_logic(self)

__all__ = ["setup_voiceover_controls", "LOCAL_VOICE_MODELS"]
