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

    def test_is_installed_reports_broken_pyyaml_metadata(self):
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
        logger.warning.assert_called_once()
        self.assertIn("pyyaml", logger.warning.call_args[0][0].lower())
        self.assertIn("version=none", logger.warning.call_args[0][0].lower())

    def test_install_raises_readable_error_for_broken_pyyaml(self):
        logger = Mock()
        recognizer = WhisperRecognizer(pip_installer=None, logger=logger)
        recognizer._last_requirements_probe_status = {
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

        with patch.object(recognizer, "is_installed", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "PyYAML looks corrupted"):
                import asyncio
                asyncio.run(recognizer.install())

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
