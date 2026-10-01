from handlers.asr_capture_progress import CaptureProgressTracker, GameCaptureTranscripts
import pytest


def context(press=1, active=True, epoch=0):
    return dict(input_mode="radio", target="game", session_id="game#1",
                press_generation=press, epoch=epoch, active=active, permitted=True)


def test_release_waits_for_buffer_and_all_queued_transcriptions():
    events = []
    tracker = CaptureProgressTracker(events.append)
    c = context()
    tracker.observe(c, c, voiced=True)
    tracker.enqueue(c)
    tracker.observe(context(active=False), c, voiced=False)
    tracker.finish(c)
    assert events[-1]["phase"] == "recognizing"
    tracker.enqueue(c)
    tracker.observe(context(active=False), None, voiced=False)
    assert events[-1]["phase"] == "recognizing"
    tracker.finish(c)
    assert events[-1]["phase"] == "completed"
    assert sum(e["phase"] == "completed" for e in events) == 1


def test_silence_returns_to_hollow_mic_before_segment_finishes():
    events = []
    tracker = CaptureProgressTracker(events.append)
    c = context()
    tracker.observe(c, c, voiced=True)
    assert events[-1]["phase"] == "speech"
    tracker.observe(c, c, voiced=False)
    assert events[-1]["phase"] == "listening"


def test_previous_completion_keeps_new_capture_identity():
    events = []
    tracker = CaptureProgressTracker(events.append)
    old = context()
    tracker.observe(old, old, voiced=True)
    tracker.enqueue(old)
    new = context(press=3)
    tracker.observe(new, new, voiced=True)
    tracker.finish(old)
    assert events[-1]["capture_context"]["press_generation"] == 1
    assert events[-1]["phase"] == "completed"
    tracker.observe(new, new, voiced=False)
    assert events[-1]["capture_context"]["press_generation"] == 3


def test_transcripts_are_cumulative_and_only_complete_once():
    capture = GameCaptureTranscripts()
    c = context()
    assert capture.append(c, "Первая фраза")["text"] == "Первая фраза"
    assert capture.append(c, "Вторая фраза")["text"] == "Первая фраза Вторая фраза"
    final = capture.complete(c)
    assert final["final"] and final["text"] == "Первая фраза Вторая фраза"
    assert capture.complete(c) is None


def test_cancelled_capture_does_not_leak_text_into_next_press():
    capture = GameCaptureTranscripts()
    capture.append(context(), "discard")
    capture.discard_invalid(lambda c: c["epoch"] == 1)
    newer = context(press=3, epoch=1)
    assert capture.complete(newer) is None
    assert capture.append(newer, "new")["text"] == "new"


@pytest.mark.parametrize("mode", ["radio", "ptt"])
@pytest.mark.parametrize("autosend", [False, True])
def test_game_routes_fragments_as_preview_then_one_final_after_completion(monkeypatch, mode, autosend):
    from core.events import Event
    from handlers.asr_handler import SpeechRecognition
    from handlers.asr_input_gate import ASRInputGate
    from utils.Testing.test_asr_session_routing import _Speech
    import threading

    gate = ASRInputGate(clock=lambda: 10)
    gate.configure(input_mode=mode)
    command = gate.radio if mode == "radio" else gate.ptt
    extra = {"target": "game"} if mode == "radio" else {}
    command(active=True, session_id="game#1", generation=1, **extra)
    monkeypatch.setattr(SpeechRecognition, "_input_gate", gate)
    speech = _Speech(turn_owner="game#1")
    speech.ctrl._instant_send_policy = lambda: (autosend, 0.0)
    speech.ctrl._capture_ui_lock = threading.RLock()
    speech.ctrl._capture_phase = "listening"
    speech.ctrl._capture_error = ""
    speech.ctrl.mic_recognition_active = speech.ctrl.asr_is_ready = True
    c = {**gate.snapshot(), "capture_tracking": True}
    for text in ("first", "second"):
        speech.ctrl._on_speech_text_recognized(Event("text", dict(text=text, capture_context=c)))
    assert [p["text"] for p in speech.sent_to_game()] == ["first", "first second"]
    assert not any(p["final"] for p in speech.sent_to_game())
    command(active=False, session_id="game#1", generation=2, **extra)
    speech.ctrl._on_capture_progress(Event("progress", dict(
        phase="completed", capture_context=c, capture_id="0:1", revision=3, pending=0, active=False)))
    final = speech.sent_to_game()[-1]
    assert final["final"] and final["autosend"] == autosend and final["text"] == "first second"
    speech.ctrl._on_capture_progress(Event("progress", dict(
        phase="completed", capture_context=c, capture_id="0:1", revision=3, pending=0, active=False)))
    assert len(speech.sent_to_game()) == 3


def test_completion_cannot_overtake_text_on_event_bus():
    from core.events import EventBus, Events
    import threading

    bus = EventBus()
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    order = []

    def text(event):
        entered.set()
        release.wait(2)
        order.append("text")

    def progress(event):
        order.append("completed")
        completed.set()

    bus.subscribe(Events.Speech.SPEECH_TEXT_RECOGNIZED, text, weak=False)
    bus.subscribe(Events.Speech.ASR_CAPTURE_PROGRESS, progress, weak=False)
    try:
        bus.emit(Events.Speech.SPEECH_TEXT_RECOGNIZED, {})
        assert entered.wait(1)
        bus.emit(Events.Speech.ASR_CAPTURE_PROGRESS, {})
        assert not completed.wait(0.1)
        release.set()
        assert bus.flush()
        assert order == ["text", "completed"]
    finally:
        release.set()
        bus.shutdown()


def test_empty_press_finishes_even_if_capture_loop_missed_the_active_interval():
    events = []
    tracker = CaptureProgressTracker(events.append)
    c = context(active=False)
    tracker.observe(c, None, voiced=False)
    tracker.observe(c, None, voiced=False)
    assert len(events) == 1 and events[0]["phase"] == "completed"


def test_wire_keeps_preview_final_and_status_in_order_for_original_session():
    from utils.Testing.test_asr_session_routing import _Loop, _server, _FakeWriter
    writer, other = _FakeWriter(), _FakeWriter()
    with _Loop() as loop:
        server = _server(loop, {"game#1": writer, "game#2": other})
        for final, revision in ((False, 1), (True, 2)):
            assert server.schedule_send_asr_text(
                client_id="game#1", text="phrase", utterance_id=str(revision), final=final,
                capture_id="0:1", press_generation=1, revision=revision,
                autosend=final).result(2)
        assert server.schedule_send_asr_capture_state(dict(
            client_id="game#1", capture_id="0:1", press_generation=1,
            revision=3, phase="completed", active=False, pending=0)).result(2)
    messages = writer.payloads()
    assert [m["type"] for m in messages] == ["asr_text", "asr_text", "asr_capture_state"]
    assert not messages[0]["autosend"] and not messages[0]["final"]
    assert messages[1]["autosend"] and messages[1]["final"]
    assert all(m["session_id"] == "game#1" and m["capture_id"] == "0:1" for m in messages)
    assert other.payloads() == []
