from __future__ import annotations

import os
import shutil
from core.install_types import InstallAction
from utils import getTranslationVariant as _


def torch_install_action(ctx: dict, *, progress: int = 10) -> InstallAction:
    gpu = str((ctx or {}).get("gpu_vendor") or "CPU")
    if gpu == "NVIDIA":
        return InstallAction(
            type="pip",
            description=_("Установка PyTorch с CUDA (cu128)...", "Installing PyTorch with CUDA (cu128)..."),
            progress=int(progress),
            packages=["torch==2.7.1", "torchaudio==2.7.1"],
            extra_args=["--index-url", "https://download.pytorch.org/whl/cu128"],
        )
    return InstallAction(
        type="pip",
        description=_("Установка PyTorch CPU...", "Installing PyTorch CPU..."),
        progress=int(progress),
        packages=["torch==2.7.1", "torchaudio==2.7.1"],
        extra_args=None,
    )


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