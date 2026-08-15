from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_SOURCE = PROJECT_ROOT / "scripts" / "launcher.c"
RUN_SCRIPT = PROJECT_ROOT / "scripts" / "run.py"
APP_RESTART = PROJECT_ROOT / "src" / "utils" / "app_restart.py"
RUNTIME_BOOTSTRAP = PROJECT_ROOT / "src" / "startup" / "runtime_bootstrap.py"
UPDATER = PROJECT_ROOT / "src" / "updater.py"


def test_native_launcher_delegates_to_batch_without_waiting() -> None:
    source = LAUNCHER_SOURCE.read_text(encoding="utf-8")

    assert 'L"%ls\\\\run.bat"' in source
    assert "CreateProcessW(cmd_exe" in source
    assert "WaitForSingleObject" not in source
    assert 'L"%ls\\\\run.py"' not in source
    assert 'L"%ls\\\\libs\\\\python\\\\python.exe"' not in source


def test_supervised_restart_contract_stays_inside_run_py() -> None:
    run_source = RUN_SCRIPT.read_text(encoding="utf-8")
    restart_source = APP_RESTART.read_text(encoding="utf-8")

    assert "if code == 42:" in run_source
    assert "continue" in run_source[run_source.index("if code == 42:") :]
    restart_body = restart_source[restart_source.index("def restart_app()") :]
    assert "app.exit(42)" in restart_body
    assert "spawn_detached_run()" not in restart_body


def test_legacy_locked_launcher_update_keeps_detached_recovery_handoff() -> None:
    bootstrap_source = RUNTIME_BOOTSTRAP.read_text(encoding="utf-8")
    updater_source = UPDATER.read_text(encoding="utf-8")

    recovery_branch = bootstrap_source[
        bootstrap_source.index('python_recovery.status == "waiting_for_restart"') :
    ]
    assert "note_locked_restart_attempt(base_dir)" in recovery_branch
    assert "if spawn_detached_run():" in recovery_branch
    assert "raise SystemExit(0)" in recovery_branch

    resume_body = updater_source[
        updater_source.index("def resume_pending_python_update(") :
    ]
    assert 'os.environ.get("NEUROMITA_DETACHED_RESTART") != "1"' in resume_body
    assert "locked_retry_seconds=5.0" in resume_body
