from __future__ import annotations

import os
from pathlib import Path


def base_dir() -> Path:
    configured = str(os.environ.get("NEUROMITA_BASE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def settings_dir(*, create: bool = False) -> Path:
    path = base_dir() / "Settings"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path(*parts: str, create_parent: bool = False) -> Path:
    path = settings_dir(create=create_parent).joinpath(*parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def runtime_log_path() -> Path:
    configured = str(os.environ.get("NEUROMITA_LOG_PATH", "") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = base_dir() / path
        return path.resolve()
    return base_dir() / "NeuroMitaLogs.log"
