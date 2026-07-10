from __future__ import annotations

import os
import sys
from pathlib import Path

from handlers.ai_engine.worker_process import _ensure_lib_on_path


def test_managed_worker_does_not_append_legacy_mutable_lib(tmp_path: Path, monkeypatch) -> None:
    overlay = tmp_path / "Lib" / "environment" / "tts" / "rev" / "site-packages"
    core = tmp_path / "Lib" / "core" / "torch" / "site-packages"
    legacy = tmp_path / "Lib"
    overlay.mkdir(parents=True)
    core.mkdir(parents=True)
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(legacy))
    old_path = list(sys.path)
    sys.path.insert(0, str(legacy.resolve()))
    try:
        _ensure_lib_on_path([str(overlay), str(core)])
        assert sys.path[:2] == [str(overlay.resolve()), str(core.resolve())]
        assert str(legacy.resolve()) not in sys.path[:2]
        assert str(legacy.resolve()) not in sys.path
        assert os.environ["NEUROMITA_RUNTIME_TARGET_DIR"] == str(overlay.resolve())
        assert os.environ["NEUROMITA_RUNTIME_PYTHON_PATHS"].split(os.pathsep) == [
            str(overlay.resolve()),
            str(core.resolve()),
        ]
    finally:
        sys.path[:] = old_path
