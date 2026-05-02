from main_logger import logger
from PyQt6.QtCore import QThread, pyqtSignal


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

    class CancelledError(Exception):
        pass

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

