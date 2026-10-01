import asyncio
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from handlers import asr_audio_capture as capture


def gate():
    from handlers.asr_input_gate import ASRInputGate
    result = ASRInputGate(clock=lambda: 10.0)
    result.configure(input_mode="ptt", enabled=True)
    return result


def segmenter(g, **kwargs):
    return capture.AudioSegmenter(capture.AudioCaptureConfig(**kwargs), g)


def feed(s, count, probability=0.9, value=1.0):
    results = []
    for _ in range(count):
        result = s.feed(np.full((512, 1), value, np.float32), probability)
        if result is not None:
            results.append(result)
    return results


def test_ptt_holds_across_silence_then_release_collects_four_tail_chunks():
    g = gate()
    s = segmenter(g)
    feed(s, 10, 0.0, 0.2)
    assert g.ptt(active=True, session_id="game#1", generation=1)
    assert feed(s, 12) == []
    assert feed(s, 30, 0.0) == []
    assert g.ptt(active=False, session_id="game#1", generation=2)
    assert feed(s, 3, 0.0) == []
    audio, context = feed(s, 1, 0.0)[0]
    assert len(audio) == 3200 + (12 + 30 + 4) * 512
    assert np.all(audio[:3200] == np.float32(0.2))
    assert context["session_id"] == "game#1"
    assert context["input_mode"] == "ptt"
    assert g.valid(context)  # Release never invalidates completed text.


@pytest.mark.parametrize("speech_chunks", [0, 1, 5])
def test_ptt_silence_or_too_short_voiced_audio_is_dropped(speech_chunks):
    g = gate()
    s = segmenter(g)
    g.ptt(active=True, session_id="game#1", generation=1)
    feed(s, speech_chunks)
    feed(s, 20, 0.0)
    g.ptt(active=False, session_id="game#1", generation=2)
    assert feed(s, 4, 0.0) == []


def test_duration_limit_emits_once_and_requires_another_press():
    g = gate()
    s = segmenter(g, max_speech_duration=0.64)
    g.ptt(active=True, session_id="game#1", generation=1)
    audio, _ = feed(s, 20)[0]
    assert len(audio) == 10240
    assert feed(s, 100) == []
    g.ptt(active=False, session_id="game#1", generation=2)
    feed(s, 4, 0.0)
    g.ptt(active=True, session_id="game#1", generation=3)
    assert len(feed(s, 20)) == 1


def test_stale_release_and_duplicate_press_cannot_change_newer_state():
    g = gate()
    assert g.ptt(active=True, session_id="game#1", generation=3)
    assert not g.ptt(active=False, session_id="game#1", generation=2)
    assert not g.ptt(active=True, session_id="game#1", generation=3)
    assert g.snapshot()["active"]
    assert g.ptt(active=False, session_id="game#1", generation=3)
    assert not g.ptt(active=True, session_id="game#1", generation=3)


@pytest.mark.parametrize("cancel", ["disconnect", "mute", "mode", "disabled", "reset"])
def test_cancel_discards_partial_audio_and_invalidates_inflight_text(cancel):
    g = gate()
    s = segmenter(g)
    g.ptt(active=True, session_id="game#1", generation=1)
    context = g.snapshot()
    feed(s, 12)
    if cancel == "disconnect":
        g.disconnect("game#1")
        assert not g.ptt(active=True, session_id="game#1", generation=99)
    elif cancel == "mute":
        g.configure(blocked_until=11.0)
    elif cancel == "mode":
        g.configure(input_mode="vad")
    elif cancel == "disabled":
        g.configure(enabled=False)
    else:
        g.reset()
    assert feed(s, 4, 0.0) == []
    assert not g.valid(context)


def test_new_session_cancels_old_audio_and_old_release_cannot_steal_owner():
    g = gate()
    s = segmenter(g)
    g.ptt(active=True, session_id="old", generation=50)
    feed(s, 12)
    g.ptt(active=True, session_id="new", generation=1)
    assert not g.ptt(active=False, session_id="old", generation=51)
    assert feed(s, 12) == []
    g.ptt(active=False, session_id="new", generation=2)
    audio, context = feed(s, 4, 0.0)[0]
    assert context["session_id"] == "new"
    assert len(audio) == 16 * 512


