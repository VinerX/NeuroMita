from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from handlers.ai_engine.worker_process import (
    _ensure_lib_on_path,
    _probe_runtime_modules,
)


def test_managed_worker_does_not_append_legacy_mutable_lib(tmp_path: Path, monkeypatch) -> None:
    overlay = tmp_path / "Lib" / "environment" / "tts" / "rev" / "site-packages"
    core = tmp_path / "Lib" / "environment" / "bases" / "torch" / "site-packages"
    stale_overlay = tmp_path / "Lib" / "environment" / "overlays" / "old" / "site-packages"
    stale_base = tmp_path / "Lib" / "environment" / "bases" / "old-torch" / "site-packages"
    legacy = tmp_path / "Lib"
    main_core = legacy / "core"
    overlay.mkdir(parents=True)
    core.mkdir(parents=True)
    stale_overlay.mkdir(parents=True)
    stale_base.mkdir(parents=True)
    main_core.mkdir(parents=True)
    monkeypatch.setenv("NEUROMITA_RUNTIME_ROOT", str(legacy))
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(main_core))
    monkeypatch.setenv("NEUROMITA_CORE_DIR", str(main_core))
    old_path = list(sys.path)
    sys.path.insert(0, str(legacy.resolve()))
    sys.path.insert(0, str(main_core.resolve()))
    sys.path.insert(0, str(stale_overlay.resolve()))
    sys.path.insert(0, str(stale_base.resolve()))
    try:
        _ensure_lib_on_path([str(overlay), str(core)])
        assert sys.path[:2] == [str(overlay.resolve()), str(core.resolve())]
        assert str(legacy.resolve()) not in sys.path[:2]
        assert str(legacy.resolve()) not in sys.path
        assert str(main_core.resolve()) not in sys.path
        assert str(stale_overlay.resolve()) not in sys.path
        assert str(stale_base.resolve()) not in sys.path
        assert os.environ["NEUROMITA_RUNTIME_TARGET_DIR"] == str(overlay.resolve())
        assert os.environ["NEUROMITA_RUNTIME_PYTHON_PATHS"].split(os.pathsep) == [
            str(overlay.resolve()),
            str(core.resolve()),
        ]
    finally:
        sys.path[:] = old_path


def test_runtime_probe_imports_each_module_once() -> None:
    with patch(
        "handlers.ai_engine.worker_process.importlib.import_module"
    ) as import_module:
        _probe_runtime_modules(["torch", "f5_tts", "torch", ""])

    assert [call.args[0] for call in import_module.call_args_list] == [
        "torch",
        "f5_tts",
    ]


def test_runtime_probe_reports_failing_module() -> None:
    with patch(
        "handlers.ai_engine.worker_process.importlib.import_module",
        side_effect=ImportError("missing native dll"),
    ), pytest.raises(RuntimeError, match="broken_backend"):
        _probe_runtime_modules(["broken_backend"])
