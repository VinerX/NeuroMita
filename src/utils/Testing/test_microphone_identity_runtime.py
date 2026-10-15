import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from domain.audio_input import ASRInputDevice, MicrophoneSelection
from handlers.asr_audio_capture import (
    AudioCaptureConfig,
    AudioCaptureError,
    AudioCaptureService,
)
from handlers.asr_handler import SpeechRecognition
from handlers.ai_engine.services.asr_service import ASRService
from controllers.speech_controller import SpeechController


def test_endpoint_id_is_in_worker_start_and_replay_payload(monkeypatch):
    payload = SpeechRecognition._live_payload(
        MicrophoneSelection(uid="endpoint-A", index=24)
    )
    assert payload["microphone_uid"] == "endpoint-A"
    assert payload["microphone_index"] == 24


def test_worker_capture_gets_endpoint_id_on_start_and_switch(monkeypatch):
    captured = []

    class Capture:
        def __init__(self, logger):
            pass

        async def run(self, **kwargs):
            captured.append((kwargs["selection"].index, kwargs["selection"].uid))
            kwargs["on_ready"]()
            while kwargs["is_active"]():
                await asyncio.sleep(0.005)

    monkeypatch.setattr(
        "handlers.ai_engine.services.asr_service.AudioCaptureService", Capture
    )
    service = ASRService(emit_event=lambda *args: None)
    recognizer = SimpleNamespace(init=AsyncMock(return_value=True))
    vad = object()

    def get_recognizer(engine):
        service._recognizer = recognizer
        return recognizer

    async def get_vad():
        service._vad_model = vad
        return vad

    service._get_recognizer = get_recognizer
    service._get_vad_model = get_vad

    async def exercise():
        try:
            assert await service.handle(
                "start_live", {"microphone_index": 24, "microphone_uid": "endpoint-A"}
            )
            assert captured == [(24, "endpoint-A")]
            assert await service.handle(
                "switch_input", {"microphone_index": 39, "microphone_uid": "endpoint-B"}
            )
            assert captured[-1] == (39, "endpoint-B")
        finally:
            await service.shutdown()

    asyncio.run(exercise())


def test_capture_resolves_endpoint_in_its_own_device_catalog(monkeypatch):
    backend = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "sounddevice", backend)
    resolver = Mock(
        return_value=ASRInputDevice(39, "Renamed", "WASAPI", uid="endpoint-A")
    )
    monkeypatch.setattr("handlers.asr_audio_capture.resolve_asr_input_device", resolver)

    class ResolvedIndex(Exception):
        pass

    def describe(sd, index):
        assert sd is backend
        raise ResolvedIndex(index)

    monkeypatch.setattr("handlers.asr_audio_capture._device_description", describe)
    capture = AudioCaptureService(Mock())
    with pytest.raises(ResolvedIndex) as caught:
        asyncio.run(
            capture.run(
                selection=MicrophoneSelection(uid="endpoint-A", index=24),
                config=AudioCaptureConfig(),
                is_active=lambda: False,
                speech_probability=lambda *args: 0,
                on_segment=AsyncMock(),
            )
        )
    assert caught.value.args == (39,)
    assert resolver.call_args.kwargs["requested_uid"] == "endpoint-A"


def test_missing_capture_endpoint_fails_before_any_device_is_opened(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace())
    monkeypatch.setattr(
        "handlers.asr_audio_capture.resolve_asr_input_device",
        lambda *args, **kwargs: None,
    )
    describe = Mock()
    monkeypatch.setattr("handlers.asr_audio_capture._device_description", describe)
    with pytest.raises(AudioCaptureError, match="endpoint is unavailable"):
        asyncio.run(
            AudioCaptureService(Mock()).run(
                selection=MicrophoneSelection(uid="missing", index=24),
                config=AudioCaptureConfig(),
                is_active=lambda: False,
                speech_probability=lambda *args: 0,
                on_segment=AsyncMock(),
            )
        )
    describe.assert_not_called()
