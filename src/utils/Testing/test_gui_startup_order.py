from __future__ import annotations

import importlib.util
import ast
import os
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))


class _Trace:
    def mark(self, *_args, **_kwargs):
        return None

    def write(self):
        return None

    @contextmanager
    def phase(self, *_args, **_kwargs):
        yield


class GuiStartupOrderTests(unittest.TestCase):
    def test_gui_runtime_disables_global_native_widget_promotion(self):
        from startup import runtime_bootstrap

        calls = []
        native_windows = object()
        dont_create_native_siblings = object()

        class QCoreApplication:
            @staticmethod
            def setAttribute(attribute, enabled=True):
                calls.append((attribute, enabled))

        application_attributes = SimpleNamespace(
            AA_NativeWindows=native_windows,
            AA_DontCreateNativeWidgetSiblings=dont_create_native_siblings,
        )
        qapplication = object()

        def fake_module(name: str, **attrs):
            result = types.ModuleType(name)
            for key, value in attrs.items():
                setattr(result, key, value)
            return result

        pyqt = fake_module("PyQt6")
        pyqt.__path__ = []
        qt_core = fake_module(
            "PyQt6.QtCore",
            QCoreApplication=QCoreApplication,
            Qt=SimpleNamespace(ApplicationAttribute=application_attributes),
        )
        qt_widgets = fake_module(
            "PyQt6.QtWidgets",
            QApplication=qapplication,
        )
        pyqt.QtCore = qt_core
        pyqt.QtWidgets = qt_widgets

        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt,
                "PyQt6.QtCore": qt_core,
                "PyQt6.QtWidgets": qt_widgets,
            },
        ), patch.dict(os.environ, {"QT_USE_NATIVE_WINDOWS": "1"}, clear=False):
            imported = runtime_bootstrap._import_gui_runtime()
            self.assertNotIn("QT_USE_NATIVE_WINDOWS", os.environ)

        self.assertIs(imported, qapplication)
        self.assertEqual(
            calls,
            [
                (native_windows, False),
                (dont_create_native_siblings, True),
            ],
        )

    def test_home_is_the_initial_main_page(self):
        window_source = (PROJECT_SRC / "ui" / "windows" / "main_window.py").read_text(
            encoding="utf-8"
        )
        coordinator_source = (
            PROJECT_SRC / "controllers" / "gui" / "main_window_coordinator.py"
        ).read_text(encoding="utf-8")
        window_tree = ast.parse(window_source)
        coordinator_tree = ast.parse(coordinator_source)
        initial_page_values = []
        initial_switches = []
        for node in ast.walk(window_tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "initial_page" and isinstance(keyword.value, ast.Constant):
                        initial_page_values.append(keyword.value.value)
        for node in ast.walk(coordinator_tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "switch_page" and node.args and isinstance(node.args[0], ast.Constant):
                    initial_switches.append(node.args[0].value)
        self.assertIn("home", initial_page_values)
        self.assertIn("home", initial_switches)

    def test_window_is_painted_before_backend_controller_is_constructed(self):
        spec = importlib.util.spec_from_file_location(
            "neuromita_gui_order_entrypoint",
            PROJECT_SRC / "__main__.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            module.startup_trace = _Trace()

            events: list[str] = []
            registry = SimpleNamespace(
                get=lambda _contract: object(),
                register=lambda *_args, **_kwargs: None,
                is_registered=lambda _contract: False,
            )

            scheduled_callbacks = []

            class _Signal:
                def __init__(self):
                    self.callbacks = []

                def connect(self, callback):
                    self.callbacks.append(callback)

                def emit(self):
                    for callback in list(self.callbacks):
                        callback()

            class QApplication:
                def __init__(self, _argv):
                    events.append("qapplication")
                    self.aboutToQuit = _Signal()

                def processEvents(self):
                    events.append("first_paint")

                def exec(self):
                    events.append("event_loop_entered")
                    while scheduled_callbacks:
                        scheduled_callbacks.pop(0)()
                    self.aboutToQuit.emit()
                    events.append("event_loop_exited")
                    return 0

            class SettingsController:
                def __init__(self, _path):
                    events.append("settings")
                    self.settings = {"LANGUAGE": "RU"}

            class MainWindow:
                def __init__(self, settings):
                    self.settings = settings
                    events.append("window_created")

                def show(self):
                    events.append("window_shown")

                def load_chat_history(self):
                    events.append("history_scheduled")

                def activate_current_main_page(self):
                    events.append("home_activated")

            class GuiCompositionRoot:
                def __init__(self, settings_controller):
                    events.append("composition_root_created")
                    self.window = MainWindow(settings_controller.settings)

                def attach_backend(self, controller):
                    controller.update_view(self.window)

                def backend_failed(self, _error):
                    events.append("backend_failed")

                def close(self):
                    events.append("composition_root_closed")

            created_settings_controller = None

            class MainController:
                def __init__(self, _view, startup_mode, settings_controller):
                    nonlocal created_settings_controller
                    created_settings_controller = settings_controller
                    events.append("backend_created")

                def update_view(self, _view):
                    events.append("backend_attached")

                def close_app(self):
                    events.append("backend_closed")

            class QTimer:
                @staticmethod
                def singleShot(_delay, callback):
                    events.append("timer_scheduled")
                    scheduled_callbacks.append(callback)

            class GuiBackendLoader:
                def __init__(
                    self,
                    *,
                    runtime,
                    startup_mode,
                    settings_controller,
                    on_ready,
                    on_failed,
                    parent=None,
                ):
                    del startup_mode, on_failed, parent
                    self.runtime = runtime
                    self.settings_controller = settings_controller
                    self.on_ready = on_ready
                    self.controller = None

                def start(self):
                    self.runtime.ensure_backend_bootstrap()
                    self.controller = MainController(
                        None,
                        startup_mode="full",
                        settings_controller=self.settings_controller,
                    )
                    self.on_ready(self.controller)

                def request_shutdown(self):
                    if self.controller is not None:
                        self.controller.close_app()

                def wait(self, timeout=5.0):
                    del timeout
                    return True

            def fake_module(name: str, **attrs):
                result = types.ModuleType(name)
                for key, value in attrs.items():
                    setattr(result, key, value)
                return result

            dummy_contracts = {
                name: type(name, (), {})
                for name in (
                    "AppVarsService",
                    "ASRSettingsService",
                    "CharacterRegistry",
                    "GameLinkService",
                    "LoopService",
                    "SettingsService",
                    "InstallableCatalogService",
                    "HardwareInventoryService",
                )
            }
            pyqt = fake_module("PyQt6")
            pyqt.__path__ = []
            qt_core = fake_module("PyQt6.QtCore", QTimer=QTimer)
            pyqt.QtCore = qt_core

            fake_modules = {
                "PyQt6": pyqt,
                "PyQt6.QtCore": qt_core,
                "ui.wheel_guard": fake_module(
                    "ui.wheel_guard",
                    install_combobox_wheel_guard=lambda _app: events.append("wheel_guard"),
                ),
                "controllers.settings_controller": fake_module(
                    "controllers.settings_controller",
                    SettingsController=SettingsController,
                ),
                "core.app_paths": fake_module(
                    "core.app_paths",
                    settings_path=lambda *_args, **_kwargs: PROJECT_SRC / "Settings" / "settings.json",
                ),
                "core.services": fake_module("core.services", services=lambda: registry),
                "services.character_registry": fake_module(
                    "services.character_registry",
                    SettingsOnlyCharacterRegistry=lambda _settings: object(),
                ),
                "services.contracts": fake_module("services.contracts", **dummy_contracts),
                "services.game_link_service": fake_module(
                    "services.game_link_service",
                    DisconnectedGameLinkService=lambda: object(),
                ),
                "services.loop_service": fake_module(
                    "services.loop_service",
                    NoLoopService=lambda: object(),
                ),
                "services.settings_service": fake_module(
                    "services.settings_service",
                    DefaultAppVarsService=lambda *_args: object(),
                ),
                "services.asr_settings_service": fake_module(
                    "services.asr_settings_service",
                    ensure_asr_settings_service=lambda: object(),
                ),
                "services.installable_catalog_service": fake_module(
                    "services.installable_catalog_service",
                    DefaultInstallableCatalogService=lambda *_args: object(),
                ),
                "services.hardware_inventory_service": fake_module(
                    "services.hardware_inventory_service",
                    WindowsHardwareInventoryService=lambda: object(),
                ),
                "controllers.gui.composition_root": fake_module(
                    "controllers.gui.composition_root",
                    GuiCompositionRoot=GuiCompositionRoot,
                ),
                "controllers.gui.qt_dispatch": fake_module(
                    "controllers.gui.qt_dispatch",
                    install_qt_dispatcher=lambda _app: events.append("qt_dispatcher"),
                ),
                "controllers.gui.qt_logging": fake_module(
                    "controllers.gui.qt_logging",
                    install_qt_message_logging=lambda _logger: events.append("qt_logging"),
                ),
                "controllers.main_controller": fake_module(
                    "controllers.main_controller",
                    MainController=MainController,
                ),
                "startup.gui_backend_loader": fake_module(
                    "startup.gui_backend_loader",
                    GuiBackendLoader=GuiBackendLoader,
                ),
            }

            logger = SimpleNamespace(
                success=lambda *_args: None,
                info=lambda *_args: None,
                warning=lambda *_args: None,
            )
            runtime = SimpleNamespace(
                logger=logger,
                QApplication=QApplication,
                ensure_backend_bootstrap=lambda: events.append("backend_bootstrap"),
            )

            with patch.dict(sys.modules, fake_modules):
                result = module._run_gui(runtime, "full")

            self.assertEqual(result, 0)
            self.assertIsNotNone(created_settings_controller)
            self.assertLess(events.index("window_shown"), events.index("backend_created"))
            self.assertLess(events.index("first_paint"), events.index("backend_created"))
            self.assertLess(events.index("event_loop_entered"), events.index("backend_bootstrap"))
            self.assertLess(events.index("backend_bootstrap"), events.index("backend_created"))
            self.assertLess(events.index("backend_created"), events.index("backend_attached"))
            self.assertLess(events.index("backend_attached"), events.index("event_loop_exited"))
        finally:
            sys.modules.pop(spec.name, None)


if __name__ == "__main__":
    unittest.main()
