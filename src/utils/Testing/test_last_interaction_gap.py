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


class _HistoryControllerFixture(unittest.TestCase):
    """Общая заготовка контроллера: тесты ниже отличаются только настройками."""

    def _make_controller(self, settings: dict | None = None) -> HistoryController:
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
        cfg = dict(settings or {})
        controller._get_setting = lambda key, default=None: cfg.get(key, default)
        return controller

    def _prepare(self, messages):
        return self._make_controller().prepare_for_prompt(
            character=_StubCharacter(messages),
            memory_limit=10,
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )


class LastMessageTimeTests(_HistoryControllerFixture):
    """Таймстемп последнего сообщения должен переживать подготовку истории.

    Регрессия: `_format_last_interaction_line` читала время из уже
    санитизированной истории (там строго role/content), поэтому строка
    «сколько прошло» не печаталась никогда.
    """

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


class HistoryGapMarkerTests(_HistoryControllerFixture):
    """Отметки долгих пауз между репликами внутри окна истории."""

    def _sanitize(self, messages, settings=None):
        controller = self._make_controller(settings)
        return controller._sanitize_history_for_llm(_StubCharacter([]), messages)

    @staticmethod
    def _text(msg):
        content = msg["content"]
        if isinstance(content, str):
            return content
        return " ".join(str(c.get("text", "")) for c in content if isinstance(c, dict))

    def test_long_pause_is_marked_before_player_message(self):
        out = self._sanitize([
            {"role": "user", "content": "пока", "time": "01.02.2026 10:00:00"},
            {"role": "assistant", "content": "пока-пока", "time": "01.02.2026 10:00:30"},
            {"role": "user", "content": "я вернулся", "time": "03.02.2026 12:00:00"},
        ])
        self.assertTrue(self._text(out[2]).startswith("[Gap: 2 days] "))
        self.assertEqual("пока", self._text(out[0]))

    def test_short_pause_is_not_marked(self):
        out = self._sanitize([
            {"role": "assistant", "content": "ответ", "time": "01.02.2026 10:00:00"},
            {"role": "user", "content": "вопрос", "time": "01.02.2026 10:30:00"},
        ])
        self.assertEqual("вопрос", self._text(out[1]))

    def test_marker_is_not_added_to_character_messages(self):
        """Служебный тег в репликах Миты учил бы модель писать такие теги самой."""
        out = self._sanitize([
            {"role": "user", "content": "спокойной ночи", "time": "01.02.2026 23:00:00"},
            {"role": "assistant", "content": "проснулась", "time": "02.02.2026 09:00:00"},
        ])
        self.assertEqual("проснулась", self._text(out[1]))

    def test_threshold_is_configurable(self):
        messages = [
            {"role": "assistant", "content": "ответ", "time": "01.02.2026 10:00:00"},
            {"role": "user", "content": "вопрос", "time": "01.02.2026 12:00:00"},
        ]
        self.assertTrue(self._text(self._sanitize(messages)[1]).startswith("[Gap: 2 hours] "))
        out = self._sanitize(messages, {"HISTORY_TIME_GAP_MIN_MINUTES": 240})
        self.assertEqual("вопрос", self._text(out[1]))

    def test_markers_can_be_disabled(self):
        out = self._sanitize([
            {"role": "assistant", "content": "ответ", "time": "01.02.2026 10:00:00"},
            {"role": "user", "content": "вопрос", "time": "05.02.2026 10:00:00"},
        ], {"HISTORY_TIME_GAP_MARKERS": False})
        self.assertEqual("вопрос", self._text(out[1]))

    def test_marker_is_stable_across_rebuilds(self):
        """Отметка не зависит от «сейчас» — иначе каждый ход ломался бы кэш промпта."""
        messages = [
            {"role": "assistant", "content": "ответ", "time": "01.02.2026 10:00:00"},
            {"role": "user", "content": "вопрос", "time": "04.02.2026 10:00:00"},
        ]
        self.assertEqual(self._sanitize(messages), self._sanitize(messages))
        self.assertTrue(self._text(self._sanitize(messages)[1]).startswith("[Gap: 3 days] "))

    def test_marker_keeps_images_in_multimodal_message(self):
        out = self._sanitize([
            {"role": "assistant", "content": "ответ", "time": "01.02.2026 10:00:00"},
            {"role": "user", "time": "04.02.2026 10:00:00", "content": [
                {"type": "text", "text": "глянь"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
            ]},
        ])
        chunks = out[1]["content"]
        self.assertEqual("[Gap: 3 days] глянь", chunks[0]["text"])
        self.assertEqual("image_url", chunks[1]["type"])

    def test_message_without_timestamp_does_not_reset_anchor(self):
        out = self._sanitize([
            {"role": "assistant", "content": "ответ", "time": "01.02.2026 10:00:00"},
            {"role": "assistant", "content": "без времени"},
            {"role": "user", "content": "вопрос", "time": "03.02.2026 10:00:00"},
        ])
        self.assertTrue(self._text(out[2]).startswith("[Gap: 2 days] "))

    def test_speaker_prefix_and_gap_coexist(self):
        out = self._sanitize([
            {"role": "assistant", "content": "ответ", "time": "01.02.2026 10:00:00"},
            {"role": "user", "content": "привет", "sender": "Ghost", "time": "04.02.2026 10:00:00"},
        ])
        self.assertEqual("[Gap: 3 days] [Собеседник: Ghost] привет", self._text(out[1]))


class LastInteractionLineTests(unittest.TestCase):
    def _controller(self, settings: dict | None = None) -> PromptController:
        controller = PromptController.__new__(PromptController)
        cfg = dict(settings or {})
        controller._get_setting = lambda key, default=None: cfg.get(key, default)
        return controller

    def _line(self, settings: dict | None = None, **delta) -> str:
        then = datetime.datetime.now() - datetime.timedelta(**delta)
        return self._controller(settings)._format_last_interaction_line(then)

    def test_ongoing_conversation_has_no_line(self):
        self.assertEqual("", self._line(minutes=2))

    def test_minutes_gap(self):
        self.assertEqual("Time since last message: 25 minutes", self._line(minutes=25))

    def test_hours_gap(self):
        self.assertEqual("Time since last message: 3 hours", self._line(hours=3, minutes=5))

    def test_days_gap_uses_singular_for_one(self):
        self.assertEqual("Time since last message: 1 day", self._line(days=1, hours=2))

    def test_missing_timestamp_has_no_line(self):
        self.assertEqual("", self._controller()._format_last_interaction_line(None))

    def test_threshold_is_configurable(self):
        settings = {"CURRENT_STATE_GAP_MIN_MINUTES": 120}
        self.assertEqual("", self._line(settings, minutes=30))
        self.assertEqual("Time since last message: 3 hours", self._line(settings, hours=3))

    def test_zero_threshold_disables_line(self):
        self.assertEqual("", self._line({"CURRENT_STATE_GAP_MIN_MINUTES": 0}, days=5))


if __name__ == "__main__":
    unittest.main()
