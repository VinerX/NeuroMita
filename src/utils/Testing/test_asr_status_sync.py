from __future__ import annotations

import time

from controllers.gui.asr_events_controller import AsrEventsController
from controllers.gui.microphone_settings_controller import MicrophoneSettingsController
from controllers.gui import microphone_settings_logic
from core.events import Event, Events


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, name, data=None):
        self.events.append((name, data))


class _Signal:
    def __init__(self):
        self.payloads = []
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, slot):
        if slot not in self._slots:
            raise TypeError
        self._slots.remove(slot)

    def emit(self, payload):
        self.payloads.append(payload)
        for slot in tuple(self._slots):
            slot(payload)


class _Label:
    def __init__(self):
        self.text = ""
        self.style = ""

    def setText(self, text):
        self.text = text

    def setStyleSheet(self, style):
        self.style = style


def test_initialized_event_replaces_stale_not_ready_cache_before_render():
    controller = AsrEventsController.__new__(AsrEventsController)
    controller._asr_initializing = True
    controller._asr_error = "old error"
    controller._init_engine = "whisper"
    controller._settings_cache = {"RECOGNIZER_TYPE": "whisper"}
    controller._installed_cache = {}
    controller._ready_cache = (False, time.time())
    controller.event_bus = _Bus()
    observed = []
    controller._set_pill = lambda kind: observed.append(("pill", kind))
    controller._sync_indicator = lambda force=False: observed.append(
        ("sync", force, controller._ready_cache[0])
    )

    controller._on_asr_initialized(Event(Events.Speech.ASR_MODEL_INITIALIZED))

    assert controller._ready_cache[0] is True
    assert controller._installed_cache["whisper"][0] is True
    assert observed == [("pill", "ready"), ("sync", True, True)]
    assert controller.event_bus.events == [(Events.GUI.UPDATE_STATUS_COLORS, None)]


def test_late_settings_page_refresh_renders_the_current_ready_state():
    signal = _Signal()
    status_label = object()
    controller = AsrEventsController.__new__(AsrEventsController)
    controller.view = type(
        "_View",
        (),
        {"asr_set_pill": signal, "asr_init_status": status_label},
    )()
    controller.event_bus = _Bus()
    controller._settings_cache = {
        "MIC_ACTIVE": True,
        "RECOGNIZER_TYPE": "whisper",
    }
    controller._asr_installing = False
    controller._asr_initializing = True
    controller._asr_error = "stale startup state"
    controller._init_engine = "whisper"
    controller._pill_kind = None
    controller._installed_cache = {"whisper": (True, time.time())}
    controller._installed_ttl_sec = 10.0
    controller._ready_cache = (True, time.time())
    controller._ready_ttl_sec = 0.8
    controller._last_state = "green"
    controller._last_tooltip = "old"

    controller._read_runtime_ready = lambda: True

    controller._on_asr_status_refresh(Event(Events.Speech.REFRESH_ASR_STATUS))

    assert controller._asr_initializing is False
    assert controller._asr_error is None
    assert signal.payloads[-1]["label"] is status_label
    assert signal.payloads[-1]["kind"] == "ok"
    assert controller._pill_kind == "ready"
    assert controller.event_bus.events[-1][1]["state"] == "green"


def test_microphone_settings_restart_requests_full_asr_restart():
    controller = MicrophoneSettingsController.__new__(MicrophoneSettingsController)
    controller.event_bus = _Bus()
    controller.view = type("_View", (), {"settings": {"MIC_ACTIVE": True}})()

    controller._on_restart_asr()

    assert controller.event_bus.events == [
        (Events.Speech.RESTART_SPEECH_RECOGNITION, {"full_restart": True})
    ]


def test_wiring_lazy_settings_page_replaces_reset_with_live_ready_status(monkeypatch):
    bus = _Bus()
    signal = _Signal()
    status_label = _Label()
    view = type(
        "_View",
        (),
        {"asr_set_pill": signal, "asr_init_status": status_label},
    )()
    controller = AsrEventsController.__new__(AsrEventsController)
    controller.view = view
    controller.event_bus = bus
    controller._settings_cache = {
        "MIC_ACTIVE": True,
        "RECOGNIZER_TYPE": "whisper",
    }
    controller._asr_installing = False
    controller._asr_initializing = True
    controller._asr_error = None
    controller._init_engine = "whisper"
    controller._pill_kind = None
    controller._installed_cache = {}
    controller._installed_ttl_sec = 10.0
    controller._ready_cache = (None, 0.0)
    controller._ready_ttl_sec = 0.8
    controller._last_state = None
    controller._last_tooltip = None
    controller._read_runtime_ready = lambda: True

    original_emit = bus.emit

    def emit_and_dispatch(name, data=None):
        original_emit(name, data)
        if name == Events.Speech.REFRESH_ASR_STATUS:
            controller._on_asr_status_refresh(Event(name, data))

    bus.emit = emit_and_dispatch
    monkeypatch.setattr(microphone_settings_logic, "get_event_bus", lambda: bus)

    microphone_settings_logic.wire_microphone_settings_logic(view)

    assert any(payload["text"] == "—" for payload in signal.payloads)
    assert signal.payloads[-1]["kind"] == "ok"
    assert status_label.text != "—"
    assert controller._pill_kind == "ready"
