# -*- coding: utf-8 -*-
"""Launcher for the packaged NeuroMita build.

Started by ``libs\\python\\python.exe run.py``. Application dependencies are
materialized transactionally into ``Lib/core``; AI backends are intentionally
excluded and are managed by AI Hub in ``Lib/environment``.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)
REQ_FILE = ROOT / "requirements.txt"
PYZ = ROOT / "NeuroMita.pyz"
RUNTIME_ROOT = ROOT / "Lib"
CORE_DIR = RUNTIME_ROOT / "core"
BOOTSTRAP_DIR = ROOT / ".bootstrap"
CORE_STATE_FILE = BOOTSTRAP_DIR / "core-state.json"
LEGACY_HASH_FILE = ROOT / ".req_hash"
UV_TARGET = BOOTSTRAP_DIR / "uv"
UV_EXE = UV_TARGET / "bin" / ("uv.exe" if os.name == "nt" else "uv")
CORE_LOCK_FILE = BOOTSTRAP_DIR / "core-install.lock"
EFFECTIVE_REQ_FILE = BOOTSTRAP_DIR / "effective-requirements.txt"
SETTINGS_FILE = ROOT / "Settings" / "settings.json"
STATE_VERSION = 6

os.environ.setdefault("UV_LINK_MODE", "copy")

_RUNTIME_RESERVED_NAMES = frozenset({
    "core",
    "environment",
    "wheel-cache",
    ".staging",
    ".locks",
    ".install-staging",
    ".legacy-runtime",
    "registry.json",
})

_FORBIDDEN_CORE_DISTRIBUTIONS = frozenset({
    "bitsandbytes",
    "ctranslate2",
    "f5-tts",
    "faster-whisper",
    "fish-speech-lib",
    "onnxruntime",
    "onnxruntime-directml",
    "onnxruntime-gpu",
    "torch",
    "torchaudio",
    "torchvision",
    "triton",
    "triton-windows",
    "tts-with-rvc",
    "xformers",
})


def _normalized_distribution_name(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _forbidden_core_distributions(
    distributions: list[dict[str, Any]],
) -> tuple[str, ...]:
    installed = {
        _normalized_distribution_name(item.get("name"))
        for item in distributions
        if isinstance(item, dict)
    }
    return tuple(sorted(installed & _FORBIDDEN_CORE_DISTRIBUTIONS))


def _legacy_runtime_payloads() -> tuple[Path, ...]:
    if not RUNTIME_ROOT.is_dir():
        return ()
    return tuple(
        child
        for child in RUNTIME_ROOT.iterdir()
        if child.name not in _RUNTIME_RESERVED_NAMES
        and not child.name.startswith((".core-", ".legacy-"))
    )


def _cleanup_legacy_runtime_payloads() -> None:
    """Quarantine the old flat ``Lib`` without blocking application startup."""
    payloads = _legacy_runtime_payloads()
    if not payloads:
        return
    log(
        "Изолирую устаревшие пакеты из корня Lib: "
        + ", ".join(path.name for path in payloads)
    )
    quarantine = RUNTIME_ROOT / ".legacy-runtime"
    quarantine.mkdir(parents=True, exist_ok=True)
    moved_any = False
    for path in payloads:
        target = quarantine / path.name
        if target.exists():
            target = quarantine / f"{path.name}.{uuid.uuid4().hex}"
        try:
            os.replace(path, target)
            moved_any = True
        except OSError as exc:
            log(
                "Не удалось переместить устаревший runtime-объект "
                f"'{path.name}': {exc}. Он не входит в sys.path и не мешает запуску; "
                "очистка будет повторена позже."
            )
    if moved_any:
        log(
            "Старый runtime сохранён в Lib/.legacy-runtime и не используется. "
            "Его можно удалить вручную после проверки новых backend/overlay."
        )


def log(msg: str) -> None:
    print(msg, flush=True)


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("QT_USE_NATIVE_WINDOWS", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONSAFEPATH"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_CONFIG_FILE"] = os.devnull
    return env


def run(cmd: list[Any], *, env: dict[str, str] | None = None) -> int:
    log("\n>>> " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=str(ROOT), env=env or _base_env()).returncode


def _normalize_child_exit_code(code: int, *, windows: bool | None = None) -> int:
    value = int(code)
    is_windows = os.name == "nt" if windows is None else bool(windows)
    if is_windows and value > 0x7FFFFFFF:
        signed = value - 0x100000000
        log(
            "NeuroMita завершилась с некорректным отрицательным кодом "
            f"{signed} (0x{value:08X}); launcher вернёт код 1."
        )
        return 1
    if value < 0:
        log(f"NeuroMita завершилась по сигналу или с кодом {value}; launcher вернёт код 1.")
        return 1
    return value


def run_quiet(
    cmd: list[Any],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> bool:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env or _base_env(),
            timeout=max(0.1, float(timeout)),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def ensure_pip() -> None:
    if run_quiet([str(PYTHON), "-m", "pip", "--version"], timeout=5.0):
        return
    log("pip не найден во встроенном питоне, включаю ensurepip...")
    if run([str(PYTHON), "-m", "ensurepip", "--upgrade"]) != 0:
        raise RuntimeError("Не удалось включить pip во встроенном Python")


def ensure_uv() -> bool:
    if UV_EXE.is_file() and run_quiet([str(UV_EXE), "--version"], timeout=3.0):
        return True

    ensure_pip()
    if UV_TARGET.exists():
        try:
            shutil.rmtree(UV_TARGET)
        except OSError as exc:
            log(f"Не удалось очистить повреждённый приватный uv: {exc}. Использую pip.")
            return False

    UV_TARGET.mkdir(parents=True, exist_ok=True)
    log(f"uv не найден, устанавливаю изолированно в: {UV_TARGET}")
    command = [
        str(PYTHON), "-m", "pip", "--isolated", "install",
        "--target", str(UV_TARGET), "--upgrade", "--force-reinstall",
        "--no-warn-script-location", "uv",
    ]
    if run(command) != 0:
        log("Не удалось установить приватный uv. Использую встроенный pip.")
        return False
    return UV_EXE.is_file() and run_quiet([str(UV_EXE), "--version"], timeout=3.0)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_settings() -> dict[str, Any]:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _desired_g4f_version(settings: dict[str, Any] | None = None) -> str | None:
    data = dict(settings or _read_settings())
    raw = data.get("G4F_TARGET_VERSION") if data.get("G4F_UPDATE_PENDING") else None
    if not raw:
        raw = data.get("G4F_VERSION")
    value = str(raw or "").strip()
    if not value:
        return None
    if value.lower() == "latest":
        return "latest"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+!_-]*", value):
        log(f"Игнорирую некорректную версию g4f в настройках: {value!r}")
        return None
    return value


def _effective_requirements_text() -> tuple[str, str | None]:
    text = REQ_FILE.read_text(encoding="utf-8")
    desired = _desired_g4f_version()
    if not desired:
        return text, None

    output: list[str] = []
    replaced = False
    pattern = re.compile(
        r"^(?P<indent>\s*)(?P<name>g4f)(?P<extras>\[[^\]]+\])?"
        r"(?P<tail>\s*(?:[<>=!~@].*)?)$",
        re.IGNORECASE,
    )
    for raw_line in text.splitlines(keepends=True):
        newline = "\n" if raw_line.endswith("\n") else ""
        line = raw_line[:-1] if newline else raw_line
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            output.append(raw_line)
            continue
        requirement, sep, comment = line.partition(" #")
        match = pattern.match(requirement)
        if match is None:
            output.append(raw_line)
            continue
        spec = f"{match.group('indent')}{match.group('name')}{match.group('extras') or ''}"
        if desired != "latest":
            spec += f"=={desired}"
        if sep:
            spec += sep + comment
        output.append(spec + newline)
        replaced = True

    if not replaced:
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        output.append("g4f" + ("" if desired == "latest" else f"=={desired}") + "\n")
    return "".join(output), desired


def _effective_requirements_hash() -> str:
    text, _desired = _effective_requirements_text()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_effective_requirements() -> tuple[Path, str | None]:
    text, desired = _effective_requirements_text()
    BOOTSTRAP_DIR.mkdir(parents=True, exist_ok=True)
    temp = EFFECTIVE_REQ_FILE.with_name(f".{EFFECTIVE_REQ_FILE.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, EFFECTIVE_REQ_FILE)
    return EFFECTIVE_REQ_FILE, desired


def _mark_pending_g4f_update_applied() -> None:
    settings = _read_settings()
    if not settings.get("G4F_UPDATE_PENDING"):
        return
    target = _desired_g4f_version(settings)
    if target:
        settings["G4F_VERSION"] = target
    settings["G4F_UPDATE_PENDING"] = False
    settings["G4F_TARGET_VERSION"] = None
    _write_json_atomic(SETTINGS_FILE, settings)
    log(f"Запланированное обновление g4f применено: {target or 'requirements.txt'}")


def _python_identity() -> dict[str, Any]:
    return {
        "version": list(sys.version_info[:3]),
        "implementation": sys.implementation.name,
        "cache_tag": getattr(sys.implementation, "cache_tag", ""),
        "executable": str(PYTHON.resolve()),
    }


def _distribution_snapshot(target: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for distribution in importlib.metadata.distributions(path=[str(target)]):
        name = str(distribution.metadata.get("Name") or "").strip()
        if not name:
            continue
        files = tuple(distribution.files or ())
        files_complete = True
        for file in files:
            try:
                if not Path(distribution.locate_file(file)).exists():
                    files_complete = False
                    break
            except (OSError, TypeError, ValueError):
                files_complete = False
                break
        probes: set[str] = set()
        top_level = distribution.read_text("top_level.txt") or ""
        for line in top_level.splitlines():
            candidate = line.strip()
            if candidate and candidate.isidentifier():
                probes.add(candidate)
        if not probes:
            for file in distribution.files or ():
                parts = Path(str(file)).parts
                if not parts:
                    continue
                first = parts[0]
                if first.endswith((".dist-info", ".data")) or first.startswith("__pycache__"):
                    continue
                if first.endswith(".py"):
                    probes.add(first)
                elif first.isidentifier():
                    probes.add(first)
        result.append({
            "name": name,
            "version": str(distribution.version or ""),
            "probes": sorted(probes),
            "file_count": len(files),
            "files_complete": files_complete,
        })
    return sorted(result, key=lambda item: item["name"].lower())


def _top_level_snapshot(target: Path) -> list[str]:
    if not target.is_dir():
        return []
    ignored = {"__pycache__", ".neuromita_backends.json"}
    result: list[str] = []
    for child in target.iterdir():
        name = child.name
        if name in ignored or name.endswith((".pyc", ".pyo", ".tmp")):
            continue
        result.append(name)
    return sorted(result, key=str.casefold)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_core_state() -> dict[str, Any] | None:
    try:
        data = json.loads(CORE_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _probe_exists(target: Path, probe: str) -> bool:
    return (target / probe).exists() or (target / f"{probe}.py").is_file()


def core_is_healthy() -> bool:
    if not REQ_FILE.is_file() or not CORE_DIR.is_dir():
        return False
    state = _read_core_state()
    if not state or state.get("state_version") != STATE_VERSION:
        return False
    if state.get("requirements_sha256") != _effective_requirements_hash():
        return False
    if state.get("python") != _python_identity():
        return False
    expected_top_level = state.get("top_level_entries")
    if not isinstance(expected_top_level, list):
        return False
    if _top_level_snapshot(CORE_DIR) != sorted(
        (str(item) for item in expected_top_level),
        key=str.casefold,
    ):
        return False

    expected = state.get("distributions")
    if not isinstance(expected, list) or not expected:
        return False
    actual_items = _distribution_snapshot(CORE_DIR)
    if not actual_items or any(not bool(item.get("files_complete")) for item in actual_items):
        return False
    if _forbidden_core_distributions(actual_items):
        return False
    actual = {
        _normalized_distribution_name(item["name"]): item
        for item in actual_items
    }
    expected_names = {
        _normalized_distribution_name(item.get("name"))
        for item in expected
        if isinstance(item, dict)
    }
    if set(actual) != expected_names:
        return False
    for item in expected:
        if not isinstance(item, dict):
            return False
        name = _normalized_distribution_name(item.get("name"))
        installed = actual.get(name)
        if not name or installed is None:
            return False
        if str(installed.get("version") or "") != str(item.get("version") or ""):
            return False
        if int(installed.get("file_count") or 0) != int(item.get("file_count") or 0):
            return False
        probes = item.get("probes")
        if isinstance(probes, list) and probes and not any(
            _probe_exists(CORE_DIR, str(probe)) for probe in probes
        ):
            return False
    return True


def _read_lock_pid() -> int | None:
    try:
        text = CORE_LOCK_FILE.read_text(encoding="ascii", errors="ignore")
    except OSError:
        return None
    for token in text.split():
        if not token.startswith("pid="):
            continue
        try:
            pid = int(token.partition("=")[2])
        except ValueError:
            return None
        return pid if pid > 0 else None
    return None


def _process_is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        # Windows reports access denied for protected, but alive, processes.
        if getattr(exc, "winerror", None) == 5:
            return True
        return False
    return True


class _CoreInstallLock:
    def __init__(self, *, timeout: float = 900.0, stale_after: float = 1800.0) -> None:
        self.timeout = max(1.0, float(timeout))
        # Retained for compatibility. Kernel locks are released on process exit,
        # therefore stale lock-file deletion is no longer required.
        self.stale_after = max(self.timeout, float(stale_after))
        self._fd: int | None = None

    @staticmethod
    def _try_lock(fd: int) -> bool:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False

        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    @staticmethod
    def _unlock(fd: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)

    def __enter__(self) -> "_CoreInstallLock":
        BOOTSTRAP_DIR.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        self._fd = os.open(CORE_LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(self._fd).st_size == 0:
            os.write(self._fd, b"\0")
        while True:
            if self._try_lock(self._fd):
                os.ftruncate(self._fd, 0)
                os.lseek(self._fd, 0, os.SEEK_SET)
                os.write(self._fd, f"pid={os.getpid()} time={time.time()}\n".encode("ascii"))
                os.fsync(self._fd)
                return self
            if time.monotonic() >= deadline:
                os.close(self._fd)
                self._fd = None
                raise TimeoutError("Истекло время ожидания другой установки core")
            time.sleep(0.25)

    def __exit__(self, *_exc: Any) -> None:
        if self._fd is not None:
            try:
                self._unlock(self._fd)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


def install_requirements(target: Path | None = None) -> bool:
    """Materialize main-process dependencies into an explicit target."""
    install_target = Path(target or CORE_DIR)
    install_target.mkdir(parents=True, exist_ok=True)
    log(f"Python: {PYTHON}")
    log(f"Core зависимости: {install_target}")
    log(f"Приватный uv: {UV_TARGET}")

    effective_requirements, desired_g4f = _write_effective_requirements()
    if desired_g4f:
        log(f"Версия g4f для core: {desired_g4f}")

    if ensure_uv():
        code = run([
            str(UV_EXE), "pip", "install", "-r", str(effective_requirements),
            "--python", str(PYTHON), "--target", str(install_target),
            "--no-cache-dir",
        ])
        if code == 0:
            return True
        log("\nuv не справился, пробую обычный pip...")

    ensure_pip()
    return run([
        str(PYTHON), "-m", "pip", "--isolated", "install",
        "-r", str(effective_requirements), "--target", str(install_target),
        "--upgrade", "--no-cache-dir",
    ]) == 0


def _activate_core(staging: Path) -> None:
    backup = RUNTIME_ROOT / f".core-backup-{os.getpid()}"
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    try:
        if CORE_DIR.exists():
            CORE_DIR.replace(backup)
        staging.replace(CORE_DIR)
    except BaseException:
        if not CORE_DIR.exists() and backup.exists():
            backup.replace(CORE_DIR)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def install_core_transactionally() -> bool:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    staging = RUNTIME_ROOT / f".core-staging-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        if not install_requirements(staging):
            return False
        distributions = _distribution_snapshot(staging)
        if not distributions or any(
            not bool(item.get("files_complete")) for item in distributions
        ):
            log("Установка завершилась с неполными package-файлами — core не активирован.")
            return False
        forbidden = _forbidden_core_distributions(distributions)
        if forbidden:
            log(
                "requirements.txt содержит AI runtime-пакеты, которые должны "
                "устанавливаться через AI Hub в Lib/environment: "
                + ", ".join(forbidden)
            )
            return False
        for item in distributions:
            item.pop("files_complete", None)
        top_level_entries = _top_level_snapshot(staging)
        _activate_core(staging)
        _write_json_atomic(CORE_STATE_FILE, {
            "state_version": STATE_VERSION,
            "requirements_sha256": _effective_requirements_hash(),
            "python": _python_identity(),
            "top_level_entries": top_level_entries,
            "distributions": distributions,
        })
        LEGACY_HASH_FILE.unlink(missing_ok=True)
        return True
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def pywin32_postinstall() -> None:
    candidates = (
        CORE_DIR / "pywin32_postinstall.py",
        PYTHON.parent / "Scripts" / "pywin32_postinstall.py",
    )
    env = _base_env()
    env["PYTHONPATH"] = str(CORE_DIR)
    for script in candidates:
        if script.exists():
            run_quiet([str(PYTHON), "-S", str(script), "-install"], env=env, timeout=20.0)
            break


def ensure_core_ready() -> bool:
    if core_is_healthy():
        _cleanup_legacy_runtime_payloads()
        return True
    try:
        with _CoreInstallLock():
            # Другой launcher мог закончить установку, пока мы ждали lock.
            if core_is_healthy():
                _cleanup_legacy_runtime_payloads()
                return True
            if not install_core_transactionally():
                return False
            pywin32_postinstall()
            if not core_is_healthy():
                return False
            _cleanup_legacy_runtime_payloads()
            return True
    except (OSError, TimeoutError) as exc:
        log(f"Не удалось синхронизировать установку core: {exc}")
        return False


def main() -> None:
    if not PYZ.exists():
        log(f"Не найден {PYZ.name} рядом с run.py — битый или неполный билд.")
        raise SystemExit(1)
    if not REQ_FILE.exists():
        log(f"Не найден {REQ_FILE.name} — невозможно проверить core-зависимости.")
        raise SystemExit(1)

    core_was_healthy = core_is_healthy()
    if not core_was_healthy:
        log("=" * 50)
        log("Core отсутствует, повреждён или устарел: восстанавливаю зависимости...")
        log("=" * 50)
    if not ensure_core_ready():
        log(
            "\nНе удалось подготовить core-зависимости. Проверь подробности выше: "
            "причиной может быть сеть, нехватка места, блокировка файлов или антивирус."
        )
        raise SystemExit(1)
    if core_was_healthy:
        log("Core-зависимости проверены — установка не требуется.")
    _mark_pending_g4f_update_applied()

    env = _base_env()
    env["PYTHONPATH"] = str(CORE_DIR)
    env["NEUROMITA_RUNTIME_ROOT"] = str(RUNTIME_ROOT)
    env["NEUROMITA_CORE_DIR"] = str(CORE_DIR)
    env["NEUROMITA_LIB_DIR"] = str(CORE_DIR)
    env["NEUROMITA_ENVIRONMENT_DIR"] = str(RUNTIME_ROOT / "environment")
    while True:
        log("=" * 50)
        log("Запуск NeuroMita...")
        log("=" * 50)
        # -S prevents packages accidentally left in libs/python/Lib/site-packages
        # from leaking into the application. runtime_bootstrap explicitly loads
        # Lib/core (including its .pth files) before importing app dependencies.
        code = _normalize_child_exit_code(
            run([str(PYTHON), "-S", str(PYZ)], env=env)
        )
        if code == 42:
            log("\nОбновление применено, перезапускаю...")
            if not ensure_core_ready():
                log("Core-зависимости после обновления восстановить не удалось.")
                raise SystemExit(1)
            _mark_pending_g4f_update_applied()
            continue
        raise SystemExit(code)


if __name__ == "__main__":
    main()
