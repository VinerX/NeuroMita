from __future__ import annotations

import os
import sys
from pathlib import Path


def unity_install_dir(configured: str | None = None) -> Path:
    if configured:
        return Path(str(configured))
    base_dir = os.environ.get("NEUROMITA_BASE_DIR", "")
    if base_dir:
        return Path(base_dir) / "NeuroMita-Unity"
    return Path(sys.argv[0]).resolve().parent / "NeuroMita-Unity"


def find_unity_executable(root: Path | str) -> Path | None:
    directory = Path(root)
    if not directory.exists() or not directory.is_dir():
        return None

    executable_files = list(directory.glob("*.exe")) + list(directory.glob("*/*.exe"))
    if not executable_files:
        return None

    by_name = {path.name.lower(): path for path in executable_files}
    for name in ("NeuroMita.exe", "NeuroMita-Unity.exe", "Unity.exe"):
        match = by_name.get(name.lower())
        if match is not None:
            return match

    for path in executable_files:
        name = path.name.lower()
        if "neuromita" in name or "unity" in name:
            return path
    return executable_files[0]
