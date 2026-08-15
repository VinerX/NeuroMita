"""Supervised restart support for the Python application.

An ordinary restart returns exit code 42 to the existing run.py process. This
keeps the same process chain and console as a run.bat launch. A detached process
is reserved for update recovery when an older released Launcher.exe is still
locking its installed image.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from main_logger import logger


def spawn_detached_run() -> bool:
    """Запустить новый процесс run.py отдельно от текущего. True — удалось."""
    base_dir_raw = str(os.environ.get("NEUROMITA_BASE_DIR", "") or "").strip()
    if not base_dir_raw:
        logger.warning("[app_restart] Detached restart skipped: NEUROMITA_BASE_DIR is empty")
        return False

    base_dir = Path(base_dir_raw)
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
        creationflags = 0
        creationflags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) or 0)
        creationflags |= int(getattr(subprocess, "DETACHED_PROCESS", 0) or 0)
        detached_env = dict(os.environ)
        detached_env["NEUROMITA_DETACHED_RESTART"] = "1"
        subprocess.Popen(
            [str(python_exe), str(run_script)],
            cwd=str(base_dir),
            env=detached_env,
            close_fds=(sys.platform == "win32"),
            creationflags=creationflags,
        )
        return True
    except Exception:
        logger.error("[app_restart] Failed to spawn detached restart process", exc_info=True)
        return False


def restart_app() -> bool:
    """Restart the application through the existing run.py supervisor.

    Exit code 42 asks the parent run.py process to restart the pyz in its
    existing loop, preserving the original process chain and console.

    Returns:
        True when restart shutdown has been initiated.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    logger.info("[app_restart] Requesting supervised restart with exit code 42")
    if app is not None:
        app.exit(42)
        return True
    os._exit(42)
    return True  # недостижимо, но для ясности контракта