def test_explicit_vad_still_finalizes_on_silence():
    from handlers.asr_input_gate import ASRInputGate
    g = ASRInputGate()
    g.configure(input_mode="vad")
    s = segmenter(g)
    feed(s, 12)
    assert len(feed(s, 19, 0.0)) == 1


def test_worker_applies_gate_without_restarting_capture():
    from handlers.ai_engine.services.asr_service import ASRService
    worker = ASRService(emit_event=lambda *_: None)
    worker._input_gate._clock = lambda: 10.0
    worker._stop_live_internal = AsyncMock()
    g = gate()
    g.ptt(active=True, session_id="game#1", generation=1)
    state = g.snapshot()
    assert asyncio.run(worker.handle("set_input_gate", state)) is True
    assert asyncio.run(worker.handle("set_input_gate", {**state, "revision": 0, "active": False})) is False
    assert worker._input_gate.snapshot()["active"] is True
    worker._stop_live_internal.assert_not_called()


@pytest.mark.parametrize("updates", [
    {"active": "false"}, {"generation": True}, {"generation": -1},
    {"generation": 1.5}, {"session_id": "spoofed"},
])
def test_action_rejects_malformed_or_foreign_session(updates):
    from game_connections.handlers import build_action_registry
    handler = build_action_registry().get("asr_ptt_state")
    assert handler is not None
    bus = SimpleNamespace(emit=lambda *args: pytest.fail("invalid request emitted"))
    server = SimpleNamespace(owns_player_input=lambda _: True, send_error=AsyncMock())
    ctx = SimpleNamespace(server=server, event_bus=bus, client_id="game#1", writer=object())
    request = {"active": True, "generation": 1, "session_id": "game#1", **updates}
    asyncio.run(handler.handle(request, ctx))
    server.send_error.assert_awaited_once()


def test_action_emits_only_for_current_player_input_owner():
    from game_connections.handlers import build_action_registry
    from core.events import Events
    handler = build_action_registry().get("asr_ptt_state")
    assert handler is not None
    events = []
    server = SimpleNamespace(owns_player_input=lambda _: True, send_error=AsyncMock())
    ctx = SimpleNamespace(server=server, event_bus=SimpleNamespace(emit=lambda *args: events.append(args)), client_id="game#1", writer=object())
    request = {"active": True, "generation": 1, "session_id": "game#1"}
    asyncio.run(handler.handle(request, ctx))
    assert events == [(Events.Speech.ASR_PTT_STATE, request)]
    server.owns_player_input = lambda _: False
    asyncio.run(handler.handle(request, ctx))
    assert len(events) == 1


def test_heartbeat_renews_press_without_splitting_audio():
    g = gate()
    s = segmenter(g)
    g.ptt(active=True, session_id="game#1", generation=1)
    feed(s, 12)
    press = g.snapshot()["press_generation"]
    g.ptt(active=True, session_id="game#1", generation=2)
    assert g.snapshot()["press_generation"] == press
    assert feed(s, 12) == []
    g.ptt(active=False, session_id="game#1", generation=3)
    audio, _ = feed(s, 4, 0.0)[0]
    assert len(audio) == 28 * 512


def test_rapid_repress_preserves_previous_completed_phrase():
    g = gate()
    s = segmenter(g)
    g.ptt(active=True, session_id="game#1", generation=1)
    feed(s, 12)
    g.ptt(active=False, session_id="game#1", generation=2)
    feed(s, 1, 0.0)
    g.ptt(active=True, session_id="game#1", generation=3)
    previous = feed(s, 1)
    assert len(previous) == 1
    assert len(previous[0][0]) == 13 * 512
    assert previous[0][1]["press_generation"] == 1
    feed(s, 11)
    g.ptt(active=False, session_id="game#1", generation=4)
    current = feed(s, 4, 0.0)
    assert len(current) == 1
    assert len(current[0][0]) == 16 * 512
    assert current[0][1]["press_generation"] == 3


def test_reset_cannot_be_reopened_by_held_heartbeat():
    g = gate()
    g.ptt(active=True, session_id="game#1", generation=1)
    g.reset()
    g.ptt(active=True, session_id="game#1", generation=2)
    assert not g.snapshot()["active"]
    g.ptt(active=False, session_id="game#1", generation=3)
    g.ptt(active=True, session_id="game#1", generation=4)
    assert g.snapshot()["active"]


