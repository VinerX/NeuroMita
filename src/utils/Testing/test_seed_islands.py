from __future__ import annotations

import os
import sys
import tempfile
import unittest

PROJECT_SRC = __import__("pathlib").Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

BASE = str(PROJECT_SRC.parent)
PROMPTS = os.path.join(BASE, "extra", "Prompts")

from managers.database_manager import DatabaseManager


class _StubChar:
    def __init__(self, cid, base, mem):
        self.char_id = cid
        self.character_base_data_path = base
        self.memory_system = mem
        self.variables = {
            "attitude": 55.0, "boredom": 35.0, "stress": 25.0,
            "attitude_band": None, "Love": None,
            "secretExposed": False, "secretExposedFirst": False,
            "secret_exposed_event_text_shown": False,
        }
        self.app_vars = {}

    def set_variable(self, name, value):
        self.variables[name] = value


# Все дефолтные персонажи, у которых init.script теперь грузит мир + личный сид.
TARGETS = [
    ("CrazyDefault", "Crazy/Default"), ("KindDefault", "Kind/Default"),
    ("CappieDefault", "Cappie/Default"), ("CreepyDefault", "Creepy/Default"),
    ("GhostDefault", "Ghost/Default"), ("MilaDefault", "Mila/Default"),
    ("ShortHairDefault", "ShortHair/Default"), ("SleepyDefault", "Sleepy/Default"),
]


class SeedIslandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="nm_seed_")
        DatabaseManager._instance = None
        DatabaseManager._path_override = os.path.join(cls._tmp, "world.db")
        from managers.memory_manager import MemoryManager
        from DSL.dsl_engine import DslInterpreter
        from DSL.path_resolver import LocalPathResolver
        cls._MM = MemoryManager
        cls._Interp = DslInterpreter
        cls._Resolver = LocalPathResolver

    @classmethod
    def tearDownClass(cls):
        DatabaseManager._instance = None
        DatabaseManager._path_override = None

    def _run_init(self, cid, sub):
        cbase = os.path.join(PROMPTS, sub)
        resolver = self._Resolver(PROMPTS, cbase)
        mem = self._MM(cid)
        mem.rag = None
        ch = _StubChar(cid, cbase, mem)
        interp = self._Interp(ch, resolver=resolver)
        interp.process_file("Scripts/init.script")
        return mem

    def _counts(self, mem, key):
        with mem.db.connection() as conn:
            cur = conn.cursor()

            def q(sql):
                cur.execute(sql, (key,))
                return cur.fetchone()[0]

            active = q("SELECT COUNT(*) FROM memories WHERE character_id=? AND is_deleted=0 "
                       "AND is_forgotten=0 AND (type IS NULL OR type NOT LIKE 'island:%')")
            islands = q("SELECT COUNT(*) FROM memories WHERE character_id=? AND is_deleted=0 "
                        "AND is_forgotten=0 AND type LIKE 'island:%'")
            forgotten = q("SELECT COUNT(*) FROM memories WHERE character_id=? AND is_deleted=0 "
                          "AND is_forgotten=1")
            cur.execute("SELECT content FROM memories WHERE character_id=? AND type='island:relationship' "
                        "AND is_deleted=0 LIMIT 1", (key,))
            row = cur.fetchone()
            return active, islands, forgotten, (row[0] if row else None)

    def test_every_character_seeds_world_and_relationship_island(self):
        for cid, sub in TARGETS:
            mem = self._run_init(cid, sub)
            a1, i1, f1, isl1 = self._counts(mem, cid)
            # Пересборка init.script (следующий ход) — должна быть идемпотентной.
            self._run_init(cid, sub)
            a2, i2, f2, isl2 = self._counts(mem, cid)
            self.assertEqual(i1, 1, f"{cid}: ожидался ровно 1 остров relationship")
            self.assertEqual(i2, 1, f"{cid}: остров продублировался при пересборке")
            self.assertEqual(isl1, isl2, f"{cid}: контент острова изменился при пересборке")
            self.assertIsNotNone(isl1, f"{cid}: остров relationship пуст")
            self.assertGreater(f1, 90, f"{cid}: слишком мало RAG-фактов ({f1}) — мир не подключился")
            self.assertEqual(f1, f2, f"{cid}: RAG-факты изменились при пересборке")
            self.assertEqual(a1, a2, f"{cid}: активные факты изменились при пересборке")

    def test_seed_island_does_not_overwrite_evolved_island(self):
        cid, sub = "KindDefault", "Kind/Default"
        mem = self._run_init(cid, sub)
        evolved = "ЭВОЛЮЦИОНИРОВАВШЕЕ отношение: игрок и Мита прошли долгий путь вместе."
        mem.upsert_island("relationship", evolved)
        # Повторная сборка не должна затирать прожитое стартовым сидом.
        self._run_init(cid, sub)
        _, _, _, isl = self._counts(mem, cid)
        self.assertEqual(isl, evolved, "seed_island затёр эволюционировавший остров")


if __name__ == "__main__":
    unittest.main()
