import io
import logging
import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core import console_logging


@pytest.fixture
def windows_console(monkeypatch):
    monkeypatch.setattr(console_logging.sys, "platform", "win32")


def record(message):
    return logging.LogRecord("probe", logging.INFO, __file__, 1, message, (), None)


def test_handler_keeps_original_destination_during_descriptor_redirection(
    tmp_path, windows_console
):
    original = tmp_path / "original.log"
    redirected = tmp_path / "redirected.log"
    with original.open("w", encoding="utf-8") as source, redirected.open(
        "w", encoding="utf-8"
    ) as other:
        handler = console_logging.ConsoleLogHandler(source)
        saved = os.dup(source.fileno())
        try:
            handler.emit(record("before"))
            os.dup2(other.fileno(), source.fileno())
            handler.emit(record("during"))
        finally:
            os.dup2(saved, source.fileno())
            os.close(saved)
            handler.close()
    assert original.read_text(encoding="utf-8").splitlines() == ["before", "during"]
    assert redirected.read_text(encoding="utf-8") == ""


def test_close_releases_owned_descriptor_without_closing_source(
    tmp_path, windows_console
):
    with (tmp_path / "console.log").open("w", encoding="utf-8") as source:
        handler = console_logging.ConsoleLogHandler(source)
        owned = handler.stream
        descriptor = owned.fileno()
        handler.close()
        handler.close()
        assert owned.closed
        assert not source.closed
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_non_descriptor_stream_is_borrowed_and_left_open(windows_console):
    source = io.StringIO()
    handler = console_logging.ConsoleLogHandler(source)
    handler.emit(record("captured"))
    handler.close()
    assert source.getvalue() == "captured\n"
    assert not source.closed


def test_failed_stream_creation_releases_duplicate_and_borrows_source(
    tmp_path, windows_console, monkeypatch
):
    with (tmp_path / "console.log").open("w", encoding="utf-8") as source:
        descriptors = []
        original_dup = os.dup

        def tracked_dup(descriptor):
            duplicate = original_dup(descriptor)
            descriptors.append(duplicate)
            return duplicate

        def failed_open(*args, **kwargs):
            raise OSError("cannot wrap stream")

        monkeypatch.setattr(console_logging.os, "dup", tracked_dup)
        monkeypatch.setattr(console_logging.io, "open", failed_open)
        handler = console_logging.ConsoleLogHandler(source)
        assert handler.stream is source
        assert len(descriptors) == 1
        with pytest.raises(OSError):
            os.fstat(descriptors[0])
        handler.close()
        assert not source.closed


def test_non_windows_stream_uses_standard_handler_behavior(monkeypatch):
    monkeypatch.setattr(console_logging.sys, "platform", "linux")
    source = io.StringIO()
    handler = console_logging.ConsoleLogHandler(source)
    assert handler.stream is source
    assert handler._owned_stream is None
    handler.close()
    assert not source.closed


@pytest.mark.skipif(sys.platform != "win32", reason="Requires a real Windows console")
def test_real_windows_console_survives_stderr_redirected_to_nul(tmp_path):
    result_path = tmp_path / "console-result.json"
    program = """
import json, logging, os, sys
from pathlib import Path
from core.console_logging import ConsoleLogHandler

handler = ConsoleLogHandler(sys.stderr)
record = logging.LogRecord('probe', logging.INFO, __file__ if '__file__' in globals() else 'probe', 1, 'console probe', (), None)
saved = os.dup(2)
devnull = os.open(os.devnull, os.O_WRONLY)
result = {'raw_type': type(sys.stderr.buffer.raw).__name__}
try:
    os.dup2(devnull, 2)
    try:
        sys.stderr.write('original stderr during redirection\\n')
        sys.stderr.flush()
    except OSError as error:
        result['original_winerror'] = error.winerror
    errors = []
    handler.handleError = lambda record: errors.append(repr(sys.exc_info()[1]))
    handler.emit(record)
    result['handler_errors'] = errors
finally:
    os.dup2(saved, 2)
    os.close(saved)
    os.close(devnull)
    owned = handler.stream
    handler.close()
    result['owned_closed'] = owned.closed
    result['source_closed'] = sys.stderr.closed
Path(sys.argv[1]).write_text(json.dumps(result), encoding='utf-8')
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen(
        [sys.executable, "-S", "-c", program, str(result_path)],
        env=environment,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        startupinfo=startup,
    )
    try:
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["raw_type"] == "_WindowsConsoleIO"
    assert result["original_winerror"] == 1
    assert result["handler_errors"] == []
    assert result["owned_closed"]
    assert not result["source_closed"]
