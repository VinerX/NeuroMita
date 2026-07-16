from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.gui.status_controller import StatusController


class _SignalStub:
    def __init__(self):
        self.calls = []

    def emit(self, payload=None):
        self.calls.append(payload)


class StatusControllerTests(unittest.TestCase):
    def _make_controller(self) -> tuple[StatusController, SimpleNamespace]:
        view = SimpleNamespace(
            show_thinking_signal=_SignalStub(),
            show_error_signal=_SignalStub(),
            hide_status_signal=_SignalStub(),
            pulse_error_signal=_SignalStub(),
            update_status_signal=_SignalStub(),
            show_voicing_signal=_SignalStub(),
            hide_voicing_signal=_SignalStub(),
        )
        controller = StatusController.__new__(StatusController)
        controller.view = view
        controller.event_bus = None
        controller.main_controller = None
        controller._last_detailed_error_text = ""
        controller._last_detailed_error_ts = 0.0
        return controller, view

    def test_started_response_shows_character_thinking_by_default(self):
        controller, view = self._make_controller()

        controller._on_started_response(SimpleNamespace(data={"character_name": "Мита"}))

        self.assertEqual(view.show_thinking_signal.calls, ["Мита"])

    def test_compression_started_uses_dedicated_status_event(self):
        controller, view = self._make_controller()

        controller._on_compression_started(SimpleNamespace(data={}))

        self.assertEqual(
            view.show_thinking_signal.calls,
            [{
                "state": "compression",
                "text": "Сжатие истории...",
                "icon_names": ["fa6s.box-archive", "fa5s.archive", "fa5s.compress-alt"],
            }],
        )

    def test_show_voicing_forwards_payload(self):
        controller, view = self._make_controller()
        payload = {"character_name": "Мита", "icon_names": ["fa6s.volume-high"]}

        controller._on_show_voicing(SimpleNamespace(data=payload))

        self.assertEqual(view.show_voicing_signal.calls, [payload])

    def test_terminal_provider_error_uses_structured_message(self):
        controller, view = self._make_controller()

        controller._on_failed_response(SimpleNamespace(data={
            "error": "Generic failure",
            "provider_error": {
                "message": "Network error. Reason: write operation timed out",
                "reason": "write operation timed out",
                "retryable": True,
            },
        }))

        self.assertEqual(
            view.show_error_signal.calls,
            ["Network error. Reason: write operation timed out"],
        )

    def test_retryable_attempt_only_pulses_without_terminal_error_banner(self):
        controller, view = self._make_controller()

        controller._on_failed_response_attempt(SimpleNamespace(data={
            "attempt": 1,
            "max_attempts": 5,
            "provider_error": {
                "message": "Network error. Reason: write operation timed out",
                "reason": "write operation timed out",
                "retryable": True,
            },
        }))

        self.assertEqual(view.show_error_signal.calls, [])
        self.assertEqual(view.pulse_error_signal.calls, [None])


if __name__ == "__main__":
    unittest.main()
