from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from controllers.gui.install_gui_controller import InstallGuiController
from utils.pip_installer import PipInstaller
from core.install_requirements import InstallRequirement, check_requirements


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

    def test_weak_task_percent_does_not_pin_global_progress(self):
        installer = PipInstaller(
            update_status=lambda *_: None,
            update_log=lambda *_: None,
            update_progress=lambda *_: None,
            protected_packages=[],
        )

        state = installer._RunState("Installing...", [sys.executable, "-m", "uv"])
        state.uv_progress = installer._UvProgressAggregator()

        installer._process_line(state, "jinja2")
        installer._process_line(state, "numpy 1%")

        self.assertEqual(state.percent, 0)
        self.assertFalse(installer._is_progress_confident(state))
        self.assertIn(
            "Ожидание данных о размере пакетов…",
            "\n".join(state.uv_progress.snapshot_lines()),
        )

    def test_snapshot_hides_service_status_tokens_and_normalizes_names(self):
        installer = PipInstaller(
            update_status=lambda *_: None,
            update_log=lambda *_: None,
            update_progress=lambda *_: None,
            protected_packages=[],
        )

        agg = installer._UvProgressAggregator()
        for line in ("Installed", "Downloading", "Resolved", "absl_py", "typing_extensions"):
            agg.update(line)

        rendered = "\n".join(agg.snapshot_lines())
        self.assertNotIn("Installed", rendered)
        self.assertNotIn("Downloading", rendered)
        self.assertNotIn("Resolved", rendered)
        self.assertIn("absl-py", rendered)
        self.assertIn("typing-extensions", rendered)

    def test_failed_run_logs_recent_output_instead_of_log_above_stub(self):
        messages: list[str] = []
        tmp = tempfile.mkdtemp(prefix="pip-installer-error-log-")
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

                def fake_run(_cmd, _env, state):
                    state.recent_lines.extend(
                        [
                            "Using uv dependency overrides: C:\\temp\\overrides.txt",
                            "No solution found when resolving dependencies",
                        ]
                    )
                    return True, 2

                with patch.object(installer, "_ensure_pty_available", return_value=False), patch.object(
                    installer, "_detect_pty", return_value=(False, None)
                ), patch.object(installer, "_run_with_pipes", side_effect=fake_run):
                    ok = installer._run_pip_process(
                        [sys.executable, "-m", "uv", "--verbose", "pip", "install", "tts-with-rvc"],
                        "Installing...",
                    )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertFalse(ok)
        joined = "\n".join(messages)
        self.assertIn("Последние строки установщика перед ошибкой:", joined)
        self.assertIn("No solution found when resolving dependencies", joined)
        self.assertIn("ОШИБКА: Процесс завершился с кодом 2.", joined)

    def test_winpty_reader_does_not_block_status_refresh(self):
        installer = PipInstaller(
            update_status=lambda *_: None,
            update_log=lambda *_: None,
            update_progress=lambda *_: None,
            protected_packages=[],
        )
        state = installer._RunState("Installing...", [sys.executable, "-m", "uv"])
        state.last_status_emit = state.start - 10.0

        class FakePty:
            def __init__(self):
                self.started = time.time()
                self.exitstatus = 0

            def isalive(self):
                return (time.time() - self.started) < 0.35

            def read(self, _size):
                time.sleep(0.2)
                return ""

            def close(self, force=True):
                return None

        class FakePtyProcess:
            @staticmethod
            def spawn(_cmdline, env=None):
                return FakePty()

        calls = {"count": 0}
        original = installer._update_status_if_needed

        def wrapped(s):
            calls["count"] += 1
            return original(s)

        with patch.object(installer, "_update_status_if_needed", side_effect=wrapped):
            ok, ret = installer._run_with_winpty(
                [sys.executable, "-m", "uv", "--verbose", "pip", "install", "torch"],
                {},
                state,
                FakePtyProcess,
            )

        self.assertTrue(ok)
        self.assertEqual(ret, 0)
        self.assertGreater(calls["count"], 3)


class CheckRequirementsCacheTests(unittest.TestCase):
    """Регресс на ложноотрицательную финальную проверку: пакет, установленный в
    target-Lib посреди сессии, не виден find_spec/metadata из-за кеша FileFinder
    (sys.path_importer_cache) — из-за чего установка ложно падала «не найден»,
    хотя после перезахода «повисала установленной». Фикс — invalidate_caches()
    в начале check_requirements."""

    def test_check_requirements_invalidates_import_caches(self):
        import importlib

        with patch.object(importlib, "invalidate_caches") as inv:
            check_requirements(
                [InstallRequirement(id="probe", kind="python_module", module="sys", required=True)]
            )
        inv.assert_called()

    def test_check_requirements_sees_module_created_after_cache_primed(self):
        modname = "neuromita_probe_pkg_20260704"
        tmpdir = tempfile.mkdtemp(prefix="reqcheck-")
        sys.path.insert(0, tmpdir)
        try:
            # Прогреваем кеш промахом — FileFinder закеширует пустую директорию.
            self.assertIsNone(importlib.util.find_spec(modname))
            # Создаём пакет уже ПОСЛЕ прогрева кеша (имитация установки в сессии).
            os.makedirs(os.path.join(tmpdir, modname))
            open(os.path.join(tmpdir, modname, "__init__.py"), "w").close()
            # check_requirements должен увидеть его благодаря invalidate_caches().
            res = check_requirements(
                [InstallRequirement(id="probe", kind="python_module", module=modname, required=True)]
            )
            self.assertTrue(res["ok"], res)
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop(modname, None)
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
