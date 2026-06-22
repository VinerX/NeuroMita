from __future__ import annotations

from core.backends.installable_component import create_backend_installable_components
from core.installables import InstallableRegistry
from game_connections.services.beat_install import create_beat_installable_components
from installables.ffmpeg_component import create_ffmpeg_installable_components
from installables.voice_assets import create_voice_asset_installable_components
from handlers.asr_handler import SpeechRecognition
from handlers.voice_models.edge_tts_rvc_model import EdgeTTSRVCCudaModel, EdgeTTSRVCOnnxModel
from handlers.voice_models.f5_tts_model import F5TTSModel
from handlers.voice_models.fish_speech_model import FishSpeechModel
from main_logger import logger
from managers.rag.install_spec import create_rag_installable_components


def _register_component_group(
    registry: InstallableRegistry,
    *,
    label: str,
    factory,
) -> None:
    try:
        registry.register_many(factory())
    except Exception as exc:
        logger.error(f"Installable registry: failed to register '{label}': {exc}", exc_info=True)


def build_installable_registry() -> InstallableRegistry:
    registry = InstallableRegistry()
    _register_component_group(registry, label="backends", factory=create_backend_installable_components)
    _register_component_group(registry, label="edge_tts_rvc_cuda", factory=EdgeTTSRVCCudaModel.create_installable_components)
    _register_component_group(registry, label="edge_tts_rvc_onnx", factory=EdgeTTSRVCOnnxModel.create_installable_components)
    _register_component_group(registry, label="fish_speech", factory=FishSpeechModel.create_installable_components)
    _register_component_group(registry, label="f5_tts", factory=F5TTSModel.create_installable_components)
    _register_component_group(registry, label="speech_recognition", factory=SpeechRecognition.create_installable_components)
    _register_component_group(registry, label="rag", factory=create_rag_installable_components)
    _register_component_group(registry, label="beat_sync", factory=create_beat_installable_components)
    _register_component_group(registry, label="ffmpeg", factory=create_ffmpeg_installable_components)
    _register_component_group(registry, label="voice_assets", factory=create_voice_asset_installable_components)
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
