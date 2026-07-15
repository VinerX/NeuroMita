from __future__ import annotations

import threading
import time
from typing import Callable

from main_logger import logger


class TextDeltaCoalescer:
    def __init__(
        self,
        emit: Callable[[str], None],
        *,
        interval_seconds: float = 0.025,
        max_buffer_chars: int = 16_384,
        flush_timeout_seconds: float = 5.0,
        close_timeout_seconds: float = 2.0,
    ) -> None:
        self._emit = emit
        self._interval_seconds = max(0.001, float(interval_seconds))
        self._max_buffer_chars = max(1, int(max_buffer_chars))
        self._flush_timeout_seconds = max(0.1, float(flush_timeout_seconds))
        self._close_timeout_seconds = max(0.1, float(close_timeout_seconds))
        self._parts: list[str] = []
        self._buffer_chars = 0
        self._deadline: float | None = None
        self._flush_requested = False
        self._emitting = False
        self._closed = False
        self._condition = threading.Condition()
        self._worker = threading.Thread(
            target=self._run,
            name="stream-presentation-coalescer",
            daemon=True,
        )
        self._worker.start()

    def push(self, text: str) -> None:
        value = str(text or "")
        if not value:
            return
        with self._condition:
            if self._closed:
                return
            if not self._parts:
                self._deadline = time.monotonic() + self._interval_seconds
            self._parts.append(value)
            self._buffer_chars += len(value)
            if self._buffer_chars >= self._max_buffer_chars:
                self._flush_requested = True
            self._condition.notify()

    def flush(self, *, timeout_seconds: float | None = None) -> bool:
        timeout = self._flush_timeout_seconds if timeout_seconds is None else max(0.0, float(timeout_seconds))
        with self._condition:
            if self._closed and not self._parts and not self._emitting:
                return True
            self._flush_requested = True
            self._condition.notify()
            completed = self._condition.wait_for(
                lambda: not self._parts and not self._emitting,
                timeout=timeout,
            )
        if not completed:
            logger.warning("Timed out while flushing coalesced stream text")
        return completed

    def close(self, *, flush: bool = True, timeout_seconds: float | None = None) -> bool:
        timeout = self._close_timeout_seconds if timeout_seconds is None else max(0.0, float(timeout_seconds))
        with self._condition:
            if self._closed:
                worker = self._worker
            else:
                self._closed = True
                if flush:
                    self._flush_requested = True
                else:
                    self._parts.clear()
                    self._buffer_chars = 0
                    self._deadline = None
                self._condition.notify_all()
                worker = self._worker
        if worker is threading.current_thread():
            return True
        worker.join(timeout=timeout)
        if worker.is_alive():
            logger.warning("Timed out while closing stream presentation coalescer")
            return False
        return True

    def _run(self) -> None:
        while True:
            with self._condition:
                batch = self._wait_for_batch_locked()
                if batch is None:
                    return
                self._emitting = True
            try:
                self._safe_emit(batch)
            finally:
                with self._condition:
                    self._emitting = False
                    self._condition.notify_all()

    def _wait_for_batch_locked(self) -> str | None:
        while True:
            if self._closed and not self._parts:
                return None
            if self._parts:
                now = time.monotonic()
                deadline_reached = self._deadline is not None and now >= self._deadline
                if self._closed or self._flush_requested or deadline_reached:
                    return self._take_locked()
                self._condition.wait(timeout=max(0.0, self._deadline - now))
                continue
            self._condition.wait()

    def _take_locked(self) -> str:
        text = "".join(self._parts)
        self._parts.clear()
        self._buffer_chars = 0
        self._deadline = None
        self._flush_requested = False
        return text

    def _safe_emit(self, text: str) -> None:
        if not text:
            return
        try:
            self._emit(text)
        except Exception:
            logger.exception("Failed to deliver coalesced stream text to presentation layer")


__all__ = ["TextDeltaCoalescer"]
