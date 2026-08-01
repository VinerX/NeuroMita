"""Владелец GUI-воркеров: strong ownership, ворота на закрытии, выжившие.

Раньше воркеры лежали в WeakSet и в атрибутах виджета. Оттуда следовали три
беды: живой поток мог быть собран GC, после начала закрытия окна кто угодно мог
стартовать новую задачу, а колбэк старого воркера затирал ссылку на новый.
Здесь проверяется поведение супервизора, который эти роли забрал себе.

Qt не поднимается: супервизору нужны только методы жизненного цикла потока.
"""
import gc

import pytest

from core.gui_task_supervisor import GuiTaskSupervisor


class _FakeWorker:
    """Минимальный двойник QThread: интересен только его жизненный цикл."""

    def __init__(self, name="w", *, obeys_interruption=True, task_key=""):
        self.name = name
        self.task_key = task_key
        self._running = True
        self._obeys = obeys_interruption
        self.interrupted = False
        self.signals_blocked = False

    def isRunning(self):
        return self._running

    def requestInterruption(self):
        self.interrupted = True
        if self._obeys:
            self._running = False

    def wait(self, msec):
        return not self._running

    def blockSignals(self, value):
        self.signals_blocked = bool(value)

    def objectName(self):
        return self.name

    def finish(self):
        self._running = False


def test_supervisor_keeps_strong_reference():
    sup = GuiTaskSupervisor()
    sup.register(_FakeWorker("alive"))
    gc.collect()

    assert [w.name for w in sup.active_workers()] == ["alive"]


def test_stop_all_interrupts_and_reports_no_survivors():
    sup = GuiTaskSupervisor()
    worker = _FakeWorker("obedient")
    sup.register(worker)

    survivors = sup.stop_all(timeout_ms=10)

    assert worker.interrupted is True
    assert survivors == []
    assert worker.signals_blocked is False


def test_worker_ignoring_interruption_becomes_survivor_and_is_detached():
    sup = GuiTaskSupervisor()
    stubborn = _FakeWorker("stubborn", obeys_interruption=False)
    sup.register(stubborn)

    survivors = sup.stop_all(timeout_ms=10)

    assert survivors == [stubborn]
    assert stubborn.interrupted is True
    # Отвязан от GUI: задача внутри может висеть в SQLite, но её сигналы уже
    # никого не разбудят — именно это раньше и роняло приложение при закрытии.
    assert stubborn.signals_blocked is True


def test_start_is_forbidden_after_shutdown_began():
    sup = GuiTaskSupervisor()
    sup.stop_all(timeout_ms=10)

    assert sup.is_shutting_down() is True
    with pytest.raises(RuntimeError):
        sup.register(_FakeWorker("late"))


def test_finished_old_worker_does_not_drop_the_new_one():
    sup = GuiTaskSupervisor()
    old = _FakeWorker("old", task_key="reindex_all")
    new = _FakeWorker("new", task_key="reindex_all")
    sup.register(old)
    sup.register(new)

    # Старый досчитал и отписался — ссылка на новый обязана уцелеть.
    old.finish()
    sup.forget(old)

    assert [w.name for w in sup.active_workers()] == ["new"]
    assert sup.running("reindex_all") is new


def test_running_ignores_finished_and_foreign_tasks():
    sup = GuiTaskSupervisor()
    done = _FakeWorker("done", task_key="reindex_all")
    done.finish()
    other = _FakeWorker("other", task_key="export")
    sup.register(done)
    sup.register(other)

    assert sup.running("reindex_all") is None
    assert sup.running("export") is other
    assert sup.running("") is None


def test_forget_of_unknown_worker_is_harmless():
    sup = GuiTaskSupervisor()
    sup.forget(_FakeWorker("ghost"))
    assert sup.active_workers() == []
