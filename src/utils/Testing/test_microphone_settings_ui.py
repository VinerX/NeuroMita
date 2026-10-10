import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
import pytest

from domain.audio_input import ASRInputDevice, MicrophoneSelection
from domain.audio_input import AudioInputCatalog, EndpointIdentityStatus
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
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
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
    assert controller.event_bus.emit.call_args.args[1] == MicrophoneSelection(
        index=12, name=long_name
    )


def test_pause_while_mita_speaks_defaults_to_off(panel):
    root, _, _ = panel
    assert not root.mic_mute_while_speaking_checkbox.isChecked()


def test_complete_display_name_is_used_but_selection_keeps_raw_name_and_id(panel):
    root, controller, callbacks = panel
    full_name = "Microphone (FIFINE K670 Microphone)"
    raw_name = full_name[:31]
    device = ASRInputDevice(1, raw_name, "MME", display_name=full_name)
    root.settings.update(NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME=raw_name)
    controller.refresh_microphones()
    callbacks.pop()([device])
    assert root.mic_combobox.itemText(0) == full_name
    assert root.mic_combobox.currentText() == full_name
    assert full_name in root.mic_combobox.itemData(0, Qt.ItemDataRole.ToolTipRole)
    controller._on_mic_changed(0)
    assert full_name in root.mic_combobox.toolTip()
    assert controller.event_bus.emit.call_args.args[1] == MicrophoneSelection(
        index=1, name=raw_name
    )


def test_legacy_selection_gets_endpoint_id_migration_without_runtime_change(panel):
    root, controller, callbacks = panel
    controller.refresh_microphones()
    callbacks.pop()([ASRInputDevice(38, "Desk microphone", "WASAPI", uid="endpoint-A")])
    controller._save_setting.assert_not_called()
    assert root.mic_combobox.currentData().uid == "endpoint-A"
    controller.event_bus.emit.assert_not_called()


def test_saved_endpoint_survives_name_and_index_change_in_ui(panel):
    root, controller, callbacks = panel
    root.settings["NM_MICROPHONE_UID"] = "endpoint-A"
    controller.refresh_microphones()
    callbacks.pop()(
        [
            ASRInputDevice(24, "Desk microphone", "WASAPI", uid="endpoint-B"),
            ASRInputDevice(39, "Renamed microphone", "WASAPI", uid="endpoint-A"),
        ]
    )
    assert root.mic_combobox.currentData().index == 39
    assert root.mic_combobox.currentText() == "Renamed microphone"
    controller._on_mic_changed(1)
    assert controller.event_bus.emit.call_args.args[1] == MicrophoneSelection(
        uid="endpoint-A", index=39, name="Renamed microphone"
    )


def test_missing_endpoint_is_not_replaced_by_matching_legacy_name(panel):
    root, controller, callbacks = panel
    root.settings["NM_MICROPHONE_UID"] = "missing-endpoint"
    controller.refresh_microphones()
    callbacks.pop()(
        [ASRInputDevice(24, "Desk microphone", "WASAPI", uid="other-endpoint")]
    )
    assert root.mic_combobox.currentData() is None
    controller._save_setting.assert_not_called()


def test_existing_endpoint_binding_is_not_downgraded_by_legacy_catalog(panel):
    root, controller, callbacks = panel
    root.settings["NM_MICROPHONE_UID"] = "endpoint-A"
    root.mic_combobox.addItem(
        "Desk microphone", ASRInputDevice(24, "Desk microphone", "WASAPI")
    )
    controller.refresh_microphones()
    callbacks.pop()([ASRInputDevice(24, "Desk microphone", "WASAPI")])
    assert root.mic_combobox.currentData() is None
    controller._save_setting.assert_not_called()


def test_failed_identity_query_is_shown_as_unverified_binding_not_missing_mic(panel):
    root, controller, callbacks = panel
    root.settings["NM_MICROPHONE_UID"] = "endpoint-A"
    controller.refresh_microphones()
    device = ASRInputDevice(24, "Desk microphone", "WASAPI")
    callbacks.pop()(
        AudioInputCatalog((device,), identity_status=EndpointIdentityStatus.UNAVAILABLE)
    )
    assert "Не удалось проверить" in root.mic_combobox.currentText()
    assert root.mic_combobox.currentData() is None
    assert root.settings["NM_MICROPHONE_UID"] == "endpoint-A"
    controller._save_setting.assert_not_called()
    assert "по имени и индексу" in root.mic_combobox.itemData(
        1, Qt.ItemDataRole.ToolTipRole
    )


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


