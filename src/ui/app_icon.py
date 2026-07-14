"""Единая точка получения иконки приложения и идентичности в панели задач.

Раньше иконка грузилась по ОТНОСИТЕЛЬНОМУ пути (`QIcon("Icon.ico")` /
`QIcon("Icon.png")`) и зависела от текущей рабочей папки, а `Icon.ico` вообще
не существовал (в поставке только `Icon.png`). При перезапуске через кнопку
«Перезапустить» приложение поднимается detached-процессом `python.exe run.py`
в обход `Launcher.exe`, и без явного AppUserModelID панель задач Windows
берёт иконку самого `python.exe` — окно оказывается «без иконки».

Здесь иконка резолвится по АБСОЛЮТНОМУ пути от `NEUROMITA_BASE_DIR` или от
корня проекта, вычисленного относительно самого модуля. На Windows также
закрепляется собственный AppUserModelID.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

from main_logger import logger

# Приоритет: .ico (родной формат иконок Windows) → .png (то, что реально есть).
_ICON_CANDIDATES = ("Icon.ico", "Icon.png")
_APP_USER_MODEL_ID = "NeuroMita.App"


def _base_dir() -> Path:
    """Return the application root without falling back to the process cwd."""
    configured = str(os.environ.get("NEUROMITA_BASE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def app_icon_path() -> str | None:
    """Return a cwd-independent icon path.

    ``Icon.png`` is the packaged fallback. Returning its deterministic path
    even in source-only/test layouts keeps callers independent from cwd;
    ``QIcon`` safely handles a missing file in an incomplete checkout.
    """
    base = _base_dir()
    for name in _ICON_CANDIDATES:
        candidate = base / name
        if candidate.is_file():
            return str(candidate)
    return str(base / "Icon.png")


def application_icon():
    """QIcon приложения по абсолютному пути (пустой QIcon, если файла нет)."""
    from PyQt6.QtGui import QIcon

    path = app_icon_path()
    return QIcon(path) if path else QIcon()


def set_app_user_model_id() -> None:
    """Windows: закрепить собственный AppUserModelID.

    Иначе панель задач наследует иконку/идентичность запускающего exe
    (`python.exe` при перезапуске detached-процессом в обход Launcher.exe),
    и иконка окна не берётся. Вызывать до создания первого окна.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
    except Exception as exc:  # pragma: no cover - platform dependent
        logger.debug(f"set_app_user_model_id skipped: {exc}")
