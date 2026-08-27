from __future__ import annotations

import threading
from collections.abc import Callable


class TaskCancelledError(Exception):
    """Cooperative cancellation requested by a UI or background task."""


class OperationCancelledError(RuntimeError):
    pass


class CancellationToken:
    def __init__(self, parent: "CancellationToken | None" = None) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []
        self._reason = ""
        if parent is not None:
            parent.add_cancel_callback(
                lambda: self.cancel(parent.reason or "Parent operation was cancelled")
            )

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def add_cancel_callback(self, callback: Callable[[], None]) -> None:
        call_now = False
        with self._lock:
            if self._event.is_set():
                call_now = True
            else:
                self._callbacks.append(callback)
        if call_now:
            try:
                callback()
            except Exception:
                pass

    def cancel(self, reason: str = "") -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._reason = str(reason or "")
            self._event.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelledError(self.reason or "Operation was cancelled")

    def wait(self, timeout: float) -> bool:
        return self._event.wait(max(0.0, float(timeout)))


__all__ = ["CancellationToken", "OperationCancelledError", "TaskCancelledError"]
