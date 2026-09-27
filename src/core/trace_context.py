from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_current_trace_id: ContextVar[str] = ContextVar("neuromita_trace_id", default="")


def current_trace_id() -> str:
    return _current_trace_id.get()


@contextmanager
def trace_scope(trace_id: str | None) -> Iterator[None]:
    normalized = str(trace_id or "").strip()
    if not normalized:
        yield
        return

    token = _current_trace_id.set(normalized)
    try:
        yield
    finally:
        _current_trace_id.reset(token)
