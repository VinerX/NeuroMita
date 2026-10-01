from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QVBoxLayout

from core.events import Event, Events
from handlers.asr_audio_capture import AudioCaptureConfig, AudioCaptureService, AudioSegmenter
from handlers.asr_input_gate import ASRInputGate, normalize_input_mode
from services.contracts import ASRCaptureState
from ui.widgets.chat_panel import ChatPanel
from ui.widgets.chat_panel_presentation import ChatMicrophoneToggled, ChatPanelActions, ChatPanelState


def feed(segmenter, count, probability=0.0, value=0.0):
    results = []
    for _ in range(count):
        result = segmenter.feed(np.full(512, value, np.float32), probability)
        if result is not None:
            results.append(result)
    return results


def radio():
    gate = ASRInputGate(clock=lambda: 10.0)
    segmenter = AudioSegmenter(AudioCaptureConfig(), gate)
    return gate, segmenter


def test_radio_is_default_and_does_not_capture_before_click():
    gate, segmenter = radio()
    assert normalize_input_mode(None) == normalize_input_mode("invalid") == "radio"
    assert feed(segmenter, 100, 0.9, 1.0) == []
    assert not segmenter._buffer and not segmenter._pre
    assert not gate.snapshot()["active"]


def test_ten_minutes_of_silence_are_bounded_then_each_phrase_finishes_while_radio_stays_on():
    gate, segmenter = radio()
    assert gate.radio(active=True, session_id="desktop", generation=1)
    assert feed(segmenter, round(600 * 16000 / 512)) == []
    assert sum(map(len, segmenter._pre)) == 8000
    assert not segmenter._buffer
    for value in (1.0, 2.0):
        assert feed(segmenter, 12, 0.9, value) == []
        assert feed(segmenter, 15) == []
        audio, context = feed(segmenter, 1)[0]
        assert len(audio) == 8000 + 12 * 512 + 8000
        assert np.all(audio[:8000] == 0)
        assert np.all(audio[-8000:] == 0)
        assert context["target"] == "desktop" and gate.valid(context)
        assert gate.snapshot()["active"]


def test_stop_finishes_pending_phrase_and_cancellation_discards_it():
    gate, segmenter = radio()
    gate.radio(active=True, session_id="desktop", generation=1)
    feed(segmenter, 12, 0.9, 1.0)
    gate.radio(active=False, session_id="desktop", generation=2)
    audio, context = feed(segmenter, 16)[0]
    assert len(audio) == 12 * 512 + 8000 and gate.valid(context)
    gate.radio(active=True, session_id="desktop", generation=3)
    feed(segmenter, 12, 0.9, 1.0)
    gate.radio(active=False, session_id="desktop", generation=4, cancelled=True)
    assert feed(segmenter, 16) == []
    assert not gate.valid(context)


def test_lease_renewal_keeps_radio_on_but_never_reopens_an_expired_capture():
    now = [0.0]
    gate = ASRInputGate(clock=lambda: now[0])
    gate.radio(active=True, session_id="desktop", generation=1)
    for generation in range(2, 602):
        now[0] += 1
        assert gate.radio(active=True, session_id="desktop", generation=generation, renew=True)
    now[0] += 4
    assert not gate.radio(active=True, session_id="desktop", generation=602, renew=True)
    assert not gate.snapshot()["active"]
    assert gate.radio(active=True, session_id="desktop", generation=603)
    assert gate.snapshot()["active"]


def test_active_source_is_exclusive_and_disconnecting_it_fences_late_text():
    gate, _ = radio()
    gate.radio(active=True, session_id="desktop", generation=1)
    context = gate.snapshot()
    assert not gate.radio(active=True, session_id="game", generation=1, target="game")
    gate.disconnect("desktop")
    assert not gate.valid(context)
    assert gate.radio(active=True, session_id="game", generation=2, target="game")


def test_radio_can_continue_after_maximum_phrase_duration():
    gate = ASRInputGate(clock=lambda: 10.0)
    segmenter = AudioSegmenter(AudioCaptureConfig(max_speech_duration=1), gate)
    gate.radio(active=True, session_id="desktop", generation=1)
    results = feed(segmenter, 96, 0.9, 1.0)
    assert len(results) >= 3
    assert all(len(audio) <= 16000 for audio, _ in results)
    assert gate.snapshot()["active"]


