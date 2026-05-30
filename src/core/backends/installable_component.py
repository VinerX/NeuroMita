from __future__ import annotations

from typing import Any

from core.backends import BackendKind, get_backend_service
from core.install_types import InstallPlan
from core.installables import (
    ComponentCategory,
    ComponentMetadata,
    ComponentStatus,
    ComponentStatusCode,
    make_component_id,
)
from core.installables.helpers import build_runtime_ctx, noop_plan


class BackendInstallableComponent:
    category = ComponentCategory.BACKEND
    legacy_kind = "backend"

    def __init__(self, backend: BackendKind) -> None:
        self.backend = backend
        self.item_id = backend.value
        self.id = make_component_id(self.category, self.item_id)

    def metadata(self) -> ComponentMetadata:
        title_map = {
            BackendKind.CPU: "PyTorch CPU backend",
            BackendKind.CUDA: "PyTorch CUDA backend",
            BackendKind.ONNX: "ONNX backend",
        }
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=title_map.get(self.backend, self.item_id),
            description="System runtime used by local AI models.",
            backend=self.backend,
            legacy_kind=self.legacy_kind,
            tags=("system", self.backend.value),
        )

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        run_ctx = build_runtime_ctx(ctx)
        try:
            status = get_backend_service().get_status(self.backend, ctx=run_ctx)
            return ComponentStatus(
                id=self.id,
                code=ComponentStatusCode.READY if status.ok else ComponentStatusCode.NOT_INSTALLED,
                installed=bool(status.ok),
                ready=bool(status.ok),
                message=status.reason,
                backend=self.backend,
                backend_ok=bool(status.ok),
                details=status.as_dict(),
            )
        except Exception as exc:
            return ComponentStatus(
                id=self.id,
                code=ComponentStatusCode.FAILED,
                installed=False,
                ready=False,
                message=str(exc),
                backend=self.backend,
                backend_ok=False,
            )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        return InstallPlan(
            actions=[],
            ok_status="Done",
            required_backend=self.backend,
            backend_context=build_runtime_ctx(ctx),
        )

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        return noop_plan("Backend uninstall is managed separately.")

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


def create_backend_installable_components() -> list[BackendInstallableComponent]:
    return [BackendInstallableComponent(kind) for kind in (BackendKind.CPU, BackendKind.CUDA, BackendKind.ONNX)]
