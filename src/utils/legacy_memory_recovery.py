"""Safe import of pre-SQLite NeuroMita history and memory backups.

The old application stored a character in two JSON files.  This module accepts
those files directly, a folder containing them, or a ZIP archive.  Inspection
is deliberately read-only; ``import_legacy_backup`` is the only mutating entry
point and is idempotent per source digest and target character.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Callable, Iterable
import zipfile

from managers.database_manager import DatabaseManager


_HISTORY_SUFFIX = "_history.json"
_MEMORIES_SUFFIX = "_memories.json"
_MAX_JSON_BYTES = 32 * 1024 * 1024


class LegacyBackupError(ValueError):
    """Raised when a selected source cannot be treated as a legacy backup."""


@dataclass(frozen=True)
class LegacyBackupPreview:
    source_digest: str
    source_labels: tuple[str, ...]
    source_character_ids: tuple[str, ...]
    history: dict[str, Any] | None
    memories: list[dict[str, Any]] | None
    history_item_digest: str | None = None
    memories_item_digest: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def history_count(self) -> int:
        return len((self.history or {}).get("messages") or [])

    @property
    def memory_count(self) -> int:
        return len(self.memories or [])

    @property
    def variable_count(self) -> int:
        variables = (self.history or {}).get("variables") or {}
        return len(variables) if isinstance(variables, dict) else 0

    @property
    def fixed_parts_count(self) -> int:
        return len((self.history or {}).get("fixed_parts") or [])


def _character_id_from_name(name: str, suffix: str) -> str:
    if not name.lower().endswith(suffix):
        return ""
    return name[: -len(suffix)].strip()


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts


def _decode_json(raw: bytes, label: str) -> Any:
    if len(raw) > _MAX_JSON_BYTES:
        raise LegacyBackupError(f"{label}: JSON file is too large")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegacyBackupError(f"{label}: invalid UTF-8 JSON") from exc


def _read_json_file(path: Path) -> tuple[str, bytes, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LegacyBackupError(f"Cannot read {path}") from exc
    return str(path), raw, _decode_json(raw, str(path))


def _read_zip(path: Path) -> list[tuple[str, bytes, Any]]:
    try:
        with zipfile.ZipFile(path) as archive:
            items: list[tuple[str, bytes, Any]] = []
            for entry in archive.infolist():
                if entry.is_dir() or not entry.filename.lower().endswith(".json"):
                    continue
                if not _safe_archive_name(entry.filename):
                    raise LegacyBackupError(f"Unsafe archive member: {entry.filename}")
                if entry.file_size > _MAX_JSON_BYTES:
                    raise LegacyBackupError(f"{entry.filename}: JSON file is too large")
                raw = archive.read(entry)
                items.append((f"{path}!{entry.filename}", raw, _decode_json(raw, entry.filename)))
            return items
    except zipfile.BadZipFile as exc:
        raise LegacyBackupError(f"{path}: not a valid ZIP archive") from exc


def _collect_items(paths: Iterable[str | Path]) -> list[tuple[str, bytes, Any]]:
    items: list[tuple[str, bytes, Any]] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        try:
            path = path.resolve()
        except OSError:
            pass
        if path in seen:
            continue
        seen.add(path)
        if path.is_dir():
            for child in sorted(path.rglob("*.json")):
                items.append(_read_json_file(child))
        elif path.is_file() and path.suffix.lower() == ".zip":
            items.extend(_read_zip(path))
        elif path.is_file() and path.suffix.lower() == ".json":
            items.append(_read_json_file(path))
        else:
            raise LegacyBackupError(f"Unsupported source: {path}")
    return items


def inspect_legacy_backup(paths: Iterable[str | Path]) -> LegacyBackupPreview:
    """Read selected backup sources and return a non-mutating compatibility report."""
    items = _collect_items(paths)
    if not items:
        raise LegacyBackupError("No JSON files were found in the selected source")

    items.sort(key=lambda item: (item[0].rsplit("!", 1)[-1].casefold(), sha256(item[1]).hexdigest()))
    histories: list[tuple[str, str, dict[str, Any], bytes]] = []
    memories: list[tuple[str, str, list[dict[str, Any]], bytes]] = []
    digest = sha256()
    labels: list[str] = []
    for label, raw, data in items:
        name = label.rsplit("!", 1)[-1].replace("\\", "/").rsplit("/", 1)[-1]
        # The same backup must remain idempotent if the user moves it from the
        # Downloads folder into another directory before importing again.
        digest.update(name.casefold().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(raw).digest())
        labels.append(label)
        char_id = _character_id_from_name(name, _HISTORY_SUFFIX)
        if char_id and isinstance(data, dict) and isinstance(data.get("messages"), list):
            histories.append((char_id, label, data, raw))
            continue
        char_id = _character_id_from_name(name, _MEMORIES_SUFFIX)
        if char_id and isinstance(data, list):
            clean_rows = [row for row in data if isinstance(row, dict)]
            memories.append((char_id, label, clean_rows, raw))

    if not histories and not memories:
        raise LegacyBackupError("No *_history.json or *_memories.json files in the old format were found")
    if len(histories) > 1 or len(memories) > 1:
        raise LegacyBackupError("Select one character backup at a time")

    history_id = histories[0][0] if histories else ""
    memory_id = memories[0][0] if memories else ""
    if history_id and memory_id and history_id.casefold() != memory_id.casefold():
        raise LegacyBackupError("History and memory files belong to different characters")
    source_ids = tuple(value for value in (history_id, memory_id) if value)
    history = histories[0][2] if histories else None
    memory_rows = memories[0][2] if memories else None

    warnings: list[str] = []
    if history is None:
        warnings.append("History file was not selected; only memories will be restored.")
    if memory_rows is None:
        warnings.append("Memory file was not selected; only history and variables will be restored.")
    if history and history.get("fixed_parts"):
        warnings.append("Legacy fixed prompts will be archived for audit and will not be activated.")
    if memory_rows:
        numbers = [row.get("N") for row in memory_rows if isinstance(row.get("N"), int)]
        if len(numbers) != len(set(numbers)):
            warnings.append("Duplicate legacy memory numbers were found and will receive safe new IDs.")
        if any("<" in str(row.get("content") or "") and "memory>" in str(row.get("content") or "") for row in memory_rows):
            warnings.append("Some memories contain old memory-command tags; original text will be preserved unchanged.")

    return LegacyBackupPreview(
        source_digest=digest.hexdigest(),
        source_labels=tuple(labels),
        source_character_ids=source_ids,
        history=history,
        memories=memory_rows,
        history_item_digest=sha256(histories[0][3]).hexdigest() if histories else None,
        memories_item_digest=sha256(memories[0][3]).hexdigest() if memories else None,
        warnings=tuple(warnings),
    )


def _legacy_timestamp(raw: Any, ordinal: int) -> str:
    value = str(raw or "").strip()
    if value:
        return value.replace("_", " ")
    # These backups had no per-message timestamps.  A deterministic timestamp
    # prevents a repeated import from looking like a new conversation.
    return (datetime(1970, 1, 1) + timedelta(seconds=ordinal)).strftime("%d.%m.%Y %H:%M:%S")


def _legacy_memory_date(raw: Any) -> str:
    """Normalize v0.011 dates without replacing a known historical date."""
    value = str(raw or "").strip().replace("_", " ")
    if not value:
        return ""
    value = re.sub(r" (\d{2})\.(\d{2})$", r" \1:\2", value)
    if re.search(r" \d{2}:\d{2}$", value):
        value += ":00"
    return value


def _backup_database(db_path: str) -> str | None:
    source = Path(db_path)
    if not source.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = source.with_name(f"{source.name}.pre_legacy_import_{stamp}")
    shutil.copy2(source, target)
    return str(target)


def _ensure_import_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_imports (
            source_digest TEXT NOT NULL,
            character_id TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            source_summary TEXT NOT NULL,
            PRIMARY KEY (source_digest, character_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_import_items (
            source_item_digest TEXT NOT NULL,
            character_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            PRIMARY KEY (source_item_digest, character_id, kind)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_import_archives (
            source_digest TEXT NOT NULL,
            character_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (source_digest, character_id)
        )
        """
    )


