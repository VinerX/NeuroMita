from __future__ import annotations

import asyncio
import os

from handlers.local_voice_handler import LocalVoice


class _RuntimeAwareModel:
    seen_context: dict | None = None

    def __init__(self) -> None:
        self.initialized = False
        self.initialized_for = None
        self.initialize_calls = 0

    @classmethod
    def is_model_installed(cls, model_id: str, ctx: dict) -> bool:
        cls.seen_context = dict(ctx)
        return (
            model_id == "edge_tts_rvc_cuda"
            and ctx.get("strict_target") is True
            and ctx.get("target_dir") == os.environ["NEUROMITA_RUNTIME_TARGET_DIR"]
            and ctx.get("python_paths")
            == os.environ["NEUROMITA_RUNTIME_PYTHON_PATHS"].split(os.pathsep)
        )

    def initialize(self, init: bool = False) -> bool:
        self.initialize_calls += 1
        self.initialized = True
        self.initialized_for = "edge_tts_rvc_cuda"
        return True


def _voice_with_model(model: _RuntimeAwareModel) -> LocalVoice:
    voice = LocalVoice.__new__(LocalVoice)
    voice.provider = "NVIDIA"
    voice.current_model_id = None
    voice.active_model_instance = None
    voice._registry = {"edge_tts_rvc_cuda": model}
    return voice


def test_local_voice_installed_check_uses_worker_runtime_context(monkeypatch, tmp_path):
    overlay = tmp_path / "overlay"
    backend = tmp_path / "backend"
    core = tmp_path / "core"
    for path in (overlay, backend, core):
        path.mkdir()

    monkeypatch.setenv("NEUROMITA_RUNTIME_TARGET_DIR", str(overlay))
    monkeypatch.setenv(
        "NEUROMITA_RUNTIME_PYTHON_PATHS",
        os.pathsep.join((str(overlay), str(backend), str(core))),
    )
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(core))

    model = _RuntimeAwareModel()
    voice = _voice_with_model(model)

    assert voice.is_model_installed("edge_tts_rvc_cuda") is True
    assert model.seen_context is not None
    assert model.seen_context["gpu_vendor"] == "NVIDIA"
    assert model.seen_context["strict_target"] is True


def test_local_voice_initialization_does_not_recheck_legacy_core(monkeypatch, tmp_path):
    overlay = tmp_path / "overlay"
    backend = tmp_path / "backend"
    core = tmp_path / "core"
    for path in (overlay, backend, core):
        path.mkdir()

    monkeypatch.setenv("NEUROMITA_RUNTIME_TARGET_DIR", str(overlay))
    monkeypatch.setenv(
        "NEUROMITA_RUNTIME_PYTHON_PATHS",
        os.pathsep.join((str(overlay), str(backend), str(core))),
    )
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(core))

    model = _RuntimeAwareModel()
    voice = _voice_with_model(model)

    assert voice.initialize_model("edge_tts_rvc_cuda") is True
    assert voice.active_model_instance is model
    assert voice.current_model_id == "edge_tts_rvc_cuda"


def test_local_voiceover_never_initializes_model_on_demand():
    model = _RuntimeAwareModel()
    voice = _voice_with_model(model)
    voice.select_model("edge_tts_rvc_cuda")

    try:
        asyncio.run(voice.voiceover("hello", output_file="unused.wav"))
    except RuntimeError as exc:
        assert "Initialize it explicitly" in str(exc)
    else:
        raise AssertionError("Uninitialized voiceover must be rejected")

    assert model.initialize_calls == 0