def test_lease_expiration_cancels_audio_and_late_inference():
    from handlers.asr_input_gate import ASRInputGate
    now = [0.0]
    g = ASRInputGate(clock=lambda: now[0])
    g.configure(input_mode="ptt")
    s = segmenter(g)
    g.ptt(active=True, session_id="game#1", generation=1)
    context = g.snapshot()
    feed(s, 12)
    now[0] = 2.0
    g.ptt(active=True, session_id="game#1", generation=2)
    now[0] = 4.0
    assert g.snapshot()["active"]
    now[0] = 5.0
    assert feed(s, 4, 0.0) == []
    assert not g.valid(context)


def test_cancelled_release_discards_instead_of_collecting_tail():
    g = gate()
    s = segmenter(g)
    g.ptt(active=True, session_id="game#1", generation=1)
    context = g.snapshot()
    feed(s, 12)
    assert g.ptt(active=False, session_id="game#1", generation=2, cancelled=True)
    assert feed(s, 4, 0.0) == []
    assert not g.valid(context)


def test_press_during_mita_speech_requires_release_before_fresh_press():
    g = gate()
    g.configure(blocked_until=11.0)
    g.ptt(active=True, session_id="game#1", generation=1)
    assert not g.snapshot()["active"]
    g._clock = lambda: 12.0
    assert not g.snapshot()["active"]
    assert not g.ptt(active=True, session_id="game#1", generation=1)
    g.ptt(active=True, session_id="game#1", generation=2)
    assert not g.snapshot()["active"]
    g.ptt(active=False, session_id="game#1", generation=3)
    assert g.ptt(active=True, session_id="game#1", generation=4)
    assert g.snapshot()["active"]


def test_capture_keeps_reading_while_recognition_is_busy(monkeypatch):
    sd = types.ModuleType("sounddevice")
    state = {"reads": 0, "opens": 0}
    later_read = threading.Event()
    completed = []

    class Stream:
        def __init__(self, **_):
            state["opens"] += 1
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def read(self, size):
            state["reads"] += 1
            if state["reads"] > 31:
                later_read.set()
            value = 1.0 if state["reads"] <= 12 else 0.0
            return np.full((size, 1), value, np.float32), False

    sd.InputStream = Stream
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", sd)
    monkeypatch.setattr(capture, "refresh_portaudio_catalog", lambda _: None)
    async def recognize(audio, rate, context):
        assert later_read.wait(1.0), "Microphone stopped reading during transcription"
        completed.append((len(audio), context["input_mode"]))
    logger = SimpleNamespace(info=lambda *_: None, warning=lambda *_: None)
    from handlers.asr_input_gate import ASRInputGate
    automatic_gate = ASRInputGate()
    automatic_gate.configure(input_mode="vad")
    asyncio.run(capture.AudioCaptureService(logger).run(
        microphone_index=0, config=capture.AudioCaptureConfig(),
        is_active=lambda: state["reads"] < 40,
        speech_probability=lambda audio, _: float(audio[0]),
        on_segment=AsyncMock(), on_segment_context=recognize,
        background_transcription=True,
        input_gate=automatic_gate,
    ))
    assert state["opens"] == 1
    assert completed == [(31 * 512, "vad")]


@pytest.mark.parametrize("cancel", [False, True])
def test_worker_preserves_release_text_but_cancellation_during_inference_discards_it(monkeypatch, cancel):
    from handlers.ai_engine.services.asr_service import ASRService
    g = gate()
    g.ptt(active=True, session_id="game#1", generation=1)
    context = g.snapshot()
    emitted = []
    worker = ASRService(emit_event=lambda *args: emitted.append(args))
    worker._input_gate = g
    worker._logger = SimpleNamespace(info=lambda *_: None, warning=lambda *_: None)
    trigger = threading.Event()
    finished = threading.Event()

    async def transcribe(audio, rate):
        g.ptt(active=False, session_id="game#1", generation=2, cancelled=cancel)
        return "player phrase"
    rec = SimpleNamespace(init=AsyncMock(return_value=True), transcribe=transcribe, cleanup=lambda: None)
    monkeypatch.setattr(worker, "_get_recognizer", lambda _: rec)
    monkeypatch.setattr(worker, "_get_vad_model", AsyncMock(return_value=object()))

    async def run_capture(self, **kwargs):
        kwargs["on_ready"]()
        while not trigger.is_set():
            await asyncio.sleep(0.001)
        assert kwargs["background_transcription"] is True
        await kwargs["on_segment_context"](np.ones(8192), 16000, context)
        finished.set()
        while worker._active:
            await asyncio.sleep(0.001)
    monkeypatch.setattr(capture.AudioCaptureService, "run", run_capture)

    async def run():
        assert await worker._start_live_internal(
            engine_id="test", mic_index=0, engine_settings={}, sample_rate=16000,
            chunk_size=512, vad_threshold=0.5, silence_timeout=0.6,
            pre_buffer_duration=0.4, max_speech_duration=30,
        )
        trigger.set()
        assert await asyncio.to_thread(finished.wait, 2.0)
        await worker._stop_live_internal()
    asyncio.run(run())
    texts = [data for name, data in emitted if name == "text"]
    assert texts == ([] if cancel else [{"text": "player phrase", "capture_context": context}])


