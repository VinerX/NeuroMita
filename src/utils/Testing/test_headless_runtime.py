from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.app_paths import settings_path
from game_connections.handlers.actions.get_settings import GetSettingsAction
from game_connections.handlers.registry import RequestContext
from startup.headless_runtime import HeadlessRuntimeHost
from startup.runtime_bootstrap import RuntimeContext


class _RequestServer:
    def __init__(self):
        self.sent = []
        self.errors = []

    def build_loaded_settings_payload(self):
        return {"type": "loaded_settings", "body": {"value": 42}}

    async def send_json(self, writer, payload):
        self.sent.append((writer, payload))

    async def send_error(self, writer, error):
        self.errors.append((writer, error))


class HeadlessRuntimeTests(unittest.TestCase):
    def test_deferred_backend_bootstrap_is_idempotent(self):
        calls = []
        runtime = RuntimeContext(
            base_dir="/tmp/base",
            libs_dir="/tmp/base/Lib",
            QApplication=None,
            logger=object(),
            _backend_bootstrap=lambda: calls.append("bootstrap"),
        )

        runtime.ensure_backend_bootstrap()
        runtime.ensure_backend_bootstrap()

        self.assertEqual(calls, ["bootstrap"])

    def test_entrypoint_parses_headless_options_without_consuming_other_args(self):
        spec = importlib.util.spec_from_file_location(
            "neuromita_test_entrypoint",
            PROJECT_SRC / "__main__.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            argv = [
                "neuromita",
                "--headless",
                "--server-host=0.0.0.0",
                "--server-port=23456",
                "--run-seconds=3.5",
                "--headless-status-interval=2",
                "--unrelated-option",
            ]
            old_host = os.environ.get("NEUROMITA_SERVER_HOST")
            old_port = os.environ.get("NEUROMITA_SERVER_PORT")
            try:
                options = module._consume_startup_options(argv)
            finally:
                if old_host is None:
                    os.environ.pop("NEUROMITA_SERVER_HOST", None)
                else:
                    os.environ["NEUROMITA_SERVER_HOST"] = old_host
                if old_port is None:
                    os.environ.pop("NEUROMITA_SERVER_PORT", None)
                else:
                    os.environ["NEUROMITA_SERVER_PORT"] = old_port

            self.assertEqual(options.mode, "headless")
            self.assertEqual(options.headless_run_seconds, 3.5)
            self.assertEqual(options.headless_status_interval, 2.0)
            self.assertEqual(argv, ["neuromita", "--unrelated-option"])
        finally:
            sys.modules.pop(spec.name, None)

    def test_backend_module_import_does_not_load_qt(self):
        code = (
            "import sys; import controllers.main_controller; "
            "assert not any(name == 'PyQt6' or name.startswith('PyQt6.') "
            "for name in sys.modules), sorted(name for name in sys.modules if name.startswith('PyQt6'))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_SRC,
            env={**os.environ, "PYTHONPATH": str(PROJECT_SRC)},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_backend_settings_paths_do_not_depend_on_working_directory(self):
        old_base = os.environ.get("NEUROMITA_BASE_DIR")
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as other:
            try:
                os.environ["NEUROMITA_BASE_DIR"] = base
                os.chdir(other)
                resolved = settings_path("api_presets.json", create_parent=True)
                self.assertEqual(resolved, Path(base).resolve() / "Settings" / "api_presets.json")
                self.assertTrue(resolved.parent.is_dir())
            finally:
                os.chdir(old_cwd)
                if old_base is None:
                    os.environ.pop("NEUROMITA_BASE_DIR", None)
                else:
                    os.environ["NEUROMITA_BASE_DIR"] = old_base

    def test_get_settings_replies_only_through_request_context(self):
        server = _RequestServer()
        writer = object()
        context = RequestContext(
            server=server,
            client_id="client-1",
            writer=writer,
            event_bus=object(),
        )

        asyncio.run(GetSettingsAction().handle({"action": "get_settings"}, context))

        self.assertEqual(
            server.sent,
            [(writer, {"type": "loaded_settings", "body": {"value": 42}})],
        )
        self.assertEqual(server.errors, [])

    def test_snapshot_requires_transport_and_controller_to_be_running(self):
        runtime = SimpleNamespace(logger=SimpleNamespace(info=lambda *_: None))
        host = HeadlessRuntimeHost(runtime)
        server = SimpleNamespace(
            running=False,
            host="127.0.0.1",
            port=12345,
            active_connections={},
        )
        host.controller = SimpleNamespace(
            server_controller=SimpleNamespace(running=True, server=server),
            ai_engine_controller=SimpleNamespace(mode="shared", _workers={}),
        )

        self.assertFalse(host.snapshot()["server_running"])


if __name__ == "__main__":
    unittest.main()
