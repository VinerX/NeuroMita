from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
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
        target_input = Path(target).expanduser()
        state_input = Path(state_root).expanduser()
        if target_input.is_symlink():
            raise UpdateTransactionError(f"Transaction target must not be a symbolic link: {target_input}")
        self.target = target_input.resolve(strict=False)
        self.state_root = state_input.resolve(strict=False)
        if self.target == Path(self.target.anchor):
            raise UpdateTransactionError(f"Transaction target must not be a filesystem root: {self.target}")
        try:
            self.state_root.relative_to(self.target)
        except ValueError:
            pass
        else:
            raise UpdateTransactionError(
                f"Transaction state root must not be inside its target: {self.state_root}"
            )
        try:
            self.target.relative_to(self.state_root)
        except ValueError:
            pass
        else:
            raise UpdateTransactionError(
                f"Transaction target must not be inside its state root: {self.target}"
            )
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

    @staticmethod
    def _same_path(left: Path | str, right: Path | str) -> bool:
        return os.path.normcase(str(Path(left).expanduser().resolve(strict=False))) == os.path.normcase(
            str(Path(right).expanduser().resolve(strict=False))
        )

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        if not os.path.lexists(path):
            return False
        try:
            attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
        except OSError:
            return True
        reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
        return path.is_symlink() or bool(reparse_flag and attributes & reparse_flag)

    def _journal_owns_artifacts(self, state: dict[str, Any] | None = None) -> bool:
        journal = state if state is not None else self.state
        return (
            journal.get("schema") == 1
            and journal.get("authorized") is True
            and str(journal.get("component") or "") == self.component
            and bool(journal.get("target"))
            and bool(journal.get("stage"))
            and bool(journal.get("backup"))
            and self._same_path(str(journal["target"]), self.target)
            and self._same_path(str(journal["stage"]), self.paths.stage)
            and self._same_path(str(journal["backup"]), self.paths.backup)
        )

    def _assert_artifacts_safe(self, state: dict[str, Any] | None = None) -> None:
        artifacts = tuple(
            path for path in (self.paths.stage, self.paths.backup) if os.path.lexists(path)
        )
        if not artifacts:
            return
        if not self._journal_owns_artifacts(state):
            names = ", ".join(str(path) for path in artifacts)
            raise UpdateTransactionError(
                f"Refusing to modify transaction artifacts not owned by the current journal: {names}"
            )
        for path in artifacts:
            if self._is_reparse_point(path):
                raise UpdateTransactionError(
                    f"Refusing to modify a symbolic link or junction used as a transaction artifact: {path}"
                )
            if not path.is_dir():
                raise UpdateTransactionError(f"Transaction artifact is not a directory: {path}")

    def _remove_owned_directory(self, path: Path) -> None:
        if not os.path.lexists(path):
            return
        if self._is_reparse_point(path) or not path.is_dir():
            raise UpdateTransactionError(f"Refusing to recursively remove an unsafe path: {path}")
        shutil.rmtree(path)

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

        self._assert_artifacts_safe(current)
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
        self._assert_artifacts_safe()
        if self.paths.stage.exists():
            self._remove_owned_directory(self.paths.stage)
        self.paths.stage.mkdir(parents=True, exist_ok=True)
        return self.paths.stage

    def mark_stage_ready(self, *, tree_sha256: str) -> None:
        self.set_phase("stage_ready", tree_sha256=str(tree_sha256))

    def recover_commit(
        self,
        verifier: Callable[[Path], Any],
    ) -> bool:
        self._assert_artifacts_safe()
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
        self._assert_artifacts_safe()
        if not self.paths.stage.is_dir():
            raise UpdateTransactionError("Staging directory does not exist")
        self.set_phase("commit_prepared", had_target=self.target.exists())
        if self.paths.backup.exists():
            self._remove_owned_directory(self.paths.backup)
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
        self._assert_artifacts_safe()
        state = self.state
        had_target = bool(state.get("had_target", self.paths.backup.exists()))
        if self.paths.backup.exists() and self.target.exists():
            self._remove_owned_directory(self.target)
        elif not had_target and self.target.exists():
            self._remove_owned_directory(self.target)
        self._rollback_without_target()
        if self.state:
            self.set_phase("rolled_back")

    def _rollback_without_target(self) -> None:
        self._assert_artifacts_safe()
        if self.paths.backup.exists() and not self.target.exists():
            os.replace(self.paths.backup, self.target)

    def finalize(self) -> None:
        self._assert_artifacts_safe()
        if self.paths.backup.exists():
            self._remove_owned_directory(self.paths.backup)
        if self.paths.stage.exists():
            self._remove_owned_directory(self.paths.stage)
        self.set_phase("completed", completed_at=int(time.time()))

    def discard_artifacts(self, *, keep_journal: bool = False) -> None:
        self._assert_artifacts_safe()
        if self.paths.backup.exists() and not self.target.exists():
            os.replace(self.paths.backup, self.target)
        if self.paths.stage.exists():
            self._remove_owned_directory(self.paths.stage)
        if self.paths.backup.exists():
            self._remove_owned_directory(self.paths.backup)
        if not keep_journal:
            self.paths.journal.unlink(missing_ok=True)


def install_manifest_name() -> str:
    return _MANIFEST_NAME
