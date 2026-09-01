"""Windows path compatibility helpers for native libraries."""

from __future__ import annotations

import ctypes
import os


class NativePathError(RuntimeError):
    """Raised when a native Windows loader cannot be given a safe file path."""


def path_for_native_loader(path: os.PathLike[str] | str) -> str:
    """Return a path that can be opened by narrow-character native loaders."""

    value = os.fsdecode(os.fspath(path))
    if os.name != "nt" or value.isascii():
        return value

    short_path = _get_short_path(value)
    if short_path:
        return short_path

    raise NativePathError(
        "The native loader cannot open this non-ASCII Windows path. "
        "Enable 8.3 short names or move the AI runtime to an ASCII-only path: "
        f"{value}"
    )


def _get_short_path(path: str) -> str | None:
    """Resolve an existing Windows path to its ASCII 8.3 representation."""

    if not os.path.exists(path):
        return None

    try:
        get_short_path_name = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    except (AttributeError, OSError):
        return None

    get_short_path_name.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_wchar),
        ctypes.c_uint32,
    ]
    get_short_path_name.restype = ctypes.c_uint32

    buffer_length = 260
    for _ in range(8):
        buffer = ctypes.create_unicode_buffer(buffer_length)
        result = get_short_path_name(path, buffer, buffer_length)
        if result == 0:
            return None
        if result < buffer_length:
            short_path = buffer.value
            if short_path.isascii() and os.path.exists(short_path):
                return short_path
            return None
        buffer_length = max(buffer_length * 2, result + 1)

    return None
