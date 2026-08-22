from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from handlers.voice_models.fish_speech_model import FishSpeechInstallSpec


class FishSpeechInstallablesTests(unittest.TestCase):
    def test_all_modes_require_fish_checkpoint_files(self):
        expected = {
            "model.pth",
            "tokenizer.tiktoken",
            "config.json",
            "firefly-gan-vq-fsq-8x1024-21hz-generator.pth",
        }
        with tempfile.TemporaryDirectory() as base_dir, patch.dict(
            os.environ,
            {"NEUROMITA_BASE_DIR": base_dir},
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
            {"NEUROMITA_BASE_DIR": base_dir},
            clear=False,
        ):
            files = {
                Path(req.path_fn({}) if req.path_fn else req.path).name
                for req in FishSpeechInstallSpec.requirements("medium+low", {})
                if req.kind == "file"
            }

        self.assertTrue({"hubert_base.pt", "rmvpe.pt"}.issubset(files))

    def test_install_plan_downloads_weights_before_compile(self):
        with tempfile.TemporaryDirectory() as base_dir, patch.dict(
            os.environ,
            {"NEUROMITA_BASE_DIR": base_dir},
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
