from __future__ import annotations

import threading
from typing import Callable, Optional

from main_logger import logger


class TextDeltaCoalescer:
    def __init__(
        self,
        emit: Callable[[str], None],
        *,
        interval_seconds: float = 0.025,
        max_buffer_chars: int = 16_384,
    ) -> None:
        self._emit = emit
        self._interval_seconds = max(0.001, float(interval_seconds))
        self._max_buffer_chars = max(1, int(max_buffer_chars))
        self._parts: list[str] = []
        self._buffer_chars = 0
        self._timer: Optional[threading.Timer] = None
        self._closed = False
        self._lock = threading.Lock()

    def push(self, text: str) -> None:
        value = str(text or "")
        if not value:
            return

        emit_now = ""
        with self._lock:
            if self._closed:
                return
            self._parts.append(value)
            self._buffer_chars += len(value)
            if self._buffer_chars >= self._max_buffer_chars:
                emit_now = self._take_locked(cancel_timer=True)
            elif self._timer is None:
                timer = threading.Timer(self._interval_seconds, self._on_timer)
                timer.daemon = True
                self._timer = timer
                timer.start()
        self._safe_emit(emit_now)

    def flush(self) -> None:
        with self._lock:
            text = self._take_locked(cancel_timer=True)
        self._safe_emit(text)

    def close(self, *, flush: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            text = self._take_locked(cancel_timer=True) if flush else ""
            if not flush:
                self._parts.clear()
                self._buffer_chars = 0
        self._safe_emit(text)

    def _on_timer(self) -> None:
        with self._lock:
            self._timer = None
            if self._closed:
                return
            text = self._take_locked(cancel_timer=False)
        self._safe_emit(text)

    def _take_locked(self, *, cancel_timer: bool) -> str:
        if cancel_timer and self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._parts:
            return ""
        text = "".join(self._parts)
        self._parts.clear()
        self._buffer_chars = 0
        return text

    def _safe_emit(self, text: str) -> None:
        if not text:
            return
        try:
            self._emit(text)
        except Exception:
            logger.exception("Failed to deliver coalesced stream text to presentation layer")


__all__ = ["TextDeltaCoalescer"]
