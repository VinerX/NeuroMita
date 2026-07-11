from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.gui.voiceover_controller import VoiceoverGuiController
from core.events import Events


class _EventBusStub:
    def __init__(self):
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_name, payload):
        self.emitted.append((event_name, payload))


class VoiceoverGuiControllerTests(unittest.TestCase):
    def _make_controller(self) -> tuple[VoiceoverGuiController, _EventBusStub]:
        bus = _EventBusStub()
        controller = VoiceoverGuiController.__new__(VoiceoverGuiController)
        controller.event_bus = bus
        controller.view = SimpleNamespace()
        controller._tg_connecting = False
        controller._tg_connected = False
        controller._loading_model_id = None
        controller._effective_use_voice = lambda: True
        controller._effective_method = lambda: "Local"
        controller._current_model_id_from_settings = lambda: "high"
        controller._check_installed = lambda _model_id: True
        controller._check_initialized = lambda _model_id: False
        controller._installed_models_cache = {"high"}
        controller._initialized_models_cache = {"high"}
        return controller, bus

    def test_emit_voice_icon_state_treats_installed_local_tts_as_ready(self):
        controller, bus = self._make_controller()

        controller._emit_voice_icon_state()

        self.assertEqual(len(bus.emitted), 1)
        event_name, payload = bus.emitted[0]
        self.assertEqual(event_name, Events.GUI.SET_SETTINGS_ICON_INDICATOR)
        self.assertEqual(payload.get("category"), "voice")
        self.assertEqual(payload.get("state"), "green")


if __name__ == "__main__":
    unittest.main()
