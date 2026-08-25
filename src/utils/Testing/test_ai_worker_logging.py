from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.app_paths import ai_worker_log_path, runtime_log_path
from main_logger import AIWorkerFileLogger


class AIWorkerLoggingTests(unittest.TestCase):
    def test_worker_log_has_its_own_rotating_file_with_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"NEUROMITA_BASE_DIR": temp_dir},
        ):
            worker_logger = AIWorkerFileLogger("shared/unsafe")
            worker_logger.write("info", "worker ready")
            worker_logger.write("error", "request failed", "Traceback line")
            worker_logger.close()

            path = ai_worker_log_path("shared/unsafe")
            self.assertEqual(path, Path(temp_dir) / "Logs" / "AIWorkers" / "shared_unsafe.log")
            text = path.read_text(encoding="utf-8")
            self.assertIn("worker ready", text)
            self.assertIn("request failed", text)
            self.assertIn("Diagnostic traceback:\nTraceback line", text)

    def test_main_log_defaults_to_logs_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"NEUROMITA_BASE_DIR": temp_dir},
        ):
            self.assertEqual(
                runtime_log_path(),
                Path(temp_dir) / "Logs" / "NeuroMitaLogs.log",
            )


if __name__ == "__main__":
    unittest.main()
