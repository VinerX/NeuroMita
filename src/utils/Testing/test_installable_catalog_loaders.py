from __future__ import annotations

from types import SimpleNamespace

from handlers.voice_models.edge_tts_rvc_model import EDGE_TTS_RVC_CUDA_ID, EdgeTTSRVCCudaModel
from handlers.voice_models.install_plan_helpers import patch_tts_with_rvc_audio
from installables.catalog_manifest import CATALOG_ENTRIES
from installables.registry_builder import LazyInstallableRegistry


def test_all_catalog_loaders_resolve_and_create_components() -> None:
    loaders = dict.fromkeys(entry.loader for entry in CATALOG_ENTRIES)

    for loader_path in loaders:
        factory = LazyInstallableRegistry._resolve_loader(loader_path)
        components = list(factory() or ())
        assert components, loader_path
        assert all(str(getattr(component, "id", "")).strip() for component in components), loader_path


def test_manifest_backend_matches_canonical_component_definition() -> None:
    components = {}
    for loader_path in dict.fromkeys(entry.loader for entry in CATALOG_ENTRIES):
        factory = LazyInstallableRegistry._resolve_loader(loader_path)
        components.update({component.id: component for component in (factory() or ())})

    for entry in CATALOG_ENTRIES:
        component = components[entry.id]
        assert entry.declared_backend == component.metadata().backend.value, entry.id
        assert entry.declared_compatibility == component.metadata().compatibility.as_dict(), entry.id


def test_tts_rvc_audio_patch_is_idempotent(tmp_path) -> None:
    audio_file = tmp_path / "tts_with_rvc" / "lib" / "audio.py"
    audio_file.parent.mkdir(parents=True)
    audio_file.write_text("import ffmpeg\n", encoding="utf-8")
    installer = SimpleNamespace(libs_path_abs=str(tmp_path))

    assert patch_tts_with_rvc_audio(pip_installer=installer)
    first = audio_file.read_text(encoding="utf-8")
    assert 'ffmpeg = importlib.import_module("ffmpeg")' in first

    assert patch_tts_with_rvc_audio(pip_installer=installer)
    assert audio_file.read_text(encoding="utf-8") == first


def test_edge_rvc_install_plan_uses_voice_compatibility_patch() -> None:
    plan = EdgeTTSRVCCudaModel.build_install_plan_for_model(
        EDGE_TTS_RVC_CUDA_ID,
        {"gpu_vendor": "NVIDIA", "libs_dir": "unused"},
    )

    assert any(action.fn is patch_tts_with_rvc_audio for action in plan.actions)
