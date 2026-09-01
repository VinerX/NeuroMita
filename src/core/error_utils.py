from __future__ import annotations

from typing import Any


def format_exception(error: Any) -> str:
    """Return a non-empty diagnostic representation for an error value."""
    if error is None:
        return "UnknownError"
    if isinstance(error, BaseException):
        error_type = type(error).__name__
        try:
            message = str(error).strip()
        except Exception:
            message = ""
        return f"{error_type}: {message}" if message else error_type

    try:
        message = str(error).strip()
    except Exception:
        message = ""
    return message or "UnknownError"
