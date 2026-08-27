from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_response_status_kind: ContextVar[str] = ContextVar("response_status_kind", default="")


def get_response_status_kind() -> str:
    return _response_status_kind.get("")


@contextmanager
def response_status_kind(kind: str) -> Iterator[None]:
    token = _response_status_kind.set(str(kind or ""))
    try:
        yield
    finally:
        _response_status_kind.reset(token)
