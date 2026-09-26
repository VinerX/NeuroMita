from __future__ import annotations

import threading
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from controllers.voice_model_controller import VoiceModelController
from core.events import Event
from core.installables.compatibility import evaluate_installable_compatibility
from handlers.voice_models.edge_tts_rvc_model import EdgeTTSRVCOnnxModel
from handlers.voice_models.f5_tts_model import F5TTSModel
from handlers.voice_models.fish_speech_model import FishSpeechModel


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
    def __init__(self, components, *, gpu_vendor="INTEL"):
        self._components = list(components)
        self.gpu_vendor = gpu_vendor
        self.seen_contexts = []

    def list_rows(self, **kwargs):
        self.seen_contexts.append(dict(kwargs))
        rows = [
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
        if kwargs.get("include_status"):
            for row, component in zip(rows, self._components):
                row["status"] = {
                    "installed": bool(component._installed),
                    "ready": bool(component._installed),
                }
        return rows

    def require_component(self, component_id):
        item_id = str(component_id).split(":", 1)[-1]
        return next(component for component in self._components if component.item_id == item_id)

    def get_row(self, component_id, **_kwargs):
        item_id = str(component_id).split(":", 1)[-1]
        backend = "onnx" if item_id.endswith("_onnx") else "cpu"
        component = next(
            (item for item in self._components if item.item_id == item_id),
            None,
        )
        config = next(iter(component.get_model_configs()), {}) if component is not None else {}
        compatibility = config.get("compatibility")
        if compatibility is None and item_id in {"high", "high+low"}:
            compatibility = F5TTSModel._find_model_config(item_id).get("compatibility")
        return {
            "compatibility": evaluate_installable_compatibility(
                backend=backend,
                hardware={"vendor": self.gpu_vendor},
                compatibility=compatibility,
            )
        }

    def ready_item_ids(self, category, **_kwargs):
        self.seen_contexts.append({"category": category})
        return tuple(
            component.item_id for component in self._components if component._installed
        )

class VoiceModelControllerTests(unittest.TestCase):
    def _make_controller_stub(self) -> VoiceModelController:
        controller = VoiceModelController.__new__(VoiceModelController)
        controller.gpu_name = "Intel Arc"
        controller.detected_gpu_vendor = "INTEL"
        controller.detected_compute_capability = None
        controller._installable_catalog = _CatalogStub([])
        return controller

    def test_settings_save_rejects_unavailable_device(self):
        controller = self._make_controller_stub()
        controller.local_voice_models = [{
            "id": "edge_tts_rvc_onnx",
            "settings": [{"key": "device", "type": "combobox", "options": {
                "values": ["dml", "dml:0", "cpu"],
            }}],
        }]
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "voice_model_settings.json"
            controller.settings_values_file = str(path)
            result = controller.save_settings_values({
                "edge_tts_rvc_onnx": {"device": "dml:9"},
            })
            self.assertFalse(path.exists())

        self.assertIn("device", result["errors"]["edge_tts_rvc_onnx"])

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

    def test_all_real_f5_variants_expose_nonempty_device_choices(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce RTX 4060"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 89

        adapted = controller.finalize_model_settings(
            F5TTSModel.MODEL_CONFIGS,
            "NVIDIA",
            ["cuda:0"],
        )

        models = {model["id"]: model for model in adapted}
        for model_id in ("high", "high_clf5"):
            settings = {item["key"]: item for item in models[model_id]["settings"]}
            device = settings["device"]["options"]
            self.assertEqual(device["values"], ["cuda:0", "cpu"])
            self.assertEqual(device["default"], "cuda:0")

        for model_id in ("high+low", "high_clf5+low"):
            settings = {item["key"]: item for item in models[model_id]["settings"]}
            f5_device = settings["f5rvc_f5_device"]["options"]
            rvc_device = settings["f5rvc_rvc_device"]["options"]
            self.assertEqual(f5_device["values"], ["cuda:0", "cpu"])
            self.assertEqual(f5_device["default"], "cuda:0")
            self.assertIn("cuda:0", rvc_device["values"])
            self.assertNotIn("dml", rvc_device["values"])
            self.assertTrue(rvc_device["values"])

    def test_raw_f5_device_schemas_have_safe_fallback_choices(self):
        for model in F5TTSModel.MODEL_CONFIGS:
            settings = {item["key"]: item for item in model["settings"]}
            device_keys = (
                ("f5rvc_f5_device", "f5rvc_rvc_device")
                if "+low" in model["id"]
                else ("device",)
            )
            for key in device_keys:
                options = settings[key]["options"]
                self.assertTrue(options["values"])
                self.assertIn(options["default"], options["values"])

    def test_f5_keeps_generic_cuda_choice_before_device_enumeration(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce RTX 4060"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 89

        adapted = controller.finalize_model_settings(
            F5TTSModel.MODEL_CONFIGS,
            "NVIDIA",
            [],
        )

        models = {model["id"]: model for model in adapted}
        for model_id in ("high", "high_clf5"):
            settings = {item["key"]: item for item in models[model_id]["settings"]}
            self.assertEqual(
                settings["device"]["options"]["values"],
                ["cuda", "cpu"],
            )

    def test_onnx_device_uses_directml_on_nvidia_without_offering_cuda(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce RTX 4060"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 89

        adapted = controller.finalize_model_settings(
            _ONNX_FIXTURE,
            "NVIDIA",
            ["cuda:0"],
        )

        device = adapted[0]["settings"][0]["options"]
        self.assertEqual(device["values"], ["dml", "cpu"])
        self.assertEqual(device["default"], "dml")

    def test_gtx_1660_ti_forces_and_locks_rvc_half_precision_off(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce GTX 1660 Ti"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 75

        adapted = controller.finalize_model_settings(
            _F5_FIXTURE,
            "NVIDIA",
            ["cuda:0"],
        )

        model = next(item for item in adapted if item["id"] == "high+low")
        half = next(item for item in model["settings"] if item["key"] == "f5rvc_is_half")
        self.assertEqual(half["options"]["default"], "False")
        self.assertTrue(half["locked"])

    def test_rtx_2060_keeps_rvc_half_precision_available_on_sm75(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce RTX 2060"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 75

        adapted = controller.finalize_model_settings(
            _F5_FIXTURE,
            "NVIDIA",
            ["cuda:0"],
        )

        model = next(item for item in adapted if item["id"] == "high+low")
        half = next(item for item in model["settings"] if item["key"] == "f5rvc_is_half")
        self.assertEqual(half["options"]["default"], "True")
        self.assertFalse(bool(half.get("locked")))

    def test_gtx_1660_ti_sanitizes_persisted_half_true_to_false(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce GTX 1660 Ti"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 75

        with TemporaryDirectory() as temp_dir:
            controller.settings_values_file = str(Path(temp_dir) / "voice_model_settings.json")
            with patch.object(controller, "load_settings"):
                result = controller.save_settings_values(
                    {"silero_rvc_cuda": {"silero_rvc_is_half": "True"}}
                )

            saved = json.loads(Path(controller.settings_values_file).read_text(encoding="utf-8"))

        self.assertEqual(saved["silero_rvc_cuda"]["silero_rvc_is_half"], "False")
        self.assertEqual(result["changed"], 1)

    def test_multi_gpu_cuda_choices_include_names_and_keep_raw_ids(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce GTX 1660 Ti"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 75
        controller.detected_cuda_devices = ["cuda:0", "cuda:1"]
        controller.detected_cuda_device_records = [
            {"ordinal": 0, "name": "NVIDIA GeForce GTX 1660 Ti", "compute_major": 7, "compute_minor": 5},
            {"ordinal": 1, "name": "NVIDIA GeForce RTX 5080", "compute_major": 12, "compute_minor": 0},
        ]

        adapted = controller.finalize_model_settings(
            _F5_FIXTURE, "NVIDIA", controller.detected_cuda_devices
        )
        model = next(item for item in adapted if item["id"] == "high+low")
        settings = {item["key"]: item for item in model["settings"]}
        device_options = settings["f5rvc_rvc_device"]["options"]
        half = settings["f5rvc_is_half"]

        self.assertEqual(device_options["values"], ["cuda:0", "cuda:1", "dml", "cpu"])
        self.assertEqual(
            device_options["display_labels"],
            {
                "cuda:0": "cuda:0 (NVIDIA GeForce GTX 1660 Ti)",
                "cuda:1": "cuda:1 (NVIDIA GeForce RTX 5080)",
            },
        )
        # Default device is cuda:0 (1660 Ti), therefore half defaults off, but
        # the field remains editable because cuda:1 supports the FP16 policy.
        self.assertEqual(half["options"]["default"], "False")
        self.assertFalse(bool(half.get("locked")))

    def test_fish_device_choices_expand_to_all_detected_cuda_devices(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce RTX 4060"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 89
        controller.detected_cuda_devices = ["cuda:0", "cuda:1"]
        controller.detected_cuda_device_records = [
            {"ordinal": 0, "name": "NVIDIA GeForce RTX 4060", "compute_major": 8, "compute_minor": 9},
            {"ordinal": 1, "name": "NVIDIA GeForce RTX 5080", "compute_major": 12, "compute_minor": 0},
        ]

        adapted = controller.finalize_model_settings(
            FishSpeechModel.MODEL_CONFIGS,
            "NVIDIA",
            controller.detected_cuda_devices,
        )

        medium_plus = next(item for item in adapted if item["id"] == "medium+")
        device = next(item for item in medium_plus["settings"] if item["key"] == "device")
        self.assertEqual(device["options"]["values"], ["cuda:0", "cuda:1"])
        self.assertEqual(
            device["options"]["display_labels"]["cuda:1"],
            "cuda:1 (NVIDIA GeForce RTX 5080)",
        )
        self.assertFalse(bool(device.get("locked")))

    def test_half_sanitization_uses_selected_cuda_device_on_multi_gpu(self):
        controller = self._make_controller_stub()
        controller.gpu_name = "NVIDIA GeForce GTX 1660 Ti"
        controller.detected_gpu_vendor = "NVIDIA"
        controller.detected_compute_capability = 75
        controller.detected_cuda_devices = ["cuda:0", "cuda:1"]
        controller.detected_cuda_device_records = [
            {"ordinal": 0, "name": "NVIDIA GeForce GTX 1660 Ti", "compute_major": 7, "compute_minor": 5},
            {"ordinal": 1, "name": "NVIDIA GeForce RTX 5080", "compute_major": 12, "compute_minor": 0},
        ]

        with TemporaryDirectory() as temp_dir:
            controller.settings_values_file = str(Path(temp_dir) / "voice_model_settings.json")
            with patch.object(controller, "load_settings"):
                controller.save_settings_values({
                    "silero_rvc_cuda": {
                        "silero_rvc_device": "cuda:0",
                        "silero_rvc_is_half": "True",
                    },
                    "edge_tts_rvc_cuda": {
                        "device": "cuda:1",
                        "is_half": "True",
                    },
                })
            saved = json.loads(Path(controller.settings_values_file).read_text(encoding="utf-8"))

        self.assertEqual(saved["silero_rvc_cuda"]["silero_rvc_is_half"], "False")
        self.assertEqual(saved["edge_tts_rvc_cuda"]["is_half"], "True")

    def test_fish_compile_uses_selected_cuda_device(self):
        controller = VoiceModelController.__new__(VoiceModelController)
        controller._lock = threading.RLock()
        controller.local_voice_models = [
            {
                "id": "medium+",
                "settings": [
                    {
                        "key": "device",
                        "options": {"default": "cuda:1"},
                    }
                ],
            }
        ]
        controller.event_bus = SimpleNamespace(emit=lambda *_args, **_kwargs: None)
        seen = {}

        class _Operations:
            @staticmethod
            def initialize(payload):
                seen.update(payload)
                return SimpleNamespace(accepted=True, error="")

        registry = SimpleNamespace(get_optional=lambda _contract: _Operations())
        with patch("controllers.voice_model_controller.services", return_value=registry):
            self.assertTrue(controller.start_compile("medium+", with_ui=False))

        self.assertEqual(seen["device"], "cuda:1")

    def test_onnx_voice_model_is_supported_but_warned_on_nvidia(self):
        controller = self._make_controller_stub()
        model = EdgeTTSRVCOnnxModel.MODEL_CONFIGS[0]

        controller._installable_catalog.gpu_vendor = "NVIDIA"
        compatibility = controller._build_model_compatibility(model)

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
        self.assertTrue(catalog.seen_contexts[0]["include_status"])

    def test_refresh_installed_models_preserves_known_state_for_transient_probe(self):
        controller = VoiceModelController.__new__(VoiceModelController)
        controller._lock = threading.RLock()
        controller.installed_models = {"medium+"}
        catalog = SimpleNamespace(
            list_rows=lambda **_kwargs: [
                {
                    "metadata": {"item_id": "medium+"},
                    "status": {
                        "ready": False,
                        "probe_state": "timeout",
                        "details": {"transient": True},
                    },
                }
            ]
        )
        service_registry = SimpleNamespace(get=lambda _contract: catalog)

        with patch("controllers.voice_model_controller.services", return_value=service_registry):
            controller.refresh_installed_models()

        self.assertEqual(controller.installed_models, {"medium+"})


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

    def test_completed_tts_probe_updates_snapshot_and_requests_ui_refresh(self):
        emitted = []
        controller = VoiceModelController.__new__(VoiceModelController)
        controller._lock = threading.RLock()
        controller.installed_models = set()
        controller.event_bus = SimpleNamespace(
            emit=lambda name, data=None: emitted.append((name, data))
        )

        controller._on_component_status(
            Event(
                name="install_component_status",
                data={
                    "component_id": "tts:medium+",
                    "status": {"ready": True, "installed": True},
                },
            )
        )

        self.assertEqual(controller.installed_models, {"medium+"})
        self.assertEqual(emitted[0][0], "refresh_voice_model_panels")
        self.assertEqual(emitted[0][1]["model_id"], "medium+")

        controller._on_component_status(
            Event(
                name="install_component_status",
                data={
                    "component_id": "tts:medium+",
                    "status": {"ready": False, "installed": False},
                },
            )
        )

        self.assertEqual(controller.installed_models, set())


if __name__ == "__main__":
    unittest.main()
