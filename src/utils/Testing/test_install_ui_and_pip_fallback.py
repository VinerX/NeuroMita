from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from controllers.gui.install_gui_controller import InstallGuiController
from controllers.install_controller import InstallController
from core.events import Event, Events
from core.services import services
from utils.pip_installer import PipInstaller
from core.install_requirements import InstallRequirement, check_requirements
from services.contracts import InstallQueueService


class InstallUiCallbackTests(unittest.TestCase):
    def test_default_install_window_receives_requested_style_variant(self):
        captured: dict[str, object] = {}

        class Signal:
            def emit(self, title, initial_status, holder):
                captured.update(title=title, initial_status=initial_status, holder=holder)
                holder["window"] = object()
                holder["callbacks"] = (lambda *_: None,) * 4
                holder["ready_event"].set()

        controller = InstallGuiController.__new__(InstallGuiController)
        controller.view = type("View", (), {"create_installation_window_signal": Signal()})()

        controller._create_install_window("Installing RAG", "Preparing...", "ai_hub")

        self.assertEqual(captured["title"], "Installing RAG")
        self.assertEqual(captured["initial_status"], "Preparing...")
        self.assertEqual(captured["holder"]["style_variant"], "ai_hub")

    def test_normalize_callbacks_accepts_legacy_triplet_and_adds_raw_noop(self):
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
        callbacks[3]("raw")

        self.assertEqual(len(callbacks), 4)
        self.assertEqual(statuses, ["working"])
        self.assertEqual(logs, ["line"])

    def test_install_queue_worker_runs_the_first_enqueued_job(self):
        called = threading.Event()

        class Backend:
            def run_task(self, **_kwargs):
                called.set()
                return True

        class Main:
            backend_enabled = True
            install_controller = Backend()

        controller = InstallGuiController(Main(), None)
        try:
            controller._on_run_with_ui(
                Event(
                    Events.Install.RUN_WITH_UI,
                    {
                        "task_id": "tts:test:install",
                        "runner": lambda **_kwargs: None,
                        "meta": {
                            "category": "tts",
                            "component_id": "tts:test",
                        },
                        "title": "Test install",
                        "install_window": object(),
                        "install_callbacks": (
                            lambda *_args: None,
                            lambda *_args: None,
                            lambda *_args: None,
                            lambda *_args: None,
                        ),
                    },
                )
            )
            self.assertTrue(called.wait(2.0))
        finally:
            controller.close()

    def test_install_queue_is_registered_as_typed_service_and_admits_directly(self):
        called = threading.Event()

        class Backend:
            def run_task(self, **_kwargs):
                called.set()
                return True

        class Main:
            backend_enabled = True
            install_controller = Backend()

        controller = InstallGuiController(Main(), None)
        try:
            self.assertIs(services().get(InstallQueueService), controller)
            admission = controller.enqueue(
                {
                    "task_id": "tts:direct:install",
                    "runner": lambda **_kwargs: None,
                    "meta": {
                        "category": "tts",
                        "component_id": "tts:direct",
                    },
                    "title": "Direct install",
                },
                with_ui=False,
            )

            self.assertTrue(admission.accepted)
            self.assertFalse(admission.duplicate)
            self.assertTrue(called.wait(2.0))
        finally:
            controller.close()


    def test_runner_internal_type_error_is_not_retried_positionally(self):
        calls = {"count": 0}

        def runner(*, pip_installer, callbacks, ctx):
            calls["count"] += 1
            raise TypeError("internal runner bug")

        with self.assertRaisesRegex(TypeError, "internal runner bug"):
            InstallController._invoke_runner(
                runner,
                pip_installer=object(),
                callbacks=object(),
                ctx={},
            )

        self.assertEqual(calls["count"], 1)

    def test_worker_start_failure_does_not_leave_a_zombie_pending_job(self):
        class Main:
            backend_enabled = True
            install_controller = object()

        with patch(
            "controllers.gui.install_gui_controller.task_supervisor"
        ) as supervisor_factory:
            supervisor_factory.return_value.start_thread.side_effect = RuntimeError(
                "supervisor unavailable"
            )
            controller = InstallGuiController(Main(), None)
            try:
                accepted = controller._enqueue(
                    {
                        "task_id": "tts:test:install",
                        "title": "Test install",
                    }
                )
                self.assertFalse(accepted)
                self.assertEqual(controller._queue_snapshot()["pending"], [])
                self.assertIn("supervisor unavailable", controller._last_enqueue_error)
            finally:
                controller.close()


class PipInstallerFallbackTests(unittest.TestCase):
    def test_uv_code_2_preserves_uv_only_runtime_contract(self):
        messages: list[str] = []
        commands: list[list[str]] = []
        tmp = tempfile.mkdtemp(prefix="pip-installer-no-fallback-")
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
                    base = [sys.executable, "-m", "pip"] if force_pip else [sys.executable, "-m", "uv", "pip"]
                    return base + ["install", "--target", tmp]

                def fake_run(cmd, _description):
                    commands.append(list(cmd))
                    installer._last_run_returncode = 2
                    installer._last_run_recent_lines = ["No solution found when resolving f5-tts"]
                    installer._last_run_uv_cache_access_denied = False
                    return False

                with patch.object(installer, "_build_install_command", side_effect=fake_build), patch.object(
                    installer, "_run_pip_process", side_effect=fake_run
                ):
                    ok = installer.install_package_with_overrides(
                        ["tts-with-rvc", "f5-tts", "pyarrow<21.0.0"],
                        description="Installing F5-TTS dependencies...",
                    )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        self.assertFalse(ok)
        self.assertEqual(len(commands), 1)
        self.assertIn("uv", commands[0])
        self.assertFalse(any("-m" in cmd and "pip" in cmd and "uv" not in cmd for cmd in commands))

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

                with patch.object(installer, "_assert_not_gui_thread"), patch.object(
                    installer, "_ensure_pty_available", return_value=False
                ), patch.object(installer, "_detect_pty", return_value=(False, None)), patch.object(
                    installer, "_run_with_pipes", side_effect=fake_run
                ):
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
