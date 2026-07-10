from __future__ import annotations

import os
from typing import Any

from core.backends import BackendKind, get_backend_service
from core.install_types import InstallAction, InstallPlan
from core.installables.types import ComponentStatus, ComponentStatusCode


def build_runtime_ctx(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(ctx or {})
    runtime_target = os.environ.get("NEUROMITA_RUNTIME_TARGET_DIR")
    runtime_paths = tuple(
        item
        for item in str(os.environ.get("NEUROMITA_RUNTIME_PYTHON_PATHS") or "").split(os.pathsep)
        if item
    )
    data.setdefault("libs_dir", runtime_target or os.environ.get("NEUROMITA_LIB_DIR"))
    if runtime_target:
        data.setdefault("target_dir", runtime_target)
        data.setdefault("strict_target", True)
    if runtime_paths:
        data.setdefault("python_paths", list(runtime_paths))
    if not data.get("gpu_vendor"):
        try:
            from utils.gpu_utils import check_gpu_provider

            data["gpu_vendor"] = check_gpu_provider() or "CPU"
        except Exception:
            data["gpu_vendor"] = "CPU"
    return data


def backend_status_ok(backend: BackendKind, ctx: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if backend == BackendKind.NONE:
        return True, {}
    try:
        status = get_backend_service().get_status(backend, ctx=ctx)
        return bool(status.ok), status.as_dict()
    except Exception as exc:
        return False, {"error": str(exc)}


def status_from_installed(
    *,
    component_id: str,
    installed: bool,
    backend: BackendKind,
    ctx: dict[str, Any],
    details: dict[str, Any] | None = None,
) -> ComponentStatus:
    backend_ready, backend_details = backend_status_ok(backend, ctx)
    merged_details = dict(details or {})
    if backend_details:
        merged_details["backend"] = backend_details

    if installed and backend_ready:
        return ComponentStatus(
            id=component_id,
            code=ComponentStatusCode.READY,
            installed=True,
            ready=True,
            message="Ready",
            backend=backend,
            backend_ok=True,
            details=merged_details,
        )

    if installed and not backend_ready:
        return ComponentStatus(
            id=component_id,
            code=ComponentStatusCode.BACKEND_MISSING,
            installed=True,
            ready=False,
            message="Backend is missing",
            backend=backend,
            backend_ok=False,
            details=merged_details,
        )

    return ComponentStatus(
        id=component_id,
        code=ComponentStatusCode.NOT_INSTALLED,
        installed=False,
        ready=False,
        message="Not installed",
        backend=backend,
        backend_ok=backend_ready,
        details=merged_details,
    )


def unsupported_plan(message: str) -> InstallPlan:
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


def noop_plan(message: str) -> InstallPlan:
    return InstallPlan(actions=[], already_installed=True, already_installed_status=message)
