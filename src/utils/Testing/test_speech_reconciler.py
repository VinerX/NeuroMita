"""Тумблер микрофона: итог определяется последним щелчком, а не гонкой потоков.

Регресс: «включить» и «выключить» были двумя независимыми задачами, а общий
замок лишь выстраивал их в очередь. Протухший старт, дождавшись замка, включал
микрофон уже после выключения; последовательность вкл→выкл→вкл могла закончиться
выключенным микрофоном.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from itertools import count
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

import controllers.speech_controller as speech_module
from controllers.speech_controller import SpeechController


class _FakeSettings:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)

    def set(self, key, value):
        self._values[key] = value

    def save_settings(self):
        return None


class _FakeAsrSettings:
    def __init__(self, engine: str = "google"):
        self.engine = engine

    def snapshot(self) -> dict:
        return {"engine": self.engine, "models": {self.engine: {}}}


class _FakeRecognition:
    """Движок ASR. Старт умеет быть медленным — как загрузка модели в жизни."""

    def __init__(self, *, start_delay: float = 0.0):
        self.running = False
        self.events: list[str] = []
        self.start_delay = start_delay
        self.engine = "google"
        self.applied: list[str] = []
        self._lock = threading.Lock()

    def speech_recognition_start(self, _device_id, _loop):
        time.sleep(self.start_delay)
        with self._lock:
            self.running = True
            self.events.append("start")
        return True

    def speech_recognition_stop(self):
        with self._lock:
            self.running = False
            self.events.append("stop")

    def set_recognizer_type(self, engine):
        self.engine = engine

    def apply_settings(self, engine, _settings):
        self.applied.append(engine)


class _SpeechReconcilerCase(unittest.TestCase):
    def setUp(self):
        self._saved_recognition = speech_module.SpeechRecognition

    def tearDown(self):
        speech_module.SpeechRecognition = self._saved_recognition

    def _make(self, *, mic_active=True, start_delay=0.0):
        recognition = _FakeRecognition(start_delay=start_delay)
        speech_module.SpeechRecognition = recognition

        settings = _FakeSettings({"MIC_ACTIVE": mic_active})
        controller = SpeechController.__new__(SpeechController)
        controller.settings = settings
        controller.asr_settings = _FakeAsrSettings()
        controller.device_id = 0
        controller.mic_recognition_active = False
        controller.asr_is_ready = False
        controller.events_bus = type("_Bus", (), {"emit": staticmethod(lambda *a, **k: None)})()
        controller._lifecycle_lock = threading.Lock()
        controller._state_lock = threading.Lock()
        controller._desired_generation = 0
        controller._applied_generation = 0
        controller._reconcile_pending = False
        controller._configured_engine = "google"
        controller._running_engine = None
        controller._shutting_down = False
        controller._task_seq = count(1)

        # Заглушка ровно на «запустить движок»: проверяем логику согласования,
        # а не установку моделей и event loop.
        def _start():
            if controller.mic_recognition_active:
                return
            started = bool(recognition.speech_recognition_start(controller.device_id, None))
            controller.mic_recognition_active = started
            controller.asr_is_ready = started

        controller._start_maybe_install = _start
        return controller, recognition, settings

    @staticmethod
    def _wait_settled(controller: SpeechController, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with controller._state_lock:
                settled = (
                    controller._applied_generation == controller._desired_generation
                    and not controller._reconcile_pending
                )
            if settled and not controller._lifecycle_lock.locked():
                return True
            time.sleep(0.02)
        return False


class SpeechReconcilerTests(_SpeechReconcilerCase):
    def test_toggle_off_wins_over_a_slow_start(self):
        """Пока старт грузит модель, тумблер выключают — микрофон обязан молчать."""
        controller, recognition, settings = self._make(start_delay=0.3)

        controller._request_reconcile("on")
        time.sleep(0.05)  # реконсилятор уже внутри медленного старта
        settings.set("MIC_ACTIVE", False)
        controller._request_reconcile("off")

        self.assertTrue(self._wait_settled(controller))
        self.assertFalse(recognition.running, "микрофон обязан остаться выключенным")
        self.assertFalse(controller.mic_recognition_active)
        self.assertIsNone(controller._running_engine)
        self.assertEqual(recognition.events[-1], "stop")

    def test_on_off_on_ends_up_running(self):
        controller, recognition, settings = self._make(start_delay=0.1)

        controller._request_reconcile("on")
        settings.set("MIC_ACTIVE", False)
        controller._request_reconcile("off")
        settings.set("MIC_ACTIVE", True)
        controller._request_reconcile("on")

        self.assertTrue(self._wait_settled(controller))
        self.assertTrue(recognition.running, "последний щелчок — «включить»")
        self.assertTrue(controller.mic_recognition_active)
        self.assertEqual(controller._running_engine, "google")

    def test_off_after_on_leaves_mic_off(self):
        controller, recognition, settings = self._make(start_delay=0.05)

        controller._request_reconcile("on")
        settings.set("MIC_ACTIVE", False)
        controller._request_reconcile("off")

        self.assertTrue(self._wait_settled(controller))
        self.assertFalse(recognition.running)
        self.assertFalse(controller.mic_recognition_active)

    def test_reconcile_is_idempotent_when_nothing_changed(self):
        controller, recognition, _ = self._make()

        controller._reconcile_once()
        controller._reconcile_once()

        self.assertEqual(recognition.events, ["start"], "второй проход не должен трогать движок")
        self.assertEqual(recognition.applied, [], "движок не перенастраивали — нечего применять")

    def test_engine_switch_restarts_the_running_recognizer(self):
        controller, recognition, _ = self._make()
        controller._reconcile_once()

        controller.asr_settings.engine = "vosk"
        controller._reconcile_once()

        self.assertEqual(recognition.events, ["start", "stop", "start"])
        self.assertEqual(recognition.engine, "vosk")
        self.assertEqual(recognition.applied, ["vosk"])
        self.assertTrue(recognition.running)
        self.assertEqual(controller._running_engine, "vosk")

    def test_shutdown_flag_keeps_the_mic_off(self):
        controller, recognition, _ = self._make()
        controller._reconcile_once()
        controller._shutting_down = True

        controller._reconcile_once()

        self.assertFalse(recognition.running)
        self.assertFalse(controller.mic_recognition_active)


if __name__ == "__main__":
    unittest.main()
