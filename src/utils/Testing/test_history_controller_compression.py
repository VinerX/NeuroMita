from __future__ import annotations

import sys
import threading
import unittest
from contextlib import nullcontext
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
        controller._background_compression_timers = {}
        controller._compression_cooldowns = {}
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

    def test_prepare_for_prompt_counts_only_dialog_messages_for_tail_limit(self):
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        character = _StubCharacter(
            [
                {"role": "user", "content": "already summarized"},
                {"role": "system", "content": "older system"},
                {"role": "user", "content": "u1"},
                {"role": "event", "content": "e1"},
                {"role": "assistant", "content": "a1"},
                {"role": "system", "content": "keep system"},
                {"role": "user", "content": "u2"},
                {"role": "event", "content": "keep event"},
                {"role": "assistant", "content": "a2"},
            ]
        )
        character.vars[HistoryController._SUMMARY_TEXT_VAR] = "summary"
        character.vars[HistoryController._SUMMARY_COUNT_VAR] = 1

        result = controller._on_prepare_for_prompt(
            SimpleNamespace(
                data={
                    "character_id": "TestChar",
                    "character_ref": character,
                    "memory_limit": 2,
                    "save_missed_history": False,
                    "image_quality": {},
                }
            )
        )

        self.assertEqual(
            result["history"],
            [
                {"role": "system", "content": "keep system"},
                {"role": "user", "content": "u2"},
                {"role": "event", "content": "keep event"},
                {"role": "assistant", "content": "a2"},
            ],
        )

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

    def test_background_compression_is_delayed_and_rescheduled(self):
        controller = self._make_controller({"HISTORY_COMPRESSION_BACKGROUND_DELAY_SEC": 6})
        character = _StubCharacter([])
        created = []
        original_timer = history_controller_module.threading.Timer

        class _FakeTimer:
            def __init__(self, delay, callback, args=None, kwargs=None):
                self.delay = delay
                self.callback = callback
                self.args = args or ()
                self.kwargs = kwargs or {}
                self.daemon = False
                self.name = ""
                self.cancelled = False
                created.append(self)

            def start(self):
                return None

            def cancel(self):
                self.cancelled = True

        history_controller_module.threading.Timer = _FakeTimer
        try:
            controller._start_background_compression(character)
            controller._start_background_compression(character)
        finally:
            history_controller_module.threading.Timer = original_timer

        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].delay, 6)
        self.assertEqual(created[1].delay, 6)
        self.assertTrue(created[0].cancelled)
        self.assertIs(controller._background_compression_timers["TestChar"], created[1])

    def test_background_compression_uses_model_message_limit_setting(self):
        controller = self._make_controller({"MODEL_MESSAGE_LIMIT": 3})
        character = _StubCharacter(
            [{"role": "user", "content": f"msg-{i}"} for i in range(4)]
        )
        captured_limits = []

        controller._process_history_compression = (
            lambda _character, _history, effective_limit, **_kwargs: captured_limits.append(effective_limit)
        )

        controller._run_post_response_compression(character)

        self.assertEqual(captured_limits, [3])

    def test_compress_history_retries_retryable_failure_with_retry_after(self):
        controller = self._make_controller(
            {
                "HISTORY_COMPRESSION_MAX_ATTEMPTS": 2,
                "HISTORY_COMPRESSION_RETRY_BASE_DELAY_SEC": 1.5,
                "HISTORY_COMPRESSION_RETRY_MAX_DELAY_SEC": 10,
            }
        )
        character = _StubCharacter([])
        calls = []
        sleeps = []
        original_sleep = history_controller_module.time.sleep
        original_status = history_controller_module.response_status_kind

        def _emit_and_wait(_event_name, payload, timeout=0):
            calls.append((payload, timeout))
            if len(calls) == 1:
                return [{
                    "ok": False,
                    "text": "",
                    "error": "rate limited",
                    "details": "retry later",
                    "status_code": 429,
                    "retryable": True,
                    "retry_after_sec": 3,
                }]
            return [{"ok": True, "text": "summary"}]

        controller.event_bus = SimpleNamespace(emit_and_wait=_emit_and_wait)
        history_controller_module.time.sleep = lambda seconds: sleeps.append(seconds)
        history_controller_module.response_status_kind = lambda *_args, **_kwargs: nullcontext()
        try:
            result = controller._compress_history(character, [{"role": "user", "content": "hello"}])
        finally:
            history_controller_module.time.sleep = original_sleep
            history_controller_module.response_status_kind = original_status

        self.assertEqual(result, "summary")
        self.assertEqual(sleeps, [3])
        self.assertEqual(len(calls), 2)
        payload = calls[0][0]
        self.assertTrue(payload["return_details"])
        self.assertEqual(payload["request_options_override"]["max_attempts"], 1)
        self.assertTrue(payload["request_options_override"]["suppress_failure_events"])


if __name__ == "__main__":
    unittest.main()