def test_controller_routes_completed_ptt_to_captured_session_after_release(monkeypatch):
    from utils.Testing.test_asr_session_routing import _Speech
    from handlers.asr_handler import SpeechRecognition
    from core.events import Event
    g = gate()
    g.ptt(active=True, session_id="game#1", generation=1)
    context = g.snapshot()
    g.ptt(active=False, session_id="game#1", generation=2)
    monkeypatch.setattr(SpeechRecognition, "_input_gate", g)
    speech = _Speech(turn_owner="other#2")
    speech.ctrl._on_speech_text_recognized(Event("speech.text_recognized", {
        "text": "phrase", "capture_context": context,
    }))
    assert speech.sent_to_game()[0]["client_id"] == "game#1"
    g.disconnect("game#1")
    speech.ctrl._on_speech_text_recognized(Event("speech.text_recognized", {
        "text": "cancelled phrase", "capture_context": context,
    }))
    assert len(speech.sent_to_game()) == 1


def test_settings_broadcast_has_safe_default_mode_and_microphone_state():
    from controllers.server_controller import ServerController
    ctrl = object.__new__(ServerController)
    ctrl.settings = SimpleNamespace(revision=0)
    ctrl.settings_to_send = ["ASR_INPUT_MODE", "MIC_ACTIVE"]
    ctrl._collect_characters_stats = lambda: {}
    values = {}
    ctrl._get_setting = lambda key, default=None: values.get(key, default)
    body = ctrl._prepare_loaded_settings_body()
    assert body["settings"]["ASR_INPUT_MODE"] == "radio"
    assert body["settings"]["MIC_ACTIVE"] is False
    values.update(ASR_INPUT_MODE=" PTT ", MIC_ACTIVE=True)
    body = ctrl._prepare_loaded_settings_body()
    assert body["settings"]["ASR_INPUT_MODE"] == "ptt"
    assert body["settings"]["MIC_ACTIVE"] is True


def test_microphone_ui_mode_persists_and_reflects_external_changes(monkeypatch):
    from PyQt6.QtWidgets import QApplication, QComboBox
    from controllers.gui.microphone_settings_controller import MicrophoneSettingsController
    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItem("VAD", "vad")
    combo.addItem("PTT", "ptt")
    combo.addItem("Radio", "radio")
    ctrl = object.__new__(MicrophoneSettingsController)
    ctrl.view = SimpleNamespace(asr_input_mode_combobox=combo)
    saved = []
    ctrl._save_setting = lambda *args: saved.append(args)
    combo.setCurrentIndex(1)
    ctrl._on_input_mode_changed(1)
    assert saved == [("ASR_INPUT_MODE", "ptt")]
    ctrl._reflect_external_setting(SimpleNamespace(key="ASR_INPUT_MODE", value="invalid"))
    assert combo.currentData() == "radio"
    assert saved == [("ASR_INPUT_MODE", "ptt")]
    assert app is not None


@pytest.mark.parametrize("mode, permitted", [("vad", True), ("ptt", False)])
def test_ptt_is_half_duplex_even_when_vad_speech_muting_is_disabled(monkeypatch, mode, permitted):
    from controllers.speech_controller import SpeechController
    from handlers.asr_handler import SpeechRecognition
    g = gate()
    monkeypatch.setattr(SpeechRecognition, "_input_gate", g)
    monkeypatch.setattr(SpeechRecognition, "publish_input_gate", lambda: None)
    ctrl = object.__new__(SpeechController)
    ctrl.settings = {"MIC_ACTIVE": True, "ASR_INPUT_MODE": mode, "MIC_MUTE_WHILE_SPEAKING": False}
    ctrl._speaking_window = SimpleNamespace(blocked_until=lambda: 11.0)
    ctrl._sync_input_gate()
    assert g.snapshot()["permitted"] is permitted


