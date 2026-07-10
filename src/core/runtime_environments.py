from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from core.backends import (
    BackendKind,
    ONNX_DIRECTML_SPEC,
    ONNX_SPEC,
    TORCH_VERSION,
    get_backend_service,
)
from core.install_requirements import is_pip_spec_satisfied


_LAYOUT_VERSION = 1
_CORE_DISTRIBUTIONS = frozenset(
    canonicalize_name(name)
    for name in (
        "torch",
        "torchaudio",
        "numpy",
        "onnxruntime",
        "onnxruntime-directml",
    )
)


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
    normalized = normalized.strip("-._").lower()
    return normalized or "environment"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    os.replace(temp, path)


def _hash_payload(payload: Any, length: int = 16) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _python_tag() -> str:
    return f"py{sys.version_info.major}{sys.version_info.minor}"


def _platform_tag() -> str:
    machine = platform.machine().lower() or "unknown"
    if os.name == "nt":
        os_tag = "win"
    elif sys.platform.startswith("linux"):
        os_tag = "linux"
    elif sys.platform == "darwin":
        os_tag = "macos"
    else:
        os_tag = _safe_id(sys.platform)
    return f"{os_tag}-{machine}"


def _requirement_name(spec: str) -> str:
    try:
        return canonicalize_name(Requirement(str(spec)).name)
    except Exception:
        return canonicalize_name(str(spec).split(";", 1)[0].strip())


def _requirement_version(spec: str) -> str:
    try:
        requirement = Requirement(str(spec))
    except Exception:
        return "unversioned"
    for item in requirement.specifier:
        if item.operator == "==":
            return _safe_id(item.version)
    return "unversioned"


class _FileLock:
    def __init__(self, path: Path, *, timeout: float = 120.0, stale_after: float = 1800.0) -> None:
        self.path = path
        self.timeout = max(0.1, float(timeout))
        self.stale_after = max(self.timeout, float(stale_after))
        self._fd: int | None = None

    def __enter__(self) -> "_FileLock":
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._fd = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                payload = f"pid={os.getpid()} time={time.time()}\n".encode("ascii", errors="ignore")
                os.write(self._fd, payload)
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                    if age > self.stale_after:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for environment lock: {self.path}")
                time.sleep(0.1)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _scan_distributions(site_packages: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not site_packages.is_dir():
        return result
    try:
        from importlib import metadata as importlib_metadata

        for distribution in importlib_metadata.distributions(path=[str(site_packages)]):
            name = str(distribution.metadata.get("Name") or "").strip()
            version = str(distribution.version or "").strip()
            if name and version:
                result[canonicalize_name(name)] = version
    except Exception:
        pass
    return result


@dataclass(frozen=True, slots=True)
class CoreLayerSpec:
    group: str
    packages: tuple[str, ...]
    capabilities: tuple[str, ...]
    extra_args: tuple[str, ...] = ()

    @property
    def owned_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(_requirement_name(spec) for spec in self.packages))

    @property
    def layer_id(self) -> str:
        payload = {
            "group": self.group,
            "packages": list(self.packages),
            "capabilities": list(self.capabilities),
            "python": _python_tag(),
            "platform": _platform_tag(),
        }
        primary_version = _requirement_version(self.packages[0]) if self.packages else "empty"
        return (
            f"{_safe_id(self.group)}-{primary_version}-"
            f"{_python_tag()}-{_platform_tag()}-{_hash_payload(payload, length=10)}"
        )


@dataclass(frozen=True, slots=True)
class CoreLayer:
    layer_id: str
    root: Path
    site_packages: Path
    packages: dict[str, str]
    owned_packages: dict[str, str]
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnvironmentRecord:
    logical_id: str
    revision_id: str
    root: Path
    site_packages: Path
    core_layer_ids: tuple[str, ...]
    category: str
    item_id: str
    packages: dict[str, str]


