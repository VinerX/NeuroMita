"""Владелец живых GUI-воркеров (QThread) — от старта до завершения.

Раньше ссылки на воркеры лежали в атрибутах виджетов (`gui._reindex_worker`), и
при закрытии окна поток продолжал работать: он дёргал колбэки уже уничтоженных
Qt-объектов, а Qt ругался «QThread: Destroyed while thread is still running».

Супервизор держит сильные ссылки (слабых мало: работающий поток нельзя отдавать
сборщику), запрещает старт новых задач после начала закрытия и честно сообщает,
кого не удалось остановить — такие воркеры отвязываются от GUI, но остаются
живыми до собственного конца.

Qt здесь не импортируется: супервизору нужны только методы жизненного цикла
потока, поэтому его можно дёргать из headless-кода (тесты, MainController).
"""
from __future__ import annotations

import threading
import time
import weakref
from typing import Any, List

from main_logger import logger


class TaskRefused(RuntimeError):
    """Супервизор отказал в запуске задачи. Приложение при этом живо."""


class TaskAlreadyRunning(TaskRefused):
    """Задача с таким ключом уже под опекой супервизора."""

    def __init__(self, task_key: str, worker: Any) -> None:
        super().__init__(f"Задача '{task_key}' уже запущена")
        self.task_key = str(task_key or "")
        self.worker = worker


class TaskResourceBusy(TaskRefused):
    """Ресурс задачи занят другой, конфликтующей с ней задачей."""

    def __init__(self, resource: str, worker: Any) -> None:
        super().__init__(f"Ресурс '{resource}' занят другой задачей")
        self.resource = str(resource or "")
        self.worker = worker


class TaskOwnerClosed(TaskRefused):
    """Владелец задачи уже закрыт: его задачи не запускаются."""


def _conflicts(first: str, second: str) -> bool:
    """Конфликтуют ли два имени ресурса.

    Имена иерархические через двоеточие: `rag-index` — вся индексная база,
    `rag-index:crazy` — индекс одного персонажа. Общий ресурс конфликтует и сам
    с собой, и со всеми своими частями, части между собой — нет.
    """
    if first == second:
        return True
    return first.startswith(f"{second}:") or second.startswith(f"{first}:")


