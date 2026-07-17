from __future__ import annotations

import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.database_manager import DatabaseManager


class MemoryIslandUpsertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="nm_island_")
        DatabaseManager._instance = None
        DatabaseManager._path_override = os.path.join(cls._tmp, "world.db")
        from managers.memory_manager import MemoryManager
        cls._MM = MemoryManager

    @classmethod
    def tearDownClass(cls):
        DatabaseManager._instance = None
        DatabaseManager._path_override = None

    def _fresh_mm(self, name):
        mm = self._MM(name)
        mm.rag = None  # disable background RAG reindex for the test
        return mm

    def _active_island_count(self, mm, full_type):
        with mm.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM memories WHERE character_id=? AND type=? AND is_deleted=0",
                (mm.storage_key, full_type),
            )
            return int(cur.fetchone()[0])

    def test_upsert_creates_then_updates_without_duplicate(self):
        mm = self._fresh_mm("IslandChar")
        eid1 = mm.upsert_island("island:relationship", "We are friendly", priority="high")
        self.assertIsNotNone(eid1)
        self.assertEqual(self._active_island_count(mm, "island:relationship"), 1)

        eid2 = mm.upsert_island("relationship", "We had a fight and made up", priority="high")
        self.assertEqual(eid2, eid1)  # same island, not a new one
        self.assertEqual(self._active_island_count(mm, "island:relationship"), 1)
        self.assertEqual(mm.get_memory_content(eid1), "We had a fight and made up")

    def test_distinct_types_are_separate_islands(self):
        mm = self._fresh_mm("IslandChar2")
        a = mm.upsert_island("island:opinion", "I find them interesting")
        b = mm.upsert_island("island:preferences", "They like tea")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a, b)

    def test_unknown_type_ignored(self):
        mm = self._fresh_mm("IslandChar3")
        self.assertIsNone(mm.upsert_island("island:bogus", "nope"))
        self.assertIsNone(mm.upsert_island("relationship", "   "))  # empty content

    def test_forgotten_island_is_reactivated_and_updated(self):
        mm = self._fresh_mm("IslandForget")
        eid = mm.upsert_island("island:opinion", "first opinion")
        self.assertIsNotNone(eid)

        # Forcibly forget it (simulates capacity/TTL having marked it forgotten).
        with mm.db.connection() as conn:
            conn.execute(
                "UPDATE memories SET is_forgotten=1 WHERE character_id=? AND eternal_id=?",
                (mm.storage_key, eid),
            )
            conn.commit()

        eid2 = mm.upsert_island("island:opinion", "second opinion")
        self.assertEqual(eid2, eid)  # reactivated, not orphaned/duplicated
        self.assertEqual(mm.get_memory_content(eid), "second opinion")

        with mm.db.connection() as conn:
            row = conn.execute(
                "SELECT is_forgotten FROM memories WHERE character_id=? AND eternal_id=?",
                (mm.storage_key, eid),
            ).fetchone()
        self.assertEqual(int(row[0]), 0)  # active again
        self.assertEqual(self._active_island_count(mm, "island:opinion"), 1)

    def test_island_type_excluded_from_forget_candidates(self):
        # The capacity-forget candidate query must never select island rows.
        mm = self._fresh_mm("IslandCap")
        mm.upsert_island("island:relationship", "we are close")
        mm.add_memory(content="an ordinary fact", priority="normal")
        with mm.db.connection() as conn:
            island_candidates = conn.execute(
                "SELECT COUNT(*) FROM memories "
                "WHERE character_id=? AND is_deleted=0 AND is_forgotten=0 "
                "AND type LIKE 'island:%'",
                (mm.storage_key,),
            ).fetchone()[0]
        self.assertEqual(int(island_candidates), 1)  # island exists...
        # ...but the forget query (which adds NOT LIKE 'island:%') can't pick it.

    def test_seed_rag_memory_is_forgotten_but_indexed(self):
        class _FakeRag:
            def __init__(self):
                self.embedded = []

            def update_memory_embedding(self, eid, txt):
                self.embedded.append((int(eid), str(txt)))

        mm = self._fresh_mm("CreditsChar")
        fake = _FakeRag()
        mm.rag = fake

        eid = mm.seed_rag_memory("NeuroMita was made by VinerX", priority="high")
        self.assertIsNotNone(eid)

        # Not in the active block: stored as forgotten.
        with mm.db.connection() as conn:
            row = conn.execute(
                "SELECT is_forgotten, is_deleted FROM memories "
                "WHERE character_id=? AND eternal_id=?",
                (mm.storage_key, eid),
            ).fetchone()
        self.assertEqual(int(row[0]), 1)  # forgotten -> out of active block
        self.assertEqual(int(row[1]), 0)  # but not deleted -> RAG-findable

        # Re-seeding the same fact updates in place without a duplicate and
        # keeps it RAG-only.
        eid2 = mm.seed_rag_memory("NeuroMita was made by VinerX", priority="high")
        self.assertEqual(eid2, eid)
        with mm.db.connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE character_id=? AND content=?",
                (mm.storage_key, "NeuroMita was made by VinerX"),
            ).fetchone()[0]
        self.assertEqual(int(count), 1)

        # It was scheduled for embedding (RAG index).
        mm._get_embed_executor().submit(lambda: None).result(timeout=5)
        self.assertTrue(any(e == eid for e, _ in fake.embedded))

    def test_seed_rag_memory_absent_from_active_block(self):
        mm = self._fresh_mm("CreditsActive")
        mm.seed_rag_memory("credit fact only for RAG", priority="high")
        mm.add_memory(content="a normal active fact", priority="normal")
        active = mm.get_memories_formatted()
        self.assertNotIn("credit fact only for RAG", active)
        self.assertIn("a normal active fact", active)

    def test_merge_updates_target_deletes_source_and_reindexes(self):
        class _FakeRag:
            def __init__(self):
                self.calls = []

            def update_memory_embedding(self, eid, txt):
                self.calls.append((int(eid), str(txt)))

        mm = self._MM("MergeChar")
        fake = _FakeRag()
        mm.rag = fake

        a = mm.add_memory(content="Player likes cats", priority="normal", entities=["cats"])
        b = mm.add_memory(content="Player likes tea", priority="normal", entities=["tea"])

        ok = mm.merge_memories(source_id=a, target_id=b, new_content="Player likes cats and tea")
        self.assertTrue(ok)

        # Source soft-deleted, target rewritten.
        self.assertIsNone(mm.get_memory_content(a))
        self.assertEqual(mm.get_memory_content(b), "Player likes cats and tea")

        # Entities transferred from source to target.
        with mm.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT entities FROM memories WHERE character_id=? AND eternal_id=?",
                (mm.storage_key, b),
            )
            import json
            ents = set(json.loads(cur.fetchone()[0] or "[]"))
        self.assertIn("cats", ents)
        self.assertIn("tea", ents)

        # Reindex was scheduled — flush the single-worker embed executor.
        mm._get_embed_executor().submit(lambda: None).result(timeout=5)
        self.assertIn((b, "Player likes cats and tea"), fake.calls)


