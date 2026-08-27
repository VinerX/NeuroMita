from __future__ import annotations

import os
import sys
import tempfile
import unittest

PROJECT_SRC = __import__("pathlib").Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.database_manager import DatabaseManager


class RetrievalAwareForgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="nm_forget_")
        DatabaseManager._instance = None
        DatabaseManager._path_override = os.path.join(cls._tmp, "world.db")
        from managers.memory_manager import MemoryManager
        cls._MM = MemoryManager

    @classmethod
    def tearDownClass(cls):
        DatabaseManager._instance = None
        DatabaseManager._path_override = None

    def _mm(self, name, cap=3, use_retrieval=True):
        mm = self._MM(name)
        mm.rag = None
        mm._dedup_enabled = lambda: False
        mm._get_memory_capacity = lambda: cap
        mm._forget_use_retrieval = lambda: use_retrieval
        # Изолируем ранг забывания от TTL-очистки (тестовые даты — 2020).
        mm.apply_ttl_cleanup = lambda *a, **k: None
        return mm

    def _set_access(self, mm, eid, n):
        with mm.db.connection() as conn:
            conn.cursor().execute(
                "UPDATE memories SET access_count=? WHERE character_id=? AND eternal_id=?",
                (n, mm.storage_key, eid),
            )
            conn.commit()

    def _forgotten(self, mm, eid):
        with mm.db.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT is_forgotten FROM memories WHERE character_id=? AND eternal_id=?",
                        (mm.storage_key, eid))
            return bool(cur.fetchone()[0])

    def test_retrieved_memory_survives_over_older_unused(self):
        mm = self._mm("RetChar", cap=3, use_retrieval=True)
        e1 = mm.add_memory("самая старая память", priority="Normal", date="01.01.2020 10:00:00")
        e2 = mm.add_memory("средняя память", priority="Normal", date="02.01.2020 10:00:00")
        e3 = mm.add_memory("свежая память", priority="Normal", date="03.01.2020 10:00:00")
        # Старейшая e1 многократно всплывала в RAG — должна пережить.
        self._set_access(mm, e1, 7)
        # Переполняем: добавление e4 требует забыть одну.
        mm.add_memory("новая память", priority="Normal", date="04.01.2020 10:00:00")
        self.assertFalse(self._forgotten(mm, e1), "полезную (retrieved) старую память забыли")
        self.assertTrue(self._forgotten(mm, e2), "ожидалось забывание старейшей неиспользованной (e2)")
        self.assertFalse(self._forgotten(mm, e3))

    def test_without_flag_oldest_forgotten_regardless_of_access(self):
        mm = self._mm("RetChar2", cap=3, use_retrieval=False)
        e1 = mm.add_memory("старейшая", priority="Normal", date="01.01.2020 10:00:00")
        mm.add_memory("средняя", priority="Normal", date="02.01.2020 10:00:00")
        mm.add_memory("свежая", priority="Normal", date="03.01.2020 10:00:00")
        self._set_access(mm, e1, 7)
        mm.add_memory("новая", priority="Normal", date="04.01.2020 10:00:00")
        # Флаг выключен — классика: забываем строго старейшую, access игнорируем.
        self.assertTrue(self._forgotten(mm, e1), "без флага должна забыться старейшая (e1)")


if __name__ == "__main__":
    unittest.main()
