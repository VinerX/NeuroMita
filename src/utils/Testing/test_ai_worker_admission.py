"""Приём запроса воркером и его остановка не должны пересекаться.

Регресс: `call()` проверял флаг остановки, и только потом регистрировал запрос
в pending и клал его в очередь. Пересборка рантайма успевала вклиниться в этот
зазор: `stop()` выставлял флаг, добивал pending, а опоздавший запрос оседал в
уже мёртвом воркере — без ответа и без шанса на повтор.
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

from controllers.ai_engine_controller import _Worker, _WorkerUnavailable


class _FakeQueue:
    def __init__(self):
        self.items: list[dict] = []
        self.closed = False

    def put(self, item, timeout=None):
        self.put_nowait(item)

    def put_nowait(self, item):
        if self.closed:
            raise RuntimeError("queue is closed")
        self.items.append(item)

    def close(self):
        self.closed = True

    def cancel_join_thread(self):
        return None


class _FakeProc:
    def __init__(self, *, on_is_alive=None):
        self.alive = True
        self.exitcode = None
        self._on_is_alive = on_is_alive

    def is_alive(self):
        if self._on_is_alive is not None:
            hook, self._on_is_alive = self._on_is_alive, None
            hook()
        return self.alive

    def terminate(self):
        self.alive = False

    def join(self, timeout=None):
        self.alive = False


def _bare_worker(proc: _FakeProc) -> _Worker:
    worker = object.__new__(_Worker)
    worker.worker_name = "shared"
    worker.primary_service = "rag"
    worker.service_names = ("rag",)
    worker.ready_by_service = {"rag": threading.Event()}
    worker.ready_by_service["rag"].set()
    worker.stopping = threading.Event()
    worker.expected_exit = threading.Event()
    worker.admission_lock = threading.Lock()
    worker.pending_lock = threading.RLock()
    worker.pending = {}
    worker.pending_deadlines = {}
    worker.pending_meta = {}
    worker.quarantined_services = {}
    worker.recovering_services = set()
    worker.request_timeout = 30.0
    worker.cmd_q = _FakeQueue()
    worker.res_q = _FakeQueue()
    worker.log_q = _FakeQueue()
    worker.proc = proc
    return worker


class WorkerAdmissionTests(unittest.TestCase):
    def test_stop_cannot_cut_in_between_check_and_enqueue(self):
        """Пока запрос принимается, остановка обязана ждать своей очереди."""
        stop_entered = threading.Event()
        stopping_seen_mid_admission: list[bool] = []

        def during_admission():
            # Внутри допуска: поднимаем остановку и даём ей время добежать.
            threading.Thread(target=lambda: worker.stop(timeout=0.1)).start()
            stop_entered.wait(1.0)
            time.sleep(0.2)
            stopping_seen_mid_admission.append(worker.stopping.is_set())

        proc = _FakeProc(on_is_alive=during_admission)
        worker = _bare_worker(proc)

        real_stop = worker.stop

        def stop_with_signal(timeout=5.0):
            stop_entered.set()
            return real_stop(timeout=timeout)

        worker.stop = stop_with_signal

        future = worker.call("get_embeddings", {"texts": ["a"]}, service="rag")

        self.assertEqual(
            stopping_seen_mid_admission,
            [False],
            "stop() не должен успевать выставить флаг посреди приёма запроса",
        )
        # Запрос приняли до остановки: он честно ушёл в очередь.
        methods = [item.get("method") for item in list(worker.cmd_q.items) if item.get("method")]
        self.assertEqual(methods, ["get_embeddings"])

        # И так же честно завершился ошибкой выключения — молча повторять уже
        # отправленный запрос нельзя, он мог успеть выполниться.
        deadline = time.monotonic() + 3.0
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(future.done(), "принятый запрос не должен остаться без ответа")
        with self.assertRaises(RuntimeError):
            future.result(timeout=1.0)
        self.assertEqual(worker.pending, {})

    def test_call_after_stop_is_retryable(self):
        """Отказ на входе — типизированный: наверху он означает «попробуй снова»."""
        worker = _bare_worker(_FakeProc())
        worker.stop(timeout=0.1)

        future = worker.call("get_embeddings", {}, service="rag")

        with self.assertRaises(_WorkerUnavailable):
            future.result(timeout=1.0)
        self.assertEqual(
            [item for item in worker.cmd_q.items if item.get("method")],
            [],
            "мёртвый воркер не должен получать запросов",
        )

    def test_dead_process_is_refused_as_retryable(self):
        proc = _FakeProc()
        proc.alive = False
        worker = _bare_worker(proc)

        future = worker.call("get_embeddings", {}, service="rag")

        with self.assertRaises(_WorkerUnavailable):
            future.result(timeout=1.0)

    def test_accepted_call_is_registered_before_enqueue(self):
        worker = _bare_worker(_FakeProc())

        future = worker.call("get_embeddings", {"texts": ["a"]}, service="rag")

        self.assertFalse(future.done())
        self.assertEqual(len(worker.pending), 1)
        req_id = next(iter(worker.pending))
        self.assertEqual(worker.cmd_q.items[0]["req_id"], req_id)
        self.assertEqual(worker.pending_meta[req_id], ("rag", "get_embeddings"))

    def test_second_stop_is_a_noop(self):
        worker = _bare_worker(_FakeProc())
        worker.stop(timeout=0.1)
        worker.cmd_q.items.clear()
        worker.cmd_q.closed = False

        worker.stop(timeout=0.1)

        self.assertEqual(worker.cmd_q.items, [])


if __name__ == "__main__":
    unittest.main()
