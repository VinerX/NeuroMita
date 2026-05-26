from __future__ import annotations

from core.backends.installable_component import create_backend_installable_components
from core.installables import InstallableRegistry
from game_connections.services.beat_install import create_beat_installable_components
from handlers.asr_handler import SpeechRecognition
from handlers.voice_models.edge_tts_rvc_model import EdgeTTS_RVC_Model
from handlers.voice_models.f5_tts_model import F5TTSModel
from handlers.voice_models.fish_speech_model import FishSpeechModel
from managers.rag.install_spec import create_rag_installable_components


def build_installable_registry() -> InstallableRegistry:
    registry = InstallableRegistry()
    registry.register_many(create_backend_installable_components())
    registry.register_many(EdgeTTS_RVC_Model.create_installable_components())
    registry.register_many(FishSpeechModel.create_installable_components())
    registry.register_many(F5TTSModel.create_installable_components())
    registry.register_many(SpeechRecognition.create_installable_components())
    registry.register_many(create_rag_installable_components())
    registry.register_many(create_beat_installable_components())
    return registry


_REGISTRY: InstallableRegistry | None = None


def get_installable_registry() -> InstallableRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_installable_registry()
    return _REGISTRY


def refresh_installable_registry() -> InstallableRegistry:
    global _REGISTRY
    _REGISTRY = build_installable_registry()
    return _REGISTRY
