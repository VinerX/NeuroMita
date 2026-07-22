from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.database_manager import DatabaseManager
from managers.history_manager import HistoryManager


class _FakeExecutor:
    def __init__(self) -> None:
        self.jobs = []

    def submit(self, fn, *args, **kwargs):
        self.jobs.append((fn, args, kwargs))
        return object()


class _FakeRag:
    def update_history_embedding(self, *_args, **_kwargs) -> None:
        return None


class _ConnectionProxy:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        return None


class HistoryManagerAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = None
        self._sqlite = sqlite3.connect(":memory:", check_same_thread=False)
        self._proxy = _ConnectionProxy(self._sqlite)
        self._conn_patcher = patch.object(DatabaseManager, "get_connection", return_value=self._proxy)
        self._conn_patcher.start()
        DatabaseManager._instance = None
        DatabaseManager._path_override = None
        self.hm = HistoryManager(character_name="Test", character_id="char:test")

    def tearDown(self) -> None:
        self._conn_patcher.stop()
        self._sqlite.close()
        DatabaseManager._instance = None
        DatabaseManager._path_override = None

    def test_save_history_rolls_back_on_insert_failure(self) -> None:
        original = {
            "messages": [
                {"role": "user", "content": "old", "time": "01.01.2026 10:00:00"},
            ],
            "variables": {"mood": "old"},
        }
        self.hm.save_history(original)

        original_insert = self.hm._insert_history_row_tx
        call_counter = {"count": 0}

        def failing_insert(cursor, *, msg, is_active, dedupe=True):
            call_counter["count"] += 1
            if call_counter["count"] == 1:
                raise RuntimeError("boom")
            return original_insert(cursor, msg=msg, is_active=is_active, dedupe=dedupe)

        replacement = {
            "messages": [
                {"role": "user", "content": "new-1", "time": "01.01.2026 10:01:00"},
                {"role": "assistant", "content": "new-2", "time": "01.01.2026 10:02:00"},
            ],
            "variables": {"mood": "new"},
        }

        with patch.object(self.hm, "_insert_history_row_tx", side_effect=failing_insert):
            self.hm.save_history(replacement)

        loaded = self.hm.load_history()
        self.assertEqual([m["content"] for m in loaded["messages"]], ["old"])
        self.assertEqual(loaded["variables"]["mood"], "old")

    def test_save_history_replaces_active_history_on_success(self) -> None:
        self.hm.save_history(
            {
                "messages": [{"role": "user", "content": "before", "time": "01.01.2026 10:00:00"}],
                "variables": {"state": "before"},
            }
        )

        self.hm.save_history(
            {
                "messages": [
                    {"role": "user", "content": "after-1", "time": "01.01.2026 10:05:00"},
                    {"role": "assistant", "content": "after-2", "time": "01.01.2026 10:06:00"},
                ],
                "variables": {"state": "after"},
            }
        )

        loaded = self.hm.load_history()
        self.assertEqual([m["content"] for m in loaded["messages"]], ["after-1", "after-2"])
        self.assertEqual(loaded["variables"]["state"], "after")

    def test_save_history_preserves_existing_row_identity(self) -> None:
        self.hm.save_history(
            {
                "messages": [{"role": "user", "content": "before", "time": "01.01.2026 10:00:00"}],
                "variables": {},
            }
        )
        before = self.hm.load_history()["messages"][0]

        self.hm.save_history(
            {
                "messages": [{**before, "content": "after"}],
                "variables": {},
            }
        )
        after = self.hm.load_history()["messages"][0]

        self.assertEqual(after["_history_row_id"], before["_history_row_id"])
        self.assertEqual(after["content"], "after")

    def test_updating_message_content_invalidates_stale_embeddings(self) -> None:
        self.hm.save_history(
            {
                "messages": [
                    {"role": "user", "content": "before", "time": "01.01.2026 10:00:00"}
                ],
                "variables": {},
            }
        )
        message = self.hm.load_history()["messages"][0]
        row_id = message["_history_row_id"]
        self._sqlite.execute(
            "UPDATE history SET embedding = ? WHERE id = ?",
            (b"legacy", row_id),
        )
        self._sqlite.execute(
            """
            INSERT INTO embeddings
                (source_table, source_id, character_id, model_name, dimensions, embedding)
            VALUES ('history', ?, ?, 'test-model', 1, ?)
            """,
            (row_id, self.hm.storage_key, b"vector"),
        )
        self._sqlite.execute(
            """
            INSERT INTO sentence_embeddings
                (source_table, source_id, character_id, model_name, sentence_idx, embedding)
            VALUES ('history', ?, ?, 'test-model', 0, ?)
            """,
            (row_id, self.hm.storage_key, b"sentence"),
        )
        self._sqlite.commit()

        executor = _FakeExecutor()
        with patch.object(HistoryManager, "_get_embed_executor", return_value=executor):
            self.hm.save_history(
                {
                    "messages": [{**message, "content": "after"}],
                    "variables": {},
                }
            )

        cursor = self._sqlite.cursor()
        cursor.execute("SELECT embedding FROM history WHERE id = ?", (row_id,))
        self.assertIsNone(cursor.fetchone()[0])
        for table in ("embeddings", "sentence_embeddings"):
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE source_table='history' AND source_id = ?",
                (row_id,),
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        self.assertEqual(len(executor.jobs), 1)

    def test_prepending_new_message_does_not_steal_existing_row_identity(self) -> None:
        self.hm.save_history(
            {
                "messages": [
                    {"role": "user", "content": "first", "time": "01.01.2026 10:00:00"},
                    {"role": "assistant", "content": "second", "time": "01.01.2026 10:00:01"},
                ],
                "variables": {},
            }
        )
        existing = self.hm.load_history()["messages"]
        first_id = existing[0]["_history_row_id"]
        second_id = existing[1]["_history_row_id"]

        self.hm.save_history(
            {
                "messages": [
                    {"role": "system", "content": "prepended", "time": "01.01.2026 09:59:59"},
                    existing[0],
                    existing[1],
                ],
                "variables": {},
            }
        )
        loaded = self.hm.load_history()["messages"]

        by_content = {message["content"]: message["_history_row_id"] for message in loaded}
        self.assertEqual(by_content["first"], first_id)
        self.assertEqual(by_content["second"], second_id)
        self.assertNotIn(by_content["prepended"], {first_id, second_id})

    def test_snapshot_reconcile_soft_deletes_stale_rows_without_reembedding_unchanged_rows(self) -> None:
        self.hm.save_history(
            {
                "messages": [
                    {"role": "user", "content": "keep", "time": "01.01.2026 10:00:00"},
                    {"role": "assistant", "content": "remove", "time": "01.01.2026 10:00:01"},
                ],
                "variables": {},
            }
        )
        before = self.hm.load_history()["messages"]
        stale_row_id = before[1]["_history_row_id"]
        executor = _FakeExecutor()

        with patch.object(HistoryManager, "_get_embed_executor", return_value=executor):
            self.hm.save_history({"messages": [before[0]], "variables": {}})

        self.assertEqual(executor.jobs, [])
        self.assertEqual([m["content"] for m in self.hm.load_history()["messages"]], ["keep"])
        cursor = self._sqlite.cursor()
        cursor.execute(
            "SELECT is_active, is_deleted FROM history WHERE id = ?",
            (stale_row_id,),
        )
        self.assertEqual(cursor.fetchone(), (0, 1))

    def test_embeddings_are_scheduled_only_after_successful_commit(self) -> None:
        self.hm.rag = _FakeRag()
        executor = _FakeExecutor()

        with patch.object(HistoryManager, "_get_embed_executor", return_value=executor):
            self.hm.save_history(
                {
                    "messages": [{"role": "assistant", "content": "embed me", "time": "01.01.2026 11:00:00"}],
                    "variables": {},
                }
            )

        self.assertEqual(len(executor.jobs), 1)

    def test_add_messages_commits_completed_turn_in_one_transaction(self) -> None:
        turn_id = "turn:test-1"
        row_ids = self.hm.add_messages(
            [
                {
                    "message_id": "in:test-1",
                    "turn_id": turn_id,
                    "role": "user",
                    "content": "question",
                    "time": "01.01.2026 12:00:00",
                },
                {
                    "message_id": "out:test-1",
                    "turn_id": turn_id,
                    "role": "assistant",
                    "content": "answer",
                    "time": "01.01.2026 12:00:01",
                },
            ]
        )

        self.assertEqual(len(row_ids), 2)
        loaded = self.hm.load_history()["messages"]
        self.assertEqual([item["content"] for item in loaded], ["question", "answer"])
        self.assertEqual({item.get("turn_id") for item in loaded}, {turn_id})

    def test_add_messages_rolls_back_entire_turn_on_insert_failure(self) -> None:
        self.hm.add_message(
            {
                "message_id": "existing",
                "role": "user",
                "content": "existing",
                "time": "01.01.2026 12:00:00",
            }
        )

        original_insert = self.hm._insert_history_row_tx
        rich_calls = {"count": 0}

        def failing_rich(cursor, *, msg, is_active, dedupe=True):
            rich_calls["count"] += 1
            if rich_calls["count"] == 2:
                raise RuntimeError("rich failure")
            return original_insert(cursor, msg=msg, is_active=is_active, dedupe=dedupe)

        with patch.object(self.hm, "_insert_history_row_tx", side_effect=failing_rich):
            row_ids = self.hm.add_messages(
                [
                    {
                        "message_id": "in:failed-turn",
                        "turn_id": "turn:failed-turn",
                        "role": "user",
                        "content": "question",
                        "time": "01.01.2026 12:01:00",
                    },
                    {
                        "message_id": "out:failed-turn",
                        "turn_id": "turn:failed-turn",
                        "role": "assistant",
                        "content": "answer",
                        "time": "01.01.2026 12:01:01",
                    },
                ]
            )

        self.assertEqual(row_ids, [])
        loaded = self.hm.load_history()["messages"]
        self.assertEqual([item["content"] for item in loaded], ["existing"])


if __name__ == "__main__":
    unittest.main()
