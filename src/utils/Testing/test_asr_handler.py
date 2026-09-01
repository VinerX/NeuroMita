from __future__ import annotations

import asyncio
import builtins
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np

from core.backends import BackendKind
from core.events import Event, Events
from handlers.ai_engine.services.asr_service import ASRService
from handlers.asr_audio_capture import (
    AudioCaptureConfig,
    AudioCaptureError,
    AudioCaptureService,
    _describe_audio_capture_error,
)
from handlers.asr_handler import SpeechRecognition
from handlers.asr_models.google_recognizer import GoogleRecognizer
from utils.native_paths import path_for_native_loader


class _FakeFuture:
    def __init__(self, result_value):
        self._result_value = result_value

    def result(self, timeout=None):
        return self._result_value


class _FakeTask:
    def done(self):
        return True


class _FakeEngine:
    def __init__(self, result_value, *, activation_result: bool = True):
        self._result_value = result_value
        self._activation_result = activation_result
        self.calls: list[tuple[str, str, dict]] = []
        self.activations: list[tuple[str, str, str | None, str | None]] = []

    def activate_environment(
        self,
        service,
        item_id,
        *,
        category=None,
        timeout=0.0,
        validation_method=None,
        validation_payload=None,
        validation_timeout=None,
    ):
        self.activations.append((service, item_id, category, validation_method))
        if validation_method:
            return self._activation_result and bool(self._result_value)
        return self._activation_result

    def call(self, service, method, payload):
        self.calls.append((service, method, payload))
        return _FakeFuture(self._result_value)


class _FakeEventBus:
    def __init__(self):
        self.events = []

    def emit(self, name, data=None):
        self.events.append((name, data))


class _FakeRecognizer:
    def apply_settings(self, _settings):
        return None

    def is_installed(self):
        return True

    async def init(self):
        return True

    async def transcribe(self, _audio, _rate):
        return ""

    def cleanup(self):
        return None


class _FailingAudioCapture:
    def __init__(self, _logger):
        pass

    async def run(self, **_kwargs):
        raise AudioCaptureError("microphone permission denied")


class _ReadyAudioCapture:
    def __init__(self, _logger):
        pass

    async def run(self, **kwargs):
        kwargs["on_ready"]()
        while kwargs["is_active"]():
            await asyncio.sleep(0.005)


class _SilentLogger:
    def info(self, _message):
        pass

    def warning(self, _message):
        pass


def _consume_coroutine(coro, loop):
    coro.close()
    return _FakeTask()


