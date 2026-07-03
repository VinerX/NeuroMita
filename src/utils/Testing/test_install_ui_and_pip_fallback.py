from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from controllers.gui.install_gui_controller import InstallGuiController
from utils.pip_installer import PipInstaller


class InstallUiCallbackTests(unittest.TestCase):
    def test_normalize_callback_triplet_replaces_missing_progress_with_noop(self):
        statuses: list[str] = []
        logs: list[str] = []

        callbacks = InstallGuiController._normalize_callback_triplet(
            (None, statuses.append, logs.append)
        )

        self.assertIsNotNone(callbacks)
        self.assertTrue(all(callable(cb) for cb in callbacks))

        callbacks[0](42)
        callbacks[1]("working")
        callbacks[2]("line")

        self.assertEqual(statuses, ["working"])
        self.assertEqual(logs, ["line"])


class PipInstallerFallbackTests(unittest.TestCase):
    def test_uv_code_2_retries_f5_stack_with_builtin_pip(self):
        messages: list[str] = []
        commands: list[list[str]] = []
        tmp = tempfile.mkdtemp(prefix="pip-installer-fallback-")
        try:
            with patch.dict(
                os.environ,
                {"NEUROMITA_LIB_DIR": tmp, "NEUROMITA_PYTHON": sys.executable},
                clear=False,
            ):
                installer = PipInstaller(
                    update_status=lambda *_: None,
                    update_log=messages.append,
                    update_progress=lambda *_: None,
                    protected_packages=[],
                )

                def fake_build(force_pip: bool = False):
                    base = [sys.executable, "-m", "pip"] if force_pip else [sys.executable, "-m", "uv", "--verbose", "pip"]
                    return base + ["install", "--target", tmp]

                def fake_run(cmd, _description):
                    commands.append(list(cmd))
                    if "uv" in cmd:
                        installer._last_run_returncode = 2
                        installer._last_run_recent_lines = ["No solution found when resolving f5-tts"]
                        installer._last_run_uv_cache_access_denied = False
                        return False
                    installer._last_run_returncode = 0
                    installer._last_run_recent_lines = []
                    installer._last_run_uv_cache_access_denied = False
                    return True

                with patch.object(installer, "_build_install_command", side_effect=fake_build), patch.object(
                    installer, "_run_pip_process", side_effect=fake_run
                ):
                    ok = installer.install_package_with_overrides(
                        ["tts-with-rvc", "f5-tts", "pyarrow<21.0.0"],
                        description="Installing F5-TTS dependencies...",
                    )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertTrue(ok)
        self.assertEqual(len(commands), 2)
        self.assertIn("uv", commands[0])
        self.assertIn("pip", commands[1])
        self.assertTrue(
            any("встроенный pip" in msg for msg in messages),
            f"fallback log message missing: {messages}",
        )


if __name__ == "__main__":
    unittest.main()
