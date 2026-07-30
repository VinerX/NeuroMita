from __future__ import annotations

import datetime
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.history_controller import HistoryController
from controllers.prompt_controller import PromptController


class _StubHistoryManager:
    def __init__(self, messages):
        self._messages = list(messages)

    def load_history(self):
        return {"messages": list(self._messages)}

    def save_missed_history(self, messages):
        return None


class _StubCharacter:
    def __init__(self, messages):
        self.char_id = "TestChar"
        self.name = "TestChar"
        self.history_manager = _StubHistoryManager(messages)
        self.vars = {}

    def get_variable(self, key, default=None):
        return self.vars.get(key, default)

    def set_variable(self, key, value):
        self.vars[key] = value


class LastMessageTimeTests(unittest.TestCase):
    """Таймстемп последнего сообщения должен переживать подготовку истории.

    Регрессия: `_format_last_interaction_line` читала время из уже
    санитизированной истории (там строго role/content), поэтому строка
    «сколько прошло» не печаталась никогда.
    """

    def _make_controller(self) -> HistoryController:
        controller = HistoryController.__new__(HistoryController)
        controller.event_bus = SimpleNamespace()
        controller._messages_since_last_periodic_compression = {}
        controller._compression_guard = threading.Lock()
        controller._compression_inflight = set()
        controller._background_compression_inflight = set()
        controller._background_compression_timers = {}
        controller._compression_cooldowns = {}
        controller._messages_since_last_maintenance = {}
        controller._maintenance_inflight = set()
        controller._get_setting = lambda key, default=None: default
        return controller

    def _prepare(self, messages):
        return self._make_controller().prepare_for_prompt(
            character=_StubCharacter(messages),
            memory_limit=10,
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )

    def test_last_message_time_survives_sanitization(self):
        prepared = self._prepare([
            {"role": "user", "content": "привет", "time": "01.02.2026 10:00:00"},
            {"role": "assistant", "content": "и тебе", "time": "01.02.2026 10:00:30"},
        ])

        self.assertEqual(
            prepared.last_message_at,
            datetime.datetime(2026, 2, 1, 10, 0, 30),
        )
        # сами сообщения уезжают провайдеру без лишних полей
        self.assertEqual({"role", "content"}, set(prepared.messages[-1].keys()))

    def test_iso_like_timestamp_is_understood(self):
        prepared = self._prepare([
            {"role": "user", "content": "привет", "time": "2026-02-01 10:00:00"},
        ])
        self.assertEqual(
            prepared.last_message_at,
            datetime.datetime(2026, 2, 1, 10, 0, 0),
        )

    def test_garbled_timestamp_falls_back_to_earlier_message(self):
        prepared = self._prepare([
            {"role": "user", "content": "привет", "time": "01.02.2026 10:00:00"},
            {"role": "assistant", "content": "и тебе", "time": "не время"},
        ])
        self.assertEqual(
            prepared.last_message_at,
            datetime.datetime(2026, 2, 1, 10, 0, 0),
        )

    def test_history_without_timestamps_gives_none(self):
        prepared = self._prepare([{"role": "user", "content": "привет"}])
        self.assertIsNone(prepared.last_message_at)


class LastInteractionLineTests(unittest.TestCase):
    def _line(self, **delta) -> str:
        then = datetime.datetime.now() - datetime.timedelta(**delta)
        return PromptController._format_last_interaction_line(then)

    def test_ongoing_conversation_has_no_line(self):
        self.assertEqual("", self._line(minutes=2))

    def test_minutes_gap(self):
        self.assertEqual("Time since last message: 25 minutes", self._line(minutes=25))

    def test_hours_gap(self):
        self.assertEqual("Time since last message: 3 hours", self._line(hours=3, minutes=5))

    def test_days_gap_uses_singular_for_one(self):
        self.assertEqual("Time since last message: 1 day", self._line(days=1, hours=2))

    def test_missing_timestamp_has_no_line(self):
        self.assertEqual("", PromptController._format_last_interaction_line(None))


if __name__ == "__main__":
    unittest.main()
