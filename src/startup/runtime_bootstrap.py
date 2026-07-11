from __future__ import annotations

import faulthandler
import json
import os
import site
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from startup.startup_profiler import startup_trace


@dataclass
class RuntimeContext:
    base_dir: str
    libs_dir: str
    QApplication: Any
    logger: Any
    crash_log_handle: Any = None
    _backend_bootstrap: Callable[[], None] | None = field(default=None, repr=False)
    _backend_bootstrap_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )
    _backend_bootstrap_done: bool = field(default=False, repr=False)

    def ensure_backend_bootstrap(self) -> None:
        if self._backend_bootstrap_done:
            return
        with self._backend_bootstrap_lock:
            if self._backend_bootstrap_done:
                return
            if self._backend_bootstrap is not None:
                self._backend_bootstrap()
            self._backend_bootstrap_done = True


def _resolve_base_dir(entry_file: str | None = None) -> str:
    current_file = os.path.abspath(entry_file or str(Path(__file__).resolve().parents[1] / "__main__.py"))
    if current_file.lower().endswith(".pyz"):
        return os.path.dirname(current_file)
    return os.path.dirname(os.path.dirname(current_file))


def _is_runtime_layer(path: Path) -> bool:
    return (path / "manifest.json").is_file() and (path / "site-packages").is_dir()


def _migrate_legacy_runtime_layout(runtime_root: Path) -> None:
    core_root = runtime_root / "core"
    environment_root = runtime_root / "environment"
    bases_root = environment_root / "bases"
    overlays_root = environment_root / "overlays"

    core_root.mkdir(parents=True, exist_ok=True)
    bases_root.mkdir(parents=True, exist_ok=True)
    overlays_root.mkdir(parents=True, exist_ok=True)

    # A previous environment implementation stored AI base layers in Lib/core.
    # Move only directories that carry a layer manifest; ordinary application
    # packages belong to the main-process core and remain in place.
    for child in tuple(core_root.iterdir()):
        if not child.is_dir() or not _is_runtime_layer(child):
            continue
        target = bases_root / child.name
        if target.exists():
            continue
        child.replace(target)

    # Older overlays lived directly under Lib/environment/<logical>/<revision>.
    for logical in tuple(environment_root.iterdir()):
        if not logical.is_dir() or logical.name in {"bases", "overlays", ".staging", ".locks"}:
            continue
        target_logical = overlays_root / logical.name
        target_logical.mkdir(parents=True, exist_ok=True)
        for revision in tuple(logical.iterdir()):
            if not revision.is_dir() or not _is_runtime_layer(revision):
                continue
            target = target_logical / revision.name
            if not target.exists():
                revision.replace(target)
        try:
            logical.rmdir()
        except OSError:
            pass


def _configure_paths(base_dir: str) -> str:
    os.environ["NEUROMITA_BASE_DIR"] = base_dir
    runtime_root = Path(base_dir, "Lib").resolve()
    core_root = runtime_root / "core"
    environment_root = runtime_root / "environment"
    runtime_paths = {
        "NEUROMITA_RUNTIME_ROOT": str(runtime_root),
        "NEUROMITA_LIB_DIR": str(core_root),
        "NEUROMITA_CORE_DIR": str(core_root),
        "NEUROMITA_ENVIRONMENT_DIR": str(environment_root),
    }
    os.environ.update(runtime_paths)
    defaults = {
        "NEUROMITA_PROMPTS_DIR": os.path.join(base_dir, "Prompts"),
        "NEUROMITA_HISTORIES_DIR": os.path.join(base_dir, "Histories"),
        "NEUROMITA_MODELS_DIR": os.path.join(base_dir, "Models"),
        "NEUROMITA_CHECKPOINTS_DIR": os.path.join(base_dir, "checkpoints"),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)

    runtime_root.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_runtime_layout(runtime_root)
    core_root.mkdir(parents=True, exist_ok=True)
    environment_root.mkdir(parents=True, exist_ok=True)

    local_python = os.path.join(base_dir, "libs", "python", "python.exe")
    python_executable = local_python if os.path.exists(local_python) else sys.executable
    os.environ["NEUROMITA_PYTHON"] = python_executable

    forbidden = {
        os.path.normcase(os.path.abspath(str(runtime_root))),
        os.path.normcase(os.path.abspath(str(environment_root))),
        os.path.normcase(os.path.abspath(str(core_root))),
        os.path.normcase(
            os.path.abspath(
                os.path.join(os.path.dirname(python_executable), "Lib", "site-packages")
            )
        ),
    }
    sys.path = [
        item for item in sys.path
        if os.path.normcase(os.path.abspath(item or "")) not in forbidden
    ]
    before = tuple(sys.path)
    site.addsitedir(str(core_root))
    added = [item for item in sys.path if item not in before]
    sys.path = [item for item in sys.path if item not in added]
    sys.path[:0] = added or [str(core_root)]

    # Optional main-process dependencies are isolated from the immutable core
    # and from AI workers. They are activated only from ready registry entries.
    try:
        from core.runtime_environments import RuntimeEnvironmentManager

        manager = RuntimeEnvironmentManager(runtime_root)
        manager.cleanup_inactive_overlays()
        main_paths = manager.main_runtime_paths()
    except Exception:
        main_paths = ()

    loaded_main_paths: list[str] = []
    for dependency_path in main_paths:
        path = Path(dependency_path).resolve()
        if not path.is_dir():
            continue
        before_dependency = tuple(sys.path)
        site.addsitedir(str(path))
        dependency_added = [item for item in sys.path if item not in before_dependency]
        # Keep Lib/core authoritative; optional layers are lower-priority and
        # therefore cannot replace main-process packages accidentally.
        for item in dependency_added or [str(path)]:
            if item not in loaded_main_paths:
                loaded_main_paths.append(item)

    os.environ["NEUROMITA_MAIN_ENVIRONMENT_PATHS"] = os.pathsep.join(loaded_main_paths)
    return str(core_root)


