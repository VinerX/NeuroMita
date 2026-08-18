from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path


UPDATE_RESTART_EXIT_CODE = 43
_PENDING_ROOT = Path(".update") / "python"
_PENDING_ZIPAPP = _PENDING_ROOT / "pending" / "NeuroMita.pyz"
_ACTIVATION_MARKER = _PENDING_ROOT / "activation.json"


@dataclass(frozen=True, slots=True)
class PendingZipapp:
    path: Path
    sha256: str
    size: int


def pending_zipapp_path(base_path: Path | str) -> Path:
    return Path(base_path) / _PENDING_ZIPAPP


def activation_marker_path(base_path: Path | str) -> Path:
    return Path(base_path) / _ACTIVATION_MARKER


def active_zipapp_path(base_path: Path | str) -> Path:
    return Path(base_path) / "NeuroMita.pyz"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_zipapp(path: Path | str) -> PendingZipapp:
    candidate = Path(path)
    if not candidate.is_file():
        raise RuntimeError(f"NeuroMita.pyz is missing: {candidate}")
    try:
        with zipfile.ZipFile(candidate, "r") as archive:
            names = set(archive.namelist())
            if "__main__.py" not in names:
                raise RuntimeError("NeuroMita.pyz does not contain __main__.py")
            broken = archive.testzip()
            if broken is not None:
                raise RuntimeError(f"NeuroMita.pyz contains a corrupt member: {broken}")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"NeuroMita.pyz is not a valid ZIP application: {exc}") from exc
    return PendingZipapp(
        path=candidate,
        sha256=_sha256(candidate),
        size=candidate.stat().st_size,
    )


def stage_zipapp_for_activation(
    candidate: Path | str,
    base_path: Path | str,
    *,
    version: str = "",
    archive_sha256: str = "",
) -> PendingZipapp:
    base = Path(base_path)
    source = validate_zipapp(candidate)
    pending = pending_zipapp_path(base)
    pending.parent.mkdir(parents=True, exist_ok=True)
    temporary = pending.with_suffix(pending.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(source.path, temporary)
    copied = validate_zipapp(temporary)
    if copied.sha256 != source.sha256 or copied.size != source.size:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Staged NeuroMita.pyz changed while being copied")
    os.replace(temporary, pending)

    marker = activation_marker_path(base)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker_tmp = marker.with_suffix(marker.suffix + ".tmp")
    marker_tmp.write_text(
        json.dumps(
            {
                "schema": 1,
                "target": str(active_zipapp_path(base).resolve(strict=False)),
                "pending": str(pending.resolve(strict=False)),
                "sha256": copied.sha256,
                "size": copied.size,
                "version": str(version or ""),
                "archive_sha256": str(archive_sha256 or ""),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(marker_tmp, marker)
    return PendingZipapp(path=pending, sha256=copied.sha256, size=copied.size)


def pending_activation_exists(base_path: Path | str) -> bool:
    return pending_zipapp_path(base_path).is_file()


def active_zipapp_matches(base_path: Path | str, expected_sha256: str) -> bool:
    expected = str(expected_sha256 or "").strip().lower()
    active = active_zipapp_path(base_path)
    if not expected or not active.is_file():
        return False
    try:
        return validate_zipapp(active).sha256 == expected
    except Exception:
        return False


def discard_activation_artifacts(base_path: Path | str) -> None:
    base = Path(base_path)
    pending = pending_zipapp_path(base)
    marker = activation_marker_path(base)
    pending.unlink(missing_ok=True)
    marker.unlink(missing_ok=True)
    for directory in (pending.parent, marker.parent, base / ".update"):
        try:
            directory.rmdir()
        except OSError:
            pass
