"""Регрессия на гонку состояния персонажа.

Пул GENERATION многопоточный, поэтому два запроса к ОДНОЙ Мите (реплика игрока и
idle-событие из игры) могли украсть друг у друга consume_pending_targets() и
перемешать инкременты attitude. Разные персонажи должны идти параллельно.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.character_locks import character_generation_lock, character_lock


class _Character:
    """Разделяемое изменяемое состояние, как у настоящего Character."""

    def __init__(self, char_id: str):
        self.char_id = char_id
        self.attitude = 0
        self._pending_targets: list[str] = []

    def queue_target(self, target: str):
        self._pending_targets.append(target)

    def consume_pending_targets(self) -> list[str]:
        taken = list(self._pending_targets)
        self._pending_targets.clear()
        return taken

    def bump_attitude(self, delta: int):
        # Намеренно неатомарно: read-modify-write с окном для гонки.
        current = self.attitude
        time.sleep(0.001)
        self.attitude = current + delta


def _generation(character: _Character, target: str, results: list, errors: list):
    try:
        with character_generation_lock(character.char_id):
            time.sleep(0.005)
            with character_lock(character.char_id):
                character.queue_target(target)
                taken = character.consume_pending_targets()
                character.bump_attitude(1)
                results.append(taken)
    except Exception as exc:  # pragma: no cover
        errors.append(exc)


class CharacterSerializationTests(unittest.TestCase):
    def test_same_character_requests_do_not_steal_targets(self):
        char = _Character("Crazy")
        results: list = []
        errors: list = []

        threads = [
            threading.Thread(target=_generation, args=(char, f"t{i}", results, errors))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        self.assertEqual(errors, [])
        # Каждый запрос забрал ровно свой target — никто ничего не украл и не потерял.
        self.assertEqual(len(results), 8)
        for taken in results:
            self.assertEqual(len(taken), 1, f"targets перемешались: {results}")
        self.assertEqual(sorted(t[0] for t in results), [f"t{i}" for i in range(8)])
        # Инкременты attitude не потерялись.
        self.assertEqual(char.attitude, 8)

    def test_different_characters_run_in_parallel(self):
        chars = [_Character(f"Mita{i}") for i in range(4)]
        barrier = threading.Barrier(len(chars), timeout=3)
        reached = []

        def work(character: _Character):
            with character_generation_lock(character.char_id):
                # Если бы блокировка была глобальной, барьер не собрался бы.
                barrier.wait()
                reached.append(character.char_id)

        threads = [threading.Thread(target=work, args=(c,)) for c in chars]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        self.assertEqual(len(reached), 4, "разные персонажи сериализовались между собой")

    def test_lock_is_reentrant_for_nested_sections(self):
        # generate_chat держит блокировку и внутри зовёт prepare_for_prompt,
        # который берёт её же в том же потоке.
        lock = character_lock("Crazy")
        acquired = []

        def nested():
            with character_lock("Crazy"):
                acquired.append("outer")
                with character_lock("Crazy"):
                    acquired.append("inner")

        thread = threading.Thread(target=nested)
        thread.start()
        thread.join(2)

        self.assertFalse(thread.is_alive(), "реентерабельный захват привёл к дедлоку")
        self.assertEqual(acquired, ["outer", "inner"])
        self.assertIs(character_lock("Crazy"), lock, "на один id должна быть одна блокировка")

    def test_generation_gate_does_not_hold_character_state_lock(self):
        entered = threading.Event()
        release = threading.Event()

        def generation():
            with character_generation_lock("Crazy"):
                entered.set()
                release.wait(1.0)

        thread = threading.Thread(target=generation)
        thread.start()
        self.assertTrue(entered.wait(1.0))

        state_lock = character_lock("Crazy")
        self.assertTrue(state_lock.acquire(timeout=0.2))
        state_lock.release()

        release.set()
        thread.join(1.0)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