class SpeechRecognitionStartTests(unittest.TestCase):
    def setUp(self):
        SpeechRecognition._recognizer_type = "google"
        SpeechRecognition._remote_asr_mode = True
        SpeechRecognition._is_running = False
        SpeechRecognition._recognition_task = None
        SpeechRecognition._running_event.clear()
        SpeechRecognition._stopped_event.set()
        SpeechRecognition.active = False
        SpeechRecognition.microphone_index = 0

    def test_google_declares_shared_cpu_torch_contract_for_vad(self):
        recognizer = GoogleRecognizer(None, None)

        self.assertEqual(recognizer.required_backend({}), BackendKind.CPU)

    def test_vad_load_does_not_import_embeddings_or_transformers(self):
        service = ASRService(emit_event=lambda *_args: None)
        torch = types.ModuleType("torch")
        silero_vad = types.ModuleType("silero_vad")
        vad_model = object()
        silero_vad.load_silero_vad = lambda: vad_model
        imported: list[str] = []
        real_import = builtins.__import__

        def tracked_import(name, *args, **kwargs):
            imported.append(str(name))
            return real_import(name, *args, **kwargs)

        with patch.dict(
            sys.modules,
            {"torch": torch, "silero_vad": silero_vad},
        ), patch("builtins.__import__", side_effect=tracked_import):
            loaded = asyncio.run(service._get_vad_model())

        self.assertIs(loaded, vad_model)
        self.assertNotIn("handlers.embedding_handler", imported)
        self.assertNotIn("transformers", imported)

    def test_native_loader_path_keeps_ascii_paths_unchanged(self):
        path = r"C:\NeuroMita\silero_vad.jit"

        self.assertEqual(path_for_native_loader(path), path)

    @unittest.skipUnless(os.name == "nt", "Windows native path compatibility is Windows-specific")
    def test_native_loader_path_uses_short_path_for_non_ascii_paths(self):
        path = r"C:\NeuroMita\СепарированныйТест\silero_vad.jit"
        short_path = r"C:\NEUROM~1\31C7~1\silero_vad.jit"

        with patch(
            "utils.native_paths._get_short_path",
            return_value=short_path,
        ):
            self.assertEqual(path_for_native_loader(path), short_path)

    def test_managed_asr_start_fails_before_ready_when_microphone_cannot_open(self):
        events = []
        service = ASRService(emit_event=lambda event, data: events.append((event, data)))
        recognizer = _FakeRecognizer()

        async def run_start():
            with patch.object(service, "_get_recognizer", return_value=recognizer), \
                 patch.object(service, "_get_vad_model", new=AsyncMock(return_value=lambda *_args: None)), \
                 patch("handlers.ai_engine.services.asr_service.AudioCaptureService", _FailingAudioCapture):
                await service._start_live_internal(
                    engine_id="google",
                    mic_index=18,
                    engine_settings={},
                    sample_rate=16000,
                    chunk_size=512,
                    vad_threshold=0.5,
                    silence_timeout=0.15,
                    pre_buffer_duration=0.3,
                    max_speech_duration=30.0,
                )

        with self.assertRaisesRegex(RuntimeError, "microphone permission denied"):
            asyncio.run(run_start())

        self.assertNotIn(("status", {"running": True}), events)
        self.assertFalse(service._active)
        self.assertIsNone(service._task)

    def test_managed_asr_reports_ready_only_after_audio_capture_is_open(self):
        events = []
        service = ASRService(emit_event=lambda event, data: events.append((event, data)))
        recognizer = _FakeRecognizer()

        async def run_start_and_stop():
            with patch.object(service, "_get_recognizer", return_value=recognizer), \
                 patch.object(service, "_get_vad_model", new=AsyncMock(return_value=lambda *_args: None)), \
                 patch("handlers.ai_engine.services.asr_service.AudioCaptureService", _ReadyAudioCapture):
                started = await service._start_live_internal(
                    engine_id="google",
                    mic_index=18,
                    engine_settings={},
                    sample_rate=16000,
                    chunk_size=512,
                    vad_threshold=0.5,
                    silence_timeout=0.15,
                    pre_buffer_duration=0.3,
                    max_speech_duration=30.0,
                )
                self.assertTrue(started)
                self.assertEqual(("status", {"running": True}), events[-1])
                await service._stop_live_internal()

        asyncio.run(run_start_and_stop())

    def test_audio_capture_reports_ready_after_first_successful_read(self):
        sequence = []
        sounddevice = types.ModuleType("sounddevice")

        class InputStream:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                sequence.append("open")
                return self

            def __exit__(self, *_args):
                sequence.append("close")

            def read(self, chunk_size):
                sequence.append("read")
                return np.zeros((chunk_size, 1), dtype=np.float32), False

        sounddevice.InputStream = InputStream
        active_checks = 0

        def is_active():
            nonlocal active_checks
            active_checks += 1
            return active_checks == 1

        async def run_capture():
            capture = AudioCaptureService(_SilentLogger())
            await capture.run(
                microphone_index=18,
                config=AudioCaptureConfig(),
                is_active=is_active,
                speech_probability=lambda _audio, _rate: 0.0,
                on_segment=AsyncMock(),
                on_ready=lambda: sequence.append("ready"),
            )

        with patch.dict(sys.modules, {"sounddevice": sounddevice}):
            asyncio.run(run_capture())

        self.assertEqual(["open", "read", "ready", "close"], sequence)

    def _capture_segments(self, script, **config_kwargs):
        """Прогоняет синтетический поток через захват и возвращает сегменты.

        Значение каждого чанка = вероятность речи, так что скрипт читается как
        «речь/тишина» по чанкам (при 512/16000 — 32 мс на чанк)."""
        sounddevice = types.ModuleType("sounddevice")
        state = {"index": 0}

        class InputStream:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, chunk_size):
                i = state["index"]
                value = script[i] if i < len(script) else 0.0
                state["index"] = i + 1
                return np.full((chunk_size, 1), float(value), dtype=np.float32), False

        sounddevice.InputStream = InputStream
        segments = []

        async def on_segment(audio, rate):
            segments.append(len(audio) / rate)

        async def run_capture():
            await AudioCaptureService(_SilentLogger()).run(
                microphone_index=0,
                config=AudioCaptureConfig(sample_rate=16000, chunk_size=512, **config_kwargs),
                is_active=lambda: state["index"] < len(script),
                speech_probability=lambda audio, _rate: float(audio[0]),
                on_segment=on_segment,
            )

        with patch.dict(sys.modules, {"sounddevice": sounddevice}):
            asyncio.run(run_capture())

        return segments

    def test_default_silence_timeout_keeps_phrase_with_inner_pause_whole(self):
        # 5 чанков паузы = 160 мс: пауза между словами, а не конец реплики.
        script = [0.0] * 5 + [0.9] * 10 + [0.0] * 5 + [0.9] * 10 + [0.0] * 25

        self.assertEqual(1, len(self._capture_segments(script)))
        self.assertEqual(
            2,
            len(self._capture_segments(script, silence_timeout=0.15, min_speech_duration=0.0)),
        )

    def test_too_short_segment_is_not_sent_to_recognizer(self):
        # 2 чанка речи = 64 мс: щелчок, на котором Whisper галлюцинирует.
        script = [0.0] * 5 + [0.9] * 2 + [0.0] * 25

        self.assertEqual([], self._capture_segments(script))
        self.assertEqual(1, len(self._capture_segments(script, min_speech_duration=0.0)))

    def test_pre_buffer_does_not_leak_previous_utterance(self):
        script = [0.0] * 15 + [0.9] * 15 + [0.0] * 20 + [0.9] * 15 + [0.0] * 25

        segments = self._capture_segments(script)

        self.assertEqual(2, len(segments))
        # Второй сегмент не должен тащить хвост уже отданного первого.
        self.assertLess(segments[1], segments[0])

    def test_wdm_ks_blocking_error_is_reported_as_driver_capability_problem(self):
        error = RuntimeError(
            "Error opening InputStream: Unanticipated host error "
            "[PaErrorCode -9999]: 'Blocking API not supported yet' "
            "[Windows WDM-KS error -9999]"
        )

        message = _describe_audio_capture_error(
            error,
            microphone_index=18,
            operation="open",
            device_name="Realtek HD Audio Mic input",
            host_api_name="Windows WDM-KS",
            sample_rate=16000,
        )

        self.assertIn("WDM-KS не поддерживает блокирующий режим захвата", message)
        self.assertIn("WASAPI, DirectSound или MME", message)
        self.assertIn("PortAudio -9999", message)
        self.assertNotIn("Unanticipated host error", message)

    def test_non_google_remote_failure_does_not_fallback_to_local_mode(self):
        SpeechRecognition._recognizer_type = "whisper"
        fake_engine = _FakeEngine(False)

        with patch("handlers.asr_handler.asyncio.run_coroutine_threadsafe") as run_local_mock, \
             patch.object(SpeechRecognition, "_get_ai_engine", return_value=fake_engine):
            started = SpeechRecognition.speech_recognition_start(3, object())

        self.assertFalse(started)
        self.assertFalse(SpeechRecognition._is_running)
        self.assertFalse(SpeechRecognition.active)
        run_local_mock.assert_not_called()
        self.assertEqual(
            fake_engine.activations,
            [("asr", "whisper", "asr", "start_live")],
        )
        self.assertEqual(fake_engine.calls, [])

    def test_non_google_requires_managed_environment(self):
        SpeechRecognition._recognizer_type = "whisper"
        fake_engine = _FakeEngine(True, activation_result=False)
        event_bus = _FakeEventBus()

        with patch.object(SpeechRecognition, "_get_ai_engine", return_value=fake_engine), \
             patch("handlers.asr_handler.get_event_bus", return_value=event_bus):
            started = SpeechRecognition.speech_recognition_start(3, object())

        self.assertFalse(started)
        self.assertEqual(
            fake_engine.activations,
            [("asr", "whisper", "asr", "start_live")],
        )
        self.assertEqual(fake_engine.calls, [])
        emitted_names = [name for name, _data in event_bus.events]
        self.assertIn(Events.Speech.ASR_MODEL_INIT_STARTED, emitted_names)
        self.assertIn(Events.Speech.ASR_FAILED, emitted_names)
        self.assertNotIn(Events.Speech.ASR_MODEL_INITIALIZED, emitted_names)

    def test_google_engine_uses_managed_remote_runtime(self):
        SpeechRecognition._recognizer_type = "google"
        fake_engine = _FakeEngine(True)

        with patch.object(SpeechRecognition, "_get_ai_engine", return_value=fake_engine):
            started = SpeechRecognition.speech_recognition_start(5, object())

        self.assertTrue(started)
        self.assertTrue(SpeechRecognition._is_running)
        self.assertTrue(SpeechRecognition.active)
        self.assertEqual(SpeechRecognition.microphone_index, 5)
        self.assertEqual(
            fake_engine.activations,
            [("asr", "google", "asr", "start_live")],
        )
        self.assertEqual(fake_engine.calls, [])


