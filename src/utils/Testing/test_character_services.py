from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.character_manager import CharacterDefinition, CharacterManager
from managers.character_resource_manager import CharacterResourceManager
from managers.character_scoped_service import CharacterScopedService
from managers.database_manager import DatabaseManager


class _ProbeService(CharacterScopedService):
    def identity(self, delay: float = 0.0) -> str:
        if delay:
            time.sleep(delay)
        return self.character_id


class _FakeCharacter:
    char_id = ""
    name = ""
    created = 0

    def __init__(self):
        type(self).created += 1
        self.runtime_loaded = False
        self.resource_manager = None
        self.reload_count = 0

    def bind_resource_manager(self, manager):
        self.resource_manager = manager

    def ensure_runtime_loaded(self):
        self.runtime_loaded = True

    def reload_character_data(self):
        self.reload_count += 1
        return None

    def clear_history(self):
        return None


class _FakeA(_FakeCharacter):
    char_id = "A"
    name = "A"
    created = 0


class _FakeB(_FakeCharacter):
    char_id = "B"
    name = "B"
    created = 0


class CharacterServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_histories = os.environ.get("NEUROMITA_HISTORIES_DIR")
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["NEUROMITA_HISTORIES_DIR"] = self._temp_dir.name
        DatabaseManager._instance = None
        DatabaseManager._path_override = str(Path(self._temp_dir.name) / "world.db")

    def tearDown(self) -> None:
        DatabaseManager._instance = None
        DatabaseManager._path_override = None
        if self._old_histories is None:
            os.environ.pop("NEUROMITA_HISTORIES_DIR", None)
        else:
            os.environ["NEUROMITA_HISTORIES_DIR"] = self._old_histories
        self._temp_dir.cleanup()

    def test_resources_own_one_service_instance_for_all_characters(self):
        resources = CharacterResourceManager()
        resources.register_character("A", "Character A")
        resources.register_character("B", "Character B")

        history_a = resources.history_for("A")
        history_b = resources.history_for("B")
        memory_a = resources.memory_for("A")
        memory_b = resources.memory_for("B")
        reminder_a = resources.reminders_for("A")
        reminder_b = resources.reminders_for("B")

        self.assertIs(history_a, resources.history_for("A"))
        self.assertIs(memory_a, resources.memory_for("A"))
        self.assertIs(reminder_a, resources.reminders_for("A"))

        self.assertIs(object.__getattribute__(history_a, "_service"), resources.history_manager)
        self.assertIs(object.__getattribute__(history_b, "_service"), resources.history_manager)
        self.assertIs(object.__getattribute__(memory_a, "_service"), resources.memory_manager)
        self.assertIs(object.__getattribute__(memory_b, "_service"), resources.memory_manager)
        self.assertIs(object.__getattribute__(reminder_a, "_service"), resources.reminder_manager)
        self.assertIs(object.__getattribute__(reminder_b, "_service"), resources.reminder_manager)

        history_a.append_message({"role": "user", "content": "only A", "message_id": "a1"})
        history_b.append_message({"role": "user", "content": "only B", "message_id": "b1"})

        self.assertEqual(
            [item["content"] for item in history_a.load_history()["messages"]],
            ["only A"],
        )
        self.assertEqual(
            [item["content"] for item in history_b.load_history()["messages"]],
            ["only B"],
        )

        memory_a.add_memory("A memory")
        memory_b.add_memory("B memory")
        with resources.memory_manager.db.connection() as connection:
            rows = connection.execute(
                "SELECT character_id, content FROM memories ORDER BY character_id"
            ).fetchall()
        self.assertEqual(rows, [("A", "A memory"), ("B", "B memory")])

        reminder_a.add_reminder("A reminder", "2099-01-01T00:00:00")
        self.assertIn("A reminder", reminder_a.get_reminders_formatted())
        self.assertEqual(reminder_b.get_reminders_formatted(), "")

    def test_bound_scopes_do_not_leak_between_threads(self):
        service = _ProbeService()
        a = service.bind("A", "A")
        b = service.bind("B", "B")
        results: list[str] = []
        lock = threading.Lock()

        def run(bound, expected):
            local = [bound.identity(0.001) for _ in range(25)]
            self.assertTrue(all(value == expected for value in local))
            with lock:
                results.extend(local)

        threads = [
            threading.Thread(target=run, args=(a, "A")),
            threading.Thread(target=run, args=(b, "B")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results.count("A"), 25)
        self.assertEqual(results.count("B"), 25)

    def test_character_manager_materializes_only_requested_characters(self):
        _FakeA.created = 0
        _FakeB.created = 0
        definitions = (
            CharacterDefinition("A", "A", _FakeA),
            CharacterDefinition("B", "B", _FakeB),
        )

        with patch("managers.character_manager._CHARACTER_DEFINITIONS", definitions):
            manager = CharacterManager(
                initial_character_id="A",
                resources=CharacterResourceManager(),
            )
            self.assertEqual(list(manager.characters), ["A"])
            self.assertEqual(manager.get_all_characters(), ["A", "B"])
            self.assertEqual(_FakeA.created, 1)
            self.assertEqual(_FakeB.created, 0)

            self.assertIsNotNone(manager.get_character("B"))
            self.assertEqual(list(manager.characters), ["A", "B"])
            self.assertEqual(_FakeB.created, 1)

    def test_selecting_current_character_is_idempotent(self):
        _FakeA.created = 0
        definitions = (CharacterDefinition("A", "A", _FakeA),)

        with patch("managers.character_manager._CHARACTER_DEFINITIONS", definitions):
            manager = CharacterManager(
                initial_character_id="A",
                resources=CharacterResourceManager(),
            )
            character = manager.current_character
            self.assertIsNotNone(character)
            self.assertEqual(character.reload_count, 0)

            manager.set_character_to_change("A")
            manager.check_change_current_character()

            self.assertIs(manager.current_character, character)
            self.assertEqual(character.reload_count, 0)


if __name__ == "__main__":
    unittest.main()
