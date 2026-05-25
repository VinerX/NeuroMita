from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


TORCH_VERSION = "2.7.1"
TORCH_PACKAGES = (f"torch=={TORCH_VERSION}", f"torchaudio=={TORCH_VERSION}")
CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu128"
BACKEND_NUMPY_SPEC = "numpy==1.26.0"
ONNX_PACKAGE = "onnxruntime"
ONNX_DIRECTML_PACKAGE = "onnxruntime-directml"


class BackendKind(str, Enum):
    NONE = "none"
    CPU = "cpu"
    CUDA = "cuda"
    ONNX = "onnx"


@dataclass(frozen=True)
class BackendRequirement:
    kind: BackendKind
    required: bool = True

    @classmethod
    def from_value(
        cls,
        value: "BackendRequirement | BackendKind | str | None",
        *,
        required: bool = True,
    ) -> "BackendRequirement":
        if isinstance(value, BackendRequirement):
            return value
        return cls(kind=normalize_backend_kind(value), required=required)

    @property
    def requirement_id(self) -> str:
        return f"backend_{self.kind.value}"


@dataclass(frozen=True)
class BackendStatus:
    requirement: BackendRequirement
    requested_kind: BackendKind
    resolved_kind: BackendKind
    ok: bool
    action: str
    reason: str
    variant: str
    provider: str
    cuda_available: bool
    onnx_providers: tuple[str, ...]
    install_packages: tuple[str, ...]
    uninstall_packages: tuple[str, ...]
    extra_args: tuple[str, ...]
    managed_dist_names: tuple[str, ...]
    target_dir: Optional[str]

    def as_requirement_detail(self) -> dict[str, Any]:
        extra = {
            "requested_kind": self.requested_kind.value,
            "resolved_kind": self.resolved_kind.value,
            "action": self.action,
            "reason": self.reason,
            "variant": self.variant,
            "provider": self.provider,
            "cuda_available": self.cuda_available,
            "onnx_providers": list(self.onnx_providers),
            "install_packages": list(self.install_packages),
            "uninstall_packages": list(self.uninstall_packages),
            "extra_args": list(self.extra_args),
            "managed_dist_names": list(self.managed_dist_names),
            "target_dir": self.target_dir,
        }
        return {
            "id": self.requirement.requirement_id,
            "kind": "backend",
            "required": self.requirement.required,
            "ok": self.ok,
            "extra": extra,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.requested_kind.value,
            "resolved_kind": self.resolved_kind.value,
            "ok": self.ok,
            "action": self.action,
            "reason": self.reason,
            "variant": self.variant,
            "provider": self.provider,
            "cuda_available": self.cuda_available,
            "onnx_providers": list(self.onnx_providers),
            "install_packages": list(self.install_packages),
            "uninstall_packages": list(self.uninstall_packages),
            "extra_args": list(self.extra_args),
            "managed_dist_names": list(self.managed_dist_names),
            "target_dir": self.target_dir,
        }


@dataclass(frozen=True)
class BackendInstallPlan:
    requirement: BackendRequirement
    status: BackendStatus
    install_packages: tuple[str, ...]
    uninstall_packages: tuple[str, ...]
    extra_args: tuple[str, ...]
    uv_overrides: tuple[str, ...]

    @property
    def action(self) -> str:
        return self.status.action

    @property
    def ok(self) -> bool:
        return self.status.ok

    @property
    def reason(self) -> str:
        return self.status.reason


def normalize_backend_kind(value: "BackendKind | str | None") -> BackendKind:
    if isinstance(value, BackendKind):
        return value
    raw = str(value or "").strip().lower()
    if raw in ("", "none"):
        return BackendKind.NONE
    for item in BackendKind:
        if item.value == raw or item.name.lower() == raw:
            return item
    raise ValueError(f"Unknown backend kind: {value}")