class AsrEngineStatusReasonTests(unittest.TestCase):
    """running=false должен отличать штатный съём цикла от аварии."""

    def _service(self, events):
        return ASRService(emit_event=lambda event, data: events.append((event, data)))

    def _patched_start(self, service):
        return (
            patch.object(service, "_get_recognizer", return_value=_FakeRecognizer()),
            patch.object(
                service,
                "_get_vad_model",
                new=AsyncMock(return_value=lambda *_args: None),
            ),
            patch(
                "handlers.ai_engine.services.asr_service.AudioCaptureService",
                _ReadyAudioCapture,
            ),
        )

    def _start_payload(self):
        return {
            "engine_id": "google",
            "microphone_index": 0,
            "vad": {"silence_timeout": 0.15, "pre_buffer_duration": 0.3},
        }

    def test_restart_of_live_loop_is_marked_as_requested_stop(self):
        events = []
        service = self._service(events)

        async def scenario():
            recognizer, vad, capture = self._patched_start(service)
            with recognizer, vad, capture:
                await service.handle("start_live", self._start_payload())
                events.clear()
                await service.handle("start_live", self._start_payload())
                await service._stop_live_internal()

        asyncio.run(scenario())

        self.assertIn(("status", {"running": False, "reason": "restart"}), events)
        self.assertIn(("status", {"running": True}), events)

    def test_capture_dying_on_its_own_is_reported_as_failure(self):
        events = []
        service = self._service(events)

        async def scenario():
            recognizer, vad, capture = self._patched_start(service)
            with recognizer, vad, capture:
                await service.handle("start_live", self._start_payload())
                events.clear()
                # Цикл захвата умер сам: снять его никто не просил.
                service._active = False
                task = service._task
                if task is not None:
                    await asyncio.gather(task, return_exceptions=True)

        asyncio.run(scenario())

        self.assertIn(
            ("status", {"running": False, "reason": "capture_stopped"}), events
        )

    def test_bridge_ignores_requested_stop_and_reports_real_failure(self):
        from handlers import asr_handler

        def _event(reason):
            return Event(
                Events.AI.ENGINE_EVENT,
                {"service": "asr", "event": "status", "data": {"running": False, "reason": reason}},
            )

        bus = _FakeEventBus()
        started_threads = []

        with patch.object(asr_handler, "get_event_bus", return_value=bus), \
             patch.object(
                 asr_handler,
                 "task_supervisor",
                 return_value=types.SimpleNamespace(
                     start_thread=lambda *args, **kwargs: started_threads.append(args)
                 ),
             ):
            SpeechRecognition._is_running = True
            asr_handler._on_ai_engine_event(_event("restart"))
            self.assertEqual(bus.events, [])
            self.assertEqual(started_threads, [])

            asr_handler._on_ai_engine_event(_event("capture_stopped"))

        SpeechRecognition._is_running = False
        self.assertIn(Events.Speech.ASR_FAILED, [name for name, _d in bus.events])
        self.assertEqual(len(started_threads), 1)


if __name__ == "__main__":
    unittest.main()
