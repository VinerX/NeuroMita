from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache

from core.install_types import InstallAction, InstallPlan
from utils import getTranslationVariant as _


_PYTHON_PROBE_TIMEOUT_SECONDS = 10.0


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

    return InstallAction(
        type="call",
        description=description,
        progress=int(progress),
        fn=_do_uninstall,
        environment_mutation=True,
    )


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
            timeout=_PYTHON_PROBE_TIMEOUT_SECONDS,
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
            "Внимание: пакет tts-with-rvc может работать нестабильно на встроенном Python {ver} "
            "(стек fairseq-built/torchcrepe/tts-with-rvc заточен под Python 3.11.x). "
            "Установка продолжится; если RVC-ветка не заработает — нужен рантайм 3.11.x.",
            "Warning: the tts-with-rvc package may be unstable on the embedded Python {ver} "
            "(the fairseq-built/torchcrepe/tts-with-rvc stack targets Python 3.11.x). "
            "Installation will proceed; if the RVC mode fails, a 3.11.x runtime is needed.",
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


def warning_action(message: str, *, progress: int = 1) -> InstallAction:
    """Non-fatal heads-up: surface a caveat in the install log/status but let the
    install proceed (returns True). Used for «может не работать», в отличие от
    unsupported_runtime_plan, который установку рубит."""
    def _warn(*, callbacks=None, ctx=None, **_kwargs) -> bool:
        try:
            if callbacks:
                callbacks.log(message)
                callbacks.status(message)
        except Exception:
            pass
        return True

    return InstallAction(type="call", description=message, progress=int(progress), fn=_warn)


def patch_tts_with_rvc_audio(
    *,
    pip_installer=None,
    callbacks=None,
    ctx=None,
    **_kwargs,
) -> bool:
    target = getattr(pip_installer, "libs_path_abs", None) if pip_installer is not None else None
    runtime_ctx = dict(ctx or {})
    target = str(
        target
        or runtime_ctx.get("target_dir")
        or runtime_ctx.get("libs_dir")
        or ""
    ).strip()
    if not target:
        return False

    audio_path = os.path.join(target, "tts_with_rvc", "lib", "audio.py")
    if not os.path.isfile(audio_path):
        return True

    try:
        with open(audio_path, "r", encoding="utf-8") as stream:
            source = stream.read()
        patched = source.replace(
            "import ffmpeg",
            'import importlib\nffmpeg = importlib.import_module("ffmpeg")',
            1,
        )
        if patched != source:
            with open(audio_path, "w", encoding="utf-8", newline="") as stream:
                stream.write(patched)
            if callbacks is not None:
                callbacks.log("Patched tts_with_rvc/lib/audio.py")
        return True
    except Exception as exc:
        if callbacks is not None:
            callbacks.log(f"Failed to patch tts_with_rvc/lib/audio.py: {exc}")
        return False
