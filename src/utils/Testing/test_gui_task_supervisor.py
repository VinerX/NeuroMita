"""Владелец GUI-воркеров: strong ownership, ворота на закрытии, выжившие.

Раньше воркеры лежали в WeakSet и в атрибутах виджета. Оттуда следовали три
беды: живой поток мог быть собран GC, после начала закрытия окна кто угодно мог
стартовать новую задачу, а колбэк старого воркера затирал ссылку на новый.
Здесь проверяется поведение супервизора, который эти роли забрал себе.

Qt не поднимается: супервизору нужны только методы жизненного цикла потока.
"""
import gc

import pytest

from core.gui_task_supervisor import (
    GuiTaskSupervisor,
    TaskAlreadyRunning,
    TaskOwnerClosed,
    TaskResourceBusy,
)


class _Dialog:
    """Двойник окна-владельца. Именно класс, а не `object()`: супервизор держит
    владельцев слабыми ссылками, и голый object() их не поддерживает."""


class _FakeWorker:
    """Минимальный двойник QThread: интересен только его жизненный цикл."""

    def __init__(self, name="w", *, obeys_interruption=True, task_key="", owner=None,
                 exclusive_resources=()):
        self.name = name
        self.task_key = task_key
        self.exclusive_resources = frozenset(exclusive_resources)
        self._owner = owner
        self._running = True
        self._finished = False
        self._obeys = obeys_interruption
        self.interrupted = False
        self.signals_blocked = False
        self.detached = False

    def isRunning(self):
        return self._running

    def isFinished(self):
        return self._finished

    def requestInterruption(self):
        self.interrupted = True
        if self._obeys:
            self.finish()

    def wait(self, msec):
        return not self._running

    def blockSignals(self, value):
        self.signals_blocked = bool(value)

    def detach_ui_callbacks(self):
        self.detached = True

    def task_owner(self):
        return self._owner

    def objectName(self):
        return self.name

    def finish(self):
        self._running = False
        self._finished = True


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
    assert stubborn.detached is True
    # blockSignals глушит и служебный finished — по нему воркер снимается с
    # учёта, так что заглушить его значило бы держать поток вечно.
    assert stubborn.signals_blocked is False


def test_survivor_disappears_from_supervisor_when_it_finally_finishes():
    sup = GuiTaskSupervisor()
    stubborn = _FakeWorker("stubborn", obeys_interruption=False)
    sup.register(stubborn)
    sup.stop_all(timeout_ms=10)

    # Досчитал уже после закрытия окна: finished жив, значит forget доедет.
    stubborn.finish()
    sup.forget(stubborn)

    assert sup.active_workers() == []


def test_start_is_forbidden_after_shutdown_began():
    sup = GuiTaskSupervisor()
    sup.stop_all(timeout_ms=10)

    assert sup.is_shutting_down() is True
    with pytest.raises(RuntimeError):
        sup.register(_FakeWorker("late"))


def test_finished_old_worker_does_not_drop_the_new_one():
    sup = GuiTaskSupervisor()
    old = _FakeWorker("old", task_key="reindex_all")
    sup.register(old)
    old.finish()

    new = _FakeWorker("new", task_key="reindex_all")
    sup.register(new)

    # Старый досчитал и отписался — ссылка на новый обязана уцелеть.
    sup.forget(old)

    assert [w.name for w in sup.active_workers()] == ["new"]
    assert sup.running("reindex_all") is new


def test_second_task_with_the_same_key_is_refused():
    sup = GuiTaskSupervisor()
    first = _FakeWorker("first", task_key="full_reindex_all")
    sup.register(first)

    with pytest.raises(TaskAlreadyRunning) as conflict:
        sup.register(_FakeWorker("second", task_key="full_reindex_all"))

    assert conflict.value.worker is first
    assert [w.name for w in sup.active_workers()] == ["first"]


def test_key_is_taken_from_registration_not_from_start():
    """Занятость ключа начинается с register(), а не с реального старта.

    Регистрация идёт до `QThread.start()`; если бы «занято» считалось по
    isRunning(), в это окно пролезала бы вторая переиндексация той же БД.
    """
    sup = GuiTaskSupervisor()
    pending = _FakeWorker("pending", task_key="full_reindex_all")
    pending._running = False  # зарегистрирован, поток ещё не стартовал

    sup.register(pending)

    assert sup.running("full_reindex_all") is pending
    with pytest.raises(TaskAlreadyRunning):
        sup.register(_FakeWorker("second", task_key="full_reindex_all"))


def test_finished_task_frees_its_key_even_before_forget():
    """Между концом потока и forget() ключ обязан освободиться.

    `finished` доставляется очередью в поток-владелец, поэтому forget может
    опоздать на целый цикл событий — кнопку к этому моменту уже нажали.
    """
    sup = GuiTaskSupervisor()
    done = _FakeWorker("done", task_key="full_reindex_all")
    sup.register(done)
    done.finish()

    fresh = _FakeWorker("fresh", task_key="full_reindex_all")
    sup.register(fresh)

    assert sup.running("full_reindex_all") is fresh


