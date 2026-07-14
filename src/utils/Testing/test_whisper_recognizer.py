from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from handlers.asr_models.whisper_recognizer import WhisperRecognizer


class WhisperRecognizerTests(unittest.TestCase):
    def test_install_steps_include_pyyaml_repair_dependency(self):
        recognizer = WhisperRecognizer(pip_installer=None, logger=Mock())

        steps = recognizer.pip_install_steps({})
        packages = [pkg for step in steps for pkg in (step.get("packages") or [])]

        self.assertIn("pyyaml>=5.1", packages)
        self.assertIn("transformers", packages)
        self.assertIn("ctranslate2", packages)
        self.assertIn("faster-whisper", packages)

    def test_is_installed_caches_broken_pyyaml_metadata_without_warning(self):
        logger = Mock()
        recognizer = WhisperRecognizer(pip_installer=None, logger=logger)

        broken_status = {
            "ok": False,
            "missing_required": ["pyyaml"],
            "details": [
                {
                    "id": "pyyaml",
                    "ok": False,
                    "extra": {"spec": "pyyaml>=5.1", "version": None},
                }
            ],
        }

        with patch("handlers.asr_models.whisper_recognizer.check_requirements", return_value=broken_status), \
             patch("handlers.asr_models.whisper_recognizer.check_gpu_provider", return_value="CPU"):
            installed = recognizer.is_installed()

        self.assertFalse(installed)
        logger.warning.assert_not_called()
        self.assertIs(recognizer._last_requirements_probe_status, broken_status)
        self.assertIn("pyyaml", (recognizer._last_requirements_probe_message or "").lower())
        self.assertIn("version=none", (recognizer._last_requirements_probe_message or "").lower())

    def test_describe_requirements_failure_readable_for_broken_pyyaml(self):
        # Веса теперь качает download_http, install() артефакты не трогает и не
        # бросает. Читаемая причина ("PyYAML looks corrupted") приходит из
        # _describe_requirements_failure — её используют is_installed() и
        # post-install диагностика.
        recognizer = WhisperRecognizer(pip_installer=None, logger=Mock())
        broken_status = {
            "ok": False,
            "missing_required": ["pyyaml"],
            "details": [
                {
                    "id": "pyyaml",
                    "ok": False,
                    "extra": {"spec": "pyyaml>=5.1", "version": None},
                }
            ],
        }

        message = recognizer._describe_requirements_failure(broken_status)
        self.assertIn("PyYAML looks corrupted", message)

    def test_install_manifest_covers_ct2_files_for_turbo(self):
        recognizer = WhisperRecognizer(pip_installer=None, logger=Mock())
        recognizer.whisper_model = "large-v3-turbo"

        manifest = recognizer.install_manifest()
        names = {item["dest"].replace("\\", "/").rsplit("/", 1)[-1] for item in manifest}

        self.assertEqual(names, {"config.json", "preprocessor_config.json",
                                 "tokenizer.json", "vocabulary.json", "model.bin"})
        # Все ссылки — на реальный CT2-репозиторий turbo.
        self.assertTrue(all(
            "mobiuslabsgmbh/faster-whisper-large-v3-turbo" in item["url"]
            for item in manifest
        ))

    def test_diagnose_init_failure_explains_missing_pyyaml_dist_info(self):
        recognizer = WhisperRecognizer(pip_installer=None, logger=Mock())

        msg = recognizer._diagnose_init_failure(
            ValueError("Unable to compare versions for pyyaml>=5.1: need=5.1 found=None")
        )

        self.assertIsNotNone(msg)
        self.assertIn("dist-info", msg)
        self.assertIn("PyYAML", msg)


if __name__ == "__main__":
    unittest.main()
