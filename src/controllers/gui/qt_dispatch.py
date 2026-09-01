from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import (
    QCoreApplication,
    QObject,
    QThread,
    Qt,
    pyqtSignal,
    pyqtSlot,
)

from main_logger import logger


class _QtUiDispatcher(QObject):
    requested = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.requested.connect(
            self._execute,
            Qt.ConnectionType.QueuedConnection,
        )

    @pyqtSlot(object)
    def _execute(self, callback: Any) -> None:
        if not callable(callback):
            return
        try:
            callback()
        except Exception:
            logger.error("Unhandled GUI callback failure", exc_info=True)


_dispatcher: _QtUiDispatcher | None = None


def install_qt_dispatcher(parent: QObject | None = None) -> _QtUiDispatcher:
    global _dispatcher

    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("QCoreApplication must exist before installing GUI dispatcher")
    if QThread.currentThread() != app.thread():
        raise RuntimeError("GUI dispatcher must be installed on the Qt application thread")

    current = _dispatcher
    if current is not None:
        try:
            current.thread()
            return current
        except RuntimeError:
            _dispatcher = None

    dispatcher = _QtUiDispatcher(parent or app)
    _dispatcher = dispatcher
    return dispatcher


def dispatch_to_qt(callback: Callable[[], None]) -> bool:
    if not callable(callback):
        return False

    app = QCoreApplication.instance()
    if app is None or QCoreApplication.closingDown():
        return False

    dispatcher = _dispatcher
    if dispatcher is None:
        return False

    try:
        dispatcher.requested.emit(callback)
        return True
    except RuntimeError:
        return False