class BackendService:
    DIST_MODULE_ALIASES: dict[str, tuple[str, ...]] = {
        "torch": ("torch",),
        "torchaudio": ("torchaudio",),
        "numpy": ("numpy",),
        "onnxruntime": ("onnxruntime",),
        "onnxruntime-directml": ("onnxruntime",),
    }

    def numpy_spec(self) -> str:
        return BACKEND_NUMPY_SPEC

    def torch_packages(self) -> tuple[str, ...]:
        return TORCH_PACKAGES

    def torch_package_specs(self, *, kind: BackendKind) -> tuple[str, ...]:
        if kind not in (BackendKind.CPU, BackendKind.CUDA):
            return ()
        return TORCH_PACKAGES + (BACKEND_NUMPY_SPEC,)

    def onnx_package_specs(self, *, provider: str) -> tuple[str, ...]:
        runtime_pkg = ONNX_DIRECTML_PACKAGE if provider == "dml" else ONNX_PACKAGE
        return TORCH_PACKAGES + (runtime_pkg, BACKEND_NUMPY_SPEC)

    def preferred_torch_kind(self, ctx: dict[str, Any] | None = None) -> BackendKind:
        return BackendKind.CUDA if self._should_use_cuda(ctx) else BackendKind.CPU

    def build_requirement(
        self,
        value: "BackendRequirement | BackendKind | str | None",
        *,
        required: bool = True,
    ) -> BackendRequirement:
        return BackendRequirement.from_value(value, required=required)

    def get_status(
        self,
        requirement: "BackendRequirement | BackendKind | str | None",
        *,
        ctx: dict[str, Any] | None = None,
    ) -> BackendStatus:
        backend_req = self.build_requirement(requirement)
        ctx_data = self._build_ctx(ctx)
        target_dir = self._target_dir(ctx_data)

        if backend_req.kind == BackendKind.NONE:
            return BackendStatus(
                requirement=backend_req,
                requested_kind=BackendKind.NONE,
                resolved_kind=BackendKind.NONE,
                ok=True,
                action="skip",
                reason="Backend is not required.",
                variant="none",
                provider="none",
                cuda_available=False,
                onnx_providers=(),
                install_packages=(),
                uninstall_packages=(),
                extra_args=(),
                managed_dist_names=(),
                target_dir=target_dir,
            )

        if backend_req.kind in (BackendKind.CPU, BackendKind.CUDA):
            return self._get_torch_backend_status(backend_req, ctx_data, target_dir)

        if backend_req.kind == BackendKind.ONNX:
            return self._get_onnx_backend_status(backend_req, ctx_data, target_dir)

        raise ValueError(f"Unsupported backend kind: {backend_req.kind}")

    def build_install_plan(
        self,
        requirement: "BackendRequirement | BackendKind | str | None",
        *,
        ctx: dict[str, Any] | None = None,
        requested_specs: Iterable[str] | None = None,
    ) -> BackendInstallPlan:
        status = self.get_status(requirement, ctx=ctx)
        overrides = self.build_uv_overrides(status.requirement, requested_specs=requested_specs)
        return BackendInstallPlan(
            requirement=status.requirement,
            status=status,
            install_packages=status.install_packages,
            uninstall_packages=status.uninstall_packages,
            extra_args=status.extra_args,
            uv_overrides=overrides,
        )

    def build_uv_overrides(
        self,
        requirement: "BackendRequirement | BackendKind | str | None",
        *,
        requested_specs: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        backend_req = self.build_requirement(requirement)
        if backend_req.kind == BackendKind.NONE:
            return ()

        requested_names = {
            canonicalize_name(name)
            for name in self._requested_dist_names(requested_specs or ())
        }
        overrides: list[str] = []
        for dist_name in self._managed_dist_names_for_requirement(backend_req):
            canon = canonicalize_name(dist_name)
            if canon in requested_names:
                continue
            overrides.append(f"{dist_name}; sys_platform == 'never'")
        return tuple(self._dedupe(overrides))

    def install_backend(
        self,
        requirement: "BackendRequirement | BackendKind | str | None",
        *,
        pip_installer,
        ctx: dict[str, Any] | None = None,
        callbacks=None,
        reactive_only: bool = False,
    ) -> BackendStatus:
        status = self.get_status(requirement, ctx=ctx)
        if status.ok or status.action == "skip":
            return status

        if reactive_only and status.variant == "missing":
            return status

        description = status.reason or "Installing backend..."

        if status.action == "reinstall" and status.uninstall_packages:
            if callbacks is not None:
                try:
                    callbacks.status(description)
                except Exception:
                    pass
            ok = pip_installer.uninstall_packages(list(status.uninstall_packages), description=description)
            if not ok:
                return self.get_status(requirement, ctx=ctx)

        ok = pip_installer.install_package(
            list(status.install_packages),
            description=description,
            extra_args=list(status.extra_args) or None,
        )
        if not ok:
            return self.get_status(requirement, ctx=ctx)
        return self.get_status(requirement, ctx=ctx)

    def status_snapshot(self, *, ctx: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
        ctx_data = self._build_ctx(ctx)
        result: dict[str, dict[str, Any]] = {}
        for kind in (BackendKind.CPU, BackendKind.CUDA, BackendKind.ONNX):
            result[kind.value] = self.get_status(kind, ctx=ctx_data).as_dict()
        return result

    def get_installed_torch_variant(self, target_dir: Optional[str] = None) -> Optional[str]:
        def _variant_from_version(version: str, root: Optional[str] = None) -> str:
            if "+cu" not in str(version or ""):
                return "cpu"
            if root and not self.has_cuda_libs(root):
                return "cpu"
            return "cuda"

        if target_dir:
            root = Path(target_dir)
            if root.is_dir():
                matches = list(root.glob("torch-*.dist-info"))
                if matches:
                    matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
                    version = matches[0].name[len("torch-"):-len(".dist-info")]
                    return _variant_from_version(version, str(root))

        version = self._dist_version("torch", target_dir=None)
        if not version:
            return None
        return _variant_from_version(version)

    def has_cuda_libs(self, torch_target_dir: str | None) -> bool:
        if not torch_target_dir:
            return False

        root = Path(torch_target_dir)
        if not root.is_dir():
            return False

        patterns = (
            "torch/lib/cudart64*",
            "torch/lib/cublas64*",
            "torch/lib/libcudart*",
            "torch/lib/libcublas*",
            "torch/lib/cudnn*",
            "torch/lib/libcudnn*",
            "torch/lib/torch_cuda*",
            "torch/lib/c10_cuda*",
            "nvidia/*/bin/cudart64*",
            "nvidia/*/bin/cublas64*",
            "nvidia/*/bin/cudnn*",
            "nvidia/*/lib/libcudart*",
            "nvidia/*/lib/libcublas*",
            "nvidia/*/lib/libcudnn*",
        )
        for pattern in patterns:
            if any(root.glob(pattern)):
                return True
        return False

    def verify_torch_has_cuda(self) -> bool:
        try:
            import torch

            return getattr(torch.version, "cuda", None) is not None
        except Exception:
            return False

    def _get_torch_backend_status(
        self,
        requirement: BackendRequirement,
        ctx: dict[str, Any],
        target_dir: Optional[str],
    ) -> BackendStatus:
        installed_variant = self.get_installed_torch_variant(target_dir=target_dir) or "missing"
        if installed_variant == "cuda":
            resolved_kind = BackendKind.CUDA
        elif installed_variant == "cpu":
            resolved_kind = BackendKind.CPU
        else:
            resolved_kind = requirement.kind
        runtime_ok = installed_variant == "cuda" if requirement.kind == BackendKind.CUDA else installed_variant in ("cpu", "cuda")

        torch_ok = self._spec_satisfied(TORCH_PACKAGES[0], target_dir=target_dir)
        torchaudio_ok = self._spec_satisfied(TORCH_PACKAGES[1], target_dir=target_dir)
        numpy_ok = self._spec_satisfied(BACKEND_NUMPY_SPEC, target_dir=target_dir)

        managed_dist_names = self._managed_dist_names_for_requirement(requirement)
        supplemental_kind = BackendKind.CUDA if (requirement.kind == BackendKind.CPU and installed_variant == "cuda") else requirement.kind
        supplemental_specs = self.torch_package_specs(kind=supplemental_kind)

        missing_specs: list[str] = []
        if not torch_ok:
            missing_specs.append(TORCH_PACKAGES[0])
        if not torchaudio_ok:
            missing_specs.append(TORCH_PACKAGES[1])
        if not numpy_ok:
            missing_specs.append(BACKEND_NUMPY_SPEC)

        action = "skip"
        reason = "PyTorch backend is ready."
        install_packages: tuple[str, ...] = ()
        uninstall_packages: tuple[str, ...] = ()
        extra_args: tuple[str, ...] = ()

        if not runtime_ok:
            if requirement.kind == BackendKind.CUDA and installed_variant == "cpu":
                action = "reinstall"
                reason = "Reinstalling PyTorch backend: CPU -> CUDA (cu128)..."
                install_packages = supplemental_specs
                uninstall_packages = ("torch", "torchaudio")
                extra_args = ("--reinstall", "--index-url", CUDA_INDEX_URL)
            else:
                action = "install"
                reason = "Installing PyTorch backend with CUDA (cu128)..." if requirement.kind == BackendKind.CUDA else "Installing PyTorch CPU backend..."
                install_packages = supplemental_specs
                extra_args = ("--index-url", CUDA_INDEX_URL) if requirement.kind == BackendKind.CUDA else ()
        elif missing_specs:
            action = "install"
            reason = "Installing missing backend-managed runtime packages..."
            install_packages = tuple(missing_specs)
            extra_args = ("--index-url", CUDA_INDEX_URL) if supplemental_kind == BackendKind.CUDA and any(
                spec.startswith("torch") or spec.startswith("torchaudio")
                for spec in missing_specs
            ) else ()

        ok = runtime_ok and not missing_specs
        if ok:
            reason = "PyTorch backend is ready."

        return BackendStatus(
            requirement=requirement,
            requested_kind=requirement.kind,
            resolved_kind=resolved_kind,
            ok=ok,
            action=action,
            reason=reason,
            variant=f"torch_{installed_variant}" if installed_variant != "missing" else "missing",
            provider="cuda" if installed_variant == "cuda" else ("cpu" if installed_variant == "cpu" else "missing"),
            cuda_available=self._cuda_available(ctx),
            onnx_providers=(),
            install_packages=install_packages,
            uninstall_packages=uninstall_packages,
            extra_args=extra_args,
            managed_dist_names=managed_dist_names,
            target_dir=target_dir,
        )

    def _get_onnx_backend_status(
        self,
        requirement: BackendRequirement,
        ctx: dict[str, Any],
        target_dir: Optional[str],
    ) -> BackendStatus:
        preferred_provider = self._preferred_onnx_provider(ctx)
        installed_variant = self._onnx_variant(target_dir)
        provider = "dml" if installed_variant == "onnx_dml" else ("cpu" if installed_variant == "onnx_cpu" else "missing")
        runtime_ok = installed_variant != "missing" and (preferred_provider != "dml" or installed_variant == "onnx_dml")

        torch_ok = self._spec_satisfied(TORCH_PACKAGES[0], target_dir=target_dir)
        torchaudio_ok = self._spec_satisfied(TORCH_PACKAGES[1], target_dir=target_dir)
        numpy_ok = self._spec_satisfied(BACKEND_NUMPY_SPEC, target_dir=target_dir)

        managed_dist_names = self._managed_dist_names_for_requirement(requirement)
        install_specs = self.onnx_package_specs(provider=preferred_provider)

        missing_specs: list[str] = []
        if not torch_ok:
            missing_specs.append(TORCH_PACKAGES[0])
        if not torchaudio_ok:
            missing_specs.append(TORCH_PACKAGES[1])
        if not numpy_ok:
            missing_specs.append(BACKEND_NUMPY_SPEC)

        runtime_pkg = ONNX_DIRECTML_PACKAGE if preferred_provider == "dml" else ONNX_PACKAGE
        if not runtime_ok and runtime_pkg not in missing_specs:
            missing_specs.insert(0, runtime_pkg)

        action = "skip"
        reason = "ONNX backend is ready."
        install_packages: tuple[str, ...] = ()
        uninstall_packages: tuple[str, ...] = ()

        if not runtime_ok and installed_variant != "missing":
            action = "reinstall"
            reason = "Reinstalling ONNX backend to switch provider..."
            install_packages = tuple(missing_specs or install_specs)
            uninstall_packages = (ONNX_PACKAGE, ONNX_DIRECTML_PACKAGE)
        elif missing_specs:
            action = "install"
            if runtime_ok:
                reason = "Installing missing backend-managed runtime packages..."
                install_packages = tuple(missing_specs)
            else:
                reason = "Installing ONNX backend..."
                install_packages = tuple(missing_specs or install_specs)

        ok = runtime_ok and torch_ok and torchaudio_ok and numpy_ok
        if ok:
            reason = "ONNX backend is ready."

        return BackendStatus(
            requirement=requirement,
            requested_kind=requirement.kind,
            resolved_kind=BackendKind.ONNX,
            ok=ok,
            action=action,
            reason=reason,
            variant=installed_variant,
            provider=provider,
            cuda_available=self._cuda_available(ctx),
            onnx_providers=self._onnx_providers_for_variant(installed_variant),
            install_packages=install_packages,
            uninstall_packages=uninstall_packages,
            extra_args=(),
            managed_dist_names=managed_dist_names,
            target_dir=target_dir,
        )

    def _onnx_variant(self, target_dir: Optional[str]) -> str:
        if self._dist_version(ONNX_DIRECTML_PACKAGE, target_dir):
            return "onnx_dml"
        if self._dist_version(ONNX_PACKAGE, target_dir):
            return "onnx_cpu"
        if self._module_exists("onnxruntime", target_dir):
            return "onnx_cpu"
        return "missing"

    def _onnx_providers_for_variant(self, variant: str) -> tuple[str, ...]:
        if variant == "onnx_dml":
            return ("DmlExecutionProvider", "CPUExecutionProvider")
        if variant == "onnx_cpu":
            return ("CPUExecutionProvider",)
        return ()

    def _preferred_onnx_provider(self, ctx: dict[str, Any]) -> str:
        device = str(ctx.get("device") or "").strip().lower()
        if device == "dml":
            return "dml"
        if device == "cpu":
            return "cpu"

        gpu_vendor = str(ctx.get("gpu_vendor") or "CPU").upper()
        if gpu_vendor != "NVIDIA":
            return "dml"
        return "cpu"

    def _should_use_cuda(self, ctx: dict[str, Any] | None) -> bool:
        ctx_data = self._build_ctx(ctx)
        gpu_vendor = str(ctx_data.get("gpu_vendor") or "CPU").upper()
        if gpu_vendor != "NVIDIA":
            return False
        device = str(ctx_data.get("device") or "").strip().lower()
        return device not in ("cpu", "dml")

    def _build_ctx(self, ctx: dict[str, Any] | None) -> dict[str, Any]:
        data = dict(ctx or {})
        if not data.get("gpu_vendor"):
            data["gpu_vendor"] = self._detect_gpu_vendor()
        return data

    def _target_dir(self, ctx: dict[str, Any]) -> Optional[str]:
        value = str(ctx.get("libs_dir") or os.environ.get("NEUROMITA_LIB_DIR") or "").strip()
        return value or None

    def _detect_gpu_vendor(self) -> str:
        try:
            from utils.gpu_utils import check_gpu_provider

            return str(check_gpu_provider() or "CPU")
        except Exception:
            return "CPU"

    def _cuda_available(self, ctx: dict[str, Any]) -> bool:
        return str(ctx.get("gpu_vendor") or "CPU").upper() == "NVIDIA"

    def _managed_dist_names_for_requirement(self, requirement: BackendRequirement) -> tuple[str, ...]:
        if requirement.kind in (BackendKind.CPU, BackendKind.CUDA):
            return ("torch", "torchaudio", "numpy")
        if requirement.kind == BackendKind.ONNX:
            return ("torch", "torchaudio", "numpy", ONNX_PACKAGE, ONNX_DIRECTML_PACKAGE)
        return ()

    def _requested_dist_names(self, specs: Iterable[str]) -> tuple[str, ...]:
        names: list[str] = []
        for spec in specs or ():
            value = str(spec or "").strip()
            if not value:
                continue
            try:
                req = Requirement(value)
                names.append(req.name)
            except Exception:
                names.append(value.split(";", 1)[0].strip())
        return tuple(names)

    def _dedupe(self, values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in values:
            value = str(item or "").strip()
            key = value.lower()
            if not value or key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    def _spec_satisfied(self, spec: str, *, target_dir: Optional[str]) -> bool:
        try:
            req = Requirement(spec)
        except Exception:
            req = None

        dist_name = req.name if req is not None else str(spec or "").split(";", 1)[0].strip()
        version = self._dist_version(dist_name, target_dir)
        if version is None:
            return False

        if req is not None and req.specifier:
            try:
                if not bool(req.specifier.contains(version, prereleases=True)):
                    return False
            except Exception:
                return False

        return self._module_exists(dist_name, target_dir)

    def _module_exists(self, dist_name: str, target_dir: Optional[str]) -> bool:
        base = canonicalize_name(dist_name)
        candidates = self.DIST_MODULE_ALIASES.get(base, (base.replace("-", "_"),))

        if target_dir and os.path.isdir(target_dir):
            for module_name in candidates:
                first = str(module_name or "").split(".", 1)[0]
                if not first:
                    continue
                if os.path.isdir(os.path.join(target_dir, first)):
                    return True
                if os.path.isfile(os.path.join(target_dir, first + ".py")):
                    return True
            return False

        for module_name in candidates:
            try:
                if importlib.util.find_spec(module_name) is not None:
                    return True
            except Exception:
                continue
        return False

    def _dist_version(self, dist_name: str, target_dir: Optional[str]) -> Optional[str]:
        if target_dir and os.path.isdir(target_dir):
            return self._dist_version_in_target(dist_name, target_dir)

        try:
            import importlib.metadata as importlib_metadata

            return str(importlib_metadata.version(dist_name))
        except Exception:
            return None

    def _dist_version_in_target(self, dist_name: str, target_dir: str) -> Optional[str]:
        if not dist_name or not os.path.isdir(target_dir):
            return None

        wanted = canonicalize_name(dist_name)
        for item in os.listdir(target_dir):
            if not item.endswith(".dist-info"):
                continue

            metadata_path = os.path.join(target_dir, item, "METADATA")
            name: Optional[str] = None
            version: Optional[str] = None

            if os.path.isfile(metadata_path):
                try:
                    with open(metadata_path, "r", encoding="utf-8", errors="ignore") as fh:
                        for line in fh:
                            lower = line.lower()
                            if lower.startswith("name:"):
                                name = line.split(":", 1)[1].strip()
                            elif lower.startswith("version:"):
                                version = line.split(":", 1)[1].strip()
                            if name and version:
                                break
                except Exception:
                    name = None
                    version = None

            if name is None:
                name = item.rsplit(".dist-info", 1)[0].split("-", 1)[0]
            if canonicalize_name(name) != wanted:
                continue
            if version:
                return version

            parts = item.rsplit(".dist-info", 1)[0].split("-")
            if len(parts) >= 2:
                return parts[-1]
            return ""
        return None


_BACKEND_SERVICE: BackendService | None = None


def get_backend_service() -> BackendService:
    global _BACKEND_SERVICE
    if _BACKEND_SERVICE is None:
        _BACKEND_SERVICE = BackendService()
    return _BACKEND_SERVICE
