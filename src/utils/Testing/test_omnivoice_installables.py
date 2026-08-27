import asyncio
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from handlers.voice_models.omnivoice_model import OmniVoiceInstallSpec, OmniVoiceModel


class _Parent:
    provider = "NVIDIA"
    current_model_id = "omnivoice"

    def load_model_settings(self, model_id):
        return {}

    def convert_wav_to_stereo(self, input_path, output_path, **_kwargs):
        shutil.copyfile(input_path, output_path)
        return output_path


class _RuntimeModel:
    sampling_rate = 24000

    def __init__(self):
        self.prompt_calls = []
        self.generate_calls = []

    def create_voice_clone_prompt(self, *, ref_audio, ref_text):
        self.prompt_calls.append((ref_audio, ref_text))
        return {"audio": ref_audio, "text": ref_text}

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return [[0.0, 0.1, -0.1]]


class OmniVoiceInstallablesTests(unittest.TestCase):
    def test_catalog_metadata_marks_model_as_multilingual_and_below_fish_speech(self):
        config = OmniVoiceModel._find_model_config("omnivoice")

        self.assertEqual(config["languages"], ["Multilingual"])
        self.assertIn("Fish Speech", config["description"])
        self.assertLess(float(config["size_gb"]), 5.0)

    def test_requirements_use_checkpoint_override_and_include_nested_audio_tokenizer(self):
        with tempfile.TemporaryDirectory() as checkpoint_dir, patch.dict(
            os.environ,
            {"NEUROMITA_CHECKPOINTS_DIR": checkpoint_dir},
            clear=False,
        ):
            requirements = OmniVoiceInstallSpec.requirements(
                "omnivoice",
                {"gpu_vendor": "NVIDIA"},
            )

        file_paths = {
            Path(requirement.path)
            for requirement in requirements
            if requirement.kind == "file"
        }
        root = Path(checkpoint_dir).resolve() / "OmniVoice"
        self.assertTrue(file_paths)
        self.assertTrue(all(path.is_relative_to(root) for path in file_paths))
        self.assertIn(root / "audio_tokenizer" / "model.safetensors", file_paths)
        self.assertTrue(
            any(
                requirement.kind == "python_dist"
                and requirement.spec == "scipy==1.12.0"
                for requirement in requirements
            )
        )

    def test_install_plan_uses_pinned_package_and_hugging_face_snapshot_action(self):
        with patch.object(OmniVoiceInstallSpec, "is_installed", return_value=False):
            plan = OmniVoiceInstallSpec.build_install_plan(
                "omnivoice",
                {"gpu_vendor": "NVIDIA"},
            )

        pip_action = next(action for action in plan.actions if action.type == "pip")
        download_action = next(
            action
            for action in plan.actions
            if action.type == "call" and "Hugging Face" in action.description
        )
        self.assertEqual(
            pip_action.packages,
            [
                "omnivoice==0.2.1",
                "transformers==5.3.0",
                "scipy==1.12.0",
            ],
        )
        self.assertIn("Hugging Face", download_action.description)

    def test_snapshot_download_targets_own_checkpoint_folder_and_pinned_revision(self):
        calls = []

        def fake_snapshot_download(**kwargs):
            calls.append(kwargs)
            root = Path(kwargs["local_dir"])
            for relative_path in OmniVoiceInstallSpec.REQUIRED_MODEL_FILES:
                target = root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"model")
            return str(root)

        huggingface_module = types.ModuleType("huggingface_hub")
        huggingface_module.snapshot_download = fake_snapshot_download

        with tempfile.TemporaryDirectory() as checkpoint_dir, patch.dict(
            os.environ,
            {"NEUROMITA_CHECKPOINTS_DIR": checkpoint_dir},
            clear=False,
        ), patch.dict(sys.modules, {"huggingface_hub": huggingface_module}):
            ok = OmniVoiceInstallSpec._download_snapshot(
                callbacks=SimpleNamespace(log=lambda _message: None),
                ctx={"meta": {"clean": True}},
            )

        self.assertTrue(ok)
        self.assertEqual(calls[0]["repo_id"], "k2-fsa/OmniVoice")
        self.assertEqual(calls[0]["revision"], OmniVoiceInstallSpec.MODEL_REVISION)
        self.assertTrue(calls[0]["force_download"])
        self.assertEqual(Path(calls[0]["local_dir"]).name, "OmniVoice")

    def test_voiceover_reuses_f5_cut_and_cached_voice_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cut_audio = root / "Mita_Cuts" / "Mita_default.wav"
            cut_text = root / "Mita_Cuts" / "Mita_default.txt"
            cut_audio.parent.mkdir(parents=True)
            cut_audio.write_bytes(b"wav")
            cut_text.write_text("Reference transcript.", encoding="utf-8")
            clone_audio = root / "Mita.wav"
            clone_text = root / "Mita.txt"
            clone_audio.write_bytes(b"clone")
            clone_text.write_text("Clone transcript.", encoding="utf-8")

            paths = {
                "f5_voice_filename": str(cut_audio),
                "f5_voice_text": str(cut_text),
                "clone_voice_filename": str(clone_audio),
                "clone_voice_text": str(clone_text),
                "character_name": "Mita",
            }
            soundfile_module = types.ModuleType("soundfile")
            soundfile_module.write = lambda path, *_args, **_kwargs: Path(path).write_bytes(b"audio")
            runtime_model = _RuntimeModel()
            handler = OmniVoiceModel(_Parent(), "omnivoice")
            handler.current_model = runtime_model
            handler.initialized = True
            handler.initialized_for = "omnivoice"

            with patch(
                "handlers.voice_models.omnivoice_model.get_character_voice_paths",
                return_value=paths,
            ), patch.dict(sys.modules, {"soundfile": soundfile_module}):
                first = asyncio.run(
                    handler.voiceover(
                        "First phrase",
                        character={"short_name": "Mita"},
                        output_file=str(root / "first.wav"),
                    )
                )
                second = asyncio.run(
                    handler.voiceover(
                        "Second phrase",
                        character={"short_name": "Mita"},
                        output_file=str(root / "second.wav"),
                    )
                )

        self.assertEqual(runtime_model.prompt_calls, [(str(cut_audio), "Reference transcript.")])
        self.assertEqual(len(runtime_model.generate_calls), 2)
        self.assertEqual(runtime_model.generate_calls[0]["num_step"], 16)
        self.assertTrue(first.endswith("first.wav"))
        self.assertTrue(second.endswith("second.wav"))


if __name__ == "__main__":
    unittest.main()
