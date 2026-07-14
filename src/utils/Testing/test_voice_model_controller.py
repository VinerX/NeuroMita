from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from controllers.voice_model_controller import VoiceModelController
from core.events import Event
from core.installables.compatibility import evaluate_installable_compatibility
from handlers.voice_models.edge_tts_rvc_model import EdgeTTSRVCOnnxModel


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

_ONNX_FIXTURE = [
    {
        "id": "edge_tts_rvc_onnx",
        "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
        "settings": [
            {
                "key": "device",
                "type": "combobox",
                "options": {
                    "values": ["dml", "cpu"],
                    "default": "dml",
                    "values_nvidia": ["dml", "cpu"],
                    "default_nvidia": "dml",
                    "values_amd": ["dml", "cpu"],
                    "default_amd": "dml",
                    "values_intel": ["dml", "cpu"],
                    "default_intel": "dml",
                    "values_cpu": ["cpu"],
                    "default_cpu": "cpu",
                    "values_other": ["cpu"],
                    "default_other": "cpu",
                },
            }
        ],
    }
]


class _ComponentStub:
    def __init__(self, item_id: str, installed: bool, configs=None):
        self.item_id = item_id
        self._installed = installed
        self._configs = list(configs or [])

    def get_model_configs(self):
        return list(self._configs)


class _CatalogStub:
    def __init__(self, components):
        self._components = list(components)
        self.seen_contexts = []

    def list_rows(self, **_kwargs):
        return [
            {
                "metadata": {
                    "id": f"tts:{component.item_id}",
                    "item_id": component.item_id,
                    "title": next(
                        (
                            str(config.get("name") or component.item_id)
                            for config in component.get_model_configs()
                        ),
                        component.item_id,
                    ),
                    "description": "",
                    "tags": [],
                    "languages": [],
                    "backend": "none",
                }
            }
            for component in self._components
        ]

    def require_component(self, component_id):
        item_id = str(component_id).split(":", 1)[-1]
        return next(component for component in self._components if component.item_id == item_id)

    def get_row(self, component_id, *, ctx=None, **_kwargs):
        item_id = str(component_id).split(":", 1)[-1]
        backend = "onnx" if item_id.endswith("_onnx") else "cpu"
        return {
            "compatibility": evaluate_installable_compatibility(
                component_id=str(component_id),
                backend=backend,
                gpu_vendor=str((ctx or {}).get("gpu_vendor") or "CPU"),
            )
        }

    def ready_item_ids(self, category, *, ctx=None, **_kwargs):
        self.seen_contexts.append({"category": category, "ctx": dict(ctx or {})})
        return tuple(
            component.item_id for component in self._components if component._installed
        )

class VoiceModelControllerTests(unittest.TestCase):
    def _make_controller_stub(self) -> VoiceModelController:
        controller = VoiceModelController.__new__(VoiceModelController)
        controller.gpu_name = "Intel Arc"
        controller._installable_catalog = _CatalogStub([])
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

    def test_onnx_device_uses_directml_on_nvidia_without_offering_cuda(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce RTX 4060"

        adapted = controller.finalize_model_settings(
            _ONNX_FIXTURE,
            "NVIDIA",
            ["cuda:0"],
        )

        device = adapted[0]["settings"][0]["options"]
        self.assertEqual(device["values"], ["dml", "cpu"])
        self.assertEqual(device["default"], "dml")

    def test_onnx_voice_model_is_supported_but_warned_on_nvidia(self):
        controller = self._make_controller_stub()
        model = EdgeTTSRVCOnnxModel.MODEL_CONFIGS[0]

        compatibility = controller._build_model_compatibility(model, "NVIDIA")

        self.assertTrue(compatibility["supported"])
        self.assertTrue(compatibility["warning"])
        self.assertIn("CUDA", compatibility["warning"])

    def test_real_onnx_rvc_configs_resolve_pm_as_amd_default(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "AMD Radeon RX 7800 XT"

        adapted = controller.finalize_model_settings(
            EdgeTTSRVCOnnxModel.MODEL_CONFIGS,
            "AMD",
            [],
        )

        edge = next(item for item in adapted if item["id"] == "edge_tts_rvc_onnx")
        silero = next(item for item in adapted if item["id"] == "silero_rvc_onnx")
        edge_f0 = next(item for item in edge["settings"] if item["key"] == "f0method")
        silero_f0 = next(
            item
            for item in silero["settings"]
            if item["key"] == "silero_rvc_f0method"
        )

        self.assertEqual(edge_f0["options"]["default"], "pm")
        self.assertEqual(silero_f0["options"]["default"], "pm")

    def test_refresh_installed_models_uses_canonical_catalog(self):
        controller = VoiceModelController.__new__(VoiceModelController)
        controller._lock = threading.RLock()
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_cuda_devices = [0]
        controller.gpu_name = "RTX"
        controller.installed_models = set()
        controller._ctx = lambda: {"gpu_vendor": "NVIDIA"}
        controller.get_default_model_structure = lambda: (_ for _ in ()).throw(
            AssertionError("config fallback should not be used when catalog is available")
        )

        edge = _ComponentStub("edge_tts_rvc_cuda", True)
        high = _ComponentStub("high", False)
        catalog = _CatalogStub([edge, high])
        service_registry = SimpleNamespace(
            get=lambda _contract: catalog,
            get_optional=lambda _contract: catalog,
        )

        with patch("controllers.voice_model_controller.services", return_value=service_registry):
            controller.refresh_installed_models()

        self.assertEqual(controller.installed_models, {"edge_tts_rvc_cuda"})
        self.assertEqual(catalog.seen_contexts[0]["category"], "tts")
        self.assertEqual(catalog.seen_contexts[0]["ctx"]["gpu_vendor"], "NVIDIA")


    def test_default_model_structure_comes_from_main_process_installable_catalog(self):
        controller = VoiceModelController.__new__(VoiceModelController)
        component = _ComponentStub(
            "high",
            True,
            configs=[{"id": "high", "name": "F5-TTS", "settings": []}],
        )

        catalog = _CatalogStub([component])
        service_registry = SimpleNamespace(
            get=lambda _contract: catalog,
            get_optional=lambda _contract: catalog,
        )
        with patch("controllers.voice_model_controller.services", return_value=service_registry):
            result = controller.get_default_model_structure()

        self.assertEqual(
            result,
            [
                {
                    "id": "high",
                    "name": "F5-TTS",
                    "settings": [],
                    "description": "",
                    "tags": [],
                    "languages": [],
                    "backend": "none",
                }
            ],
        )

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
