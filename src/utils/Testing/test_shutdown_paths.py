from __future__ import annotations

import sys
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.capture_controller import CaptureController
from controllers.ai_engine_controller import _Worker
from controllers.loop_controller import LoopController


class _FakeQueue:
    def __init__(self):
        self.items = []
        self.closed = 0
        self.cancelled = 0

    def put(self, item):
        self.items.append(item)

    def put_nowait(self, item):
        self.items.append(item)

    def close(self):
        self.closed += 1

    def cancel_join_thread(self):
        self.cancelled += 1


class _FakeProcess:
    def __init__(self, alive=False):
        self._alive = alive
        self.terminated = 0
        self.join_calls = []

    def is_alive(self):
        return self._alive

    def terminate(self):
        self.terminated += 1
        self._alive = False

    def join(self, timeout=None):
        self.join_calls.append(timeout)
        self._alive = False


class _FakeThread:
    def __init__(self, alive=True):
        self._alive = alive
        self.join_calls = []

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.join_calls.append(timeout)
        self._alive = False


class ShutdownPathTests(unittest.TestCase):
    def test_capture_controller_shutdown_stops_timer_and_waits_thread(self):
        capture_controller = CaptureController.__new__(CaptureController)
        capture_controller._shutdown_event = threading.Event()
        capture_controller.image_request_thread = _FakeThread(alive=True)

        calls = []

        def _record(name):
            def inner():
                calls.append(name)
            return inner

        capture_controller.stop_image_request_timer = _record("timer")
        capture_controller.stop_screen_capture_thread = _record("screen")
        capture_controller.stop_camera_capture_thread = _record("camera")

        capture_controller.shutdown()

        self.assertTrue(capture_controller._shutdown_event.is_set())
        self.assertEqual(calls, ["timer", "screen", "camera"])
        self.assertEqual(capture_controller.image_request_thread.join_calls, [2.0])

    def test_ai_worker_stop_wakes_threads_and_closes_queues(self):
        worker = _Worker.__new__(_Worker)
        worker.worker_name = "test"
        worker.stopping = threading.Event()
        worker.admission_lock = threading.Lock()
        worker.cmd_q = _FakeQueue()
        worker.res_q = _FakeQueue()
        worker.log_q = _FakeQueue()
        worker.proc = _FakeProcess(alive=False)
        worker.pending_lock = threading.RLock()
        pending_future = Future()
        worker.pending = {"req-1": pending_future}
        worker.res_thread = _FakeThread(alive=True)
        worker.log_thread = _FakeThread(alive=True)

        worker.stop(timeout=0)

        self.assertTrue(worker.stopping.is_set())
        self.assertEqual(worker.res_q.items, [None])
        self.assertEqual(worker.log_q.items, [None])
        self.assertEqual(worker.res_thread.join_calls, [1.0])
        self.assertEqual(worker.log_thread.join_calls, [1.0])
        self.assertEqual(worker.cmd_q.closed, 1)
        self.assertEqual(worker.res_q.closed, 1)
        self.assertEqual(worker.log_q.closed, 1)
        self.assertTrue(pending_future.done())
        self.assertIsInstance(pending_future.exception(), RuntimeError)

    def test_loop_controller_stop_requests_threadsafe_stop(self):
        loop_controller = LoopController.__new__(LoopController)
        calls = []

        class _FakeLoop:
            def __init__(self):
                self.stopped = 0
                self.closed = 0

            def is_closed(self):
                return False

            def is_running(self):
                return True

            def call_soon_threadsafe(self, callback):
                calls.append(callback)

            def stop(self):
                self.stopped += 1

            def close(self):
                self.closed += 1

        loop_controller.loop = _FakeLoop()
        loop_controller.asyncio_thread = _FakeThread(alive=False)

        loop_controller.stop_loop()

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
