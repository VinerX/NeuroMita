from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.backends import BackendKind
from core.runtime_environments import (
    EnvironmentTransaction,
    RuntimeEnvironmentManager,
    _short_staging_name,
)
from utils.pip_installer import PipInstaller


def _installer(tmp_path: Path, logs: list[str] | None = None) -> PipInstaller:
    target = tmp_path / "Lib" / "environment" / ".staging" / "e-deadbeef-cafebabe" / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    return PipInstaller(
        update_status=lambda *_: None,
        update_log=(logs.append if logs is not None else (lambda *_: None)),
        update_progress=lambda *_: None,
        protected_packages=[],
        target_path=target,
    )


def test_environment_transaction_uses_compact_staging_name(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    transaction = EnvironmentTransaction(
        manager=manager,
        logical_id="tts-cross-lingual-f5-tts-rvc-extremely-long-component-id",
        category="tts",
        item_id="long",
        requested_specs=("example==1.0",),
        required_backend=BackendKind.CPU,
        backend_context={},
        transaction_id="a" * 32,
    )

    assert transaction.staging_root is not None
    assert transaction.staging_root.parent == manager.staging_root
    assert transaction.staging_root.name.startswith("e-")
    assert len(transaction.staging_root.name) == 19
    assert "cross-lingual" not in transaction.staging_root.name
    transaction.abort()


def test_core_staging_name_is_compact_and_collision_resistant() -> None:
    first = _short_staging_name(
        "core",
        "torch-cu128-2.7.1-cu128-py312-win-amd64-029b747846",
        "1" * 32,
    )
    second = _short_staging_name(
        "core",
        "torch-cu128-2.7.1-cu128-py312-win-amd64-029b747846",
        "2" * 32,
    )

    assert first.startswith("c-")
    assert len(first) == 19
    assert second != first


def test_compact_core_staging_keeps_reported_numpy_path_under_260_chars() -> None:
    base = Path(r"D:\Game\NeuroMita\PythonBuild-v2026.09.02.1")
    layer_id = "torch-cu128-2.7.1-cu128-py312-win-amd64-029b747846"
    wheel_member = Path("numpy.libs") / "libopenblas64__v0.3.23-293-gc2f4bdbb-gcc_10_3_0-65e29aac85b9409a6008e2dc84b1cc09.dll"
    legacy = (
        base
        / "Lib"
        / "environment"
        / ".staging"
        / f"core-{layer_id}-{'5' * 32}"
        / "site-packages"
        / wheel_member
    )
    compact = (
        base
        / "Lib"
        / "environment"
        / ".staging"
        / _short_staging_name("core", layer_id, "5" * 32)
        / "site-packages"
        / wheel_member
    )

    # Use Windows-style separators when comparing with the user's failing path.
    legacy_len = len(str(legacy).replace("/", "\\"))
    compact_len = len(str(compact).replace("/", "\\"))
    assert legacy_len > 260
    assert compact_len < 260
    assert compact_len < legacy_len - 40


def test_uv_pe_trampoline_lock_retries_same_uv_command_with_clean_staging(tmp_path: Path) -> None:
    logs: list[str] = []
    installer = _installer(tmp_path, logs)
    target = Path(installer.libs_path_abs)
    calls: list[list[str]] = []

    def fake_run(cmd, _description):
        calls.append(list(cmd))
        if len(calls) == 1:
            (target / "partial.txt").write_text("partial", encoding="utf-8")
            installer._last_run_returncode = 1
            installer._last_run_recent_lines = [
                "error: Failed to install: uvicorn-0.52.4-py3-none-any.whl",
                r"Caused by: Failed to update Windows PE resources: C:\\Temp\\.tmp\\uv-trampoline-34876.exe",
                "Caused by: The system cannot open the device or file specified. (os error -2147024786)",
            ]
            return False
        assert not (target / "partial.txt").exists()
        installer._last_run_returncode = 0
        installer._last_run_recent_lines = []
        return True

    cmd = [str(tmp_path / "uv.exe"), "pip", "install", "--target", str(target), "uvicorn"]
    with patch.object(installer, "_run_pip_process", side_effect=fake_run), patch(
        "utils.pip_installer.time.sleep", return_value=None
    ):
        ok = installer._run_install_with_transient_retries(cmd, "Installing...")

    assert ok is True
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert any("повтор установки 2/3" in line.lower() for line in logs)


def test_uv_path_materialization_error_is_not_blindly_retried(tmp_path: Path) -> None:
    logs: list[str] = []
    installer = _installer(tmp_path, logs)
    calls = 0

    def fake_run(_cmd, _description):
        nonlocal calls
        calls += 1
        installer._last_run_returncode = 1
        installer._last_run_recent_lines = [
            "error: Failed to install: numpy-1.26.0-cp312-cp312-win_amd64.whl",
            "Caused by: Failed to persist temporary file",
            "failed to persist temporary file: Системе не удается найти указанный путь. (os error 3)",
        ]
        return False

    cmd = [str(tmp_path / "uv.exe"), "pip", "install", "numpy"]
    with patch.object(installer, "_run_pip_process", side_effect=fake_run):
        ok = installer._run_install_with_transient_retries(cmd, "Installing...")

    assert ok is False
    assert calls == 1
    assert any("os error 3" in line.lower() for line in logs)


def test_uv_resolver_failure_is_never_classified_as_windows_transient(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    installer._last_run_returncode = 2
    installer._last_run_recent_lines = ["No solution found when resolving dependencies"]
    cmd = [str(tmp_path / "uv.exe"), "pip", "install", "f5-tts"]

    assert installer._uv_windows_install_failure_kind(cmd) is None
