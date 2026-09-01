from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from handlers.voice_models.fish_speech_model import FishSpeechInstallSpec, FishSpeechModel


class FishSpeechInstallablesTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