def _configure_crash_logging(base_dir: str):
    crash_log = None
    try:
        crash_path = os.path.join(base_dir, "NeuroMitaCrash.log")
        crash_log = open(crash_path, "a", buffering=1, encoding="utf-8")
        faulthandler.enable(file=crash_log, all_threads=True)
    except Exception:
        faulthandler.enable()
    return crash_log


def _install_exception_hooks(logger: Any) -> None:
    def log_uncaught_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Неперехваченное исключение",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    def log_thread_exception(args):
        if issubclass(args.exc_type, SystemExit):
            return
        logger.critical(
            f"Неперехваченное исключение в потоке {getattr(args.thread, 'name', '?')}",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_uncaught_exception
    threading.excepthook = log_thread_exception


def _startup_banner(title: str, version: str) -> str:
    version_info = f"Version {version}"
    content_width = max(len(title), len(version_info)) + 6
    if content_width % 2:
        content_width += 1
    border = "═" * content_width
    empty = " " * content_width
    return (
        f"╔{border}╗\n"
        f"║{empty}║\n"
        f"║{title.center(content_width)}║\n"
        f"║{version_info.center(content_width)}║\n"
        f"║{empty}║\n"
        f"╚{border}╝"
    )


def _load_environment(base_dir: str, logger: Any) -> None:
    try:
        from dotenv import load_dotenv

        env_path = os.path.join(base_dir, "features.env")
        loaded = load_dotenv(dotenv_path=env_path)
        if loaded:
            logger.notify(f"Переменные окружения загружены из: {env_path}")
        else:
            logger.notify(
                f"Файл окружения не найден: {env_path}. Используются системные значения."
            )
    except Exception as exc:
        logger.warning(f"Не удалось загрузить features.env: {exc}")

    os.environ.setdefault("WHISPER_ONNX_DEBUG", "1")


def _run_update_checks(base_dir: str, logger: Any) -> None:
    try:
        from updater import check_for_unity_updates, check_for_updates

        settings: dict[str, Any] = {}
        settings_path = os.path.join(base_dir, "Settings", "settings.json")
        try:
            with open(settings_path, encoding="utf-8") as source:
                settings = json.load(source)
        except Exception:
            pass

        if bool(settings.get("AUTO_UPDATE", settings.get("AUTO_UPDATE_CHECK", False))):
            check_for_updates(
                base_dir=base_dir,
                logger=logger,
                channel=settings.get("UPDATE_CHANNEL", "stable"),
                tester_code=settings.get("TESTER_CODE") or None,
                auto_update=True,
                update_mode=settings.get("UPDATE_MODE", "diff"),
                preserve_prompts=bool(settings.get("UPDATE_PRESERVE_PROMPTS", True)),
            )

        if bool(settings.get("AUTO_UPDATE_UNITY", False)):
            check_for_unity_updates(
                base_dir=base_dir,
                logger=logger,
                unity_dir=settings.get("UNITY_INSTALL_DIR") or None,
                channel=settings.get("UPDATE_CHANNEL", "stable"),
                tester_code=settings.get("TESTER_CODE") or None,
                auto_update=True,
            )
    except Exception as exc:
        logger.warning(f"Update check failed: {exc}")


def _run_torch_bootstrap(_libs_dir: str, logger: Any) -> None:
    # Heavy AI runtimes are installed transactionally by AI Hub into
    # Lib/environment. The main process must never mutate or import them.
    logger.info("AI backend bootstrap is managed by AI Hub and deferred until use")


def _apply_compatibility_patches(_libs_dir: str, _logger: Any) -> None:
    # Backend-specific compatibility transforms belong to install plans and are
    # applied to their staging environment before activation.
    return


def _ensure_project_root(base_dir: str, logger: Any) -> None:
    marker = os.path.join(base_dir, ".project-root")
    if os.path.exists(marker):
        return
    try:
        with open(marker, "a", encoding="utf-8"):
            pass
        logger.info(f"Файл '{marker}' создан.")
    except Exception as exc:
        logger.warning(f"Не удалось создать project-root marker: {exc}")


def _prime_onnxruntime(_logger: Any) -> None:
    # ONNX Runtime is an AI backend dependency and must stay out of the main
    # process. Candidate workers validate their own native runtime before READY.
    return


def _import_gui_runtime():
    # onnxruntime уже загружен выше; здесь выполняется первый явный Qt-import.

    from PyQt6.QtWidgets import QApplication

    return QApplication


def initialize_runtime(
    entry_file: str | None = None,
    *,
    load_gui: bool = True,
    defer_backend_bootstrap: bool = False,
) -> RuntimeContext:
    os.environ.setdefault("QT_API", "pyqt6")
    os.environ.setdefault("UV_LINK_MODE", "copy")

    if os.environ.get("VERBOSE_TRITON_LOGS", "0") == "1":
        os.environ["TORCH_LOGS"] = "+dynamo"
        os.environ["TORCHDYNAMO_VERBOSE"] = "1"

    with startup_trace.phase("runtime.resolve_paths"):
        base_dir = _resolve_base_dir(entry_file)
        libs_dir = _configure_paths(base_dir)
        startup_trace.configure(base_dir=base_dir)
    with startup_trace.phase("runtime.crash_logging"):
        crash_log = _configure_crash_logging(base_dir)

    with startup_trace.phase("runtime.logger_import"):
        from main_logger import logger
        from _version import __version__

    _install_exception_hooks(logger)
    logger.success(f"\n\n{_startup_banner('NeuroMita', __version__)}\n\n")
    logger.info(f"Базовая директория: {base_dir}")
    logger.info(f"Prompts: {os.environ['NEUROMITA_PROMPTS_DIR']}")
    logger.info(f"Histories: {os.environ['NEUROMITA_HISTORIES_DIR']}")
    logger.info(f"Checkpoints: {os.environ['NEUROMITA_CHECKPOINTS_DIR']}")
    logger.info(f"Python: {os.environ['NEUROMITA_PYTHON']}")
    logger.info(f"Lib: {libs_dir}")

    with startup_trace.phase("runtime.environment"):
        _load_environment(base_dir, logger)
    with startup_trace.phase("runtime.onnxruntime_import"):
        _prime_onnxruntime(logger)
    # Update checks stay before GUI imports. Applying a source update after part
    # of the application has already been imported would create a mixed-version
    # process. The expensive backend compatibility work can safely happen after
    # the first GUI paint, but still before backend controllers are imported.
    with startup_trace.phase("runtime.update_checks"):
        _run_update_checks(base_dir, logger)

    def complete_backend_bootstrap() -> None:
        with startup_trace.phase("runtime.torch_bootstrap"):
            _run_torch_bootstrap(libs_dir, logger)
        with startup_trace.phase("runtime.compatibility_patches"):
            _apply_compatibility_patches(libs_dir, logger)
        startup_trace.mark("runtime.backend_bootstrap_ready")
        startup_trace.write()

    backend_bootstrap_done = False
    if not defer_backend_bootstrap:
        complete_backend_bootstrap()
        backend_bootstrap_done = True

    with startup_trace.phase("runtime.project_root"):
        _ensure_project_root(base_dir, logger)
    with startup_trace.phase("runtime.qt_import", enabled=bool(load_gui)):
        QApplication = _import_gui_runtime() if load_gui else None

    startup_trace.mark("runtime.ready", gui=bool(load_gui))
    startup_trace.write()

    return RuntimeContext(
        base_dir=base_dir,
        libs_dir=libs_dir,
        QApplication=QApplication,
        logger=logger,
        crash_log_handle=crash_log,
        _backend_bootstrap=complete_backend_bootstrap,
        _backend_bootstrap_done=backend_bootstrap_done,
    )