def test_backend_selector_only_offers_current_endpoint_and_updates_monitor(panel):
    root, controller, callbacks = panel
    root.settings.update(NM_MICROPHONE_UID="desk", NM_MICROPHONE_BACKEND="MME")
    mme = ASRInputDevice(1, "Desk microphone", "MME", uid="desk")
    wasapi = ASRInputDevice(38, "Desk microphone", "WASAPI", uid="desk")
    other = ASRInputDevice(2, "Other", "DirectSound", uid="other")
    controller.refresh_microphones()
    callbacks.pop()(
        AudioInputCatalog(
            devices=(wasapi, other),
            representations=(mme, wasapi, other),
            compatible_representations=(mme, wasapi, other),
        )
    )
    backend = root.mic_backend_combobox
    assert [backend.itemData(i) for i in range(backend.count())] == [
        "",
        "MME",
        "WASAPI",
    ]
    assert backend.currentData() == "MME"
    assert root.mic_combobox.currentData().index == 1
    controller.event_bus.emit.assert_not_called()
    backend.setCurrentIndex(0)
    controller._on_backend_changed(0)
    assert root.mic_combobox.currentData().index == 38
    assert controller.event_bus.emit.call_args.args[1].backend == ""


def test_unavailable_backend_preserved_and_disables_microphone_test(panel):
    root, controller, callbacks = panel
    root.settings.update(NM_MICROPHONE_UID="desk", NM_MICROPHONE_BACKEND="MME")
    wasapi = ASRInputDevice(38, "Desk microphone", "WASAPI", uid="desk")
    controller.refresh_microphones()
    callbacks.pop()(
        AudioInputCatalog(devices=(wasapi,), compatible_representations=(wasapi,))
    )
    assert root.mic_backend_combobox.currentData() == "MME"
    assert not root.mic_monitor_controller.button.isEnabled()
    controller.event_bus.emit.assert_not_called()


@pytest.mark.parametrize("missing", ["mic_combobox", "mic_refresh_button"])
def test_microphone_setting_arrives_before_widgets_are_ready(panel, missing):
    root, controller, callbacks = panel
    widget = getattr(root, missing)
    setattr(root, missing, None)
    assert controller._widgets_signature() is None
    controller._reflect_external_setting(
        SimpleNamespace(key="NM_MICROPHONE_UID", value="desk")
    )
    controller.refresh_microphones()
    assert not callbacks
    setattr(root, missing, widget)
    assert controller._widgets_signature() is not None
    controller.refresh_microphones(prefer_saved=True)
    assert len(callbacks) == 1
    callbacks.pop()([ASRInputDevice(38, "Desk microphone", "WASAPI")])
    assert root.mic_combobox.currentData().index == 38


def test_microphone_catalog_callback_ignores_replaced_widgets(panel):
    root, controller, callbacks = panel
    controller.refresh_microphones()
    combo = root.mic_combobox
    root.mic_combobox = None
    callbacks.pop()([ASRInputDevice(38, "Desk microphone", "WASAPI")])
    assert combo.count() == 0
    root.mic_combobox = combo


class _LanguageCatalog:
    def __init__(self):
        self.values = {"google": {"language": "uk-UA", "custom": 7}, "whisper": {"language": "auto"}}

    def settings_schema(self, component_id):
        engine = component_id.split(":", 1)[1]
        codes = ["ru-RU", "uk-UA"] if engine == "google" else ["ru", "uk", "auto"]
        if engine.startswith("gigaam"):
            codes = ["ru"]
        return [{"key": "language", "type": "combobox", "options": codes,
                 "option_labels": {code: "Language " + code for code in codes},
                 "default": codes[0], "enabled": not engine.startswith("gigaam"),
                 "help_ru": "Только русский" if engine.startswith("gigaam") else "Доступные языки",
                 "help_en": "Russian only" if engine.startswith("gigaam") else "Available languages"}]

    def load_settings(self, component_id):
        return dict(self.values.get(component_id.split(":", 1)[1], {}))

    def save_component_settings(self, component_id, values):
        self.values[component_id.split(":", 1)[1]] = dict(values)
        return {"ok": True}


def _language_catalog(monkeypatch):
    catalog = _LanguageCatalog()
    monkeypatch.setattr("controllers.gui.microphone_settings_controller.services",
                        lambda: SimpleNamespace(get_optional=lambda contract: catalog))
    return catalog


def test_common_asr_language_field_changes_with_engine_without_writing(panel, monkeypatch):
    root, controller, _ = panel
    catalog = _language_catalog(monkeypatch)
    root.recognizer_combobox.addItems(["google", "whisper", "gigaam", "gigaam_onnx"])
    for engine, expected, editable in [("google", "uk-UA", True), ("whisper", "auto", True),
                                       ("gigaam", "ru", False), ("gigaam_onnx", "ru", False)]:
        root.recognizer_combobox.setCurrentText(engine)
        controller._refresh_asr_language()
        assert root.asr_language_combobox.currentData() == expected
        assert root.asr_language_combobox.isEnabled() == editable
        assert root.asr_language_combobox.currentText() == "Language " + expected
        assert root.asr_language_hint.text()
    assert catalog.values["google"] == {"language": "uk-UA", "custom": 7}
    controller.event_bus.emit.assert_not_called()


