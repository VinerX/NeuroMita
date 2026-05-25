from __future__ import annotations

import os
from typing import Any

from main_logger import logger

from core.backends import BackendKind, get_backend_service
from core.install_types import InstallAction, InstallPlan
from core.installables import (
    ComponentCategory,
    ComponentMetadata,
    ComponentStatus,
    ComponentStatusCode,
    coerce_backend,
    make_component_id,
)


def _runtime_ctx(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(ctx or {})
    data.setdefault("libs_dir", os.environ.get("NEUROMITA_LIB_DIR"))
    if not data.get("gpu_vendor"):
        try:
            from utils.gpu_utils import check_gpu_provider

            data["gpu_vendor"] = check_gpu_provider() or "CPU"
        except Exception:
            data["gpu_vendor"] = "CPU"
    return data


def _backend_ok(backend: BackendKind, ctx: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if backend == BackendKind.NONE:
        return True, {}
    try:
        status = get_backend_service().get_status(backend, ctx=ctx)
        return bool(status.ok), status.as_dict()
    except Exception as exc:
        return False, {"error": str(exc)}


def _status_from_installed(
    *,
    component_id: str,
    installed: bool,
    backend: BackendKind,
    ctx: dict[str, Any],
    details: dict[str, Any] | None = None,
) -> ComponentStatus:
    backend_ready, backend_details = _backend_ok(backend, ctx)
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


def _unsupported_plan(message: str) -> InstallPlan:
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


def _noop_plan(message: str) -> InstallPlan:
    return InstallPlan(actions=[], already_installed=True, already_installed_status=message)


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
        run_ctx = _runtime_ctx(ctx)
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
            backend_context=_runtime_ctx(ctx),
        )

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        return _noop_plan("Backend uninstall is managed separately.")

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


class VoiceModelInstallableComponent:
    category = ComponentCategory.TTS
    legacy_kind = "voice"

    def __init__(self, model_id: str, spec: Any) -> None:
        self.item_id = str(model_id)
        self.spec = spec
        self.id = make_component_id(self.category, self.item_id)

    def _backend(self, ctx: dict[str, Any]) -> BackendKind:
        try:
            return coerce_backend(self.spec.required_backend(self.item_id, ctx))
        except Exception:
            return BackendKind.NONE

    def metadata(self) -> ComponentMetadata:
        ctx = _runtime_ctx()
        backend = self._backend(ctx)
        try:
            title = str(self.spec.title(self.item_id))
        except Exception:
            title = self.item_id
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=title,
            backend=backend,
            legacy_kind=self.legacy_kind,
            tags=("tts", backend.value),
        )

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        run_ctx = _runtime_ctx(ctx)
        backend = self._backend(run_ctx)
        try:
            installed = bool(self.spec.is_installed(self.item_id, run_ctx))
        except Exception as exc:
            return ComponentStatus(
                id=self.id,
                code=ComponentStatusCode.FAILED,
                installed=False,
                ready=False,
                message=str(exc),
                backend=backend,
                backend_ok=False,
            )
        return _status_from_installed(
            component_id=self.id,
            installed=installed,
            backend=backend,
            ctx=run_ctx,
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        run_ctx = _runtime_ctx(ctx)
        plan = self.spec.build_install_plan(self.item_id, run_ctx)
        if getattr(plan, "required_backend", None) is None:
            plan.required_backend = self._backend(run_ctx)
        if not getattr(plan, "backend_context", None):
            plan.backend_context = dict(run_ctx)
        return plan

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        return self.spec.build_uninstall_plan(self.item_id, _runtime_ctx(ctx))

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


class AsrModelInstallableComponent:
    category = ComponentCategory.ASR
    legacy_kind = "asr"

    def __init__(self, engine_id: str, recognizer_cls: type) -> None:
        self.item_id = str(engine_id)
        self.recognizer_cls = recognizer_cls
        self.id = make_component_id(self.category, self.item_id)

    def _new_recognizer(self):
        try:
            from utils.pip_installer import PipInstaller

            return self.recognizer_cls(PipInstaller(update_log=logger.info), logger)
        except Exception:
            return None

    def _settings(self, ctx: dict[str, Any]) -> dict[str, Any]:
        value = ctx.get("engine_settings") or ctx.get("settings") or {}
        return value if isinstance(value, dict) else {}

    def _backend(self, ctx: dict[str, Any]) -> BackendKind:
        recognizer = self._new_recognizer()
        if recognizer is None or not hasattr(recognizer, "required_backend"):
            return BackendKind.NONE
        try:
            if hasattr(recognizer, "apply_settings"):
                recognizer.apply_settings(self._settings(ctx))
        except Exception:
            pass
        try:
            return coerce_backend(recognizer.required_backend(ctx))
        except Exception:
            return BackendKind.NONE

    def metadata(self) -> ComponentMetadata:
        recognizer = self._new_recognizer()
        meta: dict[str, Any] = {}
        try:
            cfgs = recognizer.get_model_configs() if recognizer else (getattr(self.recognizer_cls, "MODEL_CONFIGS", []) or [])
            for item in cfgs or []:
                if isinstance(item, dict) and str(item.get("id") or "") == self.item_id:
                    meta = item
                    break
        except Exception:
            meta = {}

        backend = self._backend(_runtime_ctx())
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=str(meta.get("name") or self.item_id),
            description=str(meta.get("description") or ""),
            backend=backend,
            legacy_kind=self.legacy_kind,
            tags=tuple(str(x) for x in (meta.get("tags") or []) if str(x).strip()),
            languages=tuple(str(x) for x in (meta.get("languages") or []) if str(x).strip()),
        )

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        run_ctx = _runtime_ctx(ctx)
        backend = self._backend(run_ctx)
        recognizer = self._new_recognizer()
        if recognizer is None:
            return ComponentStatus(
                id=self.id,
                code=ComponentStatusCode.FAILED,
                installed=False,
                ready=False,
                message="Recognizer is not available",
                backend=backend,
                backend_ok=False,
            )
        try:
            if hasattr(recognizer, "apply_settings"):
                recognizer.apply_settings(self._settings(run_ctx))
        except Exception:
            pass
        try:
            installed = bool(recognizer.is_installed())
        except Exception:
            installed = False
        return _status_from_installed(
            component_id=self.id,
            installed=installed,
            backend=backend,
            ctx=run_ctx,
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        from handlers.asr_handler import SpeechRecognition

        run_ctx = _runtime_ctx(ctx)
        return SpeechRecognition.build_install_plan(
            self.item_id,
            pip_installer=run_ctx.get("pip_installer"),
            engine_settings=self._settings(run_ctx),
            callbacks=run_ctx.get("callbacks"),
            timeout_sec=float(run_ctx.get("timeout_sec", 3600.0) or 3600.0),
        )

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        return _noop_plan("ASR uninstall is not implemented yet.")

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


class RagInstallableComponent:
    category = ComponentCategory.RAG
    legacy_kind = "rag"

    def __init__(self, target: str, title: str) -> None:
        self.item_id = str(target)
        self.title = title
        self.id = make_component_id(self.category, self.item_id)

    def metadata(self) -> ComponentMetadata:
        status = self.status()
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=self.title,
            description="Local RAG runtime and model artifacts.",
            backend=status.backend,
            legacy_kind=self.legacy_kind,
            tags=("rag",),
        )

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        from managers.rag.install_spec import get_install_status

        run_ctx = _runtime_ctx(ctx)
        data = get_install_status(self.item_id, ctx=run_ctx)
        backend = coerce_backend(data.get("required_backend"))
        required = bool(data.get("required", True))
        ok = bool(data.get("ok", False)) or not required
        return _status_from_installed(
            component_id=self.id,
            installed=ok,
            backend=backend,
            ctx=run_ctx,
            details=dict(data or {}),
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        from managers.rag.install_spec import build_install_plan

        run_ctx = _runtime_ctx(ctx)
        return build_install_plan(
            self.item_id,
            pip_installer=run_ctx.get("pip_installer"),
            callbacks=run_ctx.get("callbacks"),
            timeout_sec=float(run_ctx.get("timeout_sec", 3600.0) or 3600.0),
        )

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        return _noop_plan("RAG uninstall is not implemented yet.")

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


class BeatInstallableComponent:
    category = ComponentCategory.BEATS
    legacy_kind = "beats"

    def __init__(self, backend_id: str, title: str) -> None:
        self.item_id = str(backend_id)
        self.title = title
        self.id = make_component_id(self.category, self.item_id)

    def _status_data(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from game_connections.services.beat_backend_spec import get_backend_status_snapshot

        return get_backend_status_snapshot(self.item_id, ctx=ctx)

    def _backend_kind(self, ctx: dict[str, Any]) -> BackendKind:
        from game_connections.services.beat_backend_spec import BACKEND_BEAT_THIS

        if self.item_id != BACKEND_BEAT_THIS:
            return BackendKind.NONE
        return get_backend_service().preferred_torch_kind(ctx)

    def metadata(self) -> ComponentMetadata:
        backend = self._backend_kind(_runtime_ctx())
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=self.title,
            description="Beat synchronization backend.",
            backend=backend,
            legacy_kind=self.legacy_kind,
            tags=("beat", self.item_id),
        )

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        run_ctx = _runtime_ctx(ctx)
        data = self._status_data(run_ctx)
        backends = data.get("backends") if isinstance(data.get("backends"), dict) else {}
        item = backends.get(self.item_id) if isinstance(backends.get(self.item_id), dict) else {}
        installed = bool(item.get("installed") or item.get("available"))
        backend = self._backend_kind(run_ctx)
        return _status_from_installed(
            component_id=self.id,
            installed=installed,
            backend=backend,
            ctx=run_ctx,
            details=dict(item or {}),
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        from game_connections.services.beat_install import build_beat_install_plan

        return build_beat_install_plan(self.item_id, ctx=_runtime_ctx(ctx))

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        from game_connections.services.beat_install import build_beat_uninstall_plan

        return build_beat_uninstall_plan(self.item_id, ctx=_runtime_ctx(ctx))

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        from game_connections.services.beat_install import build_beat_initialize_plan

        return build_beat_initialize_plan(self.item_id)
