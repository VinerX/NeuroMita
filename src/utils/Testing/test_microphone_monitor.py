import time
from threading import Event
from unittest.mock import Mock

import numpy as np

from core.audio_input import ASRInputDevice
from services.microphone_monitor import MicrophoneMonitor, MonitorBuffer


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert predicate()


class AudioBackend:
    def __init__(self, *, output_fails=False, input_name="Desk microphone"):
        self.output_fails = output_fails
        self.input_name = input_name
        self.streams = []
        self.played = None
        self.opening = None

    def query_devices(self, index=None, kind=None):
        if kind == "input":
            return {"name": self.input_name, "default_samplerate": 48000}
        return {"default_samplerate": 44100, "max_output_channels": 2}

    def stream(self, kind, **kwargs):
        backend = self

        class Stream:
            active = False
            closed = False

            def __enter__(self):
                if backend.opening and kind == "input":
                    backend.opening.wait(1)
                if kind == "output" and backend.output_fails:
                    raise RuntimeError("No output")
                self.active = True
                if kind == "input":
                    kwargs["callback"](
                        np.full((1024, 1), 0.2, dtype=np.float32), 1024, None, None
                    )
                else:
                    backend.played = np.zeros((512, 2), dtype=np.float32)
                    kwargs["callback"](backend.played, 512, None, None)
                return self

            def __exit__(self, *args):
                self.active = False
                self.closed = True

        stream = Stream()
        stream.kind, stream.options = kind, kwargs
        self.streams.append(stream)
        return stream

    def InputStream(self, **kwargs):
        return self.stream("input", **kwargs)

    def OutputStream(self, **kwargs):
        return self.stream("output", **kwargs)


def test_monitor_plays_selected_input_at_output_native_rate_and_closes_streams():
    backend = AudioBackend()
    events = Mock()
    monitor = MicrophoneMonitor(backend, event_bus=events)
    try:
        assert monitor.start(ASRInputDevice(24, "Desk microphone", "WASAPI"))
        wait_for(lambda: backend.played is not None)
        assert backend.streams[0].options["device"] == 24
        assert backend.streams[1].options["samplerate"] == 44100
        np.testing.assert_allclose(backend.played, 0.2, atol=1e-6)
        assert monitor.snapshot().level > 0
        assert not monitor.start(ASRInputDevice(25, "Other", "WASAPI"))
    finally:
        monitor.close()
    assert all(s.closed for s in backend.streams)
    assert monitor.snapshot().phase == "stopped"
    assert [call.args[1]["active"] for call in events.emit.call_args_list] == [
        True,
        False,
    ]


def test_output_failure_closes_input_and_reports_error():
    backend = AudioBackend(output_fails=True)
    monitor = MicrophoneMonitor(backend)
    monitor.start(ASRInputDevice(24, "Desk microphone", "WASAPI"))
    wait_for(lambda: monitor.snapshot().phase == "error")
    assert backend.streams[0].closed
    monitor.close()


def test_stop_during_open_does_not_start_output_or_late_listening():
    backend = AudioBackend()
    backend.opening = Event()
    monitor = MicrophoneMonitor(backend)
    monitor.start(ASRInputDevice(24, "Desk microphone", "WASAPI"))
    wait_for(lambda: bool(backend.streams))
    monitor.stop()
    backend.opening.set()
    monitor.close()
    assert len(backend.streams) == 1
    assert backend.streams[0].closed
    assert monitor.snapshot().phase == "stopped"


def test_reused_device_index_is_rejected_without_opening_streams():
    backend = AudioBackend(input_name="Different microphone")
    monitor = MicrophoneMonitor(backend)
    monitor.start(ASRInputDevice(24, "Desk microphone", "WASAPI"))
    wait_for(lambda: monitor.snapshot().phase == "error")
    assert not backend.streams
    monitor.close()


def test_endpoint_selection_resolves_current_index_before_monitoring(monkeypatch):
    backend = AudioBackend(input_name="Renamed microphone")
    resolver = Mock(
        return_value=ASRInputDevice(
            39, "Renamed microphone", "WASAPI", uid="endpoint-A"
        )
    )
    monkeypatch.setattr(
        "services.microphone_monitor.resolve_asr_input_device", resolver
    )
    monitor = MicrophoneMonitor(backend)
    try:
        monitor.start(ASRInputDevice(24, "Old name", "WASAPI", uid="endpoint-A"))
        wait_for(lambda: backend.played is not None)
        assert backend.streams[0].options["device"] == 39
        assert resolver.call_args.kwargs["requested_uid"] == "endpoint-A"
    finally:
        monitor.close()


def test_resampling_is_continuous_across_reads_and_queue_is_bounded():
    buffer = MonitorBuffer(48000, 44100)
    samples = np.linspace(-0.5, 0.5, 2000, dtype=np.float32)
    buffer.push(samples)
    first, second = buffer.read(400), buffer.read(400)
    positions = np.arange(800) * 48000 / 44100
    expected = np.interp(positions, np.arange(2000), samples)
    np.testing.assert_allclose(np.concatenate((first, second)), expected, atol=1e-6)
    buffer.push(np.full(20000, 0.7, dtype=np.float32))
    assert len(buffer._samples) == buffer.limit
    np.testing.assert_allclose(buffer.read(50), 0.7)


def test_microphone_test_temporarily_blocks_gate_without_changing_mic_setting(
    monkeypatch,
):
    from threading import RLock
    from types import SimpleNamespace
    from controllers.speech_controller import SpeechController
    from handlers.asr_handler import SpeechRecognition
    from handlers.asr_input_gate import ASRInputGate
    from core.events import Event, Events

    controller = SpeechController.__new__(SpeechController)
    controller.settings = {"MIC_ACTIVE": True, "ASR_INPUT_MODE": "vad"}
    controller._state_lock = RLock()
    controller._speaking_window = SimpleNamespace(blocked_until=lambda: 0)
    controller._game_transcripts = lambda: SimpleNamespace(
        discard_invalid=lambda fn: None
    )
    gate = ASRInputGate()
    monkeypatch.setattr(SpeechRecognition, "_input_gate", gate)
    monkeypatch.setattr(SpeechRecognition, "publish_input_gate", lambda: None)
    controller._sync_input_gate()
    assert gate.snapshot()["enabled"]
    controller._on_microphone_test_changed(
        Event(
            Events.Speech.MICROPHONE_TEST_CHANGED,
            {"active": True, "session_id": "test"},
        )
    )
    assert not gate.snapshot()["enabled"]
    assert controller.settings["MIC_ACTIVE"]
    controller._on_microphone_test_changed(
        Event(
            Events.Speech.MICROPHONE_TEST_CHANGED,
            {"active": False, "session_id": "test"},
        )
    )
    assert gate.snapshot()["enabled"]
