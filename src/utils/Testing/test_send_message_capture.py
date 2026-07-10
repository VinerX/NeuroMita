"""Регрессия на фриз GUI при отправке сообщения.

`send_message` собирал кадры экрана/камеры прямо в GUI-потоке через
`emit_and_wait` с таймаутами 5с и 2с — до семи секунд замороженного интерфейса
на каждую отправку. Теперь захват уходит в фоновый поток, а когда захватывать
нечего — работаем синхронно, без лишнего хопа.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ui.windows.app_window_base import AppWindowBase


class _FakeBus:
    def __init__(self, screen=None, camera=None, delay: float = 0.0):
        self._screen = screen or []
        self._camera = camera or []
        self._delay = delay
        self.emitted: list[tuple] = []
        self.capture_threads: list[str] = []

    def emit_and_wait(self, event_name, data=None, timeout=None):
        self.capture_threads.append(threading.current_thread().name)
        if self._delay:
            time.sleep(self._delay)
        if event_name == "capture_screen":
            return [self._screen]
        if event_name == "get_camera_frames":
            return [self._camera]
        return []

    def emit(self, event_name, data=None, sync=False):
        self.emitted.append((event_name, data))


class _NoopSignal:
    def emit(self, *_args, **_kwargs):
        return None


class _DirectGuiSignal:
    """Заменяет Qt-очередь: run_async ищет run_ui_task_signal, чтобы вернуться в GUI-поток."""

    def __init__(self):
        self.threads: list[str] = []

    def emit(self, fn):
        self.threads.append(threading.current_thread().name)
        fn()


class _Harness:
    """Минимальный объект с поведением AppWindowBase без Qt."""

    send_message = AppWindowBase.send_message
    _capture_frames_for_send = AppWindowBase._capture_frames_for_send
    _finish_send_message = AppWindowBase._finish_send_message
    # В AppWindowBase это staticmethod — переносим как staticmethod, иначе
    # первым позиционным аргументом уедет self.
    _dedupe_images = staticmethod(AppWindowBase._dedupe_images)
    _merge_explicit_and_entry_text = staticmethod(AppWindowBase._merge_explicit_and_entry_text)

    def __init__(self, settings: dict, bus: _FakeBus):
        self._settings = settings
        self.event_bus = bus
        self.backend_ready = True
        self.backend_startup_error = ""
        self.staged_image_data = []
        self.user_entry = None
        self.rendered: list = []
        self.image_preview_bar = None
        self.show_thinking_signal = _NoopSignal()
        self.show_error_signal = _NoopSignal()
        self.run_ui_task_signal = _DirectGuiSignal()

    def _get_setting(self, key, default=None):
        return self._settings.get(key, default)


class SendMessageCaptureTests(unittest.TestCase):
    def setUp(self):
        import ui.windows.app_window_base as awb

        self.awb = awb
        self._orig_renderer = awb.message_renderer
        self._orig_registry_use = awb.use

        class _Renderer:
            @staticmethod
            def insert_message(target, role, content, message_id=None):
                target.rendered.append((role, content, message_id))

        awb.message_renderer = _Renderer()
        awb.use = lambda _contract: type("R", (), {"current_id": staticmethod(lambda: "Crazy")})()

    def tearDown(self):
        self.awb.message_renderer = self._orig_renderer
        self.awb.use = self._orig_registry_use

    def test_backend_startup_blocks_early_send(self):
        bus = _FakeBus()
        h = _Harness({"AUTO_ATTACH_IMAGES": False, "ENABLE_CAMERA_CAPTURE": False}, bus)
        h.backend_ready = False

        result = h.send_message(user_input="too early")

        self.assertFalse(result)
        self.assertEqual(bus.emitted, [])

    def test_no_capture_enabled_sends_synchronously(self):
        bus = _FakeBus()
        h = _Harness({"AUTO_ATTACH_IMAGES": False, "ENABLE_CAMERA_CAPTURE": False}, bus)

        h.send_message(user_input="привет")

        # Отправка произошла сразу, без фонового потока и без захвата.
        self.assertEqual(bus.capture_threads, [])
        self.assertEqual(len(bus.emitted), 1)
        event_name, payload = bus.emitted[0]
        self.assertEqual(event_name, "send_message")
        self.assertEqual(payload["user_input"], "привет")
        self.assertEqual(payload["image_data"], [])

    def test_capture_runs_off_gui_thread_and_does_not_block(self):
        bus = _FakeBus(screen=[b"screen"], camera=[b"cam"], delay=0.3)
        h = _Harness(
            {"AUTO_ATTACH_IMAGES": True, "ENABLE_CAMERA_CAPTURE": True, "ENABLE_IMAGE_ANALYSIS": True},
            bus,
        )
        gui_thread = threading.current_thread().name

        started = time.perf_counter()
        h.send_message(user_input="что на экране?")
        elapsed = time.perf_counter() - started

        # Вызывающий (GUI) поток вернулся мгновенно, не дожидаясь захвата.
        self.assertLess(elapsed, 0.15, "send_message заблокировал GUI-поток на время захвата")

        deadline = time.time() + 5
        while not bus.emitted and time.time() < deadline:
            time.sleep(0.01)

        self.assertEqual(len(bus.emitted), 1, "сообщение не отправилось после захвата")
        self.assertTrue(bus.capture_threads, "захват не выполнялся")
        for thread_name in bus.capture_threads:
            self.assertNotEqual(thread_name, gui_thread, "захват остался в GUI-потоке")

        payload = bus.emitted[0][1]
        self.assertEqual(payload["image_data"], [b"screen", b"cam"])
        self.assertTrue(payload["images_shown"])

    def test_image_order_and_dedupe_preserved(self):
        bus = _FakeBus(screen=[b"dup"], camera=[b"cam"])
        h = _Harness(
            {"AUTO_ATTACH_IMAGES": True, "ENABLE_CAMERA_CAPTURE": True, "ENABLE_IMAGE_ANALYSIS": True},
            bus,
        )
        h.staged_image_data = [b"staged"]

        # explicit + screen + staged + camera, с дублем explicit/screen
        h._finish_send_message(
            user_input="",
            system_input="",
            explicit_image_data=[b"dup"],
            screen_frames=[b"dup"],
            camera_frames=[b"cam"],
            staged_image_data=[b"staged"],
            character_id="Crazy",
            from_entry=False,
            clear_entry_after_send=False,
        )

        payload = bus.emitted[0][1]
        self.assertEqual(payload["image_data"], [b"dup", b"staged", b"cam"])

    def test_image_analysis_disabled_drops_images(self):
        bus = _FakeBus()
        h = _Harness({"ENABLE_IMAGE_ANALYSIS": False}, bus)

        h._finish_send_message(
            user_input="текст",
            system_input="",
            explicit_image_data=[b"img"],
            screen_frames=[],
            camera_frames=[],
            staged_image_data=[],
            character_id="Crazy",
            from_entry=False,
            clear_entry_after_send=False,
        )

        payload = bus.emitted[0][1]
        self.assertEqual(payload["image_data"], [])
        self.assertFalse(payload["images_shown"])


if __name__ == "__main__":
    unittest.main()
