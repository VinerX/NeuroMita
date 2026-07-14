"""Управляемый перезапуск приложения (Python-часть).

Спавнит отдельный detached-процесс run.py из NEUROMITA_BASE_DIR и завершает
текущий. Если detached-запуск недоступен — падаем на код выхода 42, который
run.bat/run.py трактуют как «перезапустить».

Используется после установки Python-обновления и при смене языка.
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
    """Перезапустить приложение.

    Сначала пытается спавнить detached run.py и мягко закрыть текущее
    QApplication (чтобы освободить файлы), иначе — exit(42)/os._exit(42).

    Returns:
        True — перезапуск инициирован (процесс скоро завершится).
    """
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()

    if spawn_detached_run():
        if app is not None:
            QTimer.singleShot(100, app.quit)
            QTimer.singleShot(400, lambda: os._exit(0))
        else:
            os._exit(0)
        return True

    # Fallback: код 42 — run.bat/run.py перезапускают по нему.
    logger.info("[app_restart] Falling back to exit code 42 for restart")
    if app is not None:
        app.exit(42)
        return True
    os._exit(42)
    return True  # недостижимо, но для ясности контракта
