from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from handlers.asr_models.speech_recognizer_base import (
    load_asr_model_settings,
    save_asr_model_settings,
)
from services.asr_settings_service import FileASRSettingsService


class ASRSettingsServiceTests(unittest.TestCase):
    def test_settings_are_atomic_revisioned_and_shared_with_model_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asr_settings.json"
            service = FileASRSettingsService(str(path))
            changes = []
            subscription = service.subscribe(changes.append)
            try:
                with patch(
                    "handlers.asr_models.speech_recognizer_base.ensure_asr_settings_service",
                    return_value=service,
                ):
                    save_asr_model_settings("google", {"device": "cpu"})
                    self.assertEqual(load_asr_model_settings("google"), {"device": "cpu"})
                service.set_model_option("google", "language", "ru-RU")
                service.set_selected_engine("google")
            finally:
                subscription.close()

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload, service.snapshot())
            self.assertEqual(service.revision, 2)
            self.assertEqual([change.kind for change in changes], ["model", "option"])

            detached = service.snapshot()
            detached["models"]["google"]["device"] = "cuda"
            self.assertEqual(service.model_settings("google")["device"], "cpu")

            reloaded = FileASRSettingsService(str(path))
            self.assertEqual(reloaded.model_settings("google")["language"], "ru-RU")

    def test_failed_persistence_does_not_mutate_in_memory_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = FileASRSettingsService(str(Path(tmp) / "asr_settings.json"))
            before = service.snapshot()
            with patch("services.asr_settings_service.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    service.set_model_option("google", "device", "cpu")

            self.assertEqual(service.snapshot(), before)
            self.assertEqual(service.revision, 0)


if __name__ == "__main__":
    unittest.main()