def test_quick_stop_and_restart_finishes_previous_phrase_without_merging_recordings():
    gate, segmenter = radio()
    gate.radio(active=True, session_id="desktop", generation=1)
    feed(segmenter, 12, 0.9, 1.0)
    gate.radio(active=False, session_id="desktop", generation=2)
    feed(segmenter, 2)
    gate.radio(active=True, session_id="desktop", generation=3)
    previous = feed(segmenter, 1, 0.9, 2.0)[0]
    assert np.count_nonzero(previous[0] == 1.0) == 12 * 512
    assert not np.any(previous[0] == 2.0)
    feed(segmenter, 11, 0.9, 2.0)
    following = feed(segmenter, 16)[0]
    assert np.count_nonzero(following[0] == 2.0) == 12 * 512
    assert not np.any(following[0] == 1.0)


def test_capture_skips_vad_before_activation_and_recovers_after_transcription_error(monkeypatch):
    from handlers import asr_audio_capture as capture

    gate, _ = radio()
    script = [0.0] * 40 + [0.9] * 12 + [0.0] * 16 + [0.9] * 12 + [0.0] * 16
    index = [0]
    sd = types.ModuleType("sounddevice")

    class Stream:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, size):
            value = script[index[0]]
            index[0] += 1
            if index[0] == 21:
                gate.radio(active=True, session_id="desktop", generation=1)
            return np.full((size, 1), value, np.float32), False

    sd.InputStream = Stream
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setattr(capture, "refresh_portaudio_catalog", lambda _: None)
    probabilities = Mock(side_effect=lambda audio, _: float(audio[0]))
    calls, progress = [], []

    async def transcribe(audio, rate, context):
        calls.append((audio, context))
        if len(calls) == 1:
            raise RuntimeError("recognizer temporarily unavailable")

    logger = SimpleNamespace(info=Mock(), warning=Mock(), error=Mock())
    asyncio.run(AudioCaptureService(logger).run(
        microphone_index=0, config=AudioCaptureConfig(),
        is_active=lambda: index[0] < len(script), speech_probability=probabilities,
        on_segment=Mock(), on_segment_context=transcribe, input_gate=gate,
        on_activity=progress.append,
    ))
    assert probabilities.call_count == len(script) - 20
    assert len(calls) == 2
    logger.error.assert_called_once()
    assert sum(item["phase"] == "recognizing" for item in progress) == 2
    assert any(item["phase"] == "error" for item in progress)
    assert gate.snapshot()["active"]


def test_desktop_radio_text_is_inserted_during_silence_even_when_game_is_connected(monkeypatch):
    from handlers.asr_handler import SpeechRecognition
    from utils.Testing.test_asr_session_routing import _Speech

    gate, segmenter = radio()
    monkeypatch.setattr(SpeechRecognition, "_input_gate", gate)
    gate.radio(active=True, session_id="desktop", generation=1)
    feed(segmenter, 12, 0.9, 1.0)
    _, context = feed(segmenter, 16)[0]
    speech = _Speech(turn_owner="game")
    del speech.ctrl._route_to_desktop
    speech.ctrl._instant_send_policy = lambda: (False, 0.0)
    speech.ctrl._on_speech_text_recognized(Event(Events.Speech.SPEECH_TEXT_RECOGNIZED, {
        "text": "recognized phrase", "capture_context": context,
    }))
    inserts = [data for name, data in speech.bus.sent if name == Events.GUI.INSERT_TEXT_TO_INPUT]
    assert inserts == [{"text": "recognized phrase", "autosend_after": 0.0}]
    assert speech.sent_to_game() == []
    assert gate.snapshot()["active"]


class ComposerViewModel(QObject):
    state_changed = pyqtSignal(object)
    effect_emitted = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.state = ChatPanelState()
        self.dispatch = Mock()
        self.close = Mock()