def import_legacy_backup(
    preview: LegacyBackupPreview,
    *,
    target_character_id: str,
    progress_callback: Callable[[int, int], Any] | None = None,
) -> dict[str, Any]:
    """Import an inspected backup into SQLite, keeping its original payload for audit."""
    target = str(target_character_id or "").strip()
    if not target:
        raise LegacyBackupError("Choose the character that should receive the restored data")

    db = DatabaseManager()
    conn = db.get_connection()
    total = preview.history_count + preview.memory_count + preview.variable_count + 1
    done = 0
    backup_path: str | None = None
    try:
        has_import_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_imports'"
        ).fetchone()
        if has_import_table:
            existing = conn.execute(
                "SELECT 1 FROM legacy_imports WHERE source_digest=? AND character_id=?",
                (preview.source_digest, target),
            ).fetchone()
            if existing:
                return {
                    "status": "already_imported",
                    "history_inserted": 0,
                    "memories_inserted": 0,
                    "variables_written": 0,
                    "backup_path": None,
                    "warnings": list(preview.warnings),
                }
        has_item_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_import_items'"
        ).fetchone()
        history_seen = memory_seen = False
        if has_item_table:
            if preview.history_item_digest:
                history_seen = bool(conn.execute(
                    "SELECT 1 FROM legacy_import_items WHERE source_item_digest=? AND character_id=? AND kind='history'",
                    (preview.history_item_digest, target),
                ).fetchone())
            if preview.memories_item_digest:
                memory_seen = bool(conn.execute(
                    "SELECT 1 FROM legacy_import_items WHERE source_item_digest=? AND character_id=? AND kind='memories'",
                    (preview.memories_item_digest, target),
                ).fetchone())
        if (preview.history is None or history_seen) and (preview.memories is None or memory_seen):
            return {
                "status": "already_imported",
                "history_inserted": 0,
                "memories_inserted": 0,
                "variables_written": 0,
                "backup_path": None,
                "warnings": list(preview.warnings),
            }
        # Take the copy before even creating our small bookkeeping tables.
        backup_path = _backup_database(db.db_path)
        _ensure_import_tables(conn)

        conn.execute("BEGIN")
        history_inserted = history_normalized = memories_inserted = variables_written = 0
        history = preview.history or {}
        for ordinal, message in enumerate([] if history_seen else history.get("messages") or []):
            if not isinstance(message, dict):
                continue
            raw_content = message.get("content", "")
            content = raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False)
            metadata = {
                "legacy_import": True,
                "legacy_source_digest": preview.source_digest,
                "legacy_history_index": ordinal,
                "legacy_timestamp_missing": not bool(message.get("time") or message.get("timestamp")),
            }
            structured_data = None
            if isinstance(raw_content, str):
                # v0.011 sometimes wrote </#memory> instead of </memory> into
                # persisted text.  The repaired copy is only used for parsing;
                # the untouched source remains in legacy_import_archives.
                parseable_content = re.sub(r"</[+#-]memory>", "</memory>", raw_content)
                from utils.history_migration import has_old_tags, migrate_content
                if has_old_tags(parseable_content):
                    content, structured = migrate_content(parseable_content)
                    structured_data = json.dumps(structured, ensure_ascii=False)
                    metadata["legacy_original_content"] = raw_content
                    history_normalized += 1
            conn.execute(
                """
                INSERT INTO history (character_id, role, content, timestamp, is_active, meta_data, message_id, structured_data)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    target,
                    str(message.get("role") or "user"),
                    content,
                    _legacy_timestamp(message.get("time") or message.get("timestamp"), ordinal),
                    json.dumps(metadata, ensure_ascii=False),
                    f"legacy:{preview.source_digest}:history:{ordinal}",
                    structured_data,
                ),
            )
            history_inserted += 1
            done += 1
            if progress_callback:
                progress_callback(done, total)

        used_ids: set[int] = set()
        next_id = max([int(row.get("N")) for row in (preview.memories or []) if isinstance(row.get("N"), int)] or [0]) + 1
        for ordinal, memory in enumerate([] if memory_seen else preview.memories or []):
            legacy_id = memory.get("N")
            if isinstance(legacy_id, int) and legacy_id > 0 and legacy_id not in used_ids:
                eternal_id = legacy_id
            else:
                eternal_id = next_id
                next_id += 1
            used_ids.add(eternal_id)
            content = str(memory.get("content") or "")
            conn.execute(
                """
                INSERT INTO memories (character_id, eternal_id, content, priority, type, date_created, is_deleted, tags)
                VALUES (?, ?, ?, ?, 'fact', ?, 0, ?)
                """,
                (
                    target,
                    eternal_id,
                    content,
                    str(memory.get("priority") or "Normal"),
                    _legacy_memory_date(memory.get("date")),
                    json.dumps({"legacy_import": True, "legacy_original_id": legacy_id, "legacy_ordinal": ordinal}, ensure_ascii=False),
                ),
            )
            memories_inserted += 1
            done += 1
            if progress_callback:
                progress_callback(done, total)

        variables = {} if history_seen else history.get("variables") or {}
        if isinstance(variables, dict):
            for key, value in variables.items():
                conn.execute(
                    "INSERT OR REPLACE INTO variables (character_id, key, value) VALUES (?, ?, ?)",
                    (target, str(key), json.dumps(value, ensure_ascii=False)),
                )
                variables_written += 1
                done += 1
                if progress_callback:
                    progress_callback(done, total)

        payload = {"history": preview.history, "memories": preview.memories, "sources": preview.source_labels}
        summary = {
            "source_character_ids": preview.source_character_ids,
            "history_count": preview.history_count,
            "memory_count": preview.memory_count,
            "fixed_parts_count": preview.fixed_parts_count,
            "warnings": preview.warnings,
        }
        conn.execute(
            "INSERT INTO legacy_import_archives (source_digest, character_id, payload_json) VALUES (?, ?, ?)",
            (preview.source_digest, target, json.dumps(payload, ensure_ascii=False)),
        )
        if preview.history_item_digest and not history_seen:
            conn.execute(
                "INSERT INTO legacy_import_items (source_item_digest, character_id, kind) VALUES (?, ?, 'history')",
                (preview.history_item_digest, target),
            )
        if preview.memories_item_digest and not memory_seen:
            conn.execute(
                "INSERT INTO legacy_import_items (source_item_digest, character_id, kind) VALUES (?, ?, 'memories')",
                (preview.memories_item_digest, target),
            )
        conn.execute(
            "INSERT INTO legacy_imports (source_digest, character_id, imported_at, source_summary) VALUES (?, ?, ?, ?)",
            (preview.source_digest, target, datetime.now().isoformat(timespec="seconds"), json.dumps(summary, ensure_ascii=False)),
        )
        conn.commit()
        if progress_callback:
            progress_callback(total, total)
        return {
            "status": "imported",
            "history_inserted": history_inserted,
            "history_normalized": history_normalized,
            "memories_inserted": memories_inserted,
            "variables_written": variables_written,
            "backup_path": backup_path,
            "warnings": list(preview.warnings),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