@dataclass(slots=True)
class EnvironmentTransaction:
    manager: "RuntimeEnvironmentManager"
    logical_id: str
    category: str
    item_id: str
    requested_specs: tuple[str, ...]
    required_backend: BackendKind
    backend_context: dict[str, Any]
    transaction_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    staging_root: Path | None = None
    site_packages: Path | None = None
    core_layers: list[CoreLayer] = field(default_factory=list)
    committed: bool = False
    aborted: bool = False

    def __post_init__(self) -> None:
        self.staging_root = self.manager.staging_root / f"env-{_safe_id(self.logical_id)}-{self.transaction_id}"
        self.site_packages = self.staging_root / "site-packages"
        self.site_packages.mkdir(parents=True, exist_ok=False)

    @property
    def validation_paths(self) -> tuple[str, ...]:
        assert self.site_packages is not None
        return (str(self.site_packages), *(str(layer.site_packages) for layer in self.core_layers))

    @property
    def core_package_names(self) -> tuple[str, ...]:
        names: list[str] = []
        seen: set[str] = set()
        for layer in self.core_layers:
            provided_names = set(layer.owned_packages)
            if "onnx.dml" in layer.capabilities:
                # DirectML ships the same import runtime as the CPU wheel. A
                # dependent package may declare both names, but the overlay
                # must never materialize a second onnxruntime beside DML.
                provided_names.update({"onnxruntime", "onnxruntime-directml"})
            for name in provided_names:
                normalized = canonicalize_name(name)
                if normalized in seen:
                    continue
                seen.add(normalized)
                names.append(normalized)
        return tuple(names)

    @property
    def core_overrides(self) -> tuple[str, ...]:
        specs: list[str] = []
        seen: set[str] = set()
        for layer in self.core_layers:
            owned = dict(layer.owned_packages)
            if "onnx.dml" in layer.capabilities:
                directml_version = owned.get("onnxruntime-directml")
                if directml_version:
                    owned.setdefault("onnxruntime", directml_version)
            for name, version in owned.items():
                normalized = canonicalize_name(name)
                if normalized in seen:
                    continue
                seen.add(normalized)
                specs.append(f"{normalized}=={version}")
        return tuple(specs)

    def ensure_core_layers(
        self,
        installer_factory: Callable[[str], Any],
        *,
        log: Callable[[str], None],
    ) -> bool:
        specs = self.manager.core_layer_specs(self.required_backend, self.backend_context)
        layers: list[CoreLayer] = []
        for spec in specs:
            layer = self.manager.ensure_core_layer(spec, installer_factory=installer_factory, log=log)
            if layer is None:
                return False
            layers.append(layer)
        self.core_layers = layers
        return True

    def strip_core_packages(self) -> None:
        assert self.site_packages is not None
        provided = set()
        for layer in self.core_layers:
            provided.update(layer.owned_packages.keys())
        self.manager.remove_distributions(self.site_packages, provided)

    def commit(self, meta: dict[str, Any] | None = None) -> EnvironmentRecord:
        if self.committed:
            record = self.manager.active(self.logical_id)
            if record is None:
                raise RuntimeError(f"Environment '{self.logical_id}' was committed but is not registered")
            return record
        if self.aborted:
            raise RuntimeError("Cannot commit an aborted environment transaction")
        assert self.staging_root is not None
        assert self.site_packages is not None

        packages = _scan_distributions(self.site_packages)
        revision_payload = {
            "logical_id": self.logical_id,
            "requested_specs": list(self.requested_specs),
            "core_layers": [layer.layer_id for layer in self.core_layers],
            "packages": packages,
            "python": _python_tag(),
            "platform": _platform_tag(),
        }
        revision_id = _hash_payload(revision_payload, length=20)
        final_root = self.manager.environment_root / _safe_id(self.logical_id) / revision_id
        final_site = final_root / "site-packages"

        manifest = {
            "layout_version": _LAYOUT_VERSION,
            "state": "ready",
            "logical_id": self.logical_id,
            "revision_id": revision_id,
            "category": self.category,
            "item_id": self.item_id,
            "python": _python_tag(),
            "platform": _platform_tag(),
            "requested_specs": list(self.requested_specs),
            "core_layer_ids": [layer.layer_id for layer in self.core_layers],
            "packages": packages,
            "meta": dict(meta or {}),
        }
        _atomic_json(self.staging_root / "manifest.json", manifest)
        final_root.parent.mkdir(parents=True, exist_ok=True)

        if final_root.exists():
            shutil.rmtree(self.staging_root, ignore_errors=True)
        else:
            os.replace(self.staging_root, final_root)

        record = EnvironmentRecord(
            logical_id=self.logical_id,
            revision_id=revision_id,
            root=final_root,
            site_packages=final_site,
            core_layer_ids=tuple(layer.layer_id for layer in self.core_layers),
            category=self.category,
            item_id=self.item_id,
            packages=packages,
        )
        self.manager.activate(record)
        self.committed = True
        return record

    def abort(self) -> None:
        if self.committed or self.aborted:
            return
        self.aborted = True
        if self.staging_root is not None:
            shutil.rmtree(self.staging_root, ignore_errors=True)


