from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from services.update_transaction import install_manifest_name, read_json


class UnsafeUnityInstallPath(ValueError):
    pass


def _is_reparse_point(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    except OSError:
        return True
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    return path.is_symlink() or bool(reparse_flag and attributes & reparse_flag)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _looks_like_neuromita_unity(path: Path) -> bool:
    manifest = read_json(path / install_manifest_name())
    if manifest.get("schema") == 1 and manifest.get("component") == "unity":
        return True

    executable_names = {
        "neuromita.exe",
        "neuromita-unity.exe",
        "unity.exe",
    }
    for pattern in ("*.exe", "*/*.exe"):
        for executable in path.glob(pattern):
            name = executable.name.casefold()
            if name in executable_names or "neuromita" in name:
                return True
    return False


def validate_unity_update_target(base_dir: Path | str, target: Path | str) -> Path:
    """Reject paths that a transactional Unity replacement must never mutate."""
    base = Path(base_dir).expanduser().resolve(strict=False)
    candidate_input = Path(target).expanduser()
    if _is_reparse_point(candidate_input):
        raise UnsafeUnityInstallPath(
            f"Unity install target must not be a symbolic link or junction: {candidate_input}"
        )
    candidate = candidate_input.resolve(strict=False)

    if candidate == Path(candidate.anchor):
        raise UnsafeUnityInstallPath(f"Unity install target must not be a filesystem root: {candidate}")
    if candidate == base or _is_relative_to(base, candidate):
        raise UnsafeUnityInstallPath(
            f"Unity install target must not be the NeuroMita directory or its parent: {candidate}"
        )

    protected_exact = {Path.home().resolve(strict=False)}
    for variable in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = str(os.environ.get(variable, "") or "").strip()
        if value:
            protected_exact.add(Path(value).resolve(strict=False))
    if candidate in protected_exact:
        raise UnsafeUnityInstallPath(f"Unity install target is a protected directory: {candidate}")

    state_root = (base / "_update_state").resolve(strict=False)
    if candidate == state_root or _is_relative_to(candidate, state_root):
        raise UnsafeUnityInstallPath(
            f"Unity install target must stay outside updater state: {candidate}"
        )

    if candidate.exists():
        if not candidate.is_dir():
            raise UnsafeUnityInstallPath(f"Unity install target is not a directory: {candidate}")
        try:
            nonempty = next(candidate.iterdir(), None) is not None
        except OSError as error:
            raise UnsafeUnityInstallPath(
                f"Unity install target cannot be inspected safely: {candidate}"
            ) from error
        if nonempty and not _looks_like_neuromita_unity(candidate):
            raise UnsafeUnityInstallPath(
                "Refusing to replace a non-empty directory that is not a recognized "
                f"NeuroMita Unity installation: {candidate}"
            )
    return candidate


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
