from __future__ import annotations

import os
import threading
import time
import unittest
from concurrent.futures import Future


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
                self.mic_active_checkbox = QCheckBox(self)
                self.mic_instant_checkbox = QCheckBox(self)
                self.mic_instant_merge_input_checkbox = QCheckBox(self)
                self.mic_mute_while_speaking_checkbox = QCheckBox(self)
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
