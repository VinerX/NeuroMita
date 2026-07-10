LOCAL_VOICE_MODELS = [
    {"id": "edge_tts_rvc_cuda", "name": "Edge-TTS + RVC (CUDA)", "min_vram": 3, "rec_vram": 4, "gpu_vendor": ["NVIDIA"], "size_gb": 3},
    {"id": "edge_tts_rvc_onnx", "name": "Edge-TTS + RVC (ONNX)", "min_vram": 3, "rec_vram": 4, "gpu_vendor": ["AMD", "INTEL", "CPU"], "size_gb": 3},
    {"id": "silero_rvc_cuda", "name": "Silero + RVC (CUDA)", "min_vram": 3, "rec_vram": 4, "gpu_vendor": ["NVIDIA"], "size_gb": 3},
    {"id": "silero_rvc_onnx", "name": "Silero + RVC (ONNX)", "min_vram": 3, "rec_vram": 4, "gpu_vendor": ["AMD", "INTEL", "CPU"], "size_gb": 3},
    {"id": "medium", "name": "Fish Speech", "min_vram": 4, "rec_vram": 6, "gpu_vendor": ["NVIDIA"], "size_gb": 5},
    {"id": "medium+", "name": "Fish Speech+", "min_vram": 4, "rec_vram": 6, "gpu_vendor": ["NVIDIA"], "size_gb": 10},
    {"id": "medium+low", "name": "Fish Speech+ + RVC", "min_vram": 6, "rec_vram": 8, "gpu_vendor": ["NVIDIA"], "size_gb": 15},
    {"id": "high", "name": "F5-TTS", "min_vram": 4, "rec_vram": 8, "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"], "size_gb": 4},
    {"id": "high+low", "name": "F5-TTS + RVC", "min_vram": 6, "rec_vram": 8, "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"], "size_gb": 4},
]

__all__ = ["LOCAL_VOICE_MODELS"]
