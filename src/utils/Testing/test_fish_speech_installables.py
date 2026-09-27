from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from handlers.voice_models.fish_speech_model import FishSpeechInstallSpec, FishSpeechModel


class FishSpeechInstallablesTests(unittest.TestCase):
    def test_runtime_reinitializes_when_selected_device_changes(self):
        parent = SimpleNamespace(
            current_model_id="medium",
            provider="NVIDIA",
            load_model_settings=lambda _model_id: {"device": "cuda:1"},
        )
        model = FishSpeechModel(parent, "medium")
        model.initialized = True
        model.initialized_for = "medium"
        model.fish_speech_module = object()
        model.current_fish_speech = object()
        model._active_device = "cuda:0"

        with patch.object(model, "initialize", return_value=False) as initialize:
            result = asyncio.run(model.voiceover("test"))

        initialize.assert_called_once_with()
        self.assertIsNone(result)
        self.assertIsNone(model.current_fish_speech)

    def test_fish_runtime_device_settings_are_selectable_for_multi_gpu(self):
        for model_id, key in (
            ("medium", "device"),
            ("medium+", "device"),
            ("medium+low", "fsprvc_fsp_device"),
        ):
            model = FishSpeechModel._find_model_config(model_id)
            setting = next(item for item in model["settings"] if item["key"] == key)
            self.assertFalse(bool(setting.get("locked")), f"{model_id}:{key}")

    def test_cuda_rvc_settings_do_not_offer_directml(self):
        model = FishSpeechModel._find_model_config("medium+low")
        settings = {item["key"]: item for item in model["settings"]}
        device = settings["fsprvc_rvc_device"]["options"]

        self.assertEqual(device["values"], ["cuda:0", "cpu"])
        self.assertEqual(device["default"], "cuda:0")

    def test_all_modes_require_fish_checkpoint_files(self):
        expected = {
            "model.pth",
            "tokenizer.tiktoken",
            "config.json",
            "firefly-gan-vq-fsq-8x1024-21hz-generator.pth",
        }
        with tempfile.TemporaryDirectory() as base_dir, patch.dict(
            os.environ,
            {
                "NEUROMITA_BASE_DIR": base_dir,
                "NEUROMITA_CHECKPOINTS_DIR": os.path.join(base_dir, "checkpoints"),
            },
            clear=False,
        ):
            for model_id in FishSpeechInstallSpec.supported_model_ids():
                files = {
                    Path(req.path_fn({}) if req.path_fn else req.path).name
                    for req in FishSpeechInstallSpec.requirements(model_id, {})
                    if req.kind == "file"
                }
                self.assertTrue(expected.issubset(files))

    def test_medium_low_also_requires_cuda_rvc_assets(self):
        with tempfile.TemporaryDirectory() as base_dir, patch.dict(
            os.environ,
            {
                "NEUROMITA_BASE_DIR": base_dir,
                "NEUROMITA_CHECKPOINTS_DIR": os.path.join(base_dir, "checkpoints"),
            },
            clear=False,
        ):
            files = {
                Path(req.path_fn({}) if req.path_fn else req.path).name
                for req in FishSpeechInstallSpec.requirements("medium+low", {})
                if req.kind == "file"
            }

        self.assertTrue({"hubert_base.pt", "rmvpe.pt"}.issubset(files))

    def test_checkpoint_requirements_use_canonical_checkpoint_override(self):
        with (
            tempfile.TemporaryDirectory() as base_dir,
            tempfile.TemporaryDirectory() as checkpoint_dir,
            patch.dict(
                os.environ,
                {
                    "NEUROMITA_BASE_DIR": base_dir,
                    "NEUROMITA_CHECKPOINTS_DIR": checkpoint_dir,
                },
                clear=False,
            ),
        ):
            paths = {
                Path(req.path_fn({}) if req.path_fn else req.path)
                for req in FishSpeechInstallSpec.requirements("medium+", {})
                if req.kind == "file" and str(req.id).startswith("fish_asset_")
            }

        self.assertTrue(paths)
        self.assertTrue(
            all(path.is_relative_to(Path(checkpoint_dir).resolve()) for path in paths)
        )

    def test_install_plan_downloads_weights_before_compile(self):
        with tempfile.TemporaryDirectory() as base_dir, patch.dict(
            os.environ,
            {
                "NEUROMITA_BASE_DIR": base_dir,
                "NEUROMITA_CHECKPOINTS_DIR": os.path.join(base_dir, "checkpoints"),
            },
            clear=False,
        ), patch.object(FishSpeechInstallSpec, "is_installed", return_value=False):
            plan = FishSpeechInstallSpec.build_install_plan("medium+low", {})

        download_indexes = [
            index for index, action in enumerate(plan.actions) if action.type == "download_http"
        ]
        compile_index = next(
            index
            for index, action in enumerate(plan.actions)
            if action.type == "call" and "Fish Speech+" in str(action.description)
        )
        self.assertTrue(download_indexes)
        self.assertLess(max(download_indexes), compile_index)

        files = [
            item
            for action in plan.actions
            if action.type == "download_http"
            for item in action.files
        ]
        destinations = {Path(item["dest"]) for item in files}
        self.assertIn(
            Path(base_dir) / "checkpoints" / "fish-speech-1.5" / "model.pth",
            destinations,
        )
        self.assertIn(Path(base_dir) / "hubert_base.pt", destinations)

    def test_compile_call_passes_selected_device_to_subprocess_and_logs_it(self):
        from unittest.mock import MagicMock

        process = MagicMock()
        process.stdout = io.StringIO("")
        process.returncode = 0
        callbacks = SimpleNamespace(log=MagicMock(), status=MagicMock())
        services_registry = SimpleNamespace(get_optional=lambda _contract: None)
        with tempfile.TemporaryDirectory() as app_root:
            models_dir = Path(app_root) / "Models"
            models_dir.mkdir()
            (models_dir / "Mila.wav").touch()
            with (
                patch("handlers.voice_models.fish_speech_model.services", return_value=services_registry),
                patch("handlers.voice_models.fish_speech_model.base_dir", return_value=app_root),
                patch.object(FishSpeechInstallSpec, "_compile_entry_command", return_value=["python", "compile.py"]),
                patch.object(FishSpeechInstallSpec, "_script_path", return_value="compile.py"),
                patch("handlers.voice_models.fish_speech_model.subprocess.Popen", return_value=process) as popen,
            ):
                result = FishSpeechInstallSpec._compile_call()(
                    pip_installer=SimpleNamespace(),
                    callbacks=callbacks,
                    ctx={"device": "cuda:1"},
                )

        self.assertTrue(result)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--device") + 1], "cuda:1")
        self.assertIn("Fish Speech compile device: cuda:1", [call.args[0] for call in callbacks.log.call_args_list])


if __name__ == "__main__":
    unittest.main()
