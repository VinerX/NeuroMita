"""Живой TaskWorker: дубль задачи не стартует, отвязка от GUI не ломает учёт.

Двойники QThread проверяют логику супервизора, но два свойства держатся на
настоящем Qt: `start()` обязан отказать, если задача с тем же ключом уже идёт
(иначе две полные переиндексации пишут одну БД), а `detach_ui_callbacks()`
обязан оставить служебный `QThread.finished` живым — по нему воркер снимается
с учёта, и без него супервизор держал бы поток вечно.
"""
from __future__ import annotations

import os
import threading
import unittest


class TaskWorkerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError as exc:  # pragma: no cover - окружение без Qt
            raise unittest.SkipTest(f"PyQt6 is unavailable: {exc}") from exc

        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from core.gui_task_supervisor import gui_task_supervisor

        self.supervisor = gui_task_supervisor()
        self.release = threading.Event()
        self.started = threading.Event()
        self.workers: list = []

    def tearDown(self) -> None:
        self.release.set()
        for worker in self.workers:
            try:
                worker.wait(5000)
            except Exception:
                pass
            self.supervisor.forget(worker)
        self._drain()

    def _drain(self) -> None:
        """Довезти очередь сигналов: `finished` доставляется в GUI-поток."""
        for _ in range(3):
            self.application.processEvents()

    def _worker(self, task_key: str = ""):
        from controllers.gui.task_worker import TaskWorker

        def job():
            self.started.set()
            self.release.wait(5.0)
            return "done"

        worker = TaskWorker(job, task_key=task_key)
        self.workers.append(worker)
        return worker

    def test_second_full_reindex_all_does_not_start(self) -> None:
        first = self._worker("full_reindex_all")
        second = self._worker("full_reindex_all")

        self.assertTrue(first.start())
        self.assertTrue(self.started.wait(5.0))

        self.assertFalse(second.start())
        self.assertFalse(second.isRunning())
        self.assertNotIn(second, self.supervisor.active_workers())

        self.release.set()
        self.assertTrue(first.wait(5000))
        self._drain()
        self.assertNotIn(first, self.supervisor.active_workers())

    def test_key_is_free_again_after_the_task_finished(self) -> None:
        first = self._worker("full_reindex_all")
        self.assertTrue(first.start())
        self.release.set()
        self.assertTrue(first.wait(5000))
        self._drain()

        self.release.clear()
        self.started.clear()
        second = self._worker("full_reindex_all")
        self.assertTrue(second.start())
        self.assertTrue(self.started.wait(5.0))

    def test_detach_ui_callbacks_keeps_the_worker_accountable(self) -> None:
        results: list = []
        worker = self._worker()
        worker.finished_signal.connect(results.append)

        self.assertTrue(worker.start())
        self.assertTrue(self.started.wait(5.0))

        # Окно закрылось, а задача висит в SQLite — отвязываем её от GUI.
        worker.detach_ui_callbacks()
        self.release.set()
        self.assertTrue(worker.wait(5000))
        self._drain()

        self.assertEqual([], results)
        self.assertNotIn(worker, self.supervisor.active_workers())


if __name__ == "__main__":
    unittest.main()
