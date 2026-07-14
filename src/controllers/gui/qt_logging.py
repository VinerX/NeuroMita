from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler


_handler_ref = None
_THREAD_AFFINITY_MARKERS = (
    "QBasicTimer::start",
    "QObject::startTimer",
    "QObject::killTimer",
    "QObject::moveToThread",
    "QObject::setParent",
    "QSocketNotifier:",
    "event dispatcher has already been destroyed",
    "Timers cannot be started from another thread",
    "Timers cannot be stopped from another thread",
)


def install_qt_message_logging(logger: Any) -> None:
    """Route native Qt diagnostics through the application logger."""
    global _handler_ref

    levels = {
        QtMsgType.QtDebugMsg: logger.debug,
        QtMsgType.QtInfoMsg: logger.info,
        QtMsgType.QtWarningMsg: logger.warning,
        QtMsgType.QtCriticalMsg: logger.error,
        QtMsgType.QtFatalMsg: logger.critical,
    }

    def handler(message_type, context, message) -> None:
        text = str(message)
        log = levels.get(message_type, logger.warning)
        if message_type == QtMsgType.QtWarningMsg and any(
            marker in text for marker in _THREAD_AFFINITY_MARKERS
        ):
            log = logger.error

        location = ""
        file_name = str(getattr(context, "file", "") or "")
        line = int(getattr(context, "line", 0) or 0)
        function = str(getattr(context, "function", "") or "")
        if file_name or function:
            location = f" [{file_name}:{line} {function}]"
        try:
            log("Qt: %s%s", text, location)
        except Exception:
            return

    _handler_ref = handler
    qInstallMessageHandler(handler)
