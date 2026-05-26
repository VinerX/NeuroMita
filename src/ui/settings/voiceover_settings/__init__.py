from .ui import build_voiceover_settings_ui
from .logic import wire_voiceover_settings_logic

# Совместимость: константа доступна по прежнему импорту
LOCAL_VOICE_MODELS = [
    {"id": "edge_tts_rvc_cuda", "name": "Edge-TTS + RVC (CUDA)", "min_vram": 3, "rec_vram": 4, "gpu_vendor": ["NVIDIA"], "size_gb": 3},
    {"id": "edge_tts_rvc_onnx", "name": "Edge-TTS + RVC (ONNX/DirectML)", "min_vram": 3, "rec_vram": 4, "gpu_vendor": ["AMD", "CPU"], "size_gb": 3},
    {"id": "silero_rvc_cuda", "name": "Silero + RVC (CUDA)", "min_vram": 3, "rec_vram": 4, "gpu_vendor": ["NVIDIA"], "size_gb": 3},
    {"id": "silero_rvc_onnx", "name": "Silero + RVC (ONNX/DirectML)", "min_vram": 3, "rec_vram": 4, "gpu_vendor": ["AMD", "CPU"], "size_gb": 3},
    {"id": "medium", "name": "Fish Speech", "min_vram": 4, "rec_vram": 6, "gpu_vendor": ["NVIDIA"], "size_gb": 5},
    {"id": "medium+", "name": "Fish Speech+", "min_vram": 4, "rec_vram": 6, "gpu_vendor": ["NVIDIA"], "size_gb": 10},
    {"id": "medium+low", "name": "Fish Speech+ + RVC", "min_vram": 6, "rec_vram": 8, "gpu_vendor": ["NVIDIA"], "size_gb": 15},
    {"id": "high", "name": "F5-TTS", "min_vram": 4, "rec_vram": 8, "gpu_vendor": ["NVIDIA", "AMD"], "size_gb": 4},
    {"id": "high+low", "name": "F5-TTS + RVC", "min_vram": 6, "rec_vram": 8, "gpu_vendor": ["NVIDIA", "AMD"], "size_gb": 4}
]

def setup_voiceover_controls(self, parent_layout):
    """
    Собирает UI и подключает логику озвучки.
    self — это ваш MainView (или аналог).
    parent_layout — QVBoxLayout контейнера настройки вкладки Озвучка.
    """
    build_voiceover_settings_ui(self, parent_layout)
    wire_voiceover_settings_logic(self)

__all__ = ["setup_voiceover_controls", "LOCAL_VOICE_MODELS"]
