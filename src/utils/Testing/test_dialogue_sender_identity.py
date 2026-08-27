from __future__ import annotations

import ast
import json
import sqlite3
import sys
import textwrap
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))


def _load_sender_resolver():
    path = PROJECT_SRC / "game_connections" / "handlers" / "actions" / "create_task.py"
    code = path.read_text(encoding="utf-8")
    module = ast.parse(code)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_dialogue_sender":
            namespace = {"Any": object, "Dict": dict}
            exec(textwrap.dedent(ast.get_source_segment(code, node) or ""), namespace)
            return namespace["_resolve_dialogue_sender"]
    raise RuntimeError("_resolve_dialogue_sender not found")


class DialogueSenderIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolve_sender = _load_sender_resolver()

    def test_auto_turn_uses_character_mapped_from_dialogue_actor(self):
        sender = self.resolve_sender(
            "Player",
            {
                "speaker_actor_id": "actor-crazy-1",
                "participants": [
                    {"actor_id": "actor-kind-1", "character_id": "Kind"},
                    {"actor_id": "actor-crazy-1", "character_id": "Crazy"},
                ],
            },
        )

        self.assertEqual(sender, "Crazy")

    def test_real_player_turn_keeps_player_sender(self):
        sender = self.resolve_sender(
            "Player",
            {
                "speaker_actor_id": "Player",
                "participants": [{"actor_id": "actor-kind-1", "character_id": "Kind"}],
            },
        )

        self.assertEqual(sender, "Player")

    def test_unmapped_actor_preserves_declared_sender_for_compatibility(self):
        sender = self.resolve_sender(
            "Crazy",
            {"speaker_actor_id": "actor-missing", "participants": []},
        )

        self.assertEqual(sender, "Crazy")

    def test_database_migration_repairs_existing_dialogue_sender(self):
        from managers.database_manager import DatabaseManager

        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                """
                CREATE TABLE history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    character_id TEXT,
                    role TEXT,
                    content TEXT,
                    meta_data TEXT,
                    speaker TEXT,
                    sender TEXT,
                    target TEXT,
                    participants TEXT
                )
                """
            )
            participants = json.dumps(["Crazy", "Kind"])
            actor_ids = ["actor-crazy-1", "actor-kind-1"]
            connection.execute(
                """
                INSERT INTO history (
                    character_id, role, content, meta_data,
                    speaker, sender, target, participants
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Crazy",
                    "assistant",
                    "Previous Crazy reply",
                    json.dumps(
                        {
                            "conversation_id": "conversation-1",
                            "speaker_actor_id": "actor-crazy-1",
                            "responder_actor_id": "actor-crazy-1",
                            "participant_actor_ids": actor_ids,
                        }
                    ),
                    "Crazy",
                    "Crazy",
                    "Player",
                    participants,
                ),
            )
            bad_row_id = connection.execute(
                """
                INSERT INTO history (
                    character_id, role, content, meta_data,
                    speaker, sender, target, participants
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Kind",
                    "user",
                    "Crazy addresses Kind",
                    json.dumps(
                        {
                            "conversation_id": "conversation-1",
                            "speaker_actor_id": "actor-crazy-1",
                            "responder_actor_id": "actor-kind-1",
                            "participant_actor_ids": actor_ids,
                        }
                    ),
                    "Player",
                    "Player",
                    "Kind",
                    participants,
                ),
            ).lastrowid
            player_row_id = connection.execute(
                """
                INSERT INTO history (
                    character_id, role, content, meta_data,
                    speaker, sender, target, participants
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Kind",
                    "user",
                    "Real player message",
                    json.dumps(
                        {
                            "conversation_id": "conversation-1",
                            "speaker_actor_id": "Player",
                            "responder_actor_id": "actor-kind-1",
                            "participant_actor_ids": actor_ids,
                        }
                    ),
                    "Player",
                    "Player",
                    "Kind",
                    participants,
                ),
            ).lastrowid
            connection.commit()
            cursor = connection.cursor()
            repaired_count = DatabaseManager._repair_dialogue_sender_identity(cursor)
            DatabaseManager._ensure_migration_table(cursor)
            DatabaseManager._mark_migration(
                cursor,
                DatabaseManager._MIGRATION_DIALOGUE_SENDER_IDENTITY,
            )
            connection.commit()

            repaired = connection.execute(
                "SELECT speaker, sender FROM history WHERE id = ?",
                (bad_row_id,),
            ).fetchone()
            player = connection.execute(
                "SELECT speaker, sender FROM history WHERE id = ?",
                (player_row_id,),
            ).fetchone()
            marker = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?",
                (DatabaseManager._MIGRATION_DIALOGUE_SENDER_IDENTITY,),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(repaired_count, 1)
        self.assertEqual(repaired, ("Crazy", "Crazy"))
        self.assertEqual(player, ("Player", "Player"))
        self.assertIsNotNone(marker)


if __name__ == "__main__":
    unittest.main()
