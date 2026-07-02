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
from controllers import history_controller as history_controller_module


class _StubHistoryManager:
    def __init__(self, messages):
        self._messages = list(messages)
        self.saved_missed = []

    def load_history(self):
        return {"messages": list(self._messages)}

    def save_missed_history(self, messages):
        self.saved_missed.extend(messages)


class _StubCharacter:
    def __init__(self, messages, *, char_id="TestChar", memory_system=None):
        self.char_id = char_id
        self.name = char_id
        self.history_manager = _StubHistoryManager(messages)
        self.memory_system = memory_system
        self.vars = {}

    def get_variable(self, key, default=None):
        return self.vars.get(key, default)

    def set_variable(self, key, value):
        self.vars[key] = value

    def flush_variables(self):
        return None


class HistoryControllerCompressionTests(unittest.TestCase):
    def _make_controller(self, settings: dict | None = None) -> HistoryController:
        controller = HistoryController.__new__(HistoryController)
        controller.event_bus = SimpleNamespace()
        controller._messages_since_last_periodic_compression = {}
        controller._compression_guard = threading.Lock()
        controller._compression_inflight = set()
        controller._background_compression_inflight = set()
        cfg = dict(settings or {})
        controller._get_setting = lambda key, default=None: cfg.get(key, default)
        controller._sanitize_history_for_llm = lambda _character, messages: messages
        controller._apply_history_image_quality_reduction = lambda messages, _cfg: messages
        return controller

    def test_prepare_for_prompt_keeps_full_context_until_summary_exists(self):
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "memory"})
        character = _StubCharacter(
            [{"role": "user", "content": f"msg-{i}"} for i in range(5)]
        )
        controller._process_history_compression = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected sync compression")
        )

        result = controller._on_prepare_for_prompt(
            SimpleNamespace(
                data={
                    "character_id": "TestChar",
                    "character_ref": character,
                    "memory_limit": 3,
                    "save_missed_history": False,
                    "image_quality": {},
                }
            )
        )

        self.assertEqual(len(result["history"]), 5)

    def test_prepare_for_prompt_uses_emergency_sync_compression_when_far_over_limit(self):
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        full_history = [{"role": "user", "content": f"msg-{i}"} for i in range(14)]
        character = _StubCharacter(
            full_history
        )
        controller._process_history_compression = lambda *_args, **_kwargs: (
            list(full_history),
            "summary",
            11,
        )

        result = controller._on_prepare_for_prompt(
            SimpleNamespace(
                data={
                    "character_id": "TestChar",
                    "character_ref": character,
                    "memory_limit": 3,
                    "save_missed_history": False,
                    "image_quality": {},
                }
            )
        )

        self.assertEqual(len(result["history"]), 3)
        self.assertEqual(result["history_summary"], "summary")

    def test_apply_compression_result_does_not_advance_memory_mode_without_memory_system(self):
        controller = self._make_controller()
        character = _StubCharacter([], memory_system=None)

        summary, count = controller._apply_compression_result(
            character,
            output_target="memory",
            compressed_summary="compressed",
            previous_summary="",
            summary_count=4,
            compressed_count=3,
            history_len=20,
        )

        self.assertEqual(summary, "")
        self.assertEqual(count, 4)

    def test_message_completed_starts_background_compression(self):
        controller = self._make_controller()
        character = _StubCharacter([])
        called = []
        controller._start_background_compression = lambda ch: called.append(ch.char_id)

        controller._on_message_completed(
            SimpleNamespace(data={"character_id": "TestChar", "character_ref": character})
        )

        self.assertEqual(called, ["TestChar"])

    def test_background_compression_launch_is_singleflight_per_character(self):
        controller = self._make_controller()
        character = _StubCharacter([])
        started = []
        original_thread = history_controller_module.threading.Thread

        class _FakeThread:
            def __init__(self, *, target, args, daemon, name):
                self._target = target
                self._args = args
                self.daemon = daemon
                self.name = name

            def start(self):
                started.append((self.name, self._args))

        history_controller_module.threading.Thread = _FakeThread
        try:
            controller._start_background_compression(character)
            controller._start_background_compression(character)
        finally:
            history_controller_module.threading.Thread = original_thread

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0], "history-compress-TestChar")


if __name__ == "__main__":
    unittest.main()
