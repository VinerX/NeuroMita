from __future__ import annotations

import faulthandler
import importlib
import json
import os
import re
import sys
import tempfile
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


def _configure_paths(base_dir: str) -> str:
    os.environ["NEUROMITA_BASE_DIR"] = base_dir
    defaults = {
        "NEUROMITA_LIB_DIR": os.path.join(base_dir, "Lib"),
        "NEUROMITA_CORE_DIR": os.path.join(base_dir, "Lib", "core"),
        "NEUROMITA_ENVIRONMENT_DIR": os.path.join(base_dir, "Lib", "environment"),
        "NEUROMITA_PROMPTS_DIR": os.path.join(base_dir, "Prompts"),
        "NEUROMITA_HISTORIES_DIR": os.path.join(base_dir, "Histories"),
        "NEUROMITA_MODELS_DIR": os.path.join(base_dir, "Models"),
        "NEUROMITA_CHECKPOINTS_DIR": os.path.join(base_dir, "checkpoints"),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)

    libs_dir = os.environ["NEUROMITA_LIB_DIR"]
    os.makedirs(libs_dir, exist_ok=True)

    local_python = os.path.join(base_dir, "libs", "python", "python.exe")
    os.environ["NEUROMITA_PYTHON"] = local_python if os.path.exists(local_python) else sys.executable

    libs_norm = os.path.normcase(os.path.abspath(libs_dir))
    sys.path = [
        item
        for item in sys.path
        if os.path.normcase(os.path.abspath(item or "")) != libs_norm
    ]
    sys.path.insert(0, libs_dir)
    return libs_dir


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


def _run_torch_bootstrap(libs_dir: str, logger: Any) -> None:
    try:
        from core.backends import get_backend_service
        from utils.gpu_utils import check_gpu_provider, format_primary_gpu_label
        from utils.pip_installer import PipInstaller

        backend_service = get_backend_service()
        gpu = check_gpu_provider() or "CPU"
        gpu_label = format_primary_gpu_label()
        backend_ctx = {"gpu_vendor": gpu, "libs_dir": libs_dir}
        backend_kind = backend_service.preferred_torch_kind(backend_ctx)
        status = backend_service.get_status(backend_kind, ctx=backend_ctx)
        installed_variant = backend_service.get_installed_torch_variant(target_dir=libs_dir)

        if status.action == "reinstall" and installed_variant is not None:
            logger.info(
                f"Torch bootstrap: gpu={gpu_label}, action=reinstall (CPU→CUDA)"
            )
            pip_installer = PipInstaller(update_log=logger.info)
            pip_installer.uninstall_packages(
                ["torch", "torchaudio"],
                description="Удаление CPU-варианта PyTorch",
            )
            status = backend_service.install_backend(
                backend_kind,
                pip_installer=pip_installer,
                ctx=backend_ctx,
            )
            if not status.ok:
                raise RuntimeError(status.reason)
        elif status.action != "skip":
            logger.info(
                f"Torch bootstrap: gpu={gpu_label}, action={status.action} — "
                "отложено до первого использования"
            )
        else:
            logger.info(
                f"Torch bootstrap: gpu={gpu_label}, action=skip — {status.reason or ''}"
            )
    except Exception as exc:
        logger.warning(f"Torch early bootstrap failed: {exc}")


def _atomic_rewrite(path: str, transform: Callable[[str], str], logger: Any) -> bool:
    if not os.path.isfile(path):
        return False

    try:
        with open(path, "r", encoding="utf-8") as source:
            old_text = source.read()
        new_text = transform(old_text)
        if new_text == old_text:
            return False

        directory = os.path.dirname(path)
        fd, temp_path = tempfile.mkstemp(prefix=".neuromita-patch-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as target:
                target.write(new_text)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        logger.info(f"Compatibility patch applied: {path}")
        return True
    except Exception as exc:
        logger.warning(f"Compatibility patch failed for {path}: {exc}")
        return False


def _apply_compatibility_patches(libs_dir: str, logger: Any) -> None:
    fairseq_config = os.path.join(libs_dir, "fairseq", "dataclass", "configs.py")
    _atomic_rewrite(
        fairseq_config,
        lambda text: re.sub(r"metadata=\{(.*?)help:", r'metadata={\1"help":', text),
        logger,
    )

    rvc_audio = os.path.join(libs_dir, "tts_with_rvc", "lib", "audio.py")
    _atomic_rewrite(
        rvc_audio,
        lambda text: re.sub(
            r"\bimport ffmpeg\b",
            'import importlib\nffmpeg = importlib.import_module("ffmpeg")',
            text,
        ),
        logger,
    )

    triton_windows_utils = os.path.join(libs_dir, "triton", "windows_utils.py")
    _atomic_rewrite(
        triton_windows_utils,
        lambda text: text.replace(
            "output = subprocess.check_output(command, text=True).strip()",
            "output = subprocess.check_output(\n"
            "            command, text=True, close_fds=True, "
            "stdin=subprocess.DEVNULL, stderr=subprocess.PIPE\n"
            "        ).strip()",
        ),
        logger,
    )

    triton_compiler = os.path.join(
        libs_dir, "triton", "backends", "nvidia", "compiler.py"
    )
    _atomic_rewrite(
        triton_compiler,
        lambda text: text.replace(
            '@functools.lru_cache()\ndef get_ptxas_version():\n'
            '    version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"]).decode("utf-8")\n'
            "    return version",
            '@functools.lru_cache()\ndef get_ptxas_version():\n'
            '    version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"], '
            'stderr=subprocess.PIPE, close_fds=True, stdin=subprocess.DEVNULL).decode("utf-8")\n'
            "    return version",
        ),
        logger,
    )

    triton_build = os.path.join(libs_dir, "triton", "runtime", "build.py")
    escaped_libs = repr(libs_dir)

    def patch_build(text: str) -> str:
        text = text.replace(
            'cc = os.path.join(sysconfig.get_paths()["platlib"], "triton", "runtime", "tcc", "tcc.exe")',
            f'cc = os.path.join({escaped_libs}, "triton", "runtime", "tcc", "tcc.exe")',
        )
        return text.replace(
            'cc_cmd = [cc, src, "-O3", "-shared", "-fPIC", "-Wno-psabi", "-o", out]',
            'cc_cmd = [cc, src, "-O3", "-shared", "-Wno-psabi", "-o", out]',
        )

    _atomic_rewrite(triton_build, patch_build, logger)

    triton_tcc = os.path.join(libs_dir, "triton", "runtime", "tcc", "tcc.exe")
    if os.path.exists(triton_tcc):
        os.environ["CC"] = triton_tcc
    else:
        configured_cc = str(os.environ.get("CC", "") or "")
        if configured_cc.replace("/", "\\").lower() == triton_tcc.replace("/", "\\").lower():
            os.environ.pop("CC", None)


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


def _prime_onnxruntime(logger: Any) -> None:
    # Порядок критичен: onnxruntime должен загрузить свой native runtime раньше
    # любого кода, который потенциально может импортировать Qt.
    try:
        importlib.import_module("onnxruntime")
    except Exception as exc:
        logger.warning(f"onnxruntime не импортирован на старте: {exc}")


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
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
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
