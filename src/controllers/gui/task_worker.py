import weakref

from main_logger import logger
from PyQt6.QtCore import QThread, pyqtSignal
from core.cancellation import TaskCancelledError
from core.gui_task_supervisor import TaskRefused, gui_task_supervisor


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

    def __init__(self, func, *, args=None, kwargs=None, use_progress: bool = False,
                 task_key: str = "", owner=None, exclusive_resources=()):
        super().__init__()
        self._func = func
        self._args = tuple(args or ())
        self._kwargs = dict(kwargs or {})
        self._use_progress = bool(use_progress)
        # task_key — имя задачи для супервизора: по нему проверяют «уже запущено».
        self.task_key = str(task_key or "")
        # exclusive_resources — что задача монопольно занимает. Имена иерархичны
        # («rag-index» и «rag-index:crazy»): разные задачи над одной базой обязаны
        # исключать друг друга, даже если называются по-разному.
        self.exclusive_resources = frozenset(
            str(name) for name in (exclusive_resources or ())
        )
        # owner — окно, вместе с которым задача обязана умереть. Ссылка слабая:
        # задача не должна продлевать жизнь закрытому диалогу. Без владельца
        # задача переживает своё окно — так задуманы фоновые переиндексации.
        self._owner_ref = weakref.ref(owner) if owner is not None else None
        self.finished.connect(self._forget)

    def task_owner(self):
        return self._owner_ref() if self._owner_ref is not None else None

    CancelledError = TaskCancelledError

    def start(self, *args, **kwargs) -> bool:
        """Запустить задачу. False — супервизор отказал.

        Регистрация до запуска: воркер, стартовавший в обход супервизора,
        пережил бы закрытие окна. Она же занимает task_key и ресурсы, поэтому
        конфликт отсекается атомарно, а не проверкой `running()` перед стартом.
        """
        try:
            gui_task_supervisor().register(self)
        except TaskRefused as refusal:
            logger.warning(f"Запуск задачи отклонён: {refusal}")
            return False
        try:
            super().start(*args, **kwargs)
        except Exception:
            gui_task_supervisor().forget(self)
            raise
        return True

    def _forget(self) -> None:
        gui_task_supervisor().forget(self)

    def detach_ui_callbacks(self) -> None:
        """Отвязать воркер от GUI, не трогая служебные сигналы QThread.

        Нужно для воркеров, переживших закрытие окна: их колбэки держат виджеты
        и диалоги, которых уже нет. `blockSignals(True)` здесь не годится — он
        глушит и `QThread.finished`, а по нему воркер снимается с учёта у
        супервизора; заглушив его, мы навсегда оставили бы ссылку на поток.
        """
        for signal in (
            self.progress_signal,
            self.status_signal,
            self.finished_signal,
            self.error_signal,
            self.cancelled_signal,
        ):
            try:
                signal.disconnect()
            except TypeError:
                # Ни одного подключения — Qt считает это ошибкой, мы нет.
                pass
            except Exception:
                logger.debug("Не удалось отвязать сигнал TaskWorker", exc_info=True)

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

