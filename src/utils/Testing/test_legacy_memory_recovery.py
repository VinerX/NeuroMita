from __future__ import annotations

import json
from pathlib import Path
import sys
import zipfile

import pytest

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.database_manager import DatabaseManager
from utils.legacy_memory_recovery import (
    LegacyBackupError,
    import_legacy_backup,
    inspect_legacy_backup,
    recover_legacy_memories,
)


def _write_backup(folder: Path) -> tuple[Path, Path]:
    history = {
        "fixed_parts": [{"role": "system", "content": "old prompt"}],
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "<+memory>high|remember</memory> hi"},
        ],
        "temp_context": {"role": "system", "content": "old state"},
        "variables": {"attitude": 100, "stress": 0},
    }
    memories = [
        {"N": 1, "date": "01.01.2026_10.00", "priority": "high", "content": "first"},
        {"N": 1, "date": "01.01.2026_10.01", "priority": "high", "content": "second <#memory>1|high|tag</#memory>"},
    ]
    folder.mkdir(parents=True, exist_ok=True)
    history_path = folder / "ShortHair_history.json"
    memories_path = folder / "ShortHair_memories.json"
    history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    memories_path.write_text(json.dumps(memories, ensure_ascii=False), encoding="utf-8")
    return history_path, memories_path


def test_inspection_accepts_folder_file_list_and_zip(tmp_path: Path) -> None:
    folder = tmp_path / "ShortHair"
    history_path, memories_path = _write_backup(folder)
    by_folder = inspect_legacy_backup([folder])
    by_files = inspect_legacy_backup([history_path, memories_path])
    archive = tmp_path / "ShortHair.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.write(history_path, "ShortHair/ShortHair_history.json")
        output.write(memories_path, "ShortHair/ShortHair_memories.json")
    by_zip = inspect_legacy_backup([archive])

    for preview in (by_folder, by_files, by_zip):
        assert preview.source_character_ids == ("ShortHair", "ShortHair")
        assert preview.history_count == 2
        assert preview.memory_count == 2
        assert preview.recovered_memory_count == 2
        assert preview.variable_count == 2
        assert preview.fixed_parts_count == 1
        assert any("Duplicate" in warning for warning in preview.warnings)
    assert by_folder.source_digest == by_files.source_digest == by_zip.source_digest


def test_import_is_idempotent_and_archives_legacy_payload(tmp_path: Path) -> None:
    _write_backup(tmp_path / "source")
    preview = inspect_legacy_backup([tmp_path / "source"])
    DatabaseManager._instance = None
    DatabaseManager._path_override = str(tmp_path / "world.db")
    try:
        first = import_legacy_backup(preview, target_character_id="ShortHair")
        repeated = import_legacy_backup(preview, target_character_id="ShortHair")
        db = DatabaseManager()
        with db.connection() as conn:
            memories = conn.execute("SELECT eternal_id, content FROM memories ORDER BY id").fetchall()
            history = conn.execute("SELECT role, content, timestamp, structured_data FROM history ORDER BY id").fetchall()
            archived = conn.execute("SELECT payload_json FROM legacy_import_archives").fetchone()[0]
        assert first["status"] == "imported"
        assert first["history_inserted"] == 2
        assert first["memories_inserted"] == 2
        assert repeated["status"] == "already_imported"
        assert [row[0] for row in memories] == [1, 2]
        assert history[0][2] == "01.01.1970 00:00:00"
        assert history[1][1] == "hi"
        assert history[1][3]
        assert "old prompt" in archived
    finally:
        DatabaseManager._instance = None
        DatabaseManager._path_override = None


def test_explicit_reimport_restores_a_reset_character(tmp_path: Path) -> None:
    _write_backup(tmp_path / "source")
    preview = inspect_legacy_backup([tmp_path / "source"])
    DatabaseManager._instance = None
    DatabaseManager._path_override = str(tmp_path / "world.db")
    try:
        import_legacy_backup(preview, target_character_id="ShortHair")
        db = DatabaseManager()
        with db.connection() as conn:
            conn.execute("UPDATE history SET is_deleted=1 WHERE character_id='ShortHair'")
            conn.execute("UPDATE memories SET is_deleted=1 WHERE character_id='ShortHair'")
            conn.commit()
        repeated = import_legacy_backup(preview, target_character_id="ShortHair", allow_reimport=True)
        with db.connection() as conn:
            active_history = conn.execute(
                "SELECT COUNT(*) FROM history WHERE character_id='ShortHair' AND is_deleted=0"
            ).fetchone()[0]
            active_memories = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE character_id='ShortHair' AND is_deleted=0"
            ).fetchone()[0]
        assert repeated["status"] == "imported"
        assert repeated["history_inserted"] == 2
        assert repeated["memories_inserted"] == 2
        assert active_history == 2
        assert active_memories == 2
    finally:
        DatabaseManager._instance = None
        DatabaseManager._path_override = None


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../ShortHair_history.json", "{}")
    with pytest.raises(LegacyBackupError, match="Unsafe archive member"):
        inspect_legacy_backup([archive])


def test_recovery_replays_hash_and_unclosed_delete_tags() -> None:
    recovered, stats = recover_legacy_memories([
        {"N": 1, "date": "01.01.2026_10.00", "priority": "normal", "content": "old</+memory>\n<#memory>1|high|new\\</#memory>"},
        {"N": 2, "date": "01.01.2026_10.01", "priority": "normal", "content": "remove me</+memory>\n<-memory>2|high|old value"},
    ])
    assert [(item.legacy_id, item.priority, item.content) for item in recovered] == [(1, "high", "new")]
    assert stats["commands_seen"] == 2
    assert stats["commands_applied"] == 2


def test_importing_a_single_file_then_the_pair_never_duplicates_data(tmp_path: Path) -> None:
    history_path, memories_path = _write_backup(tmp_path / "source")
    history_only = inspect_legacy_backup([history_path])
    full = inspect_legacy_backup([history_path, memories_path])
    DatabaseManager._instance = None
    DatabaseManager._path_override = str(tmp_path / "world.db")
    try:
        import_legacy_backup(history_only, target_character_id="ShortHair")
        result = import_legacy_backup(full, target_character_id="ShortHair")
        db = DatabaseManager()
        with db.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM history WHERE character_id='ShortHair'").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM memories WHERE character_id='ShortHair'").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM variables WHERE character_id='ShortHair'").fetchone()[0] == 2
        assert result["history_inserted"] == 0
        assert result["memories_inserted"] == 2
        assert result["variables_written"] == 0
    finally:
        DatabaseManager._instance = None
        DatabaseManager._path_override = None
