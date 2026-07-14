import unittest
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from core.backends import BackendKind
from handlers.voice_models.edge_tts_rvc_model import (
    EDGE_TTS_RVC_CUDA_ID,
    EDGE_TTS_RVC_ONNX_ID,
    SILERO_RVC_CUDA_ID,
    SILERO_RVC_ONNX_ID,
    EdgeTTSRVCCudaModel,
    EdgeTTSRVCOnnxModel,
)
from handlers.voice_models.fish_speech_model import FishSpeechInstallSpec
from installables.registry_builder import build_installable_registry


class EdgeTTSRVCInstallablesTests(unittest.TestCase):
    def test_registry_exposes_edge_and_silero_backend_variants(self):
        registry = build_installable_registry()

        for item_id in (
            EDGE_TTS_RVC_CUDA_ID,
            EDGE_TTS_RVC_ONNX_ID,
            SILERO_RVC_CUDA_ID,
            SILERO_RVC_ONNX_ID,
        ):
            self.assertIsNotNone(registry.get(f"tts:{item_id}"))

    def test_backend_requirements_are_static_per_class(self):
        self.assertEqual(
            EdgeTTSRVCCudaModel.required_backend_for_model(EDGE_TTS_RVC_CUDA_ID, {"gpu_vendor": "AMD"}),
            BackendKind.CUDA,
        )
        self.assertEqual(
            EdgeTTSRVCOnnxModel.required_backend_for_model(EDGE_TTS_RVC_ONNX_ID, {"gpu_vendor": "NVIDIA"}),
            BackendKind.ONNX,
        )

    def test_install_requirements_use_explicit_rvc_package(self):
        cuda_specs = [req.spec for req in EdgeTTSRVCCudaModel.requirements(EDGE_TTS_RVC_CUDA_ID, {})]
        onnx_specs = [req.spec for req in EdgeTTSRVCOnnxModel.requirements(EDGE_TTS_RVC_ONNX_ID, {})]

        self.assertIn("tts-with-rvc", cuda_specs)
        self.assertIn("tts-with-rvc-onnx[dml]", onnx_specs)
        self.assertIn("edge-tts>=6.1.9,<8.0.0", cuda_specs)
        self.assertIn("edge-tts>=6.1.9,<8.0.0", onnx_specs)

    def test_cuda_settings_keep_full_f0_method_catalog(self):
        config = EdgeTTSRVCCudaModel._find_model_config(EDGE_TTS_RVC_CUDA_ID)
        f0_setting = next(item for item in config["settings"] if item["key"] == "f0method")

        self.assertEqual(
            f0_setting["options"]["values"],
            ["pm", "dio", "crepe", "rmvpe", "harvest", "fcpe"],
        )
        self.assertEqual(f0_setting["options"]["default"], "rmvpe")

    def test_edge_runtime_uses_schema_pitch_default_when_no_values_are_saved(self):
        class _Parent:
            current_model_id = EDGE_TTS_RVC_CUDA_ID

            @staticmethod
            def load_model_settings(_model_id):
                return {}

        model = EdgeTTSRVCCudaModel(_Parent(), EDGE_TTS_RVC_CUDA_ID)

        self.assertEqual(model._load_settings_for(EDGE_TTS_RVC_CUDA_ID)["pitch"], "6")

    def test_edge_runtime_forwards_effective_pitch_to_tts_with_rvc(self):
        output = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        output.write(b"test")
        output.close()
        captured = {}

        class _Parent:
            current_model_id = EDGE_TTS_RVC_CUDA_ID

            @staticmethod
            def load_model_settings(_model_id):
                return {}

        class _Rvc:
            def __call__(self, **kwargs):
                captured.update(kwargs)
                return output.name

        model = EdgeTTSRVCCudaModel(_Parent(), EDGE_TTS_RVC_CUDA_ID)
        model.current_tts_rvc = _Rvc()
        model._update_parent_paths = lambda _character: {"character_name": "CrazyMita"}
        model._prepare_rvc_target = lambda _character, _use_index_file: None
        model._convert_to_stereo = lambda path, _volume: path

        try:
            result = asyncio.run(model._voiceover_edge_tts_rvc("test"))
        finally:
            os.unlink(output.name)

        self.assertEqual(result, output.name)
        self.assertEqual(captured["pitch"], 6.0)

    def test_onnx_configs_include_intel_support(self):
        config = EdgeTTSRVCOnnxModel._find_model_config(EDGE_TTS_RVC_ONNX_ID)

        self.assertIn("INTEL", config["gpu_vendor"])

    def test_onnx_rvc_defaults_to_pm_on_amd(self):
        edge = EdgeTTSRVCOnnxModel._find_model_config(EDGE_TTS_RVC_ONNX_ID)
        silero = EdgeTTSRVCOnnxModel._find_model_config(SILERO_RVC_ONNX_ID)

        edge_f0 = next(item for item in edge["settings"] if item["key"] == "f0method")
        silero_f0 = next(
            item
            for item in silero["settings"]
            if item["key"] == "silero_rvc_f0method"
        )

        self.assertEqual(edge_f0["options"]["default_amd"], "pm")
        self.assertEqual(silero_f0["options"]["default_amd"], "pm")

    def test_onnx_runtime_falls_back_to_cpu_without_directml_provider(self):
        class _Parent:
            current_model_id = EDGE_TTS_RVC_ONNX_ID

            @staticmethod
            def load_model_settings(_model_id):
                return {}

        model = EdgeTTSRVCOnnxModel(_Parent(), EDGE_TTS_RVC_ONNX_ID)
        fake_ort = SimpleNamespace(
            get_available_providers=lambda: ["CPUExecutionProvider"],
        )

        with patch.dict(sys.modules, {"onnxruntime": fake_ort}):
            self.assertEqual(model._resolve_runtime_device("dml"), "cpu")

    def test_onnx_runtime_keeps_directml_when_provider_is_available(self):
        class _Parent:
            current_model_id = EDGE_TTS_RVC_ONNX_ID

            @staticmethod
            def load_model_settings(_model_id):
                return {}

        model = EdgeTTSRVCOnnxModel(_Parent(), EDGE_TTS_RVC_ONNX_ID)
        fake_ort = SimpleNamespace(
            get_available_providers=lambda: [
                "DmlExecutionProvider",
                "CPUExecutionProvider",
            ],
        )

        with patch.dict(sys.modules, {"onnxruntime": fake_ort}):
            self.assertEqual(model._resolve_runtime_device("dml"), "dml")

    def test_onnx_runtime_import_accepts_published_wheel_package_layout(self):
        fallback_module = SimpleNamespace(TTS_RVC=object())

        def fake_import(name):
            if name == "tts_with_rvc_onnx":
                raise ModuleNotFoundError(name)
            if name == "tts_with_rvc":
                return fallback_module
            raise AssertionError(name)

        with patch("handlers.voice_models.edge_tts_rvc_model.importlib.import_module", side_effect=fake_import):
            resolved = EdgeTTSRVCOnnxModel._import_rvc_class()

        self.assertIs(resolved, fallback_module.TTS_RVC)

    def test_onnx_rmvpe_predictor_is_cached_without_changing_provider(self):
        calls: list[dict] = []

        def original(method, *, hop_length, sampling_rate, device, cr_threshold=0.05):
            calls.append({
                "method": method,
                "hop_length": hop_length,
                "sampling_rate": sampling_rate,
                "device": device,
                "cr_threshold": cr_threshold,
            })
            return object()

        inference_module = SimpleNamespace(get_f0_predictor=original)

        with patch(
            "handlers.voice_models.edge_tts_rvc_model.importlib.import_module",
            return_value=inference_module,
        ):
            EdgeTTSRVCOnnxModel._configure_imported_rvc_module(
                "tts_with_rvc",
                SimpleNamespace(),
            )

        first = inference_module.get_f0_predictor(
            "rmvpe",
            hop_length=400,
            sampling_rate=40000,
            device="dml",
            cr_threshold=0.05,
        )
        second = inference_module.get_f0_predictor(
            "rmvpe",
            hop_length=400,
            sampling_rate=40000,
            device="dml",
            cr_threshold=0.05,
        )

        self.assertIs(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["device"], "dml")


    def test_fish_speech_plus_uninstall_removes_runtime_packages(self):
        plan = FishSpeechInstallSpec.build_uninstall_plan("medium+", {})
        calls: list[list[str]] = []

        class _PipInstaller:
            def uninstall_packages(self, packages, description):
                calls.append(list(packages))
                return True

        ok = plan.actions[0].fn(pip_installer=_PipInstaller(), callbacks=None, ctx={})

        self.assertTrue(ok)
        self.assertEqual(calls, [["fish-speech-lib", "triton-windows"]])

    def test_fish_speech_rvc_uninstall_removes_all_required_packages(self):
        plan = FishSpeechInstallSpec.build_uninstall_plan("medium+low", {})
        calls: list[list[str]] = []

        class _PipInstaller:
            def uninstall_packages(self, packages, description):
                calls.append(list(packages))
                return True

        ok = plan.actions[0].fn(pip_installer=_PipInstaller(), callbacks=None, ctx={})

        self.assertTrue(ok)
        self.assertEqual(calls, [["fish-speech-lib", "triton-windows", "tts-with-rvc"]])

    def test_hubert_candidates_include_runtime_locations(self):
        class _Parent:
            current_model_id = EDGE_TTS_RVC_CUDA_ID

            @staticmethod
            def load_model_settings(_model_id):
                return {}

        model = EdgeTTSRVCCudaModel(_Parent(), EDGE_TTS_RVC_CUDA_ID)
        with patch("os.getcwd", return_value=r"C:\RuntimeRoot"), patch.dict(
            "os.environ",
            {"NEUROMITA_MODELS_DIR": r"C:\RuntimeRoot\Models", "NEUROMITA_LIB_DIR": r"C:\RuntimeRoot\Lib"},
            clear=False,
        ):
            candidates = model._hubert_candidate_paths()

        self.assertIn(str(Path(r"C:\RuntimeRoot\hubert_base.pt")), candidates)
        self.assertIn(str(Path(r"C:\RuntimeRoot\Models\hubert_base.pt")), candidates)
        self.assertIn(str(Path(r"C:\RuntimeRoot\Lib\hubert_base.pt")), candidates)


if __name__ == "__main__":
    unittest.main()
