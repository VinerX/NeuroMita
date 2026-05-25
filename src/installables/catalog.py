from __future__ import annotations

from core.backends import BackendKind
from core.installables import InstallableRegistry

from installables.components import (
    AsrModelInstallableComponent,
    BackendInstallableComponent,
    BeatInstallableComponent,
    RagInstallableComponent,
    VoiceModelInstallableComponent,
)


def build_installable_registry() -> InstallableRegistry:
    registry = InstallableRegistry()
    _register_backends(registry)
    _register_voice_models(registry)
    _register_asr_models(registry)
    _register_rag_components(registry)
    _register_beat_components(registry)
    return registry


def _register_backends(registry: InstallableRegistry) -> None:
    for kind in (BackendKind.CPU, BackendKind.CUDA, BackendKind.ONNX):
        registry.register(BackendInstallableComponent(kind))


def _register_voice_models(registry: InstallableRegistry) -> None:
    try:
        from handlers.voice_models.catalog import get_all_voice_specs
    except Exception:
        return

    for spec in get_all_voice_specs() or []:
        try:
            ids = spec.supported_model_ids() or []
        except Exception:
            ids = []
        for model_id in ids:
            registry.register(VoiceModelInstallableComponent(str(model_id), spec))


def _register_asr_models(registry: InstallableRegistry) -> None:
    try:
        from handlers.asr_handler import SpeechRecognition
    except Exception:
        return

    for engine_id, recognizer_cls in (getattr(SpeechRecognition, "_registry", {}) or {}).items():
        registry.register(AsrModelInstallableComponent(str(engine_id), recognizer_cls))


def _register_rag_components(registry: InstallableRegistry) -> None:
    try:
        from managers.rag.install_spec import TARGET_CURRENT, TARGET_EMBEDDINGS, TARGET_RERANKER
    except Exception:
        return

    registry.register(RagInstallableComponent(TARGET_EMBEDDINGS, "RAG embeddings"))
    registry.register(RagInstallableComponent(TARGET_RERANKER, "RAG reranker"))
    registry.register(RagInstallableComponent(TARGET_CURRENT, "Current RAG backend"))


def _register_beat_components(registry: InstallableRegistry) -> None:
    try:
        from game_connections.services.beat_backend_spec import (
            BACKEND_AUTO,
            BACKEND_BEAT_THIS,
            BACKEND_DSP,
            BACKEND_LIBROSA,
            backend_display_name,
        )
    except Exception:
        return

    for backend_id in (BACKEND_AUTO, BACKEND_BEAT_THIS, BACKEND_LIBROSA, BACKEND_DSP):
        registry.register(BeatInstallableComponent(backend_id, backend_display_name(backend_id)))


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