def test_tasks_without_key_are_never_treated_as_duplicates():
    sup = GuiTaskSupervisor()
    sup.register(_FakeWorker("a"))
    sup.register(_FakeWorker("b"))

    assert len(sup.active_workers()) == 2


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


def test_cancel_owner_stops_only_the_tasks_of_that_window():
    """Закрытый диалог гасит свои задачи и не трогает чужие.

    Единственный глобальный stop_all для этого не годится: просмотрщик БД не
    вправе отменять переиндексацию, запущенную из главного окна.
    """
    sup = GuiTaskSupervisor()
    dialog = _Dialog()
    mine = _FakeWorker("dialog-task", owner=dialog)
    foreign = _FakeWorker("reindex-all", task_key="reindex_all")
    sup.register(mine)
    sup.register(foreign)

    sup.cancel_owner(dialog, timeout_ms=10)

    assert mine.interrupted is True
    assert foreign.interrupted is False
    assert sup.running("reindex_all") is foreign
    # Ворота остались открытыми: приложение живёт дальше.
    assert sup.is_shutting_down() is False
    assert sup.register(_FakeWorker("next")) is None


def test_cancel_owner_detaches_a_stubborn_task_of_that_window():
    sup = GuiTaskSupervisor()
    dialog = _Dialog()
    stubborn = _FakeWorker("stuck", obeys_interruption=False, owner=dialog)
    sup.register(stubborn)

    survivors = sup.cancel_owner(dialog, timeout_ms=10)

    assert survivors == [stubborn]
    assert stubborn.detached is True


def test_cancel_owner_without_owner_is_a_noop():
    sup = GuiTaskSupervisor()
    worker = _FakeWorker("ownerless")
    sup.register(worker)

    assert sup.cancel_owner(None, timeout_ms=10) == []
    assert worker.interrupted is False


def test_two_reindexings_of_the_same_base_cannot_run_together():
    """Разные ключи, одна база — вторая задача не запускается.

    «Индекс нового» и «полная переиндексация» зовутся по-разному, но пишут в
    одну индексную базу. Одного task_key тут мало — исключение идёт по ресурсу.
    """
    sup = GuiTaskSupervisor()
    first = _FakeWorker("fill", task_key="reindex_all", exclusive_resources={"rag-index"})
    sup.register(first)

    with pytest.raises(TaskResourceBusy) as conflict:
        sup.register(_FakeWorker(
            "full", task_key="full_reindex_all", exclusive_resources={"rag-index"},
        ))

    assert conflict.value.resource == "rag-index"
    assert conflict.value.worker is first


def test_index_of_all_characters_blocks_a_single_one():
    """Ресурсы иерархичны: общий занят — частный не пройдёт, и наоборот."""
    sup = GuiTaskSupervisor()
    sup.register(_FakeWorker("all", exclusive_resources={"rag-index"}))

    with pytest.raises(TaskResourceBusy):
        sup.register(_FakeWorker("one", exclusive_resources={"rag-index:crazy"}))

    other = GuiTaskSupervisor()
    other.register(_FakeWorker("one", exclusive_resources={"rag-index:crazy"}))
    with pytest.raises(TaskResourceBusy):
        other.register(_FakeWorker("all", exclusive_resources={"rag-index"}))


def test_two_characters_are_indexed_independently():
    sup = GuiTaskSupervisor()
    sup.register(_FakeWorker("crazy", exclusive_resources={"rag-index:crazy"}))
    sup.register(_FakeWorker("kind", exclusive_resources={"rag-index:kind"}))

    assert len(sup.active_workers()) == 2


def test_finished_task_releases_its_resource():
    sup = GuiTaskSupervisor()
    done = _FakeWorker("done", exclusive_resources={"rag-index"})
    sup.register(done)
    done.finish()

    sup.register(_FakeWorker("next", exclusive_resources={"rag-index:crazy"}))

    assert [w.name for w in sup.active_workers()] == ["next"]


def test_closed_owner_cannot_start_new_tasks():
    """Поздний колбэк умершего окна не заводит новую задачу.

    cancel_owner отвязывает колбэки, но один из них мог уже стоять в очереди
    GUI-потока — и раньше успевал нажать «повторить» на уничтоженном диалоге.
    """
    sup = GuiTaskSupervisor()
    dialog = _Dialog()
    first = _FakeWorker("first", owner=dialog)
    sup.register(first)
    sup.cancel_owner(dialog, timeout_ms=10)
    sup.forget(first)  # остановленный воркер снимается с учёта по finished

    with pytest.raises(TaskOwnerClosed):
        sup.register(_FakeWorker("late", owner=dialog))

    # Чужие окна закрытие диалога не задевает.
    alive = _Dialog()
    sup.register(_FakeWorker("other", owner=alive))
    assert [w.name for w in sup.active_workers()] == ["other"]


def test_forget_of_unknown_worker_is_harmless():
    sup = GuiTaskSupervisor()
    sup.forget(_FakeWorker("ghost"))
    assert sup.active_workers() == []
