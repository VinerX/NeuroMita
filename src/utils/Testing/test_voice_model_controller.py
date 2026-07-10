from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from controllers.voice_model_controller import VoiceModelController
from core.events import Event


_F5_FIXTURE = [
    {
        "id": "high",
        "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
        "settings": [],
    },
    {
        "id": "high+low",
        "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
        "settings": [
            {
                "key": "f5rvc_f5_device",
                "type": "combobox",
                "options": {
                    "values_nvidia": ["cuda", "cpu"],
                    "default_nvidia": "cuda",
                    "values_amd": ["cpu"],
                    "default_amd": "cpu",
                    "values_intel": ["cpu"],
                    "default_intel": "cpu",
                    "values_other": ["cpu"],
                    "default_other": "cpu",
                },
            },
            {
                "key": "f5rvc_rvc_device",
                "type": "combobox",
                "options": {
                    "values_nvidia": ["dml", "cuda:0", "cpu"],
                    "default_nvidia": "cuda:0",
                    "values_amd": ["dml", "cpu"],
                    "default_amd": "dml",
                    "values_intel": ["dml", "cpu"],
                    "default_intel": "dml",
                    "values_other": ["cpu", "dml"],
                    "default_other": "cpu",
                },
            },
            {
                "key": "f5rvc_is_half",
                "type": "combobox",
                "options": {"values": ["True", "False"], "default": "True"},
            },
        ],
    },
]


class _Status:
    def __init__(self, installed: bool):
        self.installed = installed


class _ComponentStub:
    def __init__(self, item_id: str, installed: bool):
        self.item_id = item_id
        self._installed = installed

    def status(self, ctx=None):
        return _Status(self._installed)


class _RegistryStub:
    def __init__(self, components):
        self._components = list(components)

    def by_category(self, category):
        return list(self._components)


class VoiceModelControllerTests(unittest.TestCase):
    def _make_controller_stub(self) -> VoiceModelController:
        controller = VoiceModelController.__new__(VoiceModelController)
        controller.gpu_name = "Intel Arc"
        return controller

    def test_f5_high_low_defaults_are_adapted_for_intel(self):
        controller = self._make_controller_stub()

        adapted = controller.finalize_model_settings(_F5_FIXTURE, "INTEL", [])

        model = next(item for item in adapted if item["id"] == "high+low")
        settings = {item["key"]: item for item in model["settings"]}

        self.assertTrue(model["compat_supported"])
        self.assertTrue(model["compat_warning"])

        self.assertEqual(settings["f5rvc_f5_device"]["options"]["values"], ["cpu"])
        self.assertEqual(settings["f5rvc_f5_device"]["options"]["default"], "cpu")
        self.assertTrue(settings["f5rvc_f5_device"]["locked"])

        self.assertEqual(settings["f5rvc_rvc_device"]["options"]["values"], ["dml", "cpu"])
        self.assertEqual(settings["f5rvc_rvc_device"]["options"]["default"], "dml")

        self.assertEqual(settings["f5rvc_is_half"]["options"]["default"], "False")
        self.assertTrue(settings["f5rvc_is_half"]["locked"])

    def test_f5_high_is_marked_supported_on_intel(self):
        controller = self._make_controller_stub()

        adapted = controller.finalize_model_settings(_F5_FIXTURE, "INTEL", [])

        model = next(item for item in adapted if item["id"] == "high")
        self.assertTrue(model["compat_supported"])
        self.assertIn("INTEL", model["gpu_vendor"])
        self.assertTrue(model["compat_warning"])

    def test_refresh_installed_models_uses_installable_registry(self):
        controller = VoiceModelController.__new__(VoiceModelController)
        controller._lock = threading.RLock()
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_cuda_devices = [0]
        controller.gpu_name = "RTX"
        controller.installed_models = set()
        controller._ctx = lambda: {"gpu_vendor": "NVIDIA"}
        controller.get_default_model_structure = lambda: (_ for _ in ()).throw(
            AssertionError("config fallback should not be used when registry is available")
        )

        registry = _RegistryStub(
            [
                _ComponentStub("edge_tts_rvc_cuda", True),
                _ComponentStub("high", False),
            ]
        )

        with patch("installables.get_installable_registry", return_value=registry):
            controller.refresh_installed_models()

        self.assertEqual(controller.installed_models, {"edge_tts_rvc_cuda"})

    def test_handle_get_installed_models_returns_snapshot_without_rescan(self):
        controller = VoiceModelController.__new__(VoiceModelController)
        controller._lock = threading.RLock()
        controller.installed_models = set()
        refresh_calls = []
        controller.refresh_installed_models = lambda: refresh_calls.append(True)

        result = controller._handle_get_installed_models(Event(name="get_installed_models"))

        self.assertEqual(result, set())
        self.assertEqual(refresh_calls, [])

    def test_installed_models_snapshot_is_detached(self):
        controller = VoiceModelController.__new__(VoiceModelController)
        controller._lock = threading.RLock()
        controller.installed_models = {"high"}

        result = controller.installed_models_snapshot()
        result.add("other")

        self.assertEqual(controller.installed_models, {"high"})


if __name__ == "__main__":
    unittest.main()
