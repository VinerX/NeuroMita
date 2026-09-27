from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.events import Event, EventBus
from core.executor_registry import ExecutorRegistry, Pools
from core.serial_dispatcher import SerialDispatcher
from core.trace_context import current_trace_id, trace_scope
from core.response_status import get_response_status_kind, response_status_kind
from main_logger import TraceContextFilter


class TraceContextTests(unittest.TestCase):
    def tearDown(self):
        if hasattr(self, "registry"):
            self.registry.shutdown_all(wait=True)

    def test_trace_scope_normalizes_and_restores_context(self):
        with trace_scope(" outer "):
            self.assertEqual(current_trace_id(), "outer")
            with trace_scope(""):
                self.assertEqual(current_trace_id(), "outer")
            with trace_scope("inner"):
                self.assertEqual(current_trace_id(), "inner")
            self.assertEqual(current_trace_id(), "outer")
        self.assertEqual(current_trace_id(), "")

    def test_log_filter_adds_full_and_short_trace_ids(self):
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
        with trace_scope("0123456789abcdef"):
            self.assertTrue(TraceContextFilter().filter(record))
        self.assertEqual(record.trace_id, "0123456789abcdef")
        self.assertEqual(record.trace_short, "0123456789ab")

    def test_executor_registry_propagates_only_trace_and_isolates_submissions(self):
        def read_trace():
            return current_trace_id(), get_response_status_kind()

        self.registry = ExecutorRegistry()
        with response_status_kind("compression"):
            with trace_scope("first"):
                first = self.registry.submit(Pools.IO, read_trace)
            with trace_scope("second"):
                second = self.registry.submit(Pools.IO, read_trace)
        self.assertEqual(first.result(timeout=2), ("first", ""))
        self.assertEqual(second.result(timeout=2), ("second", ""))
        self.assertEqual(current_trace_id(), "")
        self.assertEqual(get_response_status_kind(), "")

    def test_serial_dispatcher_propagates_only_trace(self):
        dispatcher = SerialDispatcher("trace-context-test", lanes=1)
        try:
            result = []
            with response_status_kind("compression"):
                with trace_scope("serial"):
                    self.assertTrue(
                        dispatcher.submit(
                            lambda: result.append(
                                (current_trace_id(), get_response_status_kind())
                            )
                        )
                    )
            self.assertTrue(dispatcher.wait_idle(timeout=2))
            self.assertEqual(result, [("serial", "")])
        finally:
            dispatcher.close()

    def test_serial_dispatcher_error_log_keeps_trace_id(self):
        dispatcher = SerialDispatcher("trace-error-test", lanes=1)
        logged_trace_ids = []

        def capture_error(*_args, **_kwargs):
            logged_trace_ids.append(current_trace_id())

        def fail():
            raise RuntimeError("dispatcher callback failed")

        try:
            with patch("core.serial_dispatcher.logger.error", side_effect=capture_error):
                with trace_scope("trace-error"):
                    self.assertTrue(dispatcher.submit(fail))
                self.assertTrue(dispatcher.wait_idle(timeout=2))
        finally:
            dispatcher.close()

        self.assertEqual(logged_trace_ids, ["trace-error"])

    def test_event_payload_trace_id_scopes_subscriber(self):
        bus = object.__new__(EventBus)
        received = []
        with trace_scope("ambient"):
            bus._safe_call(
                lambda _event: received.append(current_trace_id()),
                Event("test", {"trace_id": "event"}),
            )
        self.assertEqual(received, ["event"])
        self.assertEqual(current_trace_id(), "")

    def test_event_subscriber_error_log_keeps_event_trace_id(self):
        bus = object.__new__(EventBus)
        logged_trace_ids = []

        def capture_error(*_args, **_kwargs):
            logged_trace_ids.append(current_trace_id())

        def fail(_event):
            raise RuntimeError("subscriber failed")

        with patch("core.events.logger.error", side_effect=capture_error):
            bus._safe_call(fail, Event("test", {"trace_id": "event-error"}))

        self.assertEqual(logged_trace_ids, ["event-error"])
        self.assertEqual(current_trace_id(), "")


if __name__ == "__main__":
    unittest.main()
