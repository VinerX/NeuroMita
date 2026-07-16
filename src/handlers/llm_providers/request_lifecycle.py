from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional, Protocol


class _RequestLike(Protocol):
    extra: dict[str, Any]


class RequestCancelledError(RuntimeError):
    pass


class RequestCancellation:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []
        self._reason = ""
        self._started_at = time.monotonic()
        self._response_headers_received = False
        self._response_body_started = False
        self._first_meaningful_event_at: Optional[float] = None
        self._last_meaningful_event_at: Optional[float] = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    @property
    def started_at(self) -> float:
        return self._started_at

    @property
    def has_meaningful_stream_event(self) -> bool:
        with self._lock:
            return self._first_meaningful_event_at is not None

    @property
    def response_body_started(self) -> bool:
        with self._lock:
            return self._response_body_started

    @property
    def response_headers_received(self) -> bool:
        with self._lock:
            return self._response_headers_received

    def record_response_headers_received(self) -> None:
        with self._lock:
            self._response_headers_received = True

    def record_response_body_started(self) -> None:
        with self._lock:
            self._response_body_started = True

    def record_meaningful_stream_event(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._first_meaningful_event_at is None:
                self._first_meaningful_event_at = now
            self._last_meaningful_event_at = now

    def stream_activity(self) -> tuple[float, Optional[float], Optional[float]]:
        with self._lock:
            return (
                self._started_at,
                self._first_meaningful_event_at,
                self._last_meaningful_event_at,
            )

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
        if self._event.is_set():
            raise RequestCancelledError(self.reason or "LLM request was cancelled")

    def wait(self, timeout: float) -> bool:
        return self._event.wait(max(0.0, float(timeout)))


def get_request_cancellation(req: _RequestLike) -> Optional[RequestCancellation]:
    token = (req.extra or {}).get("_request_cancellation")
    return token if isinstance(token, RequestCancellation) else None


def check_request_cancelled(req: _RequestLike) -> None:
    token = get_request_cancellation(req)
    if token is not None:
        token.raise_if_cancelled()


def record_response_body_started(req: _RequestLike) -> None:
    token = get_request_cancellation(req)
    if token is not None:
        token.record_response_body_started()


def record_response_headers_received(req: _RequestLike) -> None:
    token = get_request_cancellation(req)
    if token is not None:
        token.record_response_headers_received()


def register_cancellable_resource(req: _RequestLike, resource: Any) -> Any:
    token = get_request_cancellation(req)
    close = getattr(resource, "close", None)
    if token is not None and callable(close):
        token.add_cancel_callback(close)
    return resource


def resolve_total_timeout(req: _RequestLike, *, default_total: float = 240.0) -> float:
    try:
        return max(1.0, float((req.extra or {}).get("http_timeout_seconds") or default_total))
    except (TypeError, ValueError):
        return max(1.0, float(default_total))


__all__ = [
    "RequestCancellation",
    "RequestCancelledError",
    "check_request_cancelled",
    "get_request_cancellation",
    "record_response_body_started",
    "record_response_headers_received",
    "register_cancellable_resource",
    "resolve_total_timeout",
]
