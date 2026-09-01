from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_SOURCE = PROJECT_ROOT / "scripts" / "launcher.c"
RUN_SCRIPT = PROJECT_ROOT / "scripts" / "run.py"
APP_RESTART = PROJECT_ROOT / "src" / "utils" / "app_restart.py"
RUNTIME_BOOTSTRAP = PROJECT_ROOT / "src" / "startup" / "runtime_bootstrap.py"
UPDATER = PROJECT_ROOT / "src" / "updater.py"


def test_native_launcher_owns_post_exit_zipapp_activation_then_delegates() -> None:
    source = LAUNCHER_SOURCE.read_text(encoding="utf-8")

    assert 'L"%ls\\\\run.bat"' in source
    assert "CreateProcessW(cmd_exe" in source
    assert "CREATE_NEW_CONSOLE" in source
    assert "WaitForSingleObject" in source
    assert "MoveFileExW" in source
    assert "MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH" in source
    assert '.update\\\\python\\\\pending\\\\NeuroMita.pyz' in source
    assert 'L"%ls\\\\run.py"' not in source
    assert 'L"%ls\\\\libs\\\\python\\\\python.exe"' not in source


def test_restart_contract_separates_ordinary_and_update_restarts() -> None:
    restart_source = APP_RESTART.read_text(encoding="utf-8")

    restart_body = restart_source[restart_source.index("def restart_app()") :]
    assert "pending_activation_exists" in restart_body
    assert "spawn_launcher_after_exit()" in restart_body
    assert "UPDATE_RESTART_EXIT_CODE" in restart_body
    assert "app.exit(exit_code)" in restart_body
    assert "else 42" in restart_body


def test_runtime_bootstrap_hands_pending_activation_to_launcher() -> None:
    bootstrap_source = RUNTIME_BOOTSTRAP.read_text(encoding="utf-8")

    activation_branch = bootstrap_source[
        bootstrap_source.index('python_recovery.status == "waiting_for_activation"') :
    ]
    assert "spawn_launcher_after_exit" in activation_branch
    assert "UPDATE_RESTART_EXIT_CODE" in activation_branch
    assert "raise SystemExit(UPDATE_RESTART_EXIT_CODE)" in activation_branch


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
