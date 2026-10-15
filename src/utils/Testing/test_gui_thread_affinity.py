from __future__ import annotations

import os
import threading
import time
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import patch


class GuiThreadAffinityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError as exc:
            raise unittest.SkipTest(f"PyQt6 is unavailable: {exc}") from exc

        cls.application = QApplication.instance() or QApplication([])
        from controllers.gui.qt_dispatch import install_qt_dispatcher

        install_qt_dispatcher(cls.application)

    def _register_stub_settings(self) -> None:
        """Контроллеры страниц подписываются на SettingsService прямо в
        конструкторе, поэтому без зарегистрированного сервиса тест падает ещё
        до проверки потоков."""
        from core.services import services
        from services.contracts import SettingsService

        class _Subscription:
            def close(self) -> None:
                return None

        class _Settings(SettingsService):
            def __init__(self) -> None:
                self.values: dict[str, object] = {}

            def get(self, key, default=None):
                return self.values.get(str(key), default)

            def set(self, key, value) -> None:
                self.values[str(key)] = value

            def save_settings(self) -> None:
                return None

            def update(self, key, value) -> None:
                self.values[str(key)] = value

            def snapshot(self, keys=None):
                if keys is None:
                    return dict(self.values)
                return {str(k): self.values.get(str(k)) for k in keys}

            def subscribe(self, callback, *, keys=None, replay=False):
                return _Subscription()

        registry = services()
        registry.register(SettingsService, _Settings(), replace=True)
        self.addCleanup(registry.unregister, SettingsService)

    def _drain_until(self, predicate, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.application.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        self.application.processEvents()
        return bool(predicate())

    def test_fallback_dispatch_from_python_thread_runs_on_qt_thread(self) -> None:
        from PyQt6.QtCore import QThread
        from controllers.gui.qt_dispatch import dispatch_to_qt

        applied: list[object] = []
        result: list[bool] = []

        def worker() -> None:
            result.append(
                dispatch_to_qt(lambda: applied.append(QThread.currentThread()))
            )

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual([True], result)
        self.assertTrue(self._drain_until(lambda: bool(applied)))
        self.assertIs(applied[0], self.application.thread())

    def test_settings_optional_gui_is_created_on_qt_thread(self) -> None:
        from PyQt6.QtCore import QThread
        from controllers.gui.settings_page_view_model import SettingsPageViewModel
        from ui.pages.settings.settings_presentation import (
            PrepareSettingsSection,
            SettingsSectionReady,
        )

        class SettingsData:
            worker_threads: list[object] = []

            def prefetch_section(self, _host, _category: str) -> None:
                self.worker_threads.append(QThread.currentThread())

        class AppFacade:
            backend_ready = True
            gui_ready = True
            startup_error = ""

            def __init__(self) -> None:
                self.gui_threads: list[object] = []

            def ensure_feature_async(self, _name: str):
                raise AssertionError("No backend feature was requested")

            def ensure_optional_gui(self, _name: str) -> None:
                self.gui_threads.append(QThread.currentThread())

        settings_data = SettingsData()
        app_facade = AppFacade()
        view_model = SettingsPageViewModel(
            host=object(),
            app=app_facade,
            settings_data=settings_data,
        )
        effects: list[object] = []
        view_model.effect_emitted.connect(effects.append)
        try:
            view_model.dispatch(
                PrepareSettingsSection(
                    category="microphone",
                    gui_feature="speech",
                )
            )
            self.assertTrue(
                self._drain_until(
                    lambda: any(isinstance(item, SettingsSectionReady) for item in effects)
                )
            )
            self.assertEqual(1, len(settings_data.worker_threads))
            self.assertIsNot(
                settings_data.worker_threads[0],
                self.application.thread(),
            )
            self.assertEqual([self.application.thread()], app_facade.gui_threads)
        finally:
            view_model.close()

    def test_settings_section_rejects_feature_that_did_not_become_ready(self) -> None:
        from controllers.gui.settings_page_view_model import SettingsPageViewModel
        from ui.pages.settings.settings_presentation import (
            PrepareSettingsSection,
            SettingsSectionFailed,
        )

        class SettingsData:
            def prefetch_section(self, _host, _category: str) -> None:
                return None

        class AppFacade:
            backend_ready = True
            gui_ready = True
            startup_error = ""

            def __init__(self) -> None:
                self.gui_features: list[str] = []

            def ensure_feature_async(self, _name: str):
                future: Future[object | None] = Future()
                future.set_result(None)
                return future

            def ensure_optional_gui(self, name: str) -> None:
                self.gui_features.append(str(name))

        app_facade = AppFacade()
        view_model = SettingsPageViewModel(
            host=object(),
            app=app_facade,
            settings_data=SettingsData(),
        )
        effects: list[object] = []
        view_model.effect_emitted.connect(effects.append)
        try:
            view_model.dispatch(
                PrepareSettingsSection(
                    category="microphone",
                    feature_names=("speech",),
                    gui_feature="speech",
                )
            )
            self.assertTrue(
                self._drain_until(
                    lambda: any(
                        isinstance(item, SettingsSectionFailed) for item in effects
                    )
                )
            )
            failure = next(
                item for item in effects if isinstance(item, SettingsSectionFailed)
            )
            self.assertIn("did not become ready", failure.message)
            self.assertEqual([], app_facade.gui_features)
        finally:
            view_model.close()

    def test_early_section_click_waits_for_gui_attachment_without_blocking_qt(self):
        from PyQt6.QtCore import QThread, QTimer
        from controllers.gui.presentation_hub import _ApplicationController
        from controllers.gui.settings_page_view_model import SettingsPageViewModel
        from ui.pages.settings.settings_presentation import (
            PrepareSettingsSection,
            SettingsSectionReady,
        )

        app = _ApplicationController()
        backend = SimpleNamespace(gui_controller=None)
        app.attach_backend(backend)
        self.assertTrue(app.backend_ready)
        self.assertFalse(app.gui_ready)
        entered = threading.Event()
        threads = []
        effects = []
        ticks = []
        vm = SettingsPageViewModel(
            host=object(),
            app=app,
            settings_data=SimpleNamespace(
                prefetch_section=lambda *_args: entered.set()
            ),
        )
        vm.effect_emitted.connect(effects.append)
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        try:
            vm.dispatch(
                PrepareSettingsSection(
                    category="voice",
                    gui_feature="voice",
                    defer_features=True,
                )
            )
            self.assertTrue(
                self._drain_until(lambda: entered.is_set() and len(ticks) >= 3)
            )
            self.assertEqual([], effects)
            self.assertIn("voice", vm.state.loading_sections)
            backend.gui_controller = SimpleNamespace(
                ensure_optional_gui=lambda _name: threads.append(
                    QThread.currentThread()
                ),
            )
            self.assertTrue(app.gui_ready)
            self.assertTrue(self._drain_until(lambda: bool(effects)))
            self.assertEqual([SettingsSectionReady("voice")], effects)
            self.assertEqual([self.application.thread()], threads)
            self.assertEqual((), vm.state.failed_sections)
        finally:
            timer.stop()
            vm.close()

    def test_backend_failure_releases_section_waiting_for_gui(self):
        from controllers.gui.presentation_hub import _ApplicationController
        from controllers.gui.settings_page_view_model import SettingsPageViewModel
        from ui.pages.settings.settings_presentation import (
            PrepareSettingsSection,
            SettingsSectionFailed,
        )

        app = _ApplicationController()
        entered = threading.Event()
        effects = []
        vm = SettingsPageViewModel(
            host=object(),
            app=app,
            settings_data=SimpleNamespace(
                prefetch_section=lambda *_args: entered.set()
            ),
        )
        vm.effect_emitted.connect(effects.append)
        try:
            vm.dispatch(
                PrepareSettingsSection(
                    category="voice",
                    gui_feature="voice",
                    defer_features=True,
                )
            )
            self.assertTrue(self._drain_until(entered.is_set))
            app.mark_failed("Startup failed")
            self.assertTrue(self._drain_until(lambda: bool(effects)))
            self.assertEqual(
                [SettingsSectionFailed("voice", "RuntimeError: Startup failed")],
                effects,
            )
            self.assertEqual(frozenset(), vm.state.loading_sections)
        finally:
            vm.close()

    def test_section_preparation_leaves_qt_event_loop_responsive(self) -> None:
        from PyQt6.QtCore import QThread, QTimer
        from controllers.gui.settings_page_view_model import SettingsPageViewModel
        from ui.pages.settings.settings_presentation import (
            PrepareSettingsSection,
            SettingsSectionReady,
        )

        entered = threading.Event()
        release = threading.Event()
        preparation_threads = []
        ticks = []
        effects = []

        def prepare(category):
            self.assertEqual("api", category)
            preparation_threads.append(QThread.currentThread())
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Preparation was not released")

        view_model = SettingsPageViewModel(
            host=object(),
            app=SimpleNamespace(backend_ready=True),
            settings_data=SimpleNamespace(prefetch_section=lambda *_args: None),
            prepare_section=prepare,
        )
        view_model.effect_emitted.connect(effects.append)
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        try:
            view_model.dispatch(PrepareSettingsSection(category="api"))
            self.assertTrue(
                self._drain_until(lambda: entered.is_set() and len(ticks) >= 3)
            )
            self.assertEqual([], effects)
            self.assertIsNot(preparation_threads[0], self.application.thread())
            release.set()
            self.assertTrue(
                self._drain_until(
                    lambda: any(
                        isinstance(effect, SettingsSectionReady) for effect in effects
                    )
                )
            )
        finally:
            release.set()
            timer.stop()
            view_model.close()

    def test_voice_section_is_ready_before_optional_runtime(self) -> None:
        from controllers.gui.settings_page_view_model import SettingsPageViewModel
        from ui.pages.settings.settings_presentation import (
            PrepareSettingsSection,
            SettingsSectionReady,
            SettingsSectionFeaturesReady,
        )

        pending = Future()
        requested = threading.Event()

        def ensure_feature(_name):
            requested.set()
            return pending

        vm = SettingsPageViewModel(
            host=object(),
            app=SimpleNamespace(
                backend_ready=True,
                gui_ready=True,
                startup_error="",
                ensure_feature_async=ensure_feature,
                ensure_optional_gui=lambda _name: None,
            ),
            settings_data=SimpleNamespace(prefetch_section=lambda *_args: None),
        )
        effects = []
        vm.effect_emitted.connect(effects.append)
        try:
            vm.dispatch(
                PrepareSettingsSection(
                    category="voice",
                    feature_names=("local_voice", "voice_models"),
                    gui_feature="voice",
                    defer_features=True,
                )
            )
            self.assertTrue(
                self._drain_until(lambda: requested.is_set() and bool(effects))
            )
            self.assertIsInstance(effects[0], SettingsSectionReady)
            self.assertIn("voice", vm.state.preparing_features)
            self.assertNotIn("voice", vm.state.loading_sections)
            self.assertFalse(pending.done())
            pending.set_result(object())
            self.assertTrue(
                self._drain_until(
                    lambda: any(
                        isinstance(e, SettingsSectionFeaturesReady) for e in effects
                    )
                )
            )
            self.assertEqual(frozenset(), vm.state.preparing_features)
        finally:
            if not pending.done():
                pending.set_result(object())
            vm.close()

    def test_deferred_runtime_error_does_not_discard_the_section(self) -> None:
        from controllers.gui.settings_page_view_model import SettingsPageViewModel
        from ui.pages.settings.settings_presentation import (
            PrepareSettingsSection,
            SettingsSectionReady,
        )

        pending = Future()
        pending.set_exception(RuntimeError("Local backend unavailable"))
        vm = SettingsPageViewModel(
            host=object(),
            app=SimpleNamespace(
                backend_ready=True,
                startup_error="",
                ensure_feature_async=lambda _name: pending,
            ),
            settings_data=SimpleNamespace(prefetch_section=lambda *_args: None),
        )
        effects = []
        vm.effect_emitted.connect(effects.append)
        try:
            vm.dispatch(
                PrepareSettingsSection(
                    category="voice",
                    feature_names=("voice_models",),
                    defer_features=True,
                )
            )
            self.assertTrue(self._drain_until(lambda: bool(vm.state.feature_errors)))
            self.assertEqual([SettingsSectionReady("voice")], effects)
            self.assertEqual((), vm.state.failed_sections)
            self.assertIn(
                "Local backend unavailable", dict(vm.state.feature_errors)["voice"]
            )
        finally:
            vm.close()

    def test_catalog_views_are_created_only_when_their_dialog_opens(self) -> None:
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtWidgets import QWidget, QDialog, QVBoxLayout
        from controllers.gui.voice_model_controller import VoiceModelGuiController
        from controllers.gui.asr_glossary_controller import AsrGlossaryGuiController

        cases = (
            (
                VoiceModelGuiController,
                "ui.windows.voice_model_view.VoiceModelSettingsView",
                "_on_voice_models_dialog_ready",
            ),
            (
                AsrGlossaryGuiController,
                "ui.windows.asr_glossary_view.AsrGlossaryView",
                "_on_dialog_ready",
            ),
        )
        for controller_type, factory_path, ready_method in cases:
            with self.subTest(controller=controller_type.__name__):
                root = QWidget()
                dialog = QDialog(root)
                QVBoxLayout(dialog)
                with patch.object(controller_type, "subscribe_to_events"), patch.object(
                    controller_type, "_register_window_on_ready"
                ), patch(
                    factory_path, side_effect=lambda *_args, **_kwargs: QWidget()
                ) as factory:
                    controller = controller_type(object(), root)
                    factory.assert_not_called()
                    with patch.object(controller._view_model, "refresh"):
                        getattr(controller, ready_method)(dialog, {})
                        self.application.processEvents()
                        self.assertEqual(1, factory.call_count)
                        self.assertEqual(1, dialog.layout().count())
                        self.assertIs(controller._view_model.parent(), root)
                    controller.close()
                root.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_native_qt_warning_is_routed_to_application_logger(self) -> None:
        from PyQt6.QtCore import qInstallMessageHandler, qWarning
        from controllers.gui.qt_logging import install_qt_message_logging

        class RecordingLogger:
            def __init__(self) -> None:
                self.messages: list[tuple[str, str]] = []

            def _record(self, level: str, message: str, *args) -> None:
                rendered = message % args if args else message
                self.messages.append((level, rendered))

            def debug(self, message: str, *args) -> None:
                self._record("debug", message, *args)

            def info(self, message: str, *args) -> None:
                self._record("info", message, *args)

            def warning(self, message: str, *args) -> None:
                self._record("warning", message, *args)

            def error(self, message: str, *args) -> None:
                self._record("error", message, *args)

            def critical(self, message: str, *args) -> None:
                self._record("critical", message, *args)

        previous = qInstallMessageHandler(None)
        qInstallMessageHandler(previous)
        recorder = RecordingLogger()
        try:
            install_qt_message_logging(recorder)
            qWarning("QBasicTimer::start: current thread's event dispatcher has already been destroyed")
        finally:
            qInstallMessageHandler(previous)

        self.assertTrue(
            any(
                level == "error"
                and message.startswith("Qt: QBasicTimer::start")
                for level, message in recorder.messages
            )
        )

    def test_microphone_controller_starts_timers_without_qt_thread_warning(self) -> None:
        from PyQt6.QtCore import Qt, pyqtSignal, qInstallMessageHandler
        from PyQt6.QtWidgets import (
            QCheckBox,
            QComboBox,
            QDoubleSpinBox,
            QLabel,
            QPushButton,
            QSpinBox,
            QWidget,
        )
        from controllers.gui.microphone_settings_controller import (
            MicrophoneSettingsController,
        )

        class View(QWidget):
            run_ui_task_signal = pyqtSignal(object)
            asr_set_pill = pyqtSignal(dict)

            def __init__(self) -> None:
                super().__init__()
                self.settings = {}
                self.run_ui_task_signal.connect(
                    lambda callback: callback(),
                    type=Qt.ConnectionType.QueuedConnection,
                )
                self.mic_combobox = QComboBox(self)
                self.mic_refresh_button = QPushButton(self)
                self.recognizer_combobox = QComboBox(self)
                self.asr_refresh_button = QPushButton(self)
                self.asr_restart_button = QPushButton(self)
                self.mic_active_checkbox = QCheckBox(self)
                self.mic_instant_checkbox = QCheckBox(self)
                self.mic_instant_delay_checkbox = QCheckBox(self)
                self.mic_instant_delay_spin = QDoubleSpinBox(self)
                self.mic_instant_merge_input_checkbox = QCheckBox(self)
                self.mic_mute_while_speaking_checkbox = QCheckBox(self)
                self.asr_input_mode_combobox = QComboBox(self)
                self.asr_input_mode_combobox.addItem("VAD", "vad")
                self.asr_input_mode_combobox.addItem("PTT", "ptt")
                self.vad_apply_button = QPushButton(self)
                self.vad_reset_button = QPushButton(self)
                self.vad_sample_rate_spinbox = QSpinBox(self)
                self.vad_chunk_size_spinbox = QSpinBox(self)
                self.vad_threshold_spinbox = QDoubleSpinBox(self)
                self.vad_silence_timeout_spinbox = QDoubleSpinBox(self)
                self.vad_pre_buffer_spinbox = QDoubleSpinBox(self)
                self.vad_max_speech_duration_spinbox = QDoubleSpinBox(self)
                self.asr_manage_button = QPushButton(self)
                self.asr_init_status = QLabel(self)

            def _save_setting(self, key, value) -> None:
                self.settings[str(key)] = value

        class MainController:
            backend_enabled = False

        messages: list[str] = []

        def qt_handler(_message_type, _context, message) -> None:
            messages.append(str(message))

        previous = qInstallMessageHandler(qt_handler)
        view = View()
        controller = None
        self._register_stub_settings()
        try:
            controller = MicrophoneSettingsController(MainController(), view)
            self.assertTrue(
                self._drain_until(
                    lambda: controller._bound_sig is not None,
                    timeout=1.0,
                )
            )
        finally:
            if controller is not None:
                controller.close()
            view.deleteLater()
            self.application.processEvents()
            qInstallMessageHandler(previous)

        offending = [
            message
            for message in messages
            if "QBasicTimer::start" in message
            or "event dispatcher has already been destroyed" in message
        ]
        self.assertEqual([], offending)

    def test_gui_controller_constructor_rejects_worker_thread(self) -> None:
        from controllers.gui_controller import GuiController

        errors: list[BaseException] = []

        def worker() -> None:
            try:
                GuiController(object(), object())
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("constructed on the Qt GUI thread", str(errors[0]))

    def test_global_voice_status_controller_exists_before_voice_section(self) -> None:
        import controllers.gui_controller as gui_module

        scheduled = []

        class _Subscription:
            def close(self):
                return None

        class _Settings:
            def get(self, _key, default=None):
                return default

            def subscribe(self, *_args, **_kwargs):
                return _Subscription()

        class _Controller:
            def __init__(self, *_args, **_kwargs):
                pass

            def close(self):
                pass

        class _VoiceController(_Controller):
            def __init__(self, *_args, **_kwargs):
                self.preload_calls = 0

            def preload_global_status_on_startup(self):
                self.preload_calls += 1

        class _Timer:
            @staticmethod
            def singleShot(_delay, callback):
                scheduled.append(callback)

        replacements = {
            "StatusController": _Controller,
            "ChatController": _Controller,
            "SystemController": _Controller,
            "SettingsSidebarController": _Controller,
            "VoiceoverGuiController": _VoiceController,
            "DialogController": _Controller,
            "SettingsController": _Controller,
            "ModelEventController": _Controller,
            "ViewEventController": _Controller,
            "WindowManagerController": _Controller,
            "ProtocolPipelineGuiController": _Controller,
            "QTimer": _Timer,
        }

        with patch.multiple(gui_module, **replacements), patch.object(
            gui_module,
            "use",
            return_value=_Settings(),
        ):
            controller = gui_module.GuiController(
                SimpleNamespace(backend_enabled=False),
                SimpleNamespace(),
            )

        self.assertIsInstance(controller.voiceover_controller, _VoiceController)
        self.assertEqual({}, controller._optional_gui_features)
        self.assertEqual(1, len(scheduled))
        scheduled[0]()
        self.assertEqual(1, controller.voiceover_controller.preload_calls)

    def test_optional_gui_guard_rejects_worker_thread_creation(self) -> None:
        from controllers.gui_controller import GuiController

        controller = object.__new__(GuiController)
        controller._closed = False
        controller._gui_thread = self.application.thread()

        errors: list[BaseException] = []

        def worker() -> None:
            try:
                controller.ensure_optional_gui("speech")
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("outside the Qt GUI thread", str(errors[0]))


if __name__ == "__main__":
    unittest.main()
