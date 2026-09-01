from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))



from domain.dialogue_identity import DialogueActorKind
from services.dialogue_identity_resolver import DialogueIdentityResolver


class DialogueSenderIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        characters = {
            "Crazy": SimpleNamespace(char_id="Crazy", dialogue_actor_kind=DialogueActorKind.CHARACTER),
            "Kind": SimpleNamespace(char_id="Kind", dialogue_actor_kind=DialogueActorKind.CHARACTER),
            "GameMaster": SimpleNamespace(
                char_id="GameMaster",
                dialogue_actor_kind=DialogueActorKind.GAME_MASTER,
            ),
        }
        self.resolver = DialogueIdentityResolver(characters.get)

    def test_auto_turn_uses_character_mapped_from_dialogue_actor(self):
        speaker = self.resolver.resolve(
            "Player",
            {
                "speaker_actor_id": "actor-crazy-1",
                "participants": [
                    {"actor_id": "actor-kind-1", "character_id": "Kind"},
                    {"actor_id": "actor-crazy-1", "character_id": "Crazy"},
                ],
            },
        )

        self.assertEqual(speaker.sender_id, "Crazy")
        self.assertIs(speaker.kind, DialogueActorKind.CHARACTER)
        self.assertTrue(speaker.authoritative)

    def test_actor_id_matching_is_case_insensitive(self):
        speaker = self.resolver.resolve(
            "Player",
            {
                "speaker_actor_id": "ACTOR-CRAZY-1",
                "participants": [
                    {"actor_id": "actor-crazy-1", "character_id": "Crazy"},
                ],
            },
        )

        self.assertEqual(speaker.sender_id, "Crazy")
        self.assertIs(speaker.kind, DialogueActorKind.CHARACTER)

    def test_real_player_turn_uses_authoritative_player_identity(self):
        speaker = self.resolver.resolve(
            "Crazy",
            {
                "speaker_actor_id": "player",
                "participants": [{"actor_id": "actor-kind-1", "character_id": "Kind"}],
            },
        )

        self.assertEqual(speaker.sender_id, "Player")
        self.assertIs(speaker.kind, DialogueActorKind.PLAYER)
        self.assertTrue(speaker.authoritative)

    def test_unmapped_non_player_actor_never_inherits_player_semantics(self):
        speaker = self.resolver.resolve(
            "Player",
            {"speaker_actor_id": "actor-missing", "participants": []},
        )

        self.assertEqual(speaker.sender_id, "Player")
        self.assertIs(speaker.kind, DialogueActorKind.UNKNOWN)
        self.assertFalse(speaker.authoritative)

    def test_declared_character_is_classified_through_registry_without_dialogue(self):
        speaker = self.resolver.resolve("Crazy", None)

        self.assertEqual(speaker.sender_id, "Crazy")
        self.assertIs(speaker.kind, DialogueActorKind.CHARACTER)

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
