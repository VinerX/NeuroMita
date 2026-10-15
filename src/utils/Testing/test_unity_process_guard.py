from __future__ import annotations

import threading
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import psutil
import pytest

from services import unity_process_guard as guard


class Process:
    def __init__(self, pid, executable, *, exits_on_close=True, survives_kill=False):
        self.pid = pid
        self.executable = executable
        self.alive = True
        self.exits_on_close = exits_on_close
        self.survives_kill = survives_kill
        self.killed = False

    def exe(self):
        return str(self.executable)

    def create_time(self):
        return 1.0

    def is_running(self):
        return self.alive

    def kill(self):
        self.killed = True
        self.alive = self.survives_kill


def install(tmp_path):
    root = tmp_path / "NeuroMita-Unity"
    root.mkdir()
    executable = root / "NeuroMita.exe"
    executable.write_bytes(b"game")
    return root, executable


def test_closes_all_exact_install_instances_and_preserves_other_install(tmp_path, monkeypatch):
    root, executable = install(tmp_path)
    processes = [Process(1001, executable), Process(1002, executable), Process(1003, tmp_path / "other" / executable.name)]
    monkeypatch.setattr(guard.psutil, "process_iter", lambda: [p for p in processes if p.alive])
    closed = []

    def close(process):
        closed.append(process.pid)
        process.alive = False

    monkeypatch.setattr(guard, "_request_close", close)
    guard.stop_unity_for_update(root, Mock())
    assert closed == [1001, 1002]
    assert processes[2].alive
    assert not any(p.killed for p in processes)


def test_waits_for_exit_and_kills_only_unresponsive_game(tmp_path, monkeypatch):
    root, executable = install(tmp_path)
    process = Process(1001, executable, exits_on_close=False)
    monkeypatch.setattr(guard.psutil, "process_iter", lambda: [process] if process.alive else [])
    monkeypatch.setattr(guard, "_request_close", lambda _: None)
    guard.stop_unity_for_update(root, Mock(), graceful_timeout=0, kill_timeout=0)
    assert process.killed and not process.alive


def test_surviving_process_prevents_installation(tmp_path, monkeypatch):
    root, executable = install(tmp_path)
    process = Process(1001, executable, survives_kill=True)
    monkeypatch.setattr(guard.psutil, "process_iter", lambda: [process])
    monkeypatch.setattr(guard, "_request_close", lambda _: None)
    with pytest.raises(RuntimeError, match="still running"):
        guard.stop_unity_for_update(root, Mock(), graceful_timeout=0, kill_timeout=0)


def test_cancellation_during_grace_period_does_not_kill_game(tmp_path, monkeypatch):
    root, executable = install(tmp_path)
    process = Process(1001, executable)
    cancelled = threading.Event()
    monkeypatch.setattr(guard.psutil, "process_iter", lambda: [process])
    monkeypatch.setattr(guard, "_request_close", lambda _: cancelled.set())

    def check_cancel():
        if cancelled.is_set():
            raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        guard.stop_unity_for_update(root, Mock(), check_cancel=check_cancel)
    assert not process.killed


def test_process_exit_during_close_is_harmless(tmp_path, monkeypatch):
    root, executable = install(tmp_path)
    process = Process(1001, executable)
    monkeypatch.setattr(guard.psutil, "process_iter", lambda: [process] if process.alive else [])

    def close(_):
        process.alive = False
        raise psutil.NoSuchProcess(process.pid)

    monkeypatch.setattr(guard, "_request_close", close)
    guard.stop_unity_for_update(root, Mock())


def test_rename_diagnostics_identify_directory_users_without_command_lines(tmp_path, monkeypatch):
    root, executable = install(tmp_path)
    process = Process(1001, executable)
    process.cwd = lambda: str(root)
    process.name = lambda: "NeuroMita.exe"
    monkeypatch.setattr(guard.psutil, "process_iter", lambda: [process])
    detail = guard.describe_directory_users(root)
    assert "PID 1001" in detail
    assert "working directory" in detail
    assert "does not cover all file handles" in detail


@pytest.mark.skipif(os.name != "nt", reason="Windows process shutdown")
def test_real_unresponsive_process_exits_before_guard_returns(tmp_path):
    root, executable = install(tmp_path)
    shutil.copyfile(sys._base_executable, executable)
    for dll in Path(sys.base_prefix).glob("python*.dll"):
        shutil.copyfile(dll, root / dll.name)
    environment = {**os.environ, "PYTHONHOME": sys.base_prefix}
    process = subprocess.Popen(
        [str(executable), "-I", "-c", "import time; time.sleep(30)"],
        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        assert process.poll() is None
        guard.stop_unity_for_update(root, Mock(), graceful_timeout=0.2, kill_timeout=2)
        assert process.wait(timeout=2) is not None
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=3)
