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


class GuiTaskSupervisor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: set[Any] = set()
        self._closing = False

    def register(self, worker: Any) -> None:
        """Взять воркер под опеку. RuntimeError — приложение уже закрывается."""
        with self._lock:
            if self._closing:
                raise RuntimeError(
                    "GUI закрывается: новые фоновые задачи не запускаются"
                )
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
        крутится?» адресуется ему.
        """
        key = str(task_key or "")
        if not key:
            return None
        for worker in self.active_workers():
            if getattr(worker, "task_key", "") != key:
                continue
            try:
                if worker.isRunning():
                    return worker
            except Exception:
                continue
        return None

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
            try:
                worker.blockSignals(True)
            except Exception:
                logger.debug("Не удалось отвязать GUI-воркер от сигналов", exc_info=True)
            logger.warning(
                f"GUI-воркер {getattr(worker, 'objectName', lambda: '')() or worker!r} "
                "не остановился за отведённое время — отвязан от GUI"
            )
        return survivors


_supervisor = GuiTaskSupervisor()


def gui_task_supervisor() -> GuiTaskSupervisor:
    return _supervisor
