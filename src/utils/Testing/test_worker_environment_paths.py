from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from handlers.ai_engine.worker_process import (
    _configure_torch_compile_cache,
    _ensure_lib_on_path,
    _probe_runtime_modules,
)


def test_managed_worker_layers_shared_core_before_overlays_and_stable_main_core(tmp_path: Path, monkeypatch) -> None:
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
        _ensure_lib_on_path([str(core), str(overlay)])
        assert sys.path[:3] == [
            str(core.resolve()),
            str(overlay.resolve()),
            str(main_core.resolve()),
        ]
        assert str(legacy.resolve()) not in sys.path
        assert str(stale_overlay.resolve()) not in sys.path
        assert str(stale_base.resolve()) not in sys.path
        assert os.environ["NEUROMITA_RUNTIME_TARGET_DIR"] == str(overlay.resolve())
        assert os.environ["NEUROMITA_RUNTIME_PYTHON_PATHS"].split(os.pathsep) == [
            str(core.resolve()),
            str(overlay.resolve()),
            str(main_core.resolve()),
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


def test_worker_configures_shared_inductor_and_triton_caches(tmp_path: Path, monkeypatch) -> None:
    runtime_root = tmp_path / "Lib"
    environment_root = runtime_root / "environment"
    monkeypatch.setenv("NEUROMITA_ENVIRONMENT_DIR", str(environment_root))
    monkeypatch.delenv("TORCHINDUCTOR_CACHE_DIR", raising=False)
    monkeypatch.delenv("TRITON_CACHE_DIR", raising=False)
    monkeypatch.delenv("TORCHINDUCTOR_FX_GRAPH_CACHE", raising=False)

    _configure_torch_compile_cache(str(runtime_root))

    assert os.environ["TORCHINDUCTOR_CACHE_DIR"] == str(environment_root / "cache" / "torchinductor")
    assert os.environ["TRITON_CACHE_DIR"] == str(environment_root / "cache" / "triton")
    assert os.environ["TORCHINDUCTOR_FX_GRAPH_CACHE"] == "1"
    assert (environment_root / "cache").is_dir()


def test_worker_preserves_explicit_torch_compile_cache_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TORCHINDUCTOR_CACHE_DIR", str(tmp_path / "custom-inductor"))
    monkeypatch.setenv("TRITON_CACHE_DIR", str(tmp_path / "custom-triton"))
    monkeypatch.setenv("TORCHINDUCTOR_FX_GRAPH_CACHE", "0")

    _configure_torch_compile_cache(str(tmp_path / "Lib"))

    assert os.environ["TORCHINDUCTOR_CACHE_DIR"] == str(tmp_path / "custom-inductor")
    assert os.environ["TRITON_CACHE_DIR"] == str(tmp_path / "custom-triton")
    assert os.environ["TORCHINDUCTOR_FX_GRAPH_CACHE"] == "0"


def test_worker_activates_pth_paths_from_managed_layer(tmp_path: Path, monkeypatch) -> None:
    overlay = tmp_path / "Lib" / "environment" / "tts" / "rev" / "site-packages"
    win32 = overlay / "win32"
    pywin32_lib = overlay / "win32" / "lib"
    pythonwin = overlay / "pythonwin"
    main_core = tmp_path / "Lib" / "core"
    pywin32_lib.mkdir(parents=True)
    pythonwin.mkdir()
    main_core.mkdir(parents=True)
    (overlay / "pywin32.pth").write_text(
        "win32\nwin32\\lib\npythonwin\nimport pywin32_bootstrap\n",
        encoding="utf-8",
    )
    (pywin32_lib / "pywin32_bootstrap.py").write_text(
        "ACTIVATED = True\n",
        encoding="utf-8",
    )
    (pywin32_lib / "pywintypes.py").write_text("VALUE = 'available'\n", encoding="utf-8")
    monkeypatch.setenv("NEUROMITA_RUNTIME_ROOT", str(tmp_path / "Lib"))
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(main_core))
    monkeypatch.setenv("NEUROMITA_CORE_DIR", str(main_core))
    monkeypatch.delitem(sys.modules, "pywintypes", raising=False)
    monkeypatch.delitem(sys.modules, "pywin32_bootstrap", raising=False)

    old_path = list(sys.path)
    try:
        _ensure_lib_on_path([str(overlay)])
        module = __import__("pywintypes")

        assert module.VALUE == "available"
        assert sys.modules["pywin32_bootstrap"].ACTIVATED is True
        assert sys.path[:5] == [
            str(overlay.resolve()),
            str(win32.resolve()),
            str(pywin32_lib.resolve()),
            str(pythonwin.resolve()),
            str(main_core.resolve()),
        ]
    finally:
        sys.path[:] = old_path
        sys.modules.pop("pywintypes", None)
        sys.modules.pop("pywin32_bootstrap", None)


def test_worker_without_ai_environment_uses_only_stable_main_core(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "Lib"
    main_core = runtime_root / "core"
    embedded_site = tmp_path / "libs" / "python" / "Lib" / "site-packages"
    main_core.mkdir(parents=True)
    embedded_site.mkdir(parents=True)
    monkeypatch.setenv("NEUROMITA_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("NEUROMITA_CORE_DIR", str(main_core))
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(main_core))
    monkeypatch.setenv("NEUROMITA_PYTHON", str(tmp_path / "libs" / "python" / "python.exe"))

    old_path = list(sys.path)
    sys.path.insert(0, str(runtime_root))
    sys.path.insert(0, str(embedded_site))
    try:
        _ensure_lib_on_path(())
        assert sys.path[0] == str(main_core.resolve())
        assert str(runtime_root.resolve()) not in sys.path
        assert str(embedded_site.resolve()) not in sys.path
        assert os.environ["NEUROMITA_RUNTIME_PYTHON_PATHS"].split(os.pathsep) == [
            str(main_core.resolve())
        ]
        assert "NEUROMITA_RUNTIME_TARGET_DIR" not in os.environ
    finally:
        sys.path[:] = old_path
