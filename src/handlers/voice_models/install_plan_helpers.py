from __future__ import annotations

import os
import shutil
from core.install_types import InstallAction
from utils import getTranslationVariant as _
from utils.torch_install_utils import TORCH_PACKAGES, decide_torch_install


def torch_install_action(ctx: dict, *, progress: int = 10) -> InstallAction:
    """Возвращает действие установки/переустановки PyTorch для плана.

    Учитывает уже установленный вариант torch (CPU/CUDA) и вендора GPU из ctx:
      - skip      -> no-op action (PyTorch уже установлен в нужном варианте)
      - install   -> обычный pip-action (packages + extra_args)
      - reinstall -> call-action: uninstall torch/torchaudio → install в CUDA
    """
    gpu = str((ctx or {}).get("gpu_vendor") or "CPU")
    plan = decide_torch_install(gpu)
    action = plan["action"]

    if action == "skip":
        reason = plan.get("reason", "PyTorch уже установлен")
        description = _(reason, reason)

        def _noop(**_kwargs) -> bool:
            return True

        return InstallAction(
            type="call",
            description=description,
            progress=int(progress),
            fn=_noop,
        )

    if action == "install":
        description = _(plan["description"], plan["description"])
        return InstallAction(
            type="pip",
            description=description,
            progress=int(progress),
            packages=list(TORCH_PACKAGES),
            extra_args=plan.get("extra_args"),
        )

    # action == "reinstall"
    description = _(plan["description"], plan["description"])
    extra_args = plan.get("extra_args")

    def _do_reinstall(*, pip_installer=None, callbacks=None, ctx=None, **_kwargs) -> bool:
        if pip_installer is None:
            return False
        try:
            if callbacks:
                callbacks.status(_(
                    "Удаление CPU-варианта PyTorch...",
                    "Removing CPU PyTorch...",
                ))
            ok = pip_installer.uninstall_packages(
                ["torch", "torchaudio"],
                description=_(
                    "Удаление CPU-варианта PyTorch",
                    "Removing CPU PyTorch",
                ),
            )
            if not ok:
                if callbacks:
                    callbacks.log("uninstall torch/torchaudio failed")
                return False

            if callbacks:
                callbacks.status(description)
            ok = pip_installer.install_package(
                list(TORCH_PACKAGES),
                description=description,
                extra_args=extra_args,
            )
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
        fn=_do_reinstall,
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