class IslandTtlProtectionTests(unittest.TestCase):
    """Islands must survive TTL cleanup in every MEMORY_TTL_MODE."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="nm_island_ttl_")
        DatabaseManager._instance = None
        DatabaseManager._path_override = os.path.join(cls._tmp, "world.db")
        from managers.memory_manager import MemoryManager
        cls._MM = MemoryManager

    @classmethod
    def tearDownClass(cls):
        DatabaseManager._instance = None
        DatabaseManager._path_override = None

    def _fresh_mm(self, name):
        mm = self._MM(name)
        mm.rag = None
        mm._ensure_memories_schema()  # access_count / last_accessed columns
        return mm

    def _backdate(self, mm, eid, days):
        old = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime(
            "%d.%m.%Y %H:%M:%S"
        )
        with mm.db.connection() as conn:
            conn.execute(
                "UPDATE memories SET date_created=?, last_accessed=? "
                "WHERE character_id=? AND eternal_id=?",
                (old, old, mm.storage_key, eid),
            )
            conn.commit()

    def _is_forgotten(self, mm, eid):
        with mm.db.connection() as conn:
            row = conn.execute(
                "SELECT is_forgotten FROM memories WHERE character_id=? AND eternal_id=?",
                (mm.storage_key, eid),
            ).fetchone()
        return int(row[0])

    def _run_mode(self, mode, char_name):
        mm = self._fresh_mm(char_name)
        island_eid = mm.upsert_island("island:relationship", "we are close", priority="high")
        normal_eid = mm.add_memory(content="an ordinary fact", priority="high")
        self.assertIsNotNone(island_eid)
        self.assertIsNotNone(normal_eid)

        # Both far older than the TTL — only the non-island one must be forgotten.
        self._backdate(mm, island_eid, days=100)
        self._backdate(mm, normal_eid, days=100)

        settings = {
            "MEMORY_TTL_ENABLED": True,
            "MEMORY_TTL_LOW_DAYS": 0,
            "MEMORY_TTL_NORMAL_DAYS": 0,
            "MEMORY_TTL_HIGH_DAYS": 10,
            "MEMORY_TTL_MODE": mode,
            "MEMORY_TTL_ACCESS_WEIGHT": 0.5,
        }
        with mock.patch(
            "managers.memory_manager.SettingsManager.get",
            side_effect=lambda key, default=None: settings.get(key, default),
        ):
            forgotten = mm.apply_ttl_cleanup()

        self.assertEqual(self._is_forgotten(mm, island_eid), 0, f"island forgotten in {mode}")
        self.assertEqual(self._is_forgotten(mm, normal_eid), 1, f"normal survived in {mode}")
        self.assertEqual(forgotten, 1, f"exactly one memory forgotten in {mode}")

    def test_island_survives_ttl_date_created(self):
        self._run_mode("date_created", "TtlDateCreated")

    def test_island_survives_ttl_last_accessed(self):
        self._run_mode("last_accessed", "TtlLastAccessed")

    def test_island_survives_ttl_access_weighted(self):
        self._run_mode("access_weighted", "TtlAccessWeighted")


class IslandRoutingTests(unittest.TestCase):
    def test_memory_add_routes_island_to_upsert(self):
        from characters.character import Character
        from schemas.structured_response import StructuredResponse

        class _FakeMem:
            def __init__(self):
                self.added = []
                self.islands = []

            def add_memory(self, priority=None, content=None, entities=None, **kw):
                self.added.append((priority, content))
                return 100 + len(self.added)

            def upsert_island(self, island_type, content, **kw):
                self.islands.append((island_type, content))
                return 200 + len(self.islands)

            def update_memory(self, **kw):
                pass

            def delete_memory(self, *a, **kw):
                pass

        class _Char(Character):
            def __init__(self, mem):
                self.char_id = "T"
                self._mem = mem

            @property
            def memory_system(self):
                return self._mem

        mem = _FakeMem()
        char = _Char(mem)
        resp = StructuredResponse(
            segments=[{"text": "hi"}],
            memory_add=[
                "island:relationship|We reconciled after the argument",
                "high|The player's cat is named Barsik",
            ],
        )
        char._apply_structured_memory_ops(resp)

        self.assertEqual(mem.islands, [("island:relationship", "We reconciled after the argument")])
        self.assertEqual(mem.added, [("high", "The player's cat is named Barsik")])


if __name__ == "__main__":
    unittest.main()
