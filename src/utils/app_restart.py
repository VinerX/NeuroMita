"""Application restart handoff.

Ordinary restarts stay inside the existing run.py supervisor through exit code
42. A Python self-update is different: the verified NeuroMita.pyz remains
staged while the current zipapp is alive, so restart ownership is handed back
to Launcher.exe. Launcher waits for the current Python processes to exit,
atomically promotes the staged zipapp, and only then starts run.bat again.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from main_logger import logger
from services.update_activation import (
    UPDATE_RESTART_EXIT_CODE,
    pending_activation_exists,
)


def _base_dir() -> Path | None:
    raw = str(os.environ.get("NEUROMITA_BASE_DIR", "") or "").strip()
    return Path(raw) if raw else None


def _detached_creation_flags() -> int:
    flags = 0
    flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) or 0)
    flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0) or 0)
    return flags


def spawn_detached_run() -> bool:
    """Legacy recovery path for old releases that must relaunch run.py directly."""
    base_dir = _base_dir()
    if base_dir is None:
        logger.warning("[app_restart] Detached restart skipped: NEUROMITA_BASE_DIR is empty")
        return False

    run_script = base_dir / "run.py"
    python_exe = base_dir / "libs" / "python" / "python.exe"
    if not run_script.exists() or not python_exe.exists():
        logger.warning(
            f"[app_restart] Detached restart unavailable: run.py exists={run_script.exists()}, "
            f"python.exe exists={python_exe.exists()}"
        )
        return False

    try:
        logger.info(f"[app_restart] Spawning detached restart process: {python_exe} {run_script}")
        detached_env = dict(os.environ)
        detached_env["NEUROMITA_DETACHED_RESTART"] = "1"
        subprocess.Popen(
            [str(python_exe), str(run_script)],
            cwd=str(base_dir),
            env=detached_env,
            close_fds=(sys.platform == "win32"),
            creationflags=_detached_creation_flags(),
        )
        return True
    except Exception:
        logger.error("[app_restart] Failed to spawn detached restart process", exc_info=True)
        return False


def spawn_launcher_after_exit() -> bool:
    """Hand a pending zipapp activation to Launcher.exe.

    Launcher receives both the current app PID and its run.py supervisor PID.
    It waits for those processes to disappear before touching NeuroMita.pyz,
    which removes the zipimport self-overwrite race entirely.
    """
    base_dir = _base_dir()
    if base_dir is None:
        logger.warning("[app_restart] Launcher handoff skipped: NEUROMITA_BASE_DIR is empty")
        return False

    launcher = base_dir / "Launcher.exe"
    if not launcher.is_file():
        logger.error(f"[app_restart] Launcher handoff unavailable: {launcher} is missing")
        return False

    wait_pids = []
    for pid in (os.getpid(), os.getppid()):
        if pid > 0 and pid not in wait_pids:
            wait_pids.append(pid)

    command = [str(launcher)]
    for pid in wait_pids:
        command.extend(["--wait-pid", str(pid)])

    try:
        logger.info(
            "[app_restart] Handing pending Python activation to Launcher.exe; "
            f"wait_pids={wait_pids}"
        )
        subprocess.Popen(
            command,
            cwd=str(base_dir),
            env=dict(os.environ),
            close_fds=(sys.platform == "win32"),
            creationflags=_detached_creation_flags(),
        )
        return True
    except Exception:
        logger.error("[app_restart] Failed to spawn Launcher.exe handoff", exc_info=True)
        return False


def restart_app() -> bool:
    """Restart NeuroMita using the correct owner for the requested transition."""
    from PyQt6.QtWidgets import QApplication

    base_dir = _base_dir()
    update_restart = bool(base_dir and pending_activation_exists(base_dir))
    exit_code = UPDATE_RESTART_EXIT_CODE if update_restart else 42

    if update_restart and not spawn_launcher_after_exit():
        return False

    app = QApplication.instance()
    if update_restart:
        logger.info(
            "[app_restart] Requesting update handoff shutdown with exit code "
            f"{UPDATE_RESTART_EXIT_CODE}"
        )
    else:
        logger.info("[app_restart] Requesting supervised restart with exit code 42")

    if app is not None:
        app.exit(exit_code)
        return True
    os._exit(exit_code)
    return True