class ComposerPanel(ChatPanel):
    def _build_ui(self):
        QVBoxLayout(self).addWidget(self._build_composer())


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_composer_microphone_visibility_intent_and_stable_height(app):
    from styles.compose import get_main_window_stylesheet

    vm = ComposerViewModel()
    actions = ChatPanelActions(*(Mock() for _ in range(7)))
    panel = ComposerPanel(None, vm, actions)
    panel.setStyleSheet(get_main_window_stylesheet())
    panel.resize(900, 190)
    panel.show()
    app.processEvents()
    assert panel.microphone_button.isHidden()
    state = replace(vm.state, can_send=True, capture=ASRCaptureState(enabled=True, ready=True))
    panel.render(state)
    app.processEvents()
    assert panel.microphone_button.isVisible()
    panel.microphone_button.click()
    assert isinstance(vm.dispatch.call_args.args[0], ChatMicrophoneToggled)
    height = panel.composer_bar.height()
    for phase in ("listening", "speech", "recognizing", "idle"):
        active = phase != "idle"
        panel.render(replace(state, capture_owned=True, capture=replace(
            state.capture, active=active, permitted=True, phase=phase,
        )))
        app.processEvents()
        assert panel.composer_bar.height() == height
        assert panel.user_entry.isEnabled()
        assert panel.send_button.isEnabled() == (phase != "recognizing")
        if phase == "recognizing":
            assert "Распознаю" in panel.user_entry.placeholderText() or "Transcribing" in panel.user_entry.placeholderText()
    panel.user_entry.setPlainText("typed draft")
    panel.render(replace(state, capture=replace(state.capture, phase="recognizing")))
    assert panel.user_entry.toPlainText() == "typed draft"
    panel.render(state)
    assert not panel.microphone_button.property("captureActive")
    panel.close()


def test_transcription_blocks_click_and_enter_but_keeps_generation_cancellation(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    vm = ComposerViewModel()
    actions = ChatPanelActions(*(Mock() for _ in range(7)))
    panel = ComposerPanel(None, vm, actions)
    panel.show()
    state = replace(vm.state, can_send=True, capture=ASRCaptureState(
        enabled=True, ready=True, phase="recognizing",
    ))
    panel.render(state)
    panel.user_entry.setPlainText("draft")
    panel.send_button.click()
    QTest.keyClick(panel.user_entry, Qt.Key.Key_Return)
    panel._on_send_button_clicked()
    actions.send_message.assert_not_called()
    assert panel.user_entry.toPlainText() == "draft"
    panel.render(replace(state, active_generation_count=1))
    assert panel.send_button.isEnabled()
    panel.send_button.click()
    actions.cancel_active_generations.assert_called_once()
    actions.send_message.assert_not_called()
    panel.render(replace(state, capture=replace(state.capture, phase="listening")))
    assert panel.send_button.isEnabled()
    QTest.keyClick(panel.user_entry, Qt.Key.Key_Return)
    actions.send_message.assert_called_once()
    panel.close()


def test_wave_animation_runs_only_for_visible_active_microphone(app):
    from ui.widgets.microphone_button import MicrophoneButton

    button = MicrophoneButton()
    button.show()
    app.processEvents()
    assert not button.property("captureActive")
    assert not button._animation.isActive()
    button.set_capture_visual(active=True, phase="listening")
    assert button._animation.isActive()
    assert button.icon().isNull()
    button.hide()
    assert not button._animation.isActive()
    button.show()
    assert button._animation.isActive()
    button.set_capture_visual(active=False, phase="idle")
    assert not button._animation.isActive()
    assert not button.icon().isNull()
    button.close()


def test_view_model_activation_does_not_open_capture_and_lost_lease_is_not_renewed(app):
    from controllers.gui.chat_panel_view_model import ChatPanelViewModel

    settings = SimpleNamespace(subscribe=lambda *a, **k: SimpleNamespace(close=lambda: None))
    bus = SimpleNamespace(subscribe=lambda *a, **k: SimpleNamespace(close=lambda: None))
    current = [ASRCaptureState(enabled=True, ready=True, permitted=True)]
    speech = SimpleNamespace(capture_state=lambda: current[0], set_radio_capture=Mock(return_value=True),
                             release_radio_capture=Mock())
    registry = SimpleNamespace(get_optional=lambda _: speech)
    with patch("controllers.gui.chat_panel_view_model.use", return_value=settings), \
         patch("controllers.gui.chat_panel_view_model.get_event_bus", return_value=bus), \
         patch("controllers.gui.chat_panel_view_model.services", return_value=registry):
        vm = ChatPanelViewModel(host=None, backend_ready=lambda: True)
        vm._refresh_capture()
        speech.set_radio_capture.assert_not_called()
        vm.dispatch(ChatMicrophoneToggled())
        assert speech.set_radio_capture.call_args.kwargs["active"]
        current[0] = replace(current[0], active=True, session_id=vm._capture_session)
        vm._refresh_capture()
        assert speech.set_radio_capture.call_args.kwargs["renew"]
        current[0] = replace(current[0], active=False)
        speech.set_radio_capture.reset_mock()
        vm._refresh_capture()
        vm._refresh_capture()
        speech.set_radio_capture.assert_not_called()
        vm.close()
        speech.release_radio_capture.assert_called_once_with(vm._capture_session)
