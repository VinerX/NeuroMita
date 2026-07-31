"""Сброс истории не должен частично откатываться фоновым сжатием.

Регресс: фоновое сжатие читало историю, уходило в LLM на несколько секунд и
записывало сводку/границу/факты уже ПОСЛЕ очистки чата — удалённое возвращалось.
Плюс сводка и её граница писались двумя отдельными транзакциями: падение между
ними означало повторное сжатие того же куска (дубли фактов).
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.history_controller import HistoryController
from core.character_locks import character_lock
from core.services import services
from services.contracts import (
    GenerationService,
    UtilityGenerationRequest,
    UtilityGenerationResult,
)


class _StubGenerationService(GenerationService):
    """Отдаёт заготовленный ответ и считает вызовы."""

    def __init__(self, text: str):
        self._text = text
        self.calls: list[UtilityGenerationRequest] = []

    def generate_chat(self, request):
        raise AssertionError("generate_chat не должен вызываться при сжатии истории")

    def generate_utility(self, request: UtilityGenerationRequest) -> UtilityGenerationResult:
        self.calls.append(request)
        return UtilityGenerationResult(ok=True, text=self._text)


class _StubHistoryManager:
    def __init__(self, messages):
        self._messages = list(messages)
        self.saved_missed = []

    def load_history(self):
        return {"messages": list(self._messages)}

    def save_missed_history(self, messages):
        self.saved_missed.extend(messages)


class _StubCharacter:
    def __init__(self, messages=(), *, char_id="TestChar", memory_system=None):
        self.char_id = char_id
        self.name = char_id
        self.history_manager = _StubHistoryManager(messages)
        self.memory_system = memory_system
        self.vars = {}
        self.history_epoch = 0
        self.flushes = 0
        self._pending = {}

    def get_variable(self, key, default=None):
        return self.vars.get(key, default)

    def set_variable(self, key, value):
        # Имитируем dirty-набор Character: значение видно только после flush.
        self._pending[key] = value

    def flush_variables(self):
        self.flushes += 1
        self.vars.update(self._pending)
        self._pending.clear()

    def clear_history(self):
        """Ровно то, что делает Character.clear_history(): эпоха под замком,
        затем чистка переменных и памяти."""
        with character_lock(self.char_id):
            self.history_epoch += 1
        self.vars.clear()
        self._pending.clear()
        if self.memory_system is not None:
            self.memory_system.clear_memories()


class _RecordingMemory:
    def __init__(self, on_add=None):
        self.added = []
        self.attempts = 0
        self.clears = 0
        self._on_add = on_add

    def add_memory(self, content, priority="normal", **_kw):
        self.attempts += 1
        self.added.append((priority, content))
        if self._on_add is not None:
            self._on_add(self)
        return object()

    def clear_memories(self):
        self.clears += 1
        self.added.clear()


def _make_controller(settings: dict | None = None) -> HistoryController:
    controller = HistoryController.__new__(HistoryController)
    controller.event_bus = SimpleNamespace(emit=lambda *a, **k: None)
    controller._messages_since_last_periodic_compression = {}
    controller._compression_guard = threading.Lock()
    controller._compression_inflight = set()
    controller._background_compression_inflight = set()
    controller._background_compression_timers = {}
    controller._compression_cooldowns = {}
    controller._messages_since_last_maintenance = {}
    controller._maintenance_inflight = set()
    controller._closed = False
    cfg = dict(settings or {})
    controller._get_setting = lambda key, default=None: cfg.get(key, default)
    controller._sanitize_history_for_llm = lambda _character, messages: messages
    controller._apply_history_image_quality_reduction = lambda messages, _cfg: messages
    return controller


class SummaryCommitAtomicityTests(unittest.TestCase):
    def test_summary_and_anchor_land_in_one_transaction(self):
        """Текст, счётчик, слои и граница — один flush, то есть одна транзакция.

        Раньше граница писалась вторым flush: падение между ними давало сводку
        без сдвинутой границы, и тот же кусок сжимался повторно.
        """
        controller = _make_controller()
        character = _StubCharacter()

        applied = controller._commit_summary_state(
            character,
            epoch=0,
            summary_text="сводка",
            summary_count=7,
            anchor_id=503,
            segments=[{"text": "сводка", "msg_count": 7, "level": 0}],
        )

        self.assertTrue(applied)
        self.assertEqual(character.flushes, 1)
        self.assertEqual(character.vars[HistoryController._SUMMARY_TEXT_VAR], "сводка")
        self.assertEqual(character.vars[HistoryController._SUMMARY_COUNT_VAR], 7)
        self.assertEqual(character.vars[HistoryController._SUMMARY_ANCHOR_VAR], 503)
        self.assertIn(HistoryController._SUMMARY_SEGMENTS_VAR, character.vars)

    def test_commit_is_refused_after_history_reset(self):
        controller = _make_controller()
        character = _StubCharacter()
        epoch = character.history_epoch
        character.clear_history()  # пока шёл LLM-вызов, чат очистили

        applied = controller._commit_summary_state(
            character,
            epoch=epoch,
            summary_text="сводка из стёртой истории",
            summary_count=7,
            anchor_id=503,
        )

        self.assertFalse(applied)
        self.assertEqual(character.vars, {})
        self.assertEqual(character.flushes, 0)


class CompressionAfterResetTests(unittest.TestCase):
    _SETTINGS = {
        "HISTORY_COMPRESSION_OUTPUT_TARGET": "layered",
        "HISTORY_COMPRESSION_KEEP_LAST": 2,
        "ENABLE_HISTORY_COMPRESSION_ON_LIMIT": True,
        "MEMORY_SUMMARY_CANDIDATES_ENABLED": True,
    }

    @staticmethod
    def _messages():
        return [
            {"role": "user", "content": f"m{i}", "_history_row_id": 500 + i}
            for i in range(6)
        ]

    def test_history_cleared_during_llm_call_discards_the_summary(self):
        controller = _make_controller(self._SETTINGS)
        memory = _RecordingMemory()
        character = _StubCharacter(memory_system=memory)
        messages = self._messages()
        services().register(
            GenerationService,
            _StubGenerationService('[{"priority": "high", "content": "секрет"}]'),
            replace=True,
        )

        def _slow_compress(*_a, **_k):
            # ровно то, что происходит при «очистить чат» во время сжатия
            character.clear_history()
            return "сводка стёртого диалога"

        controller._compress_history_singleflight = _slow_compress

        controller._process_history_compression(
            character, messages, effective_limit=4, history_summary="", summary_cut=0,
        )

        self.assertEqual(character.vars, {})
        self.assertEqual(memory.added, [], "факты из стёртой истории не должны попасть в память")

    def test_normal_compression_still_writes_summary_and_anchor(self):
        controller = _make_controller(
            {**self._SETTINGS, "MEMORY_SUMMARY_CANDIDATES_ENABLED": False}
        )
        character = _StubCharacter()
        messages = self._messages()
        controller._compress_history_singleflight = lambda *_a, **_k: "chunk-summary"

        controller._process_history_compression(
            character, messages, effective_limit=4, history_summary="", summary_cut=0,
        )

        self.assertEqual(character.vars[HistoryController._SUMMARY_ANCHOR_VAR], 503)
        self.assertEqual(character.vars[HistoryController._SUMMARY_COUNT_VAR], 4)
        self.assertEqual(controller._summary_cut_index(character, messages), 4)

    def test_memory_candidates_are_dropped_when_epoch_changed(self):
        controller = _make_controller(self._SETTINGS)
        memory = _RecordingMemory()
        character = _StubCharacter(memory_system=memory)
        epoch = character.history_epoch
        stub = _StubGenerationService('[{"priority": "high", "content": "секрет"}]')
        services().register(GenerationService, stub, replace=True)

        # Историю чистят, пока модель выделяет факты.
        character.clear_history()

        controller._extract_memory_candidates(
            character,
            [{"role": "user", "content": "секрет"}],
            epoch=epoch,
        )

        self.assertEqual(len(stub.calls), 1, "проверка эпохи должна быть ПОСЛЕ вызова модели")
        self.assertEqual(memory.added, [])

    def test_memory_candidates_are_stored_when_history_is_intact(self):
        controller = _make_controller(self._SETTINGS)
        memory = _RecordingMemory()
        character = _StubCharacter(memory_system=memory)
        stub = _StubGenerationService('[{"priority": "high", "content": "секрет"}]')
        services().register(GenerationService, stub, replace=True)

        controller._extract_memory_candidates(
            character,
            [{"role": "user", "content": "секрет"}],
            epoch=character.history_epoch,
        )

        self.assertEqual(memory.added, [("high", "секрет")])


class MemoryWriteEpochTests(unittest.TestCase):
    """Проверка эпохи и запись в память — один шаг, а не два.

    Одной проверки на всю пачку мало: очистка чата приходит и в середине цикла,
    и тогда факт из стёртого диалога записывается уже после clear_memories().
    """

    _SETTINGS = {"MEMORY_SUMMARY_CANDIDATES_ENABLED": True}

    def test_clear_between_candidates_stops_further_writes(self):
        controller = _make_controller(self._SETTINGS)

        def _clear_after_first(mem: _RecordingMemory) -> None:
            if mem.attempts == 1:
                character.clear_history()

        memory = _RecordingMemory(on_add=_clear_after_first)
        character = _StubCharacter(memory_system=memory)
        stub = _StubGenerationService(
            '[{"priority": "high", "content": "первый"},'
            ' {"priority": "high", "content": "второй"},'
            ' {"priority": "high", "content": "третий"}]'
        )
        services().register(GenerationService, stub, replace=True)

        controller._extract_memory_candidates(
            character,
            [{"role": "user", "content": "диалог"}],
            epoch=character.history_epoch,
        )

        self.assertEqual(memory.clears, 1)
        self.assertEqual(
            memory.attempts, 1, "после сброса записи не должны даже пытаться пройти"
        )
        self.assertEqual(memory.added, [], "в памяти не должно остаться ничего из стёртого чата")

    def test_add_memory_for_epoch_refuses_stale_epoch(self):
        controller = _make_controller()
        memory = _RecordingMemory()
        character = _StubCharacter(memory_system=memory)
        epoch = character.history_epoch
        character.clear_history()

        written = controller._add_memory_for_epoch(
            character, epoch, content="секрет", priority="high"
        )

        self.assertFalse(written)
        self.assertEqual(memory.attempts, 0)

    def test_legacy_memory_target_does_not_leave_stale_summary(self):
        """В режиме target=memory сводка уходила в память до проверки эпохи."""
        controller = _make_controller()
        memory = _RecordingMemory()
        character = _StubCharacter(memory_system=memory)
        epoch = character.history_epoch
        character.clear_history()

        summary, count = controller._apply_compression_result(
            character,
            output_target="memory",
            compressed_summary="сводка стёртого диалога",
            previous_summary="",
            summary_count=0,
            compressed_count=4,
            epoch=epoch,
            anchor_id=503,
        )

        self.assertEqual(memory.attempts, 0, "сводка не должна попасть в память после сброса")
        self.assertEqual((summary, count), ("", 0))
        self.assertEqual(character.vars, {})

    def test_legacy_memory_target_writes_summary_when_history_is_intact(self):
        controller = _make_controller()
        memory = _RecordingMemory()
        character = _StubCharacter(memory_system=memory)

        summary, count = controller._apply_compression_result(
            character,
            output_target="memory",
            compressed_summary="сводка",
            previous_summary="",
            summary_count=0,
            compressed_count=4,
            epoch=character.history_epoch,
            anchor_id=503,
        )

        self.assertEqual(memory.attempts, 1)
        self.assertEqual(count, 4)
        self.assertEqual(character.vars[HistoryController._SUMMARY_ANCHOR_VAR], 503)


class HistoryResetHookTests(unittest.TestCase):
    def test_on_history_reset_cancels_deferred_compression(self):
        controller = _make_controller()
        cancelled = []
        timer = SimpleNamespace(cancel=lambda: cancelled.append(True))
        controller._background_compression_timers["TestChar"] = timer
        controller._compression_cooldowns["TestChar"] = 123.0
        controller._messages_since_last_periodic_compression["TestChar"] = 5

        controller.on_history_reset("TestChar")

        self.assertEqual(cancelled, [True])
        self.assertNotIn("TestChar", controller._background_compression_timers)
        self.assertNotIn("TestChar", controller._compression_cooldowns)
        self.assertNotIn("TestChar", controller._messages_since_last_periodic_compression)


if __name__ == "__main__":
    unittest.main()
