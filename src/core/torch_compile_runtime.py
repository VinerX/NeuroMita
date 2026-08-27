from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, MutableMapping


def environment_root() -> Path:
    from core.app_paths import base_dir

    return Path(
        os.environ.get("NEUROMITA_ENVIRONMENT_DIR")
        or base_dir() / "Lib" / "environment"
    ).resolve()


def cache_directories() -> tuple[Path, Path]:
    root = environment_root() / "cache"
    return root / "torchinductor", root / "triton"


def configure_compile_environment(
    python_paths: Iterable[str] = (),
    env: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    target = env if env is not None else os.environ
    inductor_cache, triton_cache = cache_directories()
    inductor_cache.parent.mkdir(parents=True, exist_ok=True)
    target.setdefault("TORCHINDUCTOR_CACHE_DIR", str(inductor_cache))
    target.setdefault("TRITON_CACHE_DIR", str(triton_cache))
    target.setdefault("TORCHINDUCTOR_FX_GRAPH_CACHE", "1")

    for raw_root in python_paths:
        root = Path(str(raw_root)).resolve()
        triton_root = root / "triton"
        tcc = triton_root / "runtime" / "tcc" / "tcc.exe"
        cuda_root = triton_root / "backends" / "nvidia"
        if tcc.is_file():
            target.setdefault("CC", str(tcc))
        if (cuda_root / "bin" / "ptxas.exe").is_file():
            target.setdefault("CUDA_PATH", str(cuda_root))
        if tcc.is_file() or (cuda_root / "bin" / "ptxas.exe").is_file():
            break
    return target


def compile_cache_status() -> dict[str, object]:
    paths = cache_directories()
    size_bytes = 0
    file_count = 0
    for root in paths:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                try:
                    if path.is_file():
                        file_count += 1
                        size_bytes += path.stat().st_size
                except OSError:
                    continue
        except OSError:
            continue
    return {
        "cache_exists": file_count > 0,
        "cache_size_bytes": size_bytes,
        "cache_paths": [str(path) for path in paths],
        "long_paths_enabled": long_paths_enabled(),
    }


def _cache_locking_processes(cache_root: Path) -> list[dict[str, object]]:
    if os.name != "nt":
        return []
    try:
        import psutil
    except ImportError:
        return []

    root = os.path.normcase(str(cache_root.resolve()))
    prefix = root + os.sep
    owners: list[dict[str, object]] = []
    for process in psutil.process_iter(("pid", "ppid", "name", "exe", "cmdline")):
        try:
            if int(process.pid) == os.getpid():
                continue
            mapped = process.memory_maps(grouped=False)
            if not any(
                os.path.normcase(str(item.path or "")) == root
                or os.path.normcase(str(item.path or "")).startswith(prefix)
                for item in mapped
            ):
                continue
            info = process.info
            owners.append(
                {
                    "process": process,
                    "pid": int(process.pid),
                    "ppid": int(info.get("ppid") or 0),
                    "name": str(info.get("name") or "process"),
                    "exe": str(info.get("exe") or ""),
                    "cmdline": tuple(str(part) for part in (info.get("cmdline") or ())),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return owners


def _retire_orphaned_cache_workers(owners: list[dict[str, object]]) -> list[int]:
    try:
        import psutil
    except ImportError:
        return []

    configured_python = os.path.normcase(
        os.path.abspath(os.environ.get("NEUROMITA_PYTHON") or sys.executable)
    )
    retired: list[int] = []
    terminating = []
    for owner in owners:
        pid = int(owner["pid"])
        ppid = int(owner["ppid"])
        executable = os.path.normcase(os.path.abspath(str(owner["exe"] or "")))
        command_line = " ".join(owner["cmdline"]).casefold()
        is_managed_worker = (
            executable == configured_python
            and "multiprocessing.spawn" in command_line
            and "spawn_main" in command_line
        )
        parent_alive = ppid > 0 and psutil.pid_exists(ppid)
        if not is_managed_worker or parent_alive:
            continue
        process = owner["process"]
        try:
            process.terminate()
            terminating.append(process)
            retired.append(pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    if terminating:
        psutil.wait_procs(terminating, timeout=3.0)
    return retired


def _lock_description(owners: list[dict[str, object]]) -> str:
    if not owners:
        return "locking process could not be identified"
    return ", ".join(
        f"PID {owner['pid']} ({owner['name']}, parent PID {owner['ppid']})"
        for owner in owners
    )


def _remove_cache_tree(path: Path, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + max(0.0, float(timeout))
    orphan_cleanup_attempted = False
    last_error: PermissionError | None = None
    while path.exists():
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            owners = _cache_locking_processes(path)
            if not orphan_cleanup_attempted:
                orphan_cleanup_attempted = True
                retired = _retire_orphaned_cache_workers(owners)
                if retired:
                    from main_logger import logger

                    logger.warning(
                        "Stopped orphaned NeuroMita AI workers locking compilation cache: "
                        + ", ".join(str(pid) for pid in retired)
                    )
                    continue
            if time.monotonic() < deadline:
                time.sleep(0.2)
                continue
            owners = _cache_locking_processes(path)
            raise RuntimeError(
                f"Не удалось удалить кеш компиляции '{path}': файл используется "
                f"другим процессом ({_lock_description(owners)}). Закройте другие "
                "запущенные экземпляры NeuroMita и повторите операцию."
            ) from last_error


def clear_compile_cache() -> None:
    for path in cache_directories():
        _remove_cache_tree(path)


def long_paths_enabled() -> bool:
    if os.name != "nt":
        return True
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "LongPathsEnabled")
        return int(value) == 1
    except (OSError, ValueError, TypeError):
        return False


def enable_long_paths() -> bool:
    if os.name != "nt" or long_paths_enabled():
        return True
    command = (
        "$p=Start-Process reg.exe -Verb RunAs -Wait -PassThru -ArgumentList "
        "@('add','HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem',"
        "'/v','LongPathsEnabled','/t','REG_DWORD','/d','1','/f'); exit $p.ExitCode"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return completed.returncode == 0 and long_paths_enabled()