def test_old_capture_generation_cannot_stop_replacement_capture(monkeypatch):
    from handlers.ai_engine.services.asr_service import ASRService
    worker = ASRService(emit_event=lambda *_: None)
    worker._logger = SimpleNamespace(info=lambda *_: None)
    finish_old = threading.Event()
    flags = []
    rec = SimpleNamespace(init=AsyncMock(return_value=True), cleanup=lambda: None)
    monkeypatch.setattr(worker, "_get_recognizer", lambda _: rec)
    monkeypatch.setattr(worker, "_get_vad_model", AsyncMock(return_value=object()))
    async def run_capture(self, **kwargs):
        flags.append(kwargs["is_active"])
        kwargs["on_ready"]()
        while not finish_old.is_set():
            await asyncio.sleep(0.001)
    monkeypatch.setattr(capture.AudioCaptureService, "run", run_capture)
    async def run():
        await worker._start_live_internal(
            engine_id="test", mic_index=0, engine_settings={}, sample_rate=16000,
            chunk_size=512, vad_threshold=0.5, silence_timeout=0.6,
            pre_buffer_duration=0.4, max_speech_duration=30,
        )
        try:
            worker._capture_generation += 1
            worker._active = True  # A replacement stream has become active.
            assert not flags[0]()
            finish_old.set()
            await worker._task
            assert worker._active
        finally:
            finish_old.set()
            worker._active = False
    asyncio.run(run())


def test_controller_speech_and_disconnect_events_cancel_gate(monkeypatch):
    from controllers.speech_controller import SpeechController
    from handlers.asr_handler import SpeechRecognition
    from managers.speaking_window import SpeakingWindow
    from core.events import Event
    now = [10.0]
    g = gate()
    g._clock = lambda: now[0]
    monkeypatch.setattr(SpeechRecognition, "_input_gate", g)
    published = []
    monkeypatch.setattr(SpeechRecognition, "publish_input_gate", lambda: published.append(g.snapshot()))
    ctrl = object.__new__(SpeechController)
    ctrl.settings = {"ASR_INPUT_MODE": "ptt", "MIC_ACTIVE": True, "MIC_MUTE_WHILE_SPEAKING": True}
    ctrl._speaking_window = SpeakingWindow(clock=lambda: now[0])
    ctrl._player_turn_owner = lambda: "game#1"
    def press(active, generation):
        ctrl._on_asr_ptt_state(Event("asr_ptt_state", {
            "active": active, "generation": generation, "session_id": "game#1",
        }))
    press(True, 1)
    context = g.snapshot()
    ctrl._on_mita_speaking_window(Event("mita_speaking_window", {
        "source": "game#1", "active": True, "speech_id": "mita-1",
    }))
    assert not g.valid(context)
    assert not g.snapshot()["active"]
    ctrl._on_mita_speaking_window(Event("mita_speaking_window", {
        "source": "game#1", "active": False, "speech_id": "mita-1",
    }))
    now[0] = 11.0
    press(True, 2)
    assert not g.snapshot()["active"]
    press(False, 3)
    press(True, 4)
    assert g.snapshot()["active"]
    ctrl._on_client_disconnected(Event("client_disconnected", {"client_id": "game#1"}))
    assert not g.snapshot()["active"]
    press(True, 5)
    assert not g.snapshot()["active"]
    assert published[-1]["active"] is False


def test_reconnected_session_gets_fresh_idle_prebuffer():
    g = gate()
    s = segmenter(g)
    g.ptt(active=True, session_id="old", generation=1)
    feed(s, 12)
    g.disconnect("old")
    feed(s, 10, 0.0, 0.2)
    g.ptt(active=True, session_id="new", generation=2)
    feed(s, 12)
    g.ptt(active=False, session_id="new", generation=3)
    audio, _ = feed(s, 4, 0.0)[0]
    assert len(audio) == 3200 + 16 * 512
    assert np.all(audio[:3200] == np.float32(0.2))
