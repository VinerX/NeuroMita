from __future__ import annotations

import os
import sys
import tempfile
import unittest

PROJECT_SRC = __import__("pathlib").Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.database_manager import DatabaseManager


class MemoryDedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="nm_dedup_")
        DatabaseManager._instance = None
        DatabaseManager._path_override = os.path.join(cls._tmp, "world.db")
        from managers.memory_manager import MemoryManager
        cls._MM = MemoryManager

    @classmethod
    def tearDownClass(cls):
        DatabaseManager._instance = None
        DatabaseManager._path_override = None

    def _fresh_mm(self, name, threshold=0.8):
        mm = self._MM(name)
        mm.rag = None
        # Фиксируем порог/включённость независимо от машинных настроек.
        mm._dedup_threshold = lambda: threshold
        mm._dedup_enabled = lambda: True
        mm._maintenance_enabled = lambda: True
        return mm

    def _active(self, mm):
        with mm.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT eternal_id, priority, content FROM memories "
                "WHERE character_id=? AND is_deleted=0 AND is_forgotten=0",
                (mm.storage_key,),
            )
            return cur.fetchall()

    def test_dedup_on_insert_merges_near_identical(self):
        mm = self._fresh_mm("DedupInsert")
        eid1 = mm.add_memory("The player likes to play chess", priority="normal")
        eid2 = mm.add_memory("Player likes to play chess", priority="high")
        # Near-identical → merged into the existing one, priority raised.
        self.assertEqual(eid2, eid1)
        rows = self._active(mm)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1].lower(), "high")

    def test_dedup_keeps_distinct_memories(self):
        mm = self._fresh_mm("DedupDistinct")
        mm.add_memory("Player likes chess", priority="normal")
        mm.add_memory("Player hates loud noises", priority="normal")
        self.assertEqual(len(self._active(mm)), 2)

    def test_maintenance_collapses_accumulated_duplicates(self):
        mm = self._fresh_mm("DedupSweep")
        # skip_if_exists=True обходит дедуп на вставке — имитируем накопившиеся дубли.
        mm.add_memory("Player promised to bring flowers tomorrow", priority="normal", skip_if_exists=True)
        mm.add_memory("The player promised to bring flowers tomorrow", priority="high", skip_if_exists=True)
        mm.add_memory("Player promised to bring flowers tomorrow morning", priority="normal", skip_if_exists=True)
        mm.add_memory("Weather is nice today", priority="low", skip_if_exists=True)
        self.assertEqual(len(self._active(mm)), 4)

        res = mm.run_maintenance()
        self.assertEqual(res["merged"], 2)
        self.assertEqual(res["clusters"], 1)

        rows = self._active(mm)
        self.assertEqual(len(rows), 2)
        # Keeper — самый приоритетный из группы.
        kept_flowers = [r for r in rows if "flowers" in r[2].lower()]
        self.assertEqual(len(kept_flowers), 1)
        self.assertEqual(kept_flowers[0][1].lower(), "high")

    def test_islands_are_not_deduped(self):
        mm = self._fresh_mm("DedupIslands")
        a = mm.upsert_island("island:relationship", "We are close friends now", priority="high")
        b = mm.add_memory("We are close friends now", priority="normal")
        # Остров и обычный факт с тем же текстом не должны схлопнуться друг в друга.
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
