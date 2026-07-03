import unittest
from unittest.mock import patch
from types import SimpleNamespace

from core.install_requirements import InstallRequirement, check_requirements
from handlers.voice_models.f5_tts_model import F5TTSInstallSpec


class F5TTSInstallablesTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
