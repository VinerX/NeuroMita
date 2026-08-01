import threading
import weakref

from main_logger import logger
from PyQt6.QtCore import QThread, pyqtSignal
from core.cancellation import TaskCancelledError

_active_workers: "weakref.WeakSet[TaskWorker]" = weakref.WeakSet()
_active_lock = threading.Lock()


def stop_all_workers(timeout_ms: int = 2000) -> None:
    """Прервать все живые воркеры. Иначе QThread переживает закрытие окна и
    дёргает колбэки с уже уничтоженными Qt-объектами."""
    with _active_lock:
        workers = [w for w in _active_workers if w is not None]
    for worker in workers:
        try:
            if not worker.isRunning():
                continue
            worker.requestInterruption()
            worker.wait(int(timeout_ms))
        except Exception:
            logger.debug("Не удалось остановить TaskWorker", exc_info=True)


class TaskWorker(QThread):
    """
    Универсальный воркер для фоновых задач.
    Чтобы не плодить отдельный QThread-класс под каждую кнопку.
    """
    progress_signal = pyqtSignal(int, int)   # current, total (optional)
    status_signal = pyqtSignal(str)          # status text (e.g. character name)
    finished_signal = pyqtSignal(object)     # result
    error_signal = pyqtSignal(str)
    cancelled_signal = pyqtSignal()

    def __init__(self, func, *, args=None, kwargs=None, use_progress: bool = False):
        super().__init__()
        self._func = func
        self._args = tuple(args or ())
        self._kwargs = dict(kwargs or {})
        self._use_progress = bool(use_progress)
        self.finished.connect(self._forget)

    CancelledError = TaskCancelledError

    def start(self, *args, **kwargs):
        with _active_lock:
            _active_workers.add(self)
        super().start(*args, **kwargs)

    def _forget(self) -> None:
        with _active_lock:
            _active_workers.discard(self)

    def _emit_progress(self, curr: int, total: int):
        # Cooperative cancellation: tasks that call progress_callback can be interrupted safely.
        if self.isInterruptionRequested():
            raise TaskWorker.CancelledError()
        try:
            self.progress_signal.emit(int(curr), int(total))
        except Exception:
            pass

    def run(self):
        try:
            if self.isInterruptionRequested():
                self.cancelled_signal.emit()
                return
            if self._use_progress and "progress_callback" not in self._kwargs:
                self._kwargs["progress_callback"] = self._emit_progress
            result = self._func(*self._args, **self._kwargs)
            if self.isInterruptionRequested():
                self.cancelled_signal.emit()
                return
            self.finished_signal.emit(result)
        except TaskWorker.CancelledError:
            # No UI error popup on cancel
            try:
                self.cancelled_signal.emit()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"TaskWorker error: {e}", exc_info=True)
            self.error_signal.emit(str(e))