def test_language_change_saves_raw_code_preserves_other_options_and_applies_live(panel, monkeypatch):
    from core.events import Events
    root, controller, _ = panel
    catalog = _language_catalog(monkeypatch)
    root.recognizer_combobox.addItem("google")
    controller._refresh_asr_language()
    index = root.asr_language_combobox.findData("ru-RU")
    root.asr_language_combobox.setCurrentIndex(index)
    controller._on_asr_language_changed(index)
    assert catalog.values["google"] == {"language": "ru-RU", "custom": 7}
    assert controller.event_bus.emit.call_args.args == (
        Events.Speech.SET_RECOGNIZER_OPTION,
        {"engine": "google", "key": "language", "value": "ru-RU"},
    )


def test_failed_language_save_restores_saved_selection_and_does_not_apply(panel, monkeypatch):
    root, controller, _ = panel
    catalog = _language_catalog(monkeypatch)
    catalog.save_component_settings = lambda *args: {"ok": False, "errors": {"language": "locked file"}}
    root.recognizer_combobox.addItem("google")
    controller._refresh_asr_language()
    index = root.asr_language_combobox.findData("ru-RU")
    root.asr_language_combobox.setCurrentIndex(index)
    controller._on_asr_language_changed(index)
    assert root.asr_language_combobox.currentData() == "uk-UA"
    assert "locked file" in root.asr_language_hint.text()
    controller.event_bus.emit.assert_not_called()


def test_language_control_disables_when_no_engine_is_available(panel, monkeypatch):
    root, controller, _ = panel
    _language_catalog(monkeypatch)
    root.asr_language_combobox.setToolTip('Previous model language')
    controller._refresh_asr_language()
    assert not root.asr_language_combobox.isEnabled()
    assert root.asr_language_combobox.count() == 0
    assert root.asr_language_combobox.placeholderText()
    assert not root.asr_language_combobox.toolTip()


def test_language_control_is_inside_recognition_parameters(panel):
    root, _, _ = panel
    assert root.asr_recognition_parameters_card.isAncestorOf(root.asr_language_combobox)
    assert root.asr_recognition_parameters_card.isAncestorOf(root.asr_language_hint)


def test_model_without_language_options_has_label_without_fake_value(panel, monkeypatch):
    root, controller, _ = panel
    catalog = _language_catalog(monkeypatch)
    catalog.settings_schema = lambda _component: [{'key': 'language', 'options': []}]
    root.recognizer_combobox.addItem('unknown')
    controller._refresh_asr_language()
    assert not root.asr_language_combobox.isEnabled()
    assert root.asr_language_combobox.count() == 0
    assert root.asr_language_combobox.placeholderText()
    controller.event_bus.emit.assert_not_called()


def test_ai_hub_language_labels_keep_codes_and_fixed_language_is_locked(panel):
    from ui.windows.ai_hub.schema_renderer import SchemaForm
    field = _LanguageCatalog().settings_schema("asr:gigaam")[0]
    form = SchemaForm([field])
    combo = form._widgets["language"]
    assert combo.currentText() == "Language ru"
    assert form.values()["language"] == "ru"
    assert not combo.isEnabled()
    form.close()
    form.deleteLater()


def test_active_recognition_restarts_worker_with_new_language(panel, monkeypatch):
    from core.events import Events
    root, controller, _ = panel
    _language_catalog(monkeypatch)
    root.settings["MIC_ACTIVE"] = True
    root.recognizer_combobox.addItem("google")
    controller._refresh_asr_language()
    index = root.asr_language_combobox.findData("ru-RU")
    controller._on_asr_language_changed(index)
    calls = [call.args for call in controller.event_bus.emit.call_args_list]
    assert calls == [(Events.Speech.SET_RECOGNIZER_OPTION,
                      {"engine": "google", "key": "language", "value": "ru-RU"}),
                     (Events.Speech.RESTART_SPEECH_RECOGNITION, {"full_restart": True})]


def test_language_cannot_change_during_capture_and_fixed_model_stays_locked(panel, monkeypatch):
    root, controller, _ = panel
    _language_catalog(monkeypatch)
    root.recognizer_combobox.addItems(["google", "gigaam"])
    controller._refresh_asr_language()
    controller._set_input_mode_enabled(False)
    assert not root.asr_language_combobox.isEnabled()
    controller._refresh_asr_language()
    assert not root.asr_language_combobox.isEnabled()
    controller._set_input_mode_enabled(True)
    assert root.asr_language_combobox.isEnabled()
    root.recognizer_combobox.setCurrentText("gigaam")
    controller._refresh_asr_language()
    controller._set_input_mode_enabled(True)
    assert not root.asr_language_combobox.isEnabled()
