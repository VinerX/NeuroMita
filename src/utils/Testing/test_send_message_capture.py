"""Регрессия на фриз GUI при отправке сообщения.

Захват экрана и камеры выполняется через типизированный CaptureService в
фоновом потоке. GUI не ждёт synchronous request/response через шину, а при
выключенном захвате отправляет сообщение без лишнего thread hop.
"""
from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
import sys

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.services import services
from services.contracts import CaptureService
from ui.windows.app_window_base import AppWindowBase


class _FakeBus:
    def __init__(self):
        self.emitted: list[tuple] = []

    def emit(self, event_name, data=None, sync=False):
        self.emitted.append((event_name, data))


class _FakeCapture(CaptureService):
    def __init__(self, screen=None, camera=None, delay: float = 0.0):
        self._screen = screen or []
        self._camera = camera or []
        self._delay = delay
        self.capture_threads: list[str] = []

    def _wait(self) -> None:
        self.capture_threads.append(threading.current_thread().name)
        if self._delay:
            time.sleep(self._delay)

    def capture_screen(self, limit: int = 1):
        self._wait()
        return list(self._screen)[: max(0, int(limit))]

    def camera_frames(self, limit: int = 1):
        self._wait()
        return list(self._camera)[: max(0, int(limit))]

    def screen_capture_active(self) -> bool:
        return bool(self._screen)

    def camera_capture_active(self) -> bool:
        return bool(self._camera)


class _NoopSignal:
    def emit(self, *_args, **_kwargs):
        return None


class _DirectGuiSignal:
    """Заменяет Qt-очередь в тестовом harness."""

    def __init__(self):
        self.threads: list[str] = []

    def emit(self, fn):
        self.threads.append(threading.current_thread().name)
        fn()


class _Harness:
    """Минимальный объект с поведением AppWindowBase без создания окна."""

    send_message = AppWindowBase.send_message
    _capture_frames_for_send = AppWindowBase._capture_frames_for_send
    _finish_send_message = AppWindowBase._finish_send_message
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
        self._previous_capture = services().get_optional(CaptureService)

        class _Renderer:
            @staticmethod
            def insert_message(target, role, content, message_id=None):
                target.rendered.append((role, content, message_id))

        awb.message_renderer = _Renderer()
        awb.use = lambda _contract: type("R", (), {"current_id": staticmethod(lambda: "Crazy")})()

    def tearDown(self):
        self.awb.message_renderer = self._orig_renderer
        self.awb.use = self._orig_registry_use
        if self._previous_capture is None:
            services().unregister(CaptureService)
        else:
            services().register(CaptureService, self._previous_capture, replace=True)

    def _register_capture(self, capture: _FakeCapture) -> _FakeCapture:
        services().register(CaptureService, capture, replace=True)
        return capture

    def test_backend_startup_blocks_early_send(self):
        bus = _FakeBus()
        h = _Harness({"AUTO_ATTACH_IMAGES": False, "ENABLE_CAMERA_CAPTURE": False}, bus)
        h.backend_ready = False

        result = h.send_message(user_input="too early")

        self.assertFalse(result)
        self.assertEqual(bus.emitted, [])

    def test_no_capture_enabled_sends_synchronously(self):
        bus = _FakeBus()
        capture = self._register_capture(_FakeCapture())
        h = _Harness({"AUTO_ATTACH_IMAGES": False, "ENABLE_CAMERA_CAPTURE": False}, bus)

        h.send_message(user_input="привет")

        self.assertEqual(capture.capture_threads, [])
        self.assertEqual(len(bus.emitted), 1)
        event_name, payload = bus.emitted[0]
        self.assertEqual(event_name, "send_message")
        self.assertEqual(payload["user_input"], "привет")
        self.assertEqual(payload["image_data"], [])

    def test_capture_runs_off_gui_thread_and_does_not_block(self):
        bus = _FakeBus()
        capture = self._register_capture(
            _FakeCapture(screen=[b"screen"], camera=[b"cam"], delay=0.3)
        )
        h = _Harness(
            {"AUTO_ATTACH_IMAGES": True, "ENABLE_CAMERA_CAPTURE": True, "ENABLE_IMAGE_ANALYSIS": True},
            bus,
        )
        gui_thread = threading.current_thread().name

        started = time.perf_counter()
        h.send_message(user_input="что на экране?")
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.15, "send_message заблокировал GUI-поток на время захвата")

        deadline = time.time() + 5
        while not bus.emitted and time.time() < deadline:
            time.sleep(0.01)

        self.assertEqual(len(bus.emitted), 1, "сообщение не отправилось после захвата")
        self.assertTrue(capture.capture_threads, "захват не выполнялся")
        for thread_name in capture.capture_threads:
            self.assertNotEqual(thread_name, gui_thread, "захват остался в GUI-потоке")

        payload = bus.emitted[0][1]
        self.assertEqual(payload["image_data"], [b"screen", b"cam"])
        self.assertTrue(payload["images_shown"])

    def test_image_order_and_dedupe_preserved(self):
        bus = _FakeBus()
        h = _Harness(
            {"AUTO_ATTACH_IMAGES": True, "ENABLE_CAMERA_CAPTURE": True, "ENABLE_IMAGE_ANALYSIS": True},
            bus,
        )
        h.staged_image_data = [b"staged"]

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
