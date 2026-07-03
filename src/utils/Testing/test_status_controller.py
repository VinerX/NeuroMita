from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.gui.status_controller import StatusController
from core.response_status import response_status_kind


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

    def test_started_response_shows_compression_status_in_compression_context(self):
        controller, view = self._make_controller()

        with response_status_kind("compression"):
            controller._on_started_response(SimpleNamespace(data={"character_name": "Мита"}))

        self.assertEqual(
            view.show_thinking_signal.calls,
            [{
                "text": "Сжатие истории...",
                "character_name": "Мита",
                "avatar_name": "Мита",
            }],
        )


if __name__ == "__main__":
    unittest.main()