class GuiTaskSupervisor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: set[Any] = set()
        self._closing = False
        # Владельцы, чьи окна уже закрыты. Ссылки слабые: закрытый диалог не
        # должен жить дольше только потому, что супервизор его помнит.
        self._closed_owners: "weakref.WeakSet[Any]" = weakref.WeakSet()

    def register(self, worker: Any) -> None:
        """Взять воркер под опеку.

        RuntimeError — приложение уже закрывается. TaskRefused — задачу не
        запускаем: занят ключ, занят ресурс или закрыт владелец. Все проверки
        живут здесь, а не на стороне вызывающего: `running()` + `start()` двумя
        шагами — это гонка, в которую пролезали две переиндексации одной БД.
        """
        key = str(getattr(worker, "task_key", "") or "")
        resources = self._resources_of(worker)
        owner = self._owner_of(worker)
        with self._lock:
            if self._closing:
                raise RuntimeError(
                    "GUI закрывается: новые фоновые задачи не запускаются"
                )
            if owner is not None and owner in self._closed_owners:
                raise TaskOwnerClosed(
                    "Владелец задачи уже закрыт: запуск отменён"
                )
            if key:
                existing = self._live_with_key(key)
                if existing is not None and existing is not worker:
                    raise TaskAlreadyRunning(key, existing)
            for resource in resources:
                holder = self._live_with_resource(resource, worker)
                if holder is not None:
                    raise TaskResourceBusy(resource, holder)
            self._workers.add(worker)

    def forget(self, worker: Any) -> None:
        with self._lock:
            self._workers.discard(worker)

    def is_shutting_down(self) -> bool:
        with self._lock:
            return self._closing

    def active_workers(self) -> List[Any]:
        with self._lock:
            return list(self._workers)

    def running(self, task_key: str) -> Any:
        """Живой воркер с таким ключом задачи, либо None.

        Заменяет проверки вида `gui._reindex_all_worker.isRunning()`: владелец
        воркера — супервизор, а не виджет, поэтому и вопрос «эта задача уже
        крутится?» адресуется ему. Ответ здесь — подсказка для интерфейса
        (показать окно прогресса), а не защита от дублей: защита — в register().
        """
        key = str(task_key or "")
        if not key:
            return None
        with self._lock:
            return self._live_with_key(key)

    def _live_with_key(self, key: str) -> Any:
        """Воркер с ключом `key`, ещё не доигравший. Вызывать под self._lock."""
        return self._live_matching(
            lambda worker: str(getattr(worker, "task_key", "") or "") == key
        )

    def _live_with_resource(self, resource: str, applicant: Any) -> Any:
        """Живой воркер, чей ресурс конфликтует с `resource`. Под self._lock."""
        return self._live_matching(
            lambda worker: worker is not applicant
            and any(_conflicts(resource, held) for held in self._resources_of(worker))
        )

    def _live_matching(self, predicate) -> Any:
        """Первый подходящий воркер, ещё не доигравший. Вызывать под self._lock.

        Зарегистрированный, но не стартовавший воркер тоже считается живым:
        именно между register() и start() ключ должен быть уже занят. А вот
        доработавший — нет: `finished` доставляется очередью в поток-владелец,
        и до forget() ключ иначе оставался бы занятым.
        """
        stale: List[Any] = []
        found: Any = None
        for worker in self._workers:
            if not predicate(worker):
                continue
            try:
                if worker.isFinished() and not worker.isRunning():
                    stale.append(worker)
                    continue
            except Exception:
                pass
            found = worker
        for worker in stale:
            self._workers.discard(worker)
        return found

    def stop_all(self, timeout_ms: int = 2000) -> List[Any]:
        """Закрыть ворота и остановить всех. Возвращает не остановившихся.

        Бюджет ожидания общий, а не «по timeout на каждого»: закрытие окна не
        должно расти линейно от числа задач. От GUI отвязываются все — задача
        внутри может висеть в SQLite или сетевом запросе, и убить её снаружи
        нельзя, но её сигналы уже никого не разбудят.
        """
        with self._lock:
            self._closing = True
            workers = list(self._workers)
        return self._stop(workers, timeout_ms)

    def cancel_owner(self, owner: Any, timeout_ms: int = 2000) -> List[Any]:
        """Остановить задачи одного владельца. Возвращает не остановившихся.

        Закрывается диалог — умирают его задачи, а не все подряд: просмотрщик
        БД не вправе гасить переиндексацию, запущенную из главного окна. Ворота
        при этом не закрываются, приложение продолжает работать.

        Владелец запоминается закрытым: его поздний колбэк, доставленный уже
        после снимка, не должен зарегистрировать новую задачу на мёртвое окно.
        """
        if owner is None:
            return []
        with self._lock:
            self._closed_owners.add(owner)
            mine = [w for w in self._workers if self._owner_of(w) is owner]
        return self._stop(mine, timeout_ms)

    @staticmethod
    def _owner_of(worker: Any) -> Any:
        getter = getattr(worker, "task_owner", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    @staticmethod
    def _resources_of(worker: Any) -> frozenset:
        try:
            return frozenset(
                str(name) for name in (getattr(worker, "exclusive_resources", ()) or ())
            )
        except Exception:
            return frozenset()

    def _stop(self, workers: List[Any], timeout_ms: int) -> List[Any]:
        # Отвязываем всех и сразу, до ожидания. Послушный воркер тоже успевает
        # поставить свой cancelled/finished в очередь GUI-потока, а этот поток
        # стоит в wait() и уничтожит окно раньше, чем очередь дойдёт до колбэка.
        # Служебный finished не трогаем: по нему воркер снимется с учёта.
        for worker in workers:
            self._detach_ui(worker)

        deadline = time.monotonic() + max(0.0, float(timeout_ms) / 1000.0)
        for worker in workers:
            try:
                if not worker.isRunning():
                    continue
                worker.requestInterruption()
            except Exception:
                logger.debug("Не удалось прервать GUI-воркер", exc_info=True)

        survivors: List[Any] = []
        for worker in workers:
            try:
                if not worker.isRunning():
                    continue
                remaining = max(0.0, deadline - time.monotonic())
                if not worker.wait(int(remaining * 1000)):
                    survivors.append(worker)
            except Exception:
                logger.debug("Ошибка ожидания GUI-воркера", exc_info=True)

        for worker in survivors:
            logger.warning(
                f"GUI-воркер {getattr(worker, 'objectName', lambda: '')() or worker!r} "
                "не остановился за отведённое время — оставлен доживать без GUI"
            )
        return survivors

    @staticmethod
    def _detach_ui(worker: Any) -> None:
        """Отцепить прикладные колбэки воркера. Список сигналов знает он сам."""
        detach = getattr(worker, "detach_ui_callbacks", None)
        if not callable(detach):
            logger.warning(
                "GUI-воркер без detach_ui_callbacks — его колбэки продолжат "
                "держать закрытое окно"
            )
            return
        try:
            detach()
        except Exception:
            logger.debug("Не удалось отвязать GUI-воркер от сигналов", exc_info=True)


_supervisor = GuiTaskSupervisor()


def gui_task_supervisor() -> GuiTaskSupervisor:
    return _supervisor
