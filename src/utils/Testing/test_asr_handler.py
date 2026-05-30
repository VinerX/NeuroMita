from __future__ import annotations

import unittest
from unittest.mock import patch

from handlers.asr_handler import SpeechRecognition


class _FakeFuture:
    def __init__(self, result_value):
        self._result_value = result_value

    def result(self, timeout=None):
        return self._result_value


class _FakeTask:
    def done(self):
        return True


class _FakeEngine:
    def __init__(self, result_value):
        self._result_value = result_value
        self.calls: list[tuple[str, str, dict]] = []

    def call(self, service, method, payload):
        self.calls.append((service, method, payload))
        return _FakeFuture(self._result_value)


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
        self.assertEqual(fake_engine.calls[0][0], "asr")
        self.assertEqual(fake_engine.calls[0][1], "start_live")

    def test_google_engine_keeps_local_mode(self):
        SpeechRecognition._recognizer_type = "google"

        with patch(
            "handlers.asr_handler.asyncio.run_coroutine_threadsafe",
            side_effect=_consume_coroutine,
        ) as run_local_mock:
            started = SpeechRecognition.speech_recognition_start(5, object())

        self.assertTrue(started)
        self.assertTrue(SpeechRecognition._is_running)
        self.assertTrue(SpeechRecognition.active)
        self.assertEqual(SpeechRecognition.microphone_index, 5)
        run_local_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
