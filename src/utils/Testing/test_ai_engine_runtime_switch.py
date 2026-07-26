"""Окно пересборки AI-рантайма не должно терять вызовы.

Регресс: во время смены состава пакетов каждый вызов движка падал мгновенно.
Пакет эмбеддингов памяти (сотни элементов) терялся целиком, а лог заливало
трейсбеками — при том что окно закрывается за считанные секунды.
"""

from __future__ import annotations

import threading
import time
import unittest

from controllers.ai_engine_controller import AIEngineController, _RuntimeSwitchGate
from services.contracts import AIRuntimeUnavailable


class _FakeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def call(self, method, payload=None, *, service=None, timeout=None):
        from concurrent.futures import Future

        self.calls.append((str(service), str(method)))
        future: Future = Future()
        future.set_result({"ok": True})
        return future


def _bare_controller(gate: _RuntimeSwitchGate, worker: _FakeWorker) -> AIEngineController:
    controller = object.__new__(AIEngineController)
    controller._runtime_switching = gate
    controller._shutting_down = threading.Event()
    controller._lock = threading.RLock()
    controller._switch_dispatcher = None
    controller._deferred_calls = set()
    controller._workers = {"shared": worker}
    controller._service_to_worker = {"rag": "shared"}
    return controller


class RuntimeSwitchGateTests(unittest.TestCase):
    @staticmethod
    def _open_from_other_thread(gate: _RuntimeSwitchGate, hold_sec: float) -> threading.Thread:
        opened = threading.Event()

        def switcher():
            gate.begin(waitable=True)
            opened.set()
            time.sleep(hold_sec)
            gate.end()

        thread = threading.Thread(target=switcher)
        thread.start()
        assert opened.wait(1.0)
        return thread

    def test_waitable_window_is_waited_out(self):
        gate = _RuntimeSwitchGate()
        thread = self._open_from_other_thread(gate, 0.2)

        started = time.monotonic()
        self.assertTrue(gate.wait_idle(5.0))
        self.assertGreaterEqual(time.monotonic() - started, 0.1)
        thread.join(2.0)

    def test_waitable_window_reports_failure_after_budget(self):
        gate = _RuntimeSwitchGate()
        thread = self._open_from_other_thread(gate, 1.0)
        self.assertFalse(gate.wait_idle(0.05))
        thread.join(3.0)

    def test_maintenance_window_is_not_waitable(self):
        gate = _RuntimeSwitchGate()
        gate.begin(waitable=False)
        try:
            started = time.monotonic()
            self.assertFalse(gate.wait_idle(5.0))
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertEqual(gate.reason(), "AI runtime is suspended for maintenance")
        finally:
            gate.end()

    def test_switching_thread_never_waits_for_itself(self):
        gate = _RuntimeSwitchGate()
        gate.begin(waitable=True)  # владелец окна — текущий поток
        try:
            self.assertFalse(gate.wait_idle(5.0))
        finally:
            gate.end()

    def test_idle_gate_lets_calls_through(self):
        gate = _RuntimeSwitchGate()
        self.assertTrue(gate.wait_idle(0.0))
        self.assertEqual(gate.reason(), "")


class RuntimeSwitchCallTests(unittest.TestCase):
    def test_call_waits_for_composition_switch_instead_of_failing(self):
        gate = _RuntimeSwitchGate()
        worker = _FakeWorker()
        controller = _bare_controller(gate, worker)

        # Окно открывает другой поток: владелец не может ждать сам себя.
        opened = threading.Event()

        def switcher():
            gate.begin(waitable=True)
            opened.set()
            time.sleep(0.2)
            gate.end()

        thread = threading.Thread(target=switcher)
        thread.start()
        self.assertTrue(opened.wait(1.0))

        future = controller.call("rag", "get_embeddings", {"texts": ["a"]})
        self.assertEqual(future.result(timeout=1.0), {"ok": True})
        self.assertEqual(worker.calls, [("rag", "get_embeddings")])
        thread.join(2.0)

    def test_call_fails_typed_when_window_outlives_budget(self):
        gate = _RuntimeSwitchGate()
        worker = _FakeWorker()
        controller = _bare_controller(gate, worker)

        opened = threading.Event()
        release = threading.Event()

        def switcher():
            gate.begin(waitable=True)
            opened.set()
            release.wait(5.0)
            gate.end()

        thread = threading.Thread(target=switcher)
        thread.start()
        try:
            self.assertTrue(opened.wait(1.0))
            future = controller.call("rag", "get_embeddings", {}, timeout=0.05)
            with self.assertRaises(AIRuntimeUnavailable):
                future.result(timeout=1.0)
            self.assertEqual(worker.calls, [])
        finally:
            release.set()
            thread.join(2.0)

    def test_call_does_not_block_the_calling_thread(self):
        """`call` обязан вернуть Future сразу: иначе GUI-поток встаёт на всё окно."""
        gate = _RuntimeSwitchGate()
        worker = _FakeWorker()
        controller = _bare_controller(gate, worker)

        opened = threading.Event()
        release = threading.Event()

        def switcher():
            gate.begin(waitable=True)
            opened.set()
            release.wait(5.0)
            gate.end()

        thread = threading.Thread(target=switcher)
        thread.start()
        try:
            self.assertTrue(opened.wait(1.0))
            started = time.monotonic()
            future = controller.call("rag", "get_embeddings", {})
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertFalse(future.done())
            release.set()
            self.assertEqual(future.result(timeout=2.0), {"ok": True})
        finally:
            release.set()
            thread.join(2.0)

    def test_switching_thread_gets_immediate_answer(self):
        """Поток, ведущий пересборку, не должен ждать сам себя даже через Future."""
        gate = _RuntimeSwitchGate()
        worker = _FakeWorker()
        controller = _bare_controller(gate, worker)
        gate.begin(waitable=True)
        try:
            future = controller.call("rag", "get_embeddings", {})
            with self.assertRaises(AIRuntimeUnavailable):
                future.result(timeout=0.1)
            self.assertEqual(worker.calls, [])
        finally:
            gate.end()

    def test_shutdown_answers_deferred_calls(self):
        gate = _RuntimeSwitchGate()
        worker = _FakeWorker()
        controller = _bare_controller(gate, worker)

        opened = threading.Event()
        release = threading.Event()

        def switcher():
            gate.begin(waitable=True)
            opened.set()
            release.wait(5.0)
            gate.end()

        thread = threading.Thread(target=switcher)
        thread.start()
        try:
            self.assertTrue(opened.wait(1.0))
            future = controller.call("rag", "get_embeddings", {})
            controller._shutting_down.set()
            controller._abort_deferred_calls()
            with self.assertRaises(AIRuntimeUnavailable):
                future.result(timeout=1.0)
            self.assertEqual(worker.calls, [])
        finally:
            release.set()
            thread.join(2.0)

    def test_maintenance_window_fails_calls_immediately(self):
        gate = _RuntimeSwitchGate()
        worker = _FakeWorker()
        controller = _bare_controller(gate, worker)
        gate.begin(waitable=False)
        try:
            started = time.monotonic()
            future = controller.call("rag", "get_embeddings", {})
            with self.assertRaises(AIRuntimeUnavailable):
                future.result(timeout=1.0)
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertEqual(worker.calls, [])
        finally:
            gate.end()


if __name__ == "__main__":
    unittest.main()
