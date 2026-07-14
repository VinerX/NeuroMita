from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_MANIFEST_NAME = ".neuromita-install-manifest.json"


class UpdateTransactionError(RuntimeError):
    pass


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def file_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_files(root: Path, excluded_roots: set[str] | None = None) -> list[Path]:
    excluded = {name.casefold() for name in (excluded_roots or set())}
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0].casefold() in excluded:
            continue
        if path.is_symlink():
            raise UpdateTransactionError(f"Staging contains a symbolic link: {path}")
        if path.is_file() and path.name != _MANIFEST_NAME:
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix().casefold())


def build_install_manifest(
    root: Path,
    *,
    component: str,
    version: str,
    archive_sha256: str,
    on_progress: Callable[[int, int], None] | None = None,
    excluded_roots: set[str] | None = None,
) -> dict[str, Any]:
    files = _manifest_files(root, excluded_roots)
    total = sum(path.stat().st_size for path in files)
    processed = 0
    entries: dict[str, dict[str, Any]] = {}
    tree_digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        digest = file_sha256(path)
        entries[relative] = {"size": size, "sha256": digest}
        tree_digest.update(relative.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(str(size).encode("ascii"))
        tree_digest.update(b"\0")
        tree_digest.update(digest.encode("ascii"))
        tree_digest.update(b"\n")
        processed += size
        if on_progress is not None:
            on_progress(processed, total)
    return {
        "schema": 1,
        "component": component,
        "version": version,
        "archive_sha256": archive_sha256,
        "tree_sha256": tree_digest.hexdigest(),
        "created_at": int(time.time()),
        "files": entries,
    }


def write_install_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    path = root / _MANIFEST_NAME
    atomic_write_json(path, manifest)
    return path


def verify_install_manifest(
    root: Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    manifest_path = root / _MANIFEST_NAME
    manifest = read_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise UpdateTransactionError("Install manifest is missing or empty")

    total = sum(
        max(0, int(record.get("size") or 0))
        for record in files.values()
        if isinstance(record, dict)
    )
    processed = 0
    tree_digest = hashlib.sha256()
    for relative, record in sorted(files.items(), key=lambda item: item[0].casefold()):
        if not isinstance(record, dict):
            raise UpdateTransactionError(f"Invalid manifest entry: {relative}")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise UpdateTransactionError(f"Unsafe manifest path: {relative}")
        path = root / relative_path
        if not path.is_file():
            raise UpdateTransactionError(f"Installed file is missing: {relative}")
        expected_size = int(record.get("size") or 0)
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise UpdateTransactionError(
                f"Installed file size mismatch: {relative} ({actual_size} != {expected_size})"
            )
        expected_hash = str(record.get("sha256") or "").lower()
        actual_hash = file_sha256(path)
        if not expected_hash or actual_hash != expected_hash:
            raise UpdateTransactionError(f"Installed file hash mismatch: {relative}")
        tree_digest.update(relative.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(str(actual_size).encode("ascii"))
        tree_digest.update(b"\0")
        tree_digest.update(actual_hash.encode("ascii"))
        tree_digest.update(b"\n")
        processed += actual_size
        if on_progress is not None:
            on_progress(processed, total)

    actual_tree_hash = tree_digest.hexdigest()
    expected_tree_hash = str(manifest.get("tree_sha256") or "").lower()
    if not expected_tree_hash or actual_tree_hash != expected_tree_hash:
        raise UpdateTransactionError("Installed tree hash mismatch")
    return manifest


@dataclass(frozen=True, slots=True)
class TransactionPaths:
    journal: Path
    stage: Path
    backup: Path


class DirectoryInstallTransaction:
    """Durable same-volume directory replacement with crash recovery."""

    def __init__(
        self,
        *,
        component: str,
        target: Path,
        state_root: Path,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.component = str(component)
        self.target = target.resolve()
        self.state_root = state_root.resolve()
        safe_component = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in self.component
        )
        self.paths = TransactionPaths(
            journal=self.state_root / safe_component / "operation.json",
            stage=self.target.parent / f".{self.target.name}.{safe_component}.stage",
            backup=self.target.parent / f".{self.target.name}.{safe_component}.backup",
        )
        self._logger = logger or (lambda _message: None)

    @property
    def state(self) -> dict[str, Any]:
        return read_json(self.paths.journal)

    @property
    def phase(self) -> str:
        return str(self.state.get("phase") or "")

    def matches(self, *, version: str, archive_url: str) -> bool:
        state = self.state
        return bool(state) and str(state.get("version") or "") == str(version) and str(
            state.get("archive_url") or ""
        ) == str(archive_url) and os.path.normcase(
            str(Path(str(state.get("target") or self.target)).resolve())
        ) == os.path.normcase(str(self.target))

    def begin(self, payload: dict[str, Any]) -> None:
        current = self.state
        same_operation = bool(current) and str(current.get("version") or "") == str(
            payload.get("version") or ""
        ) and str(current.get("archive_url") or "") == str(payload.get("archive_url") or "") and os.path.normcase(
            str(Path(str(current.get("target") or self.target)).resolve())
        ) == os.path.normcase(str(self.target))
        if same_operation and self.phase not in {"completed", "rolled_back"}:
            merged = dict(current)
            merged.update(payload)
            merged["updated_at"] = int(time.time())
            atomic_write_json(self.paths.journal, merged)
            return

        if current and self.phase in {"commit_prepared", "target_backed_up", "activated"}:
            raise UpdateTransactionError(
                "A previous directory commit must be recovered before starting another update"
            )

        self.discard_artifacts(keep_journal=True)
        state = {
            "schema": 1,
            "component": self.component,
            "target": str(self.target),
            "stage": str(self.paths.stage),
            "backup": str(self.paths.backup),
            "phase": "created",
            "authorized": True,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            **payload,
        }
        atomic_write_json(self.paths.journal, state)

    def set_phase(self, phase: str, **changes: Any) -> None:
        state = self.state
        if not state:
            raise UpdateTransactionError("Cannot update a missing transaction journal")
        state.update(changes)
        state["phase"] = str(phase)
        state["updated_at"] = int(time.time())
        atomic_write_json(self.paths.journal, state)

    def reset_stage(self) -> Path:
        if self.paths.stage.exists():
            shutil.rmtree(self.paths.stage, ignore_errors=True)
        self.paths.stage.mkdir(parents=True, exist_ok=True)
        return self.paths.stage

    def mark_stage_ready(self, *, tree_sha256: str) -> None:
        self.set_phase("stage_ready", tree_sha256=str(tree_sha256))

    def recover_commit(
        self,
        verifier: Callable[[Path], Any],
    ) -> bool:
        phase = self.phase
        if phase == "stage_ready":
            return False
        if phase == "commit_prepared":
            if self.target.exists() and self.paths.stage.exists():
                return False
            if not self.target.exists() and self.paths.backup.exists():
                self.set_phase("target_backed_up")
                phase = "target_backed_up"
        if phase == "target_backed_up":
            if not self.target.exists() and self.paths.stage.exists():
                os.replace(self.paths.stage, self.target)
            elif not self.target.exists():
                self._rollback_without_target()
                raise UpdateTransactionError("Interrupted commit lost its staging directory")
            self.set_phase("activated")
            phase = "activated"
        if phase == "activated":
            try:
                verifier(self.target)
            except Exception:
                self.rollback()
                raise
            self.finalize()
            return True
        return phase == "completed"

    def commit(self, verifier: Callable[[Path], Any]) -> None:
        if not self.paths.stage.is_dir():
            raise UpdateTransactionError("Staging directory does not exist")
        self.set_phase("commit_prepared", had_target=self.target.exists())
        if self.paths.backup.exists():
            shutil.rmtree(self.paths.backup, ignore_errors=True)
        try:
            if self.target.exists():
                os.replace(self.target, self.paths.backup)
            self.set_phase("target_backed_up")
            os.replace(self.paths.stage, self.target)
            self.set_phase("activated")
            verifier(self.target)
        except Exception:
            self.rollback()
            raise
        self.finalize()

    def rollback(self) -> None:
        state = self.state
        had_target = bool(state.get("had_target", self.paths.backup.exists()))
        if self.paths.backup.exists() and self.target.exists():
            failed = self.target.parent / f".{self.target.name}.failed"
            if failed.exists():
                shutil.rmtree(failed, ignore_errors=True)
            try:
                os.replace(self.target, failed)
            except OSError:
                shutil.rmtree(self.target, ignore_errors=True)
            shutil.rmtree(failed, ignore_errors=True)
        elif not had_target and self.target.exists():
            shutil.rmtree(self.target, ignore_errors=True)
        self._rollback_without_target()
        if self.state:
            self.set_phase("rolled_back")

    def _rollback_without_target(self) -> None:
        if self.paths.backup.exists() and not self.target.exists():
            os.replace(self.paths.backup, self.target)

    def finalize(self) -> None:
        if self.paths.backup.exists():
            shutil.rmtree(self.paths.backup, ignore_errors=True)
        if self.paths.stage.exists():
            shutil.rmtree(self.paths.stage, ignore_errors=True)
        self.set_phase("completed", completed_at=int(time.time()))

    def discard_artifacts(self, *, keep_journal: bool = False) -> None:
        if self.paths.backup.exists() and not self.target.exists():
            os.replace(self.paths.backup, self.target)
        if self.paths.stage.exists():
            shutil.rmtree(self.paths.stage, ignore_errors=True)
        if self.paths.backup.exists():
            shutil.rmtree(self.paths.backup, ignore_errors=True)
        if not keep_journal:
            self.paths.journal.unlink(missing_ok=True)


def install_manifest_name() -> str:
    return _MANIFEST_NAME