class RuntimeEnvironmentManager:
    """Transactional owner of shared core layers and feature environments.

    Core layers are immutable and version-addressed. A CUDA torch layer also
    advertises the CPU capability, so a machine never needs a second CPU torch
    copy merely for CPU-only operations. Feature packages live in immutable
    overlays under ``Lib/environment`` and refer to one or more core layers.
    """

    def __init__(self, lib_root: str | os.PathLike[str] | None = None) -> None:
        root = Path(lib_root or os.environ.get("NEUROMITA_LIB_DIR") or "Lib").resolve()
        self.lib_root = root
        self.core_root = Path(os.environ.get("NEUROMITA_CORE_DIR") or (root / "core")).resolve()
        self.environment_root = Path(
            os.environ.get("NEUROMITA_ENVIRONMENT_DIR") or (root / "environment")
        ).resolve()
        self.staging_root = root / ".staging"
        self.lock_root = root / ".locks"
        self.registry_path = self.environment_root / "registry.json"
        self._lock = threading.RLock()
        for path in (self.core_root, self.environment_root, self.staging_root, self.lock_root):
            path.mkdir(parents=True, exist_ok=True)

    def file_lock(self, name: str, *, timeout: float = 120.0) -> _FileLock:
        return _FileLock(self.lock_root / f"{_safe_id(name)}.lock", timeout=timeout)

    @staticmethod
    def logical_id_from_meta(meta: dict[str, Any] | None) -> tuple[str, str, str]:
        data = dict(meta or {})
        category = str(data.get("category") or data.get("kind") or "component").strip().lower()
        item_id = str(data.get("item_id") or data.get("component_id") or "component").strip()
        logical_id = str(data.get("environment_id") or f"{category}:{item_id}")
        return _safe_id(logical_id), category, item_id

    @staticmethod
    def should_manage(meta: dict[str, Any] | None) -> bool:
        data = dict(meta or {})
        category = str(data.get("category") or data.get("kind") or "").strip().lower()
        return category in {"backend", "tts", "voice", "asr", "rag", "embedding", "beats"}

    def begin(
        self,
        *,
        meta: dict[str, Any] | None,
        requested_specs: Iterable[str],
        required_backend: BackendKind | str | None,
        backend_context: dict[str, Any] | None,
    ) -> EnvironmentTransaction:
        logical_id, category, item_id = self.logical_id_from_meta(meta)
        backend = get_backend_service().build_requirement(required_backend).kind
        return EnvironmentTransaction(
            manager=self,
            logical_id=logical_id,
            category=category,
            item_id=item_id,
            requested_specs=tuple(str(spec) for spec in requested_specs if str(spec).strip()),
            required_backend=backend,
            backend_context=dict(backend_context or {}),
        )

    def core_layer_specs(
        self,
        required_backend: BackendKind,
        ctx: dict[str, Any] | None = None,
    ) -> tuple[CoreLayerSpec, ...]:
        service = get_backend_service()
        context = dict(ctx or {})
        layers: list[CoreLayerSpec] = []

        if required_backend in (BackendKind.CPU, BackendKind.CUDA, BackendKind.ONNX):
            torch_kind = (
                BackendKind.CUDA
                if required_backend == BackendKind.CUDA
                else service.preferred_torch_kind(context)
            )
            cpu_capability = f"torch.cpu@{TORCH_VERSION}"
            cuda_capability = f"torch.cuda@{TORCH_VERSION}+cu128"
            if required_backend == BackendKind.CPU:
                reusable = self.find_core_layer(required_capabilities=(cpu_capability,))
                if reusable is not None:
                    return (
                        CoreLayerSpec(
                            group="torch-reuse",
                            packages=tuple(
                                f"{name}=={version}"
                                for name, version in reusable.owned_packages.items()
                            ),
                            capabilities=reusable.capabilities,
                        ),
                    )
            torch_specs = service.torch_package_specs(kind=torch_kind)
            torch_caps = ("torch.cpu", cpu_capability)
            if torch_kind == BackendKind.CUDA:
                torch_caps += ("torch.cuda", cuda_capability)
            torch_args = (
                "--extra-index-url",
                "https://download.pytorch.org/whl/cu128",
            ) if torch_kind == BackendKind.CUDA else ()
            variant = "cu128" if torch_kind == BackendKind.CUDA else "cpu"
            layers.append(
                CoreLayerSpec(
                    group=f"torch-{variant}",
                    packages=tuple(torch_specs),
                    capabilities=torch_caps,
                    extra_args=torch_args,
                )
            )

        if required_backend == BackendKind.ONNX:
            gpu_vendor = str(context.get("gpu_vendor") or "CPU").upper()
            device = str(context.get("device") or "").strip().lower()
            provider = "dml" if device == "dml" or (device != "cpu" and gpu_vendor != "NVIDIA") else "cpu"
            runtime_spec = ONNX_DIRECTML_SPEC if provider == "dml" else ONNX_SPEC
            capabilities = ("onnx.cpu",)
            if provider == "dml":
                capabilities += ("onnx.dml",)
            layers.append(
                CoreLayerSpec(
                    group=f"onnx-{provider}",
                    packages=(runtime_spec,),
                    capabilities=capabilities,
                )
            )

        return tuple(layers)

    def find_core_layer(self, *, required_capabilities: Sequence[str]) -> CoreLayer | None:
        wanted = set(required_capabilities)
        if not wanted:
            return None
        candidates: list[CoreLayer] = []
        for manifest_path in self.core_root.glob("*/manifest.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if data.get("state") != "ready":
                    continue
                capabilities = tuple(str(item) for item in data.get("capabilities") or ())
                if not wanted.issubset(set(capabilities)):
                    continue
                root = manifest_path.parent
                candidates.append(
                    CoreLayer(
                        layer_id=str(data["layer_id"]),
                        root=root,
                        site_packages=root / "site-packages",
                        packages={str(k): str(v) for k, v in (data.get("packages") or {}).items()},
                        owned_packages={
                            str(k): str(v)
                            for k, v in (data.get("owned_packages") or {}).items()
                        },
                        capabilities=capabilities,
                    )
                )
            except Exception:
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda layer: layer.root.stat().st_mtime, reverse=True)
        return candidates[0]

    def get_core_layer(self, layer_id: str) -> CoreLayer | None:
        root = self.core_root / str(layer_id)
        manifest_path = root / "manifest.json"
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if data.get("state") != "ready":
                return None
            return CoreLayer(
                layer_id=str(data["layer_id"]),
                root=root,
                site_packages=root / "site-packages",
                packages={str(k): str(v) for k, v in (data.get("packages") or {}).items()},
                owned_packages={
                    str(k): str(v)
                    for k, v in (data.get("owned_packages") or {}).items()
                },
                capabilities=tuple(str(item) for item in data.get("capabilities") or ()),
            )
        except Exception:
            return None

    def ensure_core_layer(
        self,
        spec: CoreLayerSpec,
        *,
        installer_factory: Callable[[str], Any],
        log: Callable[[str], None],
    ) -> CoreLayer | None:
        if spec.group == "torch-reuse":
            return self.find_core_layer(required_capabilities=spec.capabilities)

        final_root = self.core_root / spec.layer_id
        existing = self.get_core_layer(spec.layer_id)
        if existing is not None:
            return existing

        with self._lock, self.file_lock(f"core-{spec.layer_id}"):
            existing = self.get_core_layer(spec.layer_id)
            if existing is not None:
                return existing

            staging_root = self.staging_root / f"core-{spec.layer_id}-{uuid.uuid4().hex}"
            site_packages = staging_root / "site-packages"
            site_packages.mkdir(parents=True, exist_ok=False)
            installer = installer_factory(str(site_packages))
            log(f"Preparing shared core layer: {spec.layer_id}")
            ok = installer.install_package_with_overrides(
                list(spec.packages),
                description=f"Installing shared core layer {spec.group}...",
                extra_args=list(spec.extra_args) or None,
                uv_overrides=list(spec.packages),
            )
            if not ok:
                shutil.rmtree(staging_root, ignore_errors=True)
                return None

            missing = [
                package
                for package in spec.packages
                if not is_pip_spec_satisfied(package, ctx={"target_dir": str(site_packages), "strict_target": True})
            ]
            if missing:
                log(f"Core layer validation failed; missing: {', '.join(missing)}")
                shutil.rmtree(staging_root, ignore_errors=True)
                return None

            packages = _scan_distributions(site_packages)
            owned_packages = {
                name: packages[name]
                for name in spec.owned_names
                if name in packages
            }
            manifest = {
                "layout_version": _LAYOUT_VERSION,
                "state": "ready",
                "layer_id": spec.layer_id,
                "group": spec.group,
                "python": _python_tag(),
                "platform": _platform_tag(),
                "requested_specs": list(spec.packages),
                "capabilities": list(spec.capabilities),
                "packages": packages,
                "owned_packages": owned_packages,
            }
            _atomic_json(staging_root / "manifest.json", manifest)
            final_root.parent.mkdir(parents=True, exist_ok=True)
            if final_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            else:
                os.replace(staging_root, final_root)
            return self.get_core_layer(spec.layer_id)

    def _load_registry(self) -> dict[str, Any]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {"layout_version": _LAYOUT_VERSION, "environments": {}}

    def activate(self, record: EnvironmentRecord) -> None:
        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            environments = data.setdefault("environments", {})
            environments[record.logical_id] = {
                "revision_id": record.revision_id,
                "category": record.category,
                "item_id": record.item_id,
                "core_layer_ids": list(record.core_layer_ids),
            }
            _atomic_json(self.registry_path, data)

    def deactivate(self, logical_id: str, *, delete: bool = True) -> bool:
        normalized = _safe_id(logical_id)
        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            entry = (data.get("environments") or {}).pop(normalized, None)
            if entry is None:
                return False
            _atomic_json(self.registry_path, data)
        if delete:
            root = self.environment_root / normalized / str(entry.get("revision_id") or "")
            shutil.rmtree(root, ignore_errors=True)
            parent = root.parent
            try:
                parent.rmdir()
            except OSError:
                pass
        return True

    def active(self, logical_id: str) -> EnvironmentRecord | None:
        normalized = _safe_id(logical_id)
        data = self._load_registry()
        entry = (data.get("environments") or {}).get(normalized)
        if not isinstance(entry, dict):
            return None
        revision_id = str(entry.get("revision_id") or "")
        root = self.environment_root / normalized / revision_id
        manifest_path = root / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("state") != "ready":
                return None
            return EnvironmentRecord(
                logical_id=normalized,
                revision_id=revision_id,
                root=root,
                site_packages=root / "site-packages",
                core_layer_ids=tuple(str(item) for item in manifest.get("core_layer_ids") or ()),
                category=str(manifest.get("category") or entry.get("category") or ""),
                item_id=str(manifest.get("item_id") or entry.get("item_id") or ""),
                packages={str(k): str(v) for k, v in (manifest.get("packages") or {}).items()},
            )
        except Exception:
            return None

    def active_for(self, *, category: str, item_id: str) -> EnvironmentRecord | None:
        data = self._load_registry()
        for logical_id, entry in (data.get("environments") or {}).items():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("category") or "").lower() != str(category or "").lower():
                continue
            if str(entry.get("item_id") or "") != str(item_id or ""):
                continue
            return self.active(logical_id)
        return None

    def core_paths_for_backend(
        self,
        backend: BackendKind | str,
        ctx: dict[str, Any] | None = None,
    ) -> tuple[str, ...]:
        requirement = get_backend_service().build_requirement(backend).kind
        if requirement == BackendKind.NONE:
            return ()
        layers: list[CoreLayer] = []
        for spec in self.core_layer_specs(requirement, ctx):
            if spec.group == "torch-reuse":
                layer = self.find_core_layer(required_capabilities=spec.capabilities)
            else:
                layer = self.get_core_layer(spec.layer_id)
            if layer is None:
                return ()
            layers.append(layer)
        return tuple(str(layer.site_packages) for layer in layers)

    def component_context(
        self,
        *,
        category: str,
        item_id: str,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = dict(ctx or {})
        normalized_category = str(category or "").strip().lower()
        normalized_item = str(item_id or "").strip()
        record = self.active_for(category=normalized_category, item_id=normalized_item)
        if record is not None:
            paths = self.runtime_paths(record)
            result.update(
                {
                    "target_dir": str(record.site_packages),
                    "libs_dir": str(record.site_packages),
                    "lib_dir": str(record.site_packages),
                    "python_paths": list(paths),
                    "strict_target": True,
                    "environment_id": record.logical_id,
                    "environment_revision": record.revision_id,
                }
            )
            return result

        if normalized_category == "backend":
            try:
                paths = self.core_paths_for_backend(BackendKind(normalized_item), result)
            except Exception:
                paths = ()
            if paths:
                result.update(
                    {
                        "target_dir": paths[0],
                        "libs_dir": paths[0],
                        "lib_dir": paths[0],
                        "python_paths": list(paths),
                        "strict_target": True,
                    }
                )
                return result

        if self.should_manage({"category": normalized_category}):
            probe = self.staging_root / "status-empty" / _safe_id(
                f"{normalized_category}:{normalized_item}"
            )
            probe.mkdir(parents=True, exist_ok=True)
            result.update(
                {
                    "target_dir": str(probe),
                    "libs_dir": str(probe),
                    "lib_dir": str(probe),
                    "python_paths": [str(probe)],
                    "strict_target": True,
                }
            )
        return result

    def runtime_paths(self, record: EnvironmentRecord | None) -> tuple[str, ...]:
        if record is None:
            return ()
        paths = [str(record.site_packages)]
        for layer_id in record.core_layer_ids:
            layer = self.get_core_layer(layer_id)
            if layer is not None:
                paths.append(str(layer.site_packages))
        return tuple(paths)

    def remove_distributions(self, site_packages: Path, names: Iterable[str]) -> None:
        wanted = {canonicalize_name(name) for name in names}
        if not wanted or not site_packages.is_dir():
            return
        for dist_info in list(site_packages.glob("*.dist-info")):
            name = ""
            metadata = dist_info / "METADATA"
            try:
                for line in metadata.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.lower().startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                        break
            except Exception:
                pass
            if not name:
                name = dist_info.name.rsplit(".dist-info", 1)[0].split("-", 1)[0]
            if canonicalize_name(name) not in wanted:
                continue
            self._remove_distribution_files(site_packages, dist_info)

    @staticmethod
    def _remove_distribution_files(site_packages: Path, dist_info: Path) -> None:
        record = dist_info / "RECORD"
        paths: list[Path] = []
        if record.is_file():
            try:
                with record.open("r", encoding="utf-8", errors="ignore", newline="") as source:
                    for row in csv.reader(source):
                        if not row:
                            continue
                        candidate = (site_packages / row[0]).resolve()
                        try:
                            candidate.relative_to(site_packages.resolve())
                        except ValueError:
                            continue
                        paths.append(candidate)
            except Exception:
                paths = []
        if not paths:
            top_level = dist_info / "top_level.txt"
            try:
                for name in top_level.read_text(encoding="utf-8", errors="ignore").splitlines():
                    value = name.strip()
                    if value:
                        paths.extend((site_packages / value, site_packages / f"{value}.py"))
            except Exception:
                pass
        paths.append(dist_info)
        for path in sorted(set(paths), key=lambda item: len(item.parts), reverse=True):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()
            except OSError:
                pass


_default_manager: RuntimeEnvironmentManager | None = None
_default_lock = threading.Lock()


def runtime_environments() -> RuntimeEnvironmentManager:
    global _default_manager
    root = Path(os.environ.get("NEUROMITA_LIB_DIR") or "Lib").resolve()
    with _default_lock:
        if _default_manager is None or _default_manager.lib_root != root:
            _default_manager = RuntimeEnvironmentManager(root)
        return _default_manager
