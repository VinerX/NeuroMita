from __future__ import annotations

import os

import managers.rag.install_spec as install_spec
from managers.rag.install_spec import TARGET_EMBEDDINGS, ensure_runtime_ready


def _set_worker_env(monkeypatch, tmp_path):
    overlay = tmp_path / "backend"
    core = tmp_path / "core"
    for path in (overlay, core):
        path.mkdir()

    monkeypatch.setenv("NEUROMITA_RUNTIME_TARGET_DIR", str(overlay))
    monkeypatch.setenv(
        "NEUROMITA_RUNTIME_PYTHON_PATHS",
        os.pathsep.join((str(overlay), str(core))),
    )
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(core))
    return overlay, core


def test_ensure_runtime_ready_uses_worker_runtime_context(monkeypatch, tmp_path):
    """Gate must inspect the split runtime layer, not the legacy Lib/core.

    Regression: with the split backend layers the readiness gate ran
    get_install_status(ctx=None), falling back to NEUROMITA_LIB_DIR (core,
    without torch) and raising a false "backend_cuda is not installed".
    """
    overlay, core = _set_worker_env(monkeypatch, tmp_path)

    seen: dict = {}

    def _fake_status(target, *, ctx=None):
        seen["ctx"] = dict(ctx or {})
        return {"required": True, "ok": True, "missing_required": []}

    monkeypatch.setattr(install_spec, "get_install_status", _fake_status)

    ensure_runtime_ready(TARGET_EMBEDDINGS)

    ctx = seen["ctx"]
    assert ctx.get("strict_target") is True
    assert ctx.get("target_dir") == str(overlay)
    assert ctx.get("python_paths") == [str(overlay), str(core)]


def test_ensure_runtime_ready_raises_with_original_message(monkeypatch, tmp_path):
    _set_worker_env(monkeypatch, tmp_path)

    def _fake_status(target, *, ctx=None):
        return {
            "required": True,
            "ok": False,
            "missing_required": ["backend_cuda"],
        }

    monkeypatch.setattr(install_spec, "get_install_status", _fake_status)

    raised = False
    try:
        ensure_runtime_ready(TARGET_EMBEDDINGS)
    except RuntimeError as exc:
        raised = True
        assert "backend_cuda" in str(exc)
    assert raised
