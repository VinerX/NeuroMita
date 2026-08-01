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
from typing import Any, List

from main_logger import logger


class TaskAlreadyRunning(RuntimeError):
    """Задача с таким ключом уже под опекой супервизора."""

    def __init__(self, task_key: str, worker: Any) -> None:
        super().__init__(f"Задача '{task_key}' уже запущена")
        self.task_key = str(task_key or "")
        self.worker = worker


class GuiTaskSupervisor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: set[Any] = set()
        self._closing = False

    def register(self, worker: Any) -> None:
        """Взять воркер под опеку.

        RuntimeError — приложение уже закрывается, TaskAlreadyRunning — ключ
        задачи занят живым воркером. Проверка занятости живёт здесь, а не на
        стороне вызывающего: `running()` + `start()` двумя шагами — это гонка,
        в которую пролезали две полные переиндексации одной и той же БД.
        """
        key = str(getattr(worker, "task_key", "") or "")
        with self._lock:
            if self._closing:
                raise RuntimeError(
                    "GUI закрывается: новые фоновые задачи не запускаются"
                )
            if key:
                existing = self._live_with_key(key)
                if existing is not None and existing is not worker:
                    raise TaskAlreadyRunning(key, existing)
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
        """Воркер с ключом `key`, ещё не доигравший. Вызывать под self._lock.

        Зарегистрированный, но не стартовавший воркер тоже считается живым:
        именно между register() и start() ключ должен быть уже занят. А вот
        доработавший — нет: `finished` доставляется очередью в поток-владелец,
        и до forget() ключ иначе оставался бы занятым.
        """
        stale: List[Any] = []
        found: Any = None
        for worker in self._workers:
            if str(getattr(worker, "task_key", "") or "") != key:
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
        должно расти линейно от числа задач. Выжившие отвязываются от GUI —
        задача внутри может висеть в SQLite или сетевом запросе, и убить её
        снаружи нельзя, но её сигналы уже никого не разбудят.
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
        """
        if owner is None:
            return []
        with self._lock:
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

    def _stop(self, workers: List[Any], timeout_ms: int) -> List[Any]:
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
            # Отвязываем только прикладные колбэки: служебный finished обязан
            # уцелеть, по нему воркер снимется с учёта, когда всё-таки досчитает.
            # Список своих сигналов знает сам воркер, не супервизор.
            detach = getattr(worker, "detach_ui_callbacks", None)
            if callable(detach):
                try:
                    detach()
                except Exception:
                    logger.debug("Не удалось отвязать GUI-воркер от сигналов", exc_info=True)
            else:
                logger.warning(
                    "GUI-воркер без detach_ui_callbacks — его колбэки продолжат "
                    "держать закрытое окно"
                )
            logger.warning(
                f"GUI-воркер {getattr(worker, 'objectName', lambda: '')() or worker!r} "
                "не остановился за отведённое время — отвязан от GUI"
            )
        return survivors


_supervisor = GuiTaskSupervisor()


def gui_task_supervisor() -> GuiTaskSupervisor:
    return _supervisor
