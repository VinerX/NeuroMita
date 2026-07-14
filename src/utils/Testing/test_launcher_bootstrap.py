from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = next(
    candidate
    for candidate in (
        SOURCE_ROOT / "run.py",
        SOURCE_ROOT.parent / "run.py",
        SOURCE_ROOT.parent / "scripts" / "run.py",
    )
    if candidate.is_file()
)


def _load_launcher():
    name = f"neuromita_run_test_{id(object())}"
    spec = importlib.util.spec_from_file_location(name, LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_is_bound_to_the_interpreter_that_started_it() -> None:
    launcher = _load_launcher()
    assert launcher.PYTHON == Path(sys.executable)


def test_launcher_uv_is_isolated_from_embedded_python_scripts() -> None:
    launcher = _load_launcher()
    assert launcher.UV_TARGET == launcher.ROOT / ".bootstrap" / "uv"
    assert launcher.UV_EXE.parent == launcher.UV_TARGET / "bin"
    assert launcher.UV_EXE.parent != launcher.PYTHON.parent / "Scripts"


def test_launcher_does_not_forward_global_native_widget_mode(monkeypatch) -> None:
    launcher = _load_launcher()
    monkeypatch.setenv("QT_USE_NATIVE_WINDOWS", "1")

    environment = launcher._base_env()

    assert "QT_USE_NATIVE_WINDOWS" not in environment


def test_launcher_normalizes_unsigned_windows_negative_exit_code() -> None:
    launcher = _load_launcher()

    assert launcher._normalize_child_exit_code(0xFFFFFFFF, windows=True) == 1
    assert launcher._normalize_child_exit_code(42, windows=True) == 42
    assert launcher._normalize_child_exit_code(0, windows=True) == 0


def test_uv_requirements_install_targets_explicit_core(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-package\n", encoding="utf-8")
    python = tmp_path / "embedded" / "python.exe"
    target = tmp_path / "Lib" / "core"
    uv = tmp_path / ".bootstrap" / "uv" / "bin" / "uv.exe"
    commands: list[list[str]] = []

    monkeypatch.setattr(launcher, "PYTHON", python)
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "UV_EXE", uv)
    monkeypatch.setattr(launcher, "ensure_uv", lambda: True)
    monkeypatch.setattr(
        launcher,
        "run",
        lambda cmd, **_kwargs: commands.append(list(cmd)) or 0,
    )

    assert launcher.install_requirements(target) is True
    command = commands[0]
    assert command[:3] == [str(uv), "pip", "install"]
    assert command[command.index("--python") + 1] == str(python)
    assert command[command.index("--target") + 1] == str(target)


def test_pip_fallback_targets_explicit_core(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-package\n", encoding="utf-8")
    python = tmp_path / "embedded" / "python.exe"
    target = tmp_path / "Lib" / "core"
    commands: list[list[str]] = []

    monkeypatch.setattr(launcher, "PYTHON", python)
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "ensure_uv", lambda: False)
    monkeypatch.setattr(launcher, "ensure_pip", lambda: None)
    monkeypatch.setattr(
        launcher,
        "run",
        lambda cmd, **_kwargs: commands.append(list(cmd)) or 0,
    )

    assert launcher.install_requirements(target) is True
    command = commands[0]
    assert command[:5] == [str(python), "-m", "pip", "--isolated", "install"]
    assert command[command.index("--target") + 1] == str(target)


def test_uv_bootstrap_installs_only_into_private_target(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    target = tmp_path / ".bootstrap" / "uv"
    executable = target / "bin" / "uv.exe"
    commands: list[list[str]] = []

    monkeypatch.setattr(launcher, "UV_TARGET", target)
    monkeypatch.setattr(launcher, "UV_EXE", executable)
    monkeypatch.setattr(launcher, "PYTHON", tmp_path / "embedded" / "python.exe")
    monkeypatch.setattr(launcher, "ensure_pip", lambda: None)
    monkeypatch.setattr(
        launcher,
        "run_quiet",
        lambda cmd, **_kwargs: executable.is_file(),
    )

    def fake_run(cmd, **_kwargs):
        commands.append(list(cmd))
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b"")
        return 0

    monkeypatch.setattr(launcher, "run", fake_run)

    assert launcher.ensure_uv() is True
    command = commands[0]
    assert command[command.index("--target") + 1] == str(target)
    assert str(launcher.PYTHON.parent / "Scripts") not in " ".join(command)


def test_core_health_does_not_trust_state_when_files_are_missing(
    tmp_path,
    monkeypatch,
) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-package==1.0\n", encoding="utf-8")
    core = tmp_path / "Lib" / "core"
    core.mkdir(parents=True)
    state_file = tmp_path / ".bootstrap" / "core-state.json"
    state_file.parent.mkdir(parents=True)

    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "CORE_DIR", core)
    monkeypatch.setattr(launcher, "CORE_STATE_FILE", state_file)
    monkeypatch.setattr(launcher, "_python_identity", lambda: {"python": "test"})
    monkeypatch.setattr(
        launcher,
        "_distribution_snapshot",
        lambda _target: [
            {
                "name": "example-package",
                "version": "1.0",
                "probes": ["example_package"],
                "file_count": 10,
                "files_complete": False,
            }
        ],
    )
    state_file.write_text(
        json.dumps(
            {
                "state_version": launcher.STATE_VERSION,
                "requirements_sha256": launcher.file_hash(requirements),
                "python": {"python": "test"},
                "top_level_entries": [],
                "distributions": [
                    {
                        "name": "example-package",
                        "version": "1.0",
                        "probes": ["example_package"],
                        "file_count": 10,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert launcher.core_is_healthy() is False


def test_application_is_started_without_embedded_site_packages(
    tmp_path,
    monkeypatch,
) -> None:
    launcher = _load_launcher()
    pyz = tmp_path / "NeuroMita.pyz"
    requirements = tmp_path / "requirements.txt"
    pyz.write_bytes(b"pyz")
    requirements.write_text("example-package\n", encoding="utf-8")
    python = tmp_path / "libs" / "python" / "python.exe"
    core = tmp_path / "Lib" / "core"
    commands: list[tuple[list[str], dict[str, str]]] = []

    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "PYZ", pyz)
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "PYTHON", python)
    monkeypatch.setattr(launcher, "RUNTIME_ROOT", tmp_path / "Lib")
    monkeypatch.setattr(launcher, "CORE_DIR", core)
    monkeypatch.setattr(launcher, "core_is_healthy", lambda: True)

    def fake_run(cmd, *, env=None):
        commands.append((list(cmd), dict(env or {})))
        return 0

    monkeypatch.setattr(launcher, "run", fake_run)

    try:
        launcher.main()
    except SystemExit as exc:
        assert exc.code == 0

    command, env = commands[-1]
    assert command == [str(python), "-S", str(pyz)]
    assert env["PYTHONPATH"] == str(core)
    assert env["NEUROMITA_CORE_DIR"] == str(core)


def test_launcher_quarantines_legacy_root_lib_payload_after_core_validation(
    tmp_path,
    monkeypatch,
) -> None:
    launcher = _load_launcher()
    runtime = tmp_path / "Lib"
    core = runtime / "core"
    environment = runtime / "environment"
    legacy_package = runtime / "old_package"
    legacy_dist = runtime / "old_package-1.0.dist-info"
    core.mkdir(parents=True)
    environment.mkdir(parents=True)
    legacy_package.mkdir()
    legacy_dist.mkdir()

    monkeypatch.setattr(launcher, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(launcher, "CORE_DIR", core)

    launcher._cleanup_legacy_runtime_payloads()

    assert core.is_dir()
    assert environment.is_dir()
    assert not legacy_package.exists()
    assert not legacy_dist.exists()
    assert (runtime / ".legacy-runtime" / "old_package").is_dir()
    assert (runtime / ".legacy-runtime" / "old_package-1.0.dist-info").is_dir()


def test_core_health_rejects_ai_runtime_packages(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-package==1.0\n", encoding="utf-8")
    core = tmp_path / "Lib" / "core"
    core.mkdir(parents=True)
    state_file = tmp_path / ".bootstrap" / "core-state.json"
    state_file.parent.mkdir(parents=True)
    snapshot = [
        {
            "name": "torch",
            "version": "2.7.1",
            "probes": ["torch"],
            "file_count": 1,
            "files_complete": True,
        }
    ]
    state_file.write_text(
        json.dumps(
            {
                "state_version": launcher.STATE_VERSION,
                "requirements_sha256": launcher.file_hash(requirements),
                "python": {"python": "test"},
                "top_level_entries": [],
                "distributions": [
                    {
                        "name": "torch",
                        "version": "2.7.1",
                        "probes": ["torch"],
                        "file_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "CORE_DIR", core)
    monkeypatch.setattr(launcher, "CORE_STATE_FILE", state_file)
    monkeypatch.setattr(launcher, "_python_identity", lambda: {"python": "test"})
    monkeypatch.setattr(launcher, "_distribution_snapshot", lambda _target: snapshot)

    assert launcher.core_is_healthy() is False


def test_core_transaction_rejects_ai_runtime_packages(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    runtime = tmp_path / "Lib"
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("torch==2.7.1\n", encoding="utf-8")
    logs: list[str] = []

    monkeypatch.setattr(launcher, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(launcher, "CORE_DIR", runtime / "core")
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "CORE_STATE_FILE", tmp_path / ".bootstrap" / "state.json")
    monkeypatch.setattr(launcher, "LEGACY_HASH_FILE", tmp_path / ".req_hash")
    monkeypatch.setattr(launcher, "install_requirements", lambda _target: True)
    monkeypatch.setattr(
        launcher,
        "_distribution_snapshot",
        lambda _target: [
            {
                "name": "torch",
                "version": "2.7.1",
                "probes": ["torch"],
                "file_count": 1,
                "files_complete": True,
            }
        ],
    )
    monkeypatch.setattr(launcher, "log", logs.append)

    assert launcher.install_core_transactionally() is False
    assert not (runtime / "core").exists()
    assert any("Lib/environment" in message and "torch" in message for message in logs)


def test_core_lock_reuses_persistent_kernel_lock_file(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    bootstrap = tmp_path / ".bootstrap"
    lock_file = bootstrap / "core-install.lock"
    bootstrap.mkdir(parents=True)
    lock_file.write_text("pid=424242 time=0\n", encoding="ascii")

    monkeypatch.setattr(launcher, "BOOTSTRAP_DIR", bootstrap)
    monkeypatch.setattr(launcher, "CORE_LOCK_FILE", lock_file)
    with launcher._CoreInstallLock(timeout=1.0, stale_after=10.0):
        assert lock_file.is_file()

    assert lock_file.exists()
    assert f"pid={launcher.os.getpid()}" in lock_file.read_text(encoding="ascii")
    with launcher._CoreInstallLock(timeout=1.0, stale_after=10.0):
        assert lock_file.is_file()
    assert f"pid={launcher.os.getpid()}" in lock_file.read_text(encoding="ascii")


def test_core_health_rejects_unowned_top_level_payload(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-package==1.0\n", encoding="utf-8")
    core = tmp_path / "Lib" / "core"
    package_dir = core / "example_package"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (core / "random_shadow_package").mkdir()
    state_file = tmp_path / ".bootstrap" / "core-state.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        json.dumps(
            {
                "state_version": launcher.STATE_VERSION,
                "requirements_sha256": launcher.file_hash(requirements),
                "python": {"python": "test"},
                "top_level_entries": ["example_package"],
                "distributions": [
                    {
                        "name": "example-package",
                        "version": "1.0",
                        "probes": ["example_package"],
                        "file_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "CORE_DIR", core)
    monkeypatch.setattr(launcher, "CORE_STATE_FILE", state_file)
    monkeypatch.setattr(launcher, "_python_identity", lambda: {"python": "test"})
    monkeypatch.setattr(
        launcher,
        "_distribution_snapshot",
        lambda _target: [
            {
                "name": "example-package",
                "version": "1.0",
                "probes": ["example_package"],
                "file_count": 1,
                "files_complete": True,
            }
        ],
    )

    assert launcher.core_is_healthy() is False


def test_launcher_applies_g4f_override_through_effective_core_requirements(
    tmp_path,
    monkeypatch,
) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("g4f[all]==0.4.7.7\nexample-package==1.0\n", encoding="utf-8")
    settings_file = tmp_path / "Settings" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "G4F_VERSION": "0.4.7.7",
                "G4F_UPDATE_PENDING": True,
                "G4F_TARGET_VERSION": "0.5.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(launcher, "BOOTSTRAP_DIR", tmp_path / ".bootstrap")
    monkeypatch.setattr(
        launcher,
        "EFFECTIVE_REQ_FILE",
        tmp_path / ".bootstrap" / "effective-requirements.txt",
    )

    text, desired = launcher._effective_requirements_text()

    assert desired == "0.5.0"
    assert "g4f[all]==0.5.0" in text
    assert "g4f[all]==0.4.7.7" not in text

    launcher._mark_pending_g4f_update_applied()
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["G4F_VERSION"] == "0.5.0"
    assert saved["G4F_UPDATE_PENDING"] is False
    assert saved["G4F_TARGET_VERSION"] is None
