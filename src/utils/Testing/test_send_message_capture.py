from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from controllers.gui.app_shell_controller import AppShellController
from services.contracts import CaptureService, CharacterRegistry, SettingsService


class _FakeBus:
    def __init__(self):
        self.emitted: list[tuple[str, object]] = []

    def emit(self, event_name, data=None, **_kwargs):
        self.emitted.append((str(event_name), data))


class _FakeSettings:
    def __init__(self, values: dict):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def update(self, key, value):
        self.values[key] = value


class _FakeCharacterRegistry:
    @staticmethod
    def current_id():
        return "Crazy"


class _FakeCapture(CaptureService):
    def __init__(self, *, screen=None, camera=None, delay: float = 0.0):
        self.screen = list(screen or [])
        self.camera = list(camera or [])
        self.delay = delay
        self.capture_threads: list[str] = []

    def _wait(self):
        self.capture_threads.append(threading.current_thread().name)
        if self.delay:
            time.sleep(self.delay)

    def capture_screen(self, limit: int = 1):
        self._wait()
        return self.screen[:limit]

    def camera_frames(self, limit: int = 1):
        self._wait()
        return self.camera[:limit]

    def screen_capture_active(self) -> bool:
        return bool(self.screen)

    def camera_capture_active(self) -> bool:
        return bool(self.camera)


class _FakeServices:
    def __init__(self, capture):
        self.capture = capture

    def get_optional(self, contract):
        return self.capture if contract is CaptureService else None


class _FakeView:
    def __init__(self, *, input_text="", staged=None):
        self.input_text = input_text
        self.staged = list(staged or [])
        self.rendered: list[dict] = []
        self.errors: list[str] = []
        self.thinking_count = 0
        self.staged_clear_count = 0

    def user_input_text(self):
        return self.input_text

    def staged_images_snapshot(self):
        return list(self.staged)

    def render_outgoing_message(self, **payload):
        self.rendered.append(dict(payload))

    def show_send_error(self, message):
        self.errors.append(str(message))

    def show_thinking_now(self):
        self.thinking_count += 1

    def clear_staged_images_view(self):
        self.staged.clear()
        self.staged_clear_count += 1


class _AppPort:
    def attach_backend(self, _controller):
        return None

    def detach_backend(self):
        return None

    def mark_failed(self, _message):
        return None


class SendMessageCaptureTests(unittest.TestCase):
    def _make_controller(self, settings: dict, capture=None, *, view=None):
        view = view or _FakeView()
        controller = AppShellController(view, SimpleNamespace(app=_AppPort()))
        controller._main_controller = SimpleNamespace(_closing_started=False)
        controller._event_bus = _FakeBus()
        fake_settings = _FakeSettings(settings)

        def fake_use(contract):
            if contract is SettingsService:
                return fake_settings
            if contract is CharacterRegistry:
                return _FakeCharacterRegistry()
            raise KeyError(contract)

        return controller, view, fake_use, _FakeServices(capture)

    def test_page_view_models_close_before_backend_shutdown(self):
        events: list[str] = []
        controller = AppShellController(
            _FakeView(),
            SimpleNamespace(app=_AppPort()),
            close_pages=lambda: events.append("pages"),
        )
        controller._main_controller = SimpleNamespace(
            _closing_started=False,
            close_app=lambda: events.append("backend"),
        )

        controller.close_application()

        self.assertEqual(events, ["pages", "backend"])

    def test_backend_still_closes_if_page_shutdown_fails(self):
        events: list[str] = []

        def close_pages():
            events.append("pages")
            raise RuntimeError("page close failed")

        controller = AppShellController(
            _FakeView(),
            SimpleNamespace(app=_AppPort()),
            close_pages=close_pages,
        )
        controller._main_controller = SimpleNamespace(
            _closing_started=False,
            close_app=lambda: events.append("backend"),
        )

        with patch("controllers.gui.app_shell_controller.logger.exception"):
            controller.close_application()

        self.assertEqual(events, ["pages", "backend"])

    def test_backend_startup_blocks_early_send(self):
        controller, view, fake_use, fake_services = self._make_controller({}, view=_FakeView())
        controller._main_controller = None
        with patch("controllers.gui.app_shell_controller.use", fake_use), patch(
            "controllers.gui.app_shell_controller.services", lambda: fake_services
        ):
            result = controller.send_message(user_input="too early")
        self.assertFalse(result)
        self.assertTrue(view.errors)
        self.assertEqual(controller._event_bus.emitted, [])

    def test_no_capture_enabled_sends_synchronously(self):
        capture = _FakeCapture()
        controller, view, fake_use, fake_services = self._make_controller(
            {"AUTO_ATTACH_IMAGES": False, "ENABLE_CAMERA_CAPTURE": False},
            capture,
        )
        with patch("controllers.gui.app_shell_controller.use", fake_use), patch(
            "controllers.gui.app_shell_controller.services", lambda: fake_services
        ):
            self.assertTrue(controller.send_message(user_input="привет"))
        self.assertEqual(capture.capture_threads, [])
        self.assertEqual(len(controller._event_bus.emitted), 1)
        _, payload = controller._event_bus.emitted[0]
        self.assertEqual(payload["user_input"], "привет")
        self.assertEqual(payload["image_data"], [])
        self.assertEqual(len(view.rendered), 1)

    def test_capture_runs_off_caller_thread(self):
        capture = _FakeCapture(screen=[b"screen"], camera=[b"cam"], delay=0.2)
        controller, view, fake_use, fake_services = self._make_controller(
            {
                "AUTO_ATTACH_IMAGES": True,
                "ENABLE_CAMERA_CAPTURE": True,
                "ENABLE_IMAGE_ANALYSIS": True,
            },
            capture,
        )
        threads: list[threading.Thread] = []

        def fake_run_async(_target, worker, on_ok, **_kwargs):
            thread = threading.Thread(target=lambda: on_ok(worker()), name="capture-worker")
            thread.start()
            threads.append(thread)
            return thread

        caller_thread = threading.current_thread().name
        with patch("controllers.gui.app_shell_controller.use", fake_use), patch(
            "controllers.gui.app_shell_controller.services", lambda: fake_services
        ), patch("controllers.gui.app_shell_controller.run_async", fake_run_async):
            started = time.perf_counter()
            self.assertTrue(controller.send_message(user_input="что на экране?"))
            self.assertLess(time.perf_counter() - started, 0.1)
            for thread in threads:
                thread.join(timeout=3)

        self.assertTrue(capture.capture_threads)
        self.assertNotIn(caller_thread, capture.capture_threads)
        _, payload = controller._event_bus.emitted[0]
        self.assertEqual(payload["image_data"], [b"screen", b"cam"])

    def test_image_order_and_dedupe_preserved(self):
        controller, view, fake_use, fake_services = self._make_controller(
            {"ENABLE_IMAGE_ANALYSIS": True},
            view=_FakeView(staged=[b"staged"]),
        )
        with patch("controllers.gui.app_shell_controller.use", fake_use), patch(
            "controllers.gui.app_shell_controller.services", lambda: fake_services
        ):
            controller._finish_send_message(
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
        _, payload = controller._event_bus.emitted[0]
        self.assertEqual(payload["image_data"], [b"dup", b"staged", b"cam"])
        self.assertEqual(view.staged_clear_count, 1)


if __name__ == "__main__":
    unittest.main()
