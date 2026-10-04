import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
import pytest

from core.audio_input import ASRInputDevice
from controllers.gui.microphone_settings_controller import MicrophoneSettingsController
from ui.settings.microphone_settings.ui import build_microphone_settings_ui
from services.microphone_monitor import MonitorState

_APP = None


@pytest.fixture
def panel():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    root = QWidget()
    root.settings = {"NM_MICROPHONE_ID": 24, "NM_MICROPHONE_NAME": "Desk microphone"}
    build_microphone_settings_ui(root, QVBoxLayout(root))
    controller = MicrophoneSettingsController.__new__(MicrophoneSettingsController)
    controller.view = root
    controller._closed = False
    controller._ui = lambda fn: fn()
    controller._save_setting = Mock()
    controller.event_bus = Mock()
    controller._speech_service_or_retry = lambda *args: (
        SimpleNamespace(microphone_list_async=lambda cb: callbacks.append(cb)),
        False,
    )
    callbacks = []
    yield root, controller, callbacks
    root.mic_monitor_controller.monitor.close()
    root.close()
    root.deleteLater()
    _APP.processEvents()


def test_refresh_uses_device_objects_and_full_names_without_changing_runtime(panel):
    root, controller, callbacks = panel
    long_name = "A very long USB microphone name with (parentheses) and more than thirty characters"
    controller.refresh_microphones()
    callbacks.pop()(
        [
            ASRInputDevice(12, long_name, "WASAPI"),
            ASRInputDevice(38, "Desk microphone", "WASAPI"),
        ]
    )
    assert root.mic_combobox.itemText(0) == long_name
    assert root.mic_combobox.currentData().index == 38
    controller.event_bus.emit.assert_not_called()
    controller._save_setting.assert_not_called()
    controller._on_mic_changed(0)
    assert controller.event_bus.emit.call_args.args[1] == {
        "name": long_name,
        "device_id": 12,
    }


def test_missing_saved_microphone_is_not_replaced_by_first_device(panel):
    root, controller, callbacks = panel
    controller.refresh_microphones()
    callbacks.pop()([ASRInputDevice(24, "Other microphone", "WASAPI")])
    assert root.mic_combobox.currentData() is None
    assert "Desk microphone" in root.mic_combobox.currentText()
    assert not root.mic_test_button.isEnabled()
    controller.event_bus.emit.assert_not_called()


def test_stale_refresh_response_cannot_replace_new_selection(panel):
    root, controller, callbacks = panel
    controller.refresh_microphones()
    controller.refresh_microphones()
    callbacks[1]([ASRInputDevice(30, "Desk microphone", "WASAPI")])
    callbacks[0]([ASRInputDevice(24, "Desk microphone", "WASAPI")])
    assert root.mic_combobox.currentData().index == 30


def test_wheel_does_not_change_microphone(panel):
    root, controller, callbacks = panel
    combo = root.mic_combobox
    combo.addItem("First", ASRInputDevice(0, "First", "WASAPI"))
    combo.addItem("Second", ASRInputDevice(1, "Second", "WASAPI"))
    event = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(combo, event)
    assert combo.currentIndex() == 0
    assert not event.isAccepted()


def test_model_catalog_opens_asr_category(panel):
    from core.events import Events

    root, controller, callbacks = panel
    controller._open_asr_catalog()
    controller.event_bus.emit.assert_called_once_with(
        Events.GUI.SHOW_WINDOW, {"window_id": "ai_hub", "payload": {"category": "asr"}}
    )
    assert root.asr_restart_button.parentWidget() is not root.asr_status_badge


def test_status_badge_uses_semantic_colors_and_loading_indicator(panel):
    from styles.theme import get_theme

    root, controller, callbacks = panel
    theme = get_theme()
    root.asr_init_status.set_status("Ready", "ok")
    assert root.asr_status_badge.dot.color.name() == theme["success"]
    root.asr_init_status.set_status("Loading", "progress")
    assert root.asr_status_badge.dot.color.name() == theme["accent"]
    assert root.asr_status_badge.dot._timer.isActive()
    root.asr_init_status.set_status("Error", "warn")
    assert root.asr_status_badge.dot.color.name() == theme["danger"]
    assert not root.asr_status_badge.dot._timer.isActive()


def test_hiding_settings_stops_monitor_and_button_names_the_actual_device(panel):
    root, controller, callbacks = panel
    device = ASRInputDevice(24, "Desk microphone", "WASAPI")
    root.mic_combobox.addItem(device.name, device)
    monitor_controller = root.mic_monitor_controller
    monitor = Mock()
    monitor.snapshot.return_value = MonitorState("stopped")
    monitor.start.return_value = True
    monitor_controller.monitor = monitor
    root.show()
    QApplication.processEvents()
    monitor.snapshot.return_value = MonitorState("listening", device, 0.5)
    root.mic_test_button.setChecked(True)
    monitor.start.assert_called_once_with(device)
    assert "Desk microphone" in root.mic_test_device_label.text()
    monitor.snapshot.return_value = MonitorState("stopped")
    root.hide()
    assert monitor.stop.called
    assert not root.mic_test_button.isChecked()
