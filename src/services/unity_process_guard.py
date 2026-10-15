from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

import psutil


def _path_key(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _game_processes(executable: Path) -> list:
    expected = _path_key(executable)
    matches = []
    for process in psutil.process_iter():
        try:
            if process.pid != os.getpid() and _path_key(process.exe()) == expected:
                process.create_time()
                matches.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def _request_close(process) -> None:
    if os.name != "nt":
        process.terminate()
        return

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

    @callback_type
    def close_window(window, _parameter):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == process.pid and process.is_running():
            user32.PostMessageW(window, 0x0010, 0, 0)
        return True

    if not user32.EnumWindows(close_window, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def stop_unity_for_update(
    installation: Path,
    log: Callable,
    *,
    check_cancel: Callable[[], None] = lambda: None,
    graceful_timeout: float = 5.0,
    kill_timeout: float = 3.0,
) -> None:
    from core.unity_installation import find_unity_executable

    check_cancel()
    executable = find_unity_executable(installation)
    if executable is None:
        return
    processes = _game_processes(executable)
    if not processes:
        return
    log("Closing Unity before update: " + ", ".join(f"PID {p.pid}" for p in processes))
    for process in processes:
        try:
            if process.is_running() and _path_key(process.exe()) == _path_key(executable):
                _request_close(process)
        except psutil.NoSuchProcess:
            pass
        except (OSError, psutil.AccessDenied) as error:
            raise RuntimeError(f"Cannot close Unity PID {process.pid}: {error}") from error

    def wait_for_exit(timeout: float) -> list:
        deadline = time.monotonic() + timeout
        while True:
            check_cancel()
            alive = [p for p in processes if p.is_running()]
            if not alive or time.monotonic() >= deadline:
                return alive
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))

    alive = wait_for_exit(graceful_timeout)
    for process in alive:
        check_cancel()
        try:
            if process.is_running() and _path_key(process.exe()) == _path_key(executable):
                log(f"Unity PID {process.pid} did not exit; terminating it before update", "warning")
                process.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied as error:
            raise RuntimeError(f"Cannot terminate Unity PID {process.pid}: {error}") from error
    alive = wait_for_exit(kill_timeout)
    newly_running = _game_processes(executable)
    if alive or newly_running:
        pids = sorted({p.pid for p in alive + newly_running})
        raise RuntimeError(f"Unity is still running (PIDs {pids}); installation was not replaced")
    log("Unity processes exited; installation can be replaced")


def describe_directory_users(directory: Path) -> str:
    root = _path_key(directory)
    candidates = []
    for process in psutil.process_iter():
        try:
            reasons = []
            for label, getter in (("executable", process.exe), ("working directory", process.cwd)):
                try:
                    value = getter()
                except psutil.AccessDenied:
                    continue
                key = _path_key(value) if value else ""
                if key == root or key.startswith(root + os.sep):
                    reasons.append(label)
            if reasons:
                candidates.append(f"{process.name()} PID {process.pid} ({', '.join(reasons)})")
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    owners = "; ".join(candidates[:10]) or "none found by executable/working-directory scan"
    return (
        f"Possible directory users: {owners}. This scan does not cover all file handles or DLLs. "
        "Search the installation path in Process Explorer (Find Handle or DLL); "
        "also check antivirus events and delete/rename permissions on the installation and its parent."
    )
