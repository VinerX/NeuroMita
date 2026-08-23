import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from core.install_requirements import InstallRequirement, check_requirements
from handlers.voice_models.f5_tts_model import F5TTSInstallSpec, F5TTSModel


class F5TTSInstallablesTests(unittest.TestCase):
    def test_cross_lingual_variant_has_own_assets_and_dependencies(self):
        requirements = F5TTSInstallSpec.requirements(
            "high_clf5",
            {"gpu_vendor": "NVIDIA"},
        )
        specs = {req.spec for req in requirements if req.kind == "python_dist"}
        files = {
            Path(req.path_fn({}) if req.path_fn else req.path).name
            for req in requirements
            if req.kind == "file"
        }

        self.assertIn("pyphen", specs)
        self.assertNotIn("ruaccent", specs)
        self.assertIn("speaking_rate.safetensors", files)

    def test_russian_variant_requires_ruaccent_and_enables_it_by_default(self):
        requirements = F5TTSInstallSpec.requirements("high", {"gpu_vendor": "NVIDIA"})
        specs = {req.spec for req in requirements if req.kind == "python_dist"}
        defaults = F5TTSModel.default_settings_for_model("high")

        self.assertIn("ruaccent", specs)
        self.assertNotIn("pyphen", specs)
        self.assertTrue(defaults["use_ruaccent"])

    def test_cross_lingual_settings_do_not_expose_ruaccent(self):
        keys = {
            item["key"]
            for item in F5TTSModel._find_model_config("high_clf5")["settings"]
        }

        self.assertNotIn("use_ruaccent", keys)

    def test_cross_lingual_rvc_combines_clf5_and_rvc_requirements(self):
        requirements = F5TTSInstallSpec.requirements(
            "high_clf5+low",
            {"gpu_vendor": "NVIDIA"},
        )
        specs = {req.spec for req in requirements if req.kind == "python_dist"}
        files = {
            Path(req.path_fn({}) if req.path_fn else req.path).name
            for req in requirements
            if req.kind == "file"
        }
        settings = F5TTSModel._find_model_config("high_clf5+low")["settings"]
        setting_keys = {item["key"] for item in settings}

        self.assertIn("pyphen", specs)
        self.assertIn("tts-with-rvc", specs)
        self.assertNotIn("ruaccent", specs)
        self.assertIn("speaking_rate.safetensors", files)
        self.assertIn("f5rvc_f5_nfe_step", setting_keys)
        self.assertIn("f5rvc_rvc_pitch", setting_keys)
        self.assertNotIn("f5rvc_use_ruaccent", setting_keys)

    def test_rvc_variants_mirror_the_base_language_split(self):
        russian = F5TTSModel._find_model_config("high+low")
        cross_lingual = F5TTSModel._find_model_config("high_clf5+low")
        russian_defaults = F5TTSModel.default_settings_for_model("high+low")

        self.assertIn(russian["name"], {"F5-TTS + RVC (Русский)", "F5-TTS + RVC (Russian)"})
        self.assertEqual(russian["languages"], ["Russian"])
        self.assertTrue(russian_defaults["f5rvc_use_ruaccent"])
        self.assertEqual(cross_lingual["languages"], ["English", "Chinese"])
        self.assertNotIn(
            "f5rvc_use_ruaccent",
            {item["key"] for item in cross_lingual["settings"]},
        )

    def test_required_assets_include_vocoder_and_backend_specific_rvc(self):
        with tempfile.TemporaryDirectory() as base_dir, patch.dict(
            os.environ,
            {
                "NEUROMITA_BASE_DIR": base_dir,
                "NEUROMITA_CHECKPOINTS_DIR": os.path.join(base_dir, "checkpoints"),
            },
            clear=False,
        ):
            cuda_files = {
                Path(req.path_fn({}) if req.path_fn else req.path).name
                for req in F5TTSInstallSpec.requirements(
                    "high+low", {"gpu_vendor": "NVIDIA"}
                )
                if req.kind == "file"
            }
            onnx_files = {
                Path(req.path_fn({}) if req.path_fn else req.path).name
                for req in F5TTSInstallSpec.requirements(
                    "high+low", {"gpu_vendor": "AMD"}
                )
                if req.kind == "file"
            }

        common = {"model.safetensors", "vocab.txt", "config.yaml", "pytorch_model.bin"}
        self.assertTrue(common.issubset(cuda_files))
        self.assertTrue(common.issubset(onnx_files))
        self.assertTrue({"hubert_base.pt", "rmvpe.pt"}.issubset(cuda_files))
        self.assertTrue({"vec-768-layer-12.onnx", "rmvpe.onnx"}.issubset(onnx_files))

    def test_install_plan_downloads_vocoder_and_rvc_before_runtime(self):
        with tempfile.TemporaryDirectory() as base_dir, patch.dict(
            os.environ,
            {
                "NEUROMITA_BASE_DIR": base_dir,
                "NEUROMITA_CHECKPOINTS_DIR": os.path.join(base_dir, "checkpoints"),
            },
            clear=False,
        ), patch.object(F5TTSInstallSpec, "is_installed", return_value=False):
            plan = F5TTSInstallSpec.build_install_plan(
                "high+low", {"gpu_vendor": "NVIDIA"}
            )

        files = [
            item
            for action in plan.actions
            if action.type == "download_http"
            for item in action.files
        ]
        destinations = {Path(item["dest"]) for item in files}
        self.assertIn(
            Path(base_dir) / "checkpoints" / "vocos-mel-24khz" / "pytorch_model.bin",
            destinations,
        )
        self.assertIn(Path(base_dir) / "hubert_base.pt", destinations)
        self.assertIn(Path(base_dir) / "rmvpe.pt", destinations)

    def test_model_and_vocoder_paths_use_checkpoint_override(self):
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
            requirements = F5TTSInstallSpec.requirements(
                "high",
                {"gpu_vendor": "NVIDIA", "voice_language": "ru"},
            )
            file_paths = {
                Path(req.path_fn({}) if req.path_fn else req.path)
                for req in requirements
                if req.kind == "file"
            }

        root = Path(checkpoint_dir).resolve()
        self.assertTrue(file_paths)
        self.assertTrue(all(path.is_relative_to(root) for path in file_paths))

    def test_high_low_uses_cuda_rvc_package_on_nvidia(self):
        specs = [req.spec for req in F5TTSInstallSpec.requirements("high+low", {"gpu_vendor": "NVIDIA"})]

        self.assertIn("tts-with-rvc", specs)
        self.assertNotIn("tts-with-rvc-onnx[dml]", specs)

    def test_high_low_uses_onnx_rvc_package_on_amd(self):
        specs = [req.spec for req in F5TTSInstallSpec.requirements("high+low", {"gpu_vendor": "AMD"})]

        self.assertIn("tts-with-rvc-onnx[dml]", specs)
        self.assertNotIn("tts-with-rvc", specs)

    def test_high_low_install_plan_uses_onnx_rvc_package_on_cpu(self):
        plan = F5TTSInstallSpec.build_install_plan("high+low", {"gpu_vendor": "CPU"})

        pip_steps = [action for action in plan.actions if getattr(action, "type", "") == "pip"]
        self.assertTrue(pip_steps)
        self.assertIn("tts-with-rvc-onnx[dml]", pip_steps[0].packages)
        self.assertNotIn("tts-with-rvc", pip_steps[0].packages)

    def test_registered_rvc_checker_rejects_missing_onnx_module(self):
        requirement = InstallRequirement(
            id="tts_with_rvc",
            kind="python_dist",
            spec="tts-with-rvc-onnx[dml]",
            required=True,
        )

        with patch("core.install_requirements.importlib.util.find_spec", return_value=None):
            status = check_requirements([requirement], ctx={})

        self.assertFalse(status["ok"])
        self.assertEqual(status["missing_required"], ["tts_with_rvc"])

    def test_final_check_logs_missing_requirement_details(self):
        logs: list[str] = []
        callbacks = SimpleNamespace(log=logs.append)

        fake_result = {
            "ok": False,
            "missing_required": ["tts_with_rvc", "ckpt"],
            "details": [
                {
                    "id": "tts_with_rvc",
                    "kind": "python_dist",
                    "required": True,
                    "ok": False,
                    "extra": {"spec": "tts-with-rvc", "version": None},
                },
                {
                    "id": "ckpt",
                    "kind": "file",
                    "required": True,
                    "ok": False,
                    "extra": {"path": "checkpoints/F5-TTS/model.safetensors"},
                },
            ],
        }

        with patch("handlers.voice_models.f5_tts_model.check_requirements", return_value=fake_result):
            ok = F5TTSInstallSpec._final_check("high+low", {"gpu_vendor": "NVIDIA"}, callbacks=callbacks)

        self.assertFalse(ok)
        joined = "\n".join(logs)
        self.assertIn("ОШИБКА: Финальная проверка установки не пройдена.", joined)
        self.assertIn("ОШИБКА: Не выполнены обязательные требования: tts_with_rvc, ckpt", joined)
        self.assertIn("пакет tts-with-rvc не найден", joined)
        self.assertIn("отсутствует файл checkpoints/F5-TTS/model.safetensors", joined)

    def test_install_plan_final_check_uses_runtime_action_context(self):
        plan = F5TTSInstallSpec.build_install_plan(
            "high",
            {
                "gpu_vendor": "NVIDIA",
                "target_dir": "old-target",
                "python_paths": ["old-target"],
                "strict_target": True,
            },
        )
        final_action = next(
            action
            for action in plan.actions
            if getattr(action, "type", "") == "call"
            and int(getattr(action, "progress", 0) or 0) == 99
        )

        captured: dict = {}

        def fake_final_check(model_id, ctx, callbacks=None):
            captured["model_id"] = model_id
            captured["ctx"] = dict(ctx)
            captured["callbacks"] = callbacks
            return True

        callbacks = SimpleNamespace(log=lambda _message: None)
        runtime_ctx = {
            "target_dir": "staging-overlay",
            "libs_dir": "staging-overlay",
            "python_paths": ["staging-overlay", "cuda-backend"],
            "strict_target": True,
        }

        with patch.object(F5TTSInstallSpec, "_final_check", side_effect=fake_final_check):
            ok = final_action.fn(ctx=runtime_ctx, callbacks=callbacks)

        self.assertTrue(ok)
        self.assertEqual(captured["model_id"], "high")
        self.assertEqual(captured["ctx"]["gpu_vendor"], "NVIDIA")
        self.assertEqual(captured["ctx"]["target_dir"], "staging-overlay")
        self.assertEqual(
            captured["ctx"]["python_paths"],
            ["staging-overlay", "cuda-backend"],
        )
        self.assertIs(captured["callbacks"], callbacks)


if __name__ == "__main__":
    unittest.main()
