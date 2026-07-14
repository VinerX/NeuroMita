from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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


class _ComboStub:
    def __init__(self):
        self.items: list[tuple[str, str]] = []
        self.current_index = -1

    def blockSignals(self, _blocked):
        return None

    def clear(self):
        self.items.clear()
        self.current_index = -1

    def addItem(self, name, item_id):
        self.items.append((str(name), str(item_id)))

    def count(self):
        return len(self.items)

    def itemData(self, index):
        return self.items[index][1]

    def currentIndex(self):
        return self.current_index

    def setCurrentIndex(self, index):
        self.current_index = index


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

    def test_tts_selector_reads_installed_models_from_canonical_catalog(self):
        controller, _bus = self._make_controller()
        catalog = SimpleNamespace(
            ready_item_ids=lambda category: (
                "edge_tts_rvc_cuda",
                "edge_tts_rvc_onnx",
                "medium",
            )
            if category == "tts"
            else ()
        )
        registry = SimpleNamespace(
            get_optional=lambda _contract: catalog,
        )

        with patch(
            "controllers.gui.voiceover_controller.services",
            return_value=registry,
        ):
            installed = controller._canonical_installed_model_ids()

        self.assertEqual(
            installed,
            {"edge_tts_rvc_cuda", "edge_tts_rvc_onnx", "medium"},
        )

    def test_tts_selector_keeps_every_ready_catalog_model_after_onnx_install(self):
        controller, _bus = self._make_controller()
        combo = _ComboStub()
        controller.view = SimpleNamespace(local_voice_combobox=combo)
        controller._model_id_to_name = {
            "edge_tts_rvc_cuda": "Edge CUDA",
            "silero_rvc_cuda": "Silero CUDA",
            "edge_tts_rvc_onnx": "Edge ONNX",
            "medium": "Fish Speech",
        }
        controller._set_local_model_selector_state = lambda **_kwargs: None
        controller._save_setting = lambda *_args: None

        selected = controller._update_local_models_combobox_from_snapshot(
            {
                "edge_tts_rvc_cuda",
                "silero_rvc_cuda",
                "edge_tts_rvc_onnx",
                "medium",
            },
            "edge_tts_rvc_onnx",
        )

        self.assertEqual(selected, "edge_tts_rvc_onnx")
        self.assertEqual(
            [item_id for _name, item_id in combo.items],
            [
                "edge_tts_rvc_cuda",
                "silero_rvc_cuda",
                "edge_tts_rvc_onnx",
                "medium",
            ],
        )
        self.assertEqual(combo.itemData(combo.currentIndex()), "edge_tts_rvc_onnx")


if __name__ == "__main__":
    unittest.main()
