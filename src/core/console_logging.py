"""Console logging with an independently owned Windows file descriptor."""

import io
import logging
import os
import sys
from typing import TextIO


def _duplicate_stream(source: TextIO) -> TextIO | None:
    descriptor = None
    try:
        descriptor = os.dup(source.fileno())
        return io.open(
            descriptor,
            "w",
            buffering=1,
            encoding="utf-8",
            errors="replace",
            closefd=True,
        )
    except (AttributeError, OSError, ValueError):
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        return None


class ConsoleLogHandler(logging.StreamHandler):
    """Keep Windows console writes independent of third-party stderr redirection."""

    def __init__(self, stream: TextIO | None = None):
        source = stream if stream is not None else sys.stderr
        self._owned_stream = (
            _duplicate_stream(source) if sys.platform == "win32" else None
        )
        super().__init__(
            self._owned_stream if self._owned_stream is not None else source
        )

    def close(self):
        self.acquire()
        try:
            owned = self._owned_stream
            self._owned_stream = None
            if owned is not None:
                self.stream = None
                owned.close()
        finally:
            super().close()
            self.release()
