from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache

from core.install_types import InstallAction, InstallPlan
from utils import getTranslationVariant as _


def pip_uninstall_action(packages: list[str], *, description: str, progress: int = 20) -> InstallAction:
    pkgs = [str(p).strip() for p in (packages or []) if str(p).strip()]

    def _do_uninstall(*, pip_installer=None, callbacks=None, ctx=None, **_kwargs) -> bool:
        if pip_installer is None:
            return False
        if not pkgs:
            return True
        try:
            if callbacks:
                callbacks.status(description)
            ok = pip_installer.uninstall_packages(pkgs, description)
            return bool(ok)
        except Exception as e:
            try:
                if callbacks:
                    callbacks.log(str(e))
            except Exception:
                pass
            return False

    return InstallAction(type="call", description=description, progress=int(progress), fn=_do_uninstall)


def remove_paths_action(paths: list[str], *, description: str, progress: int = 90) -> InstallAction:
    pp = [str(p).strip() for p in (paths or []) if str(p).strip()]

    def _rm(p: str) -> None:
        if not p:
            return
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    def _do_rm(*, callbacks=None, ctx=None, **_kwargs) -> bool:
        for p in pp:
            _rm(p)
        try:
            if callbacks:
                callbacks.status(description)
        except Exception:
            pass
        return True

    return InstallAction(type="call", description=description, progress=int(progress), fn=_do_rm)


@lru_cache(maxsize=4)
def installer_python_version(python_path: str | None = None) -> tuple[int, int, int] | None:
    path = str(python_path or os.environ.get("NEUROMITA_PYTHON") or sys.executable).strip()
    if not path:
        return None

    current = os.path.abspath(sys.executable)
    target = os.path.abspath(path)
    if target == current:
        info = sys.version_info
        return int(info.major), int(info.minor), int(info.micro)

    try:
        result = subprocess.run(
            [path, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    try:
        major, minor, micro = (int(part) for part in result.stdout.strip().split(".", 2))
        return major, minor, micro
    except Exception:
        return None


def rvc_python_compat_error(package: str, *, python_path: str | None = None) -> str | None:
    pkg = str(package or "").strip().lower()
    version = installer_python_version(python_path)
    if version is None:
        return None

    if pkg == "tts-with-rvc" and version >= (3, 12, 0):
        ver = ".".join(str(v) for v in version)
        return _(
            "Пакет tts-with-rvc сейчас не поддерживается встроенным Python {ver}. "
            "AI Hub устанавливает зависимости через libs/python/python.exe, а у вас там Python {ver}. "
            "Для RVC-веток нужен совместимый рантайм Python 3.11.x или отдельная адаптация стека зависимостей "
            "(fairseq-built/torchcrepe/tts-with-rvc) под 3.12.",
            "The tts-with-rvc package is currently unsupported on the embedded Python {ver}. "
            "AI Hub installs dependencies through libs/python/python.exe, and that runtime is Python {ver}. "
            "RVC-based modes need a compatible Python 3.11.x runtime or an explicit dependency-stack adaptation "
            "(fairseq-built/torchcrepe/tts-with-rvc) for 3.12.",
        ).format(ver=ver)

    return None


def unsupported_runtime_plan(message: str) -> InstallPlan:
    return InstallPlan(
        actions=[
            InstallAction(
                type="call",
                description=message,
                progress=1,
                fn=lambda **_kwargs: False,
            )
        ],
        ok_status=message,
    )
