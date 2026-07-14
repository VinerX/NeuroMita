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
from typing import Any, Callable, Iterable, Mapping, Sequence

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from main_logger import logger

from core.backends import (
    BackendKind,
    CUDA_INDEX_URL,
    ONNX_DIRECTML_SPEC,
    ONNX_SPEC,
    TORCH_VERSION,
    get_backend_service,
)
from core.install_requirements import is_pip_spec_satisfied


_LAYOUT_VERSION = 2
_AI_ENVIRONMENT_CATEGORIES = frozenset({"backend", "tts", "voice", "asr", "rag", "embedding", "beats"})
_MAIN_ENVIRONMENT_CATEGORIES = frozenset({"dependency"})
_RUNTIME_SLOT_ORDER = (
    "tts",
    "asr",
    "rag:embeddings",
    "rag:reranker",
    "rag",
    "beats",
)
_CORE_FAMILY_ORDER = ("torch", "onnx")
_CORE_IMPORT_MODULES = {
    "torch": "torch",
    "torchaudio": "torchaudio",
    "numpy": "numpy",
    "onnxruntime": "onnxruntime",
    "onnxruntime-directml": "onnxruntime",
}

_IGNORED_PROBE_MODULES = frozenset(
    {
        "bin",
        "docs",
        "doc",
        "examples",
        "example",
        "scripts",
        "tests",
        "test",
    }
)


def _resolver_args_for_core_layers(values: Iterable[str]) -> tuple[str, ...]:
    args = tuple(str(value).strip() for value in values if str(value).strip())
    has_cuda_index = any(CUDA_INDEX_URL.casefold() in value.casefold() for value in args)
    has_index_strategy = any(
        value == "--index-strategy" or value.startswith("--index-strategy=")
        for value in args
    )
    if has_cuda_index and not has_index_strategy:
        return (*args, "--index-strategy", "unsafe-best-match")
    return args


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
    normalized = normalized.strip("-._").lower()
    return normalized or "environment"


def _safe_environment_id(value: str) -> str:
    """Create a filesystem key for a component identity without losing `+`."""
    raw = str(value or "").strip().replace("+", "-plus-")
    return _safe_id(raw)


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
        # Retained for API compatibility. Kernel locks disappear with the
        # owning process, so deleting allegedly stale lock files is unnecessary
        # and would reintroduce a cross-process unlink race.
        self.stale_after = max(self.timeout, float(stale_after))
        self._fd: int | None = None

    @staticmethod
    def _try_lock(fd: int) -> bool:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False

        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    @staticmethod
    def _unlock(fd: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)

    def __enter__(self) -> "_FileLock":
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(self._fd).st_size == 0:
            os.write(self._fd, b"\0")
        while True:
            if self._try_lock(self._fd):
                os.ftruncate(self._fd, 0)
                os.lseek(self._fd, 0, os.SEEK_SET)
                payload = f"pid={os.getpid()} time={time.time()}\n".encode("ascii", errors="ignore")
                os.write(self._fd, payload)
                os.fsync(self._fd)
                return self
            if time.monotonic() >= deadline:
                os.close(self._fd)
                self._fd = None
                raise TimeoutError(f"Timed out waiting for environment lock: {self.path}")
            time.sleep(0.1)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            try:
                self._unlock(self._fd)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


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


def _is_probe_module(value: str) -> bool:
    parts = tuple(part for part in str(value or "").strip().split(".") if part)
    return bool(
        parts
        and parts[0].lower() not in _IGNORED_PROBE_MODULES
        and all(part.isidentifier() for part in parts)
    )


def _distribution_name(dist_info: Path) -> str:
    metadata = dist_info / "METADATA"
    try:
        for line in metadata.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("name:"):
                return canonicalize_name(line.split(":", 1)[1].strip())
    except Exception:
        pass
    stem = dist_info.name.rsplit(".dist-info", 1)[0]
    return canonicalize_name(stem.rsplit("-", 1)[0])


def _distribution_probe_modules(
    site_packages: Path,
    requested_specs: Iterable[str],
    *,
    excluded_distributions: Iterable[str] = (),
) -> tuple[str, ...]:
    wanted = {
        _requirement_name(spec)
        for spec in requested_specs
        if str(spec or "").strip()
    }
    wanted.difference_update(
        canonicalize_name(name)
        for name in excluded_distributions
        if str(name or "").strip()
    )
    if not wanted or not site_packages.is_dir():
        return ()

    modules: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> bool:
        normalized = str(candidate or "").strip()
        if not _is_probe_module(normalized) or normalized in seen:
            return False
        top_level = normalized.split(".", 1)[0]
        if not (
            (site_packages / top_level).exists()
            or (site_packages / f"{top_level}.py").is_file()
        ):
            return False
        seen.add(normalized)
        modules.append(normalized)
        return True

    for dist_info in sorted(site_packages.glob("*.dist-info")):
        if _distribution_name(dist_info) not in wanted:
            continue

        found = False
        top_level = dist_info / "top_level.txt"
        if top_level.is_file():
            try:
                for line in top_level.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines():
                    found = add(line) or found
            except OSError:
                pass
        if found:
            continue

        record = dist_info / "RECORD"
        if not record.is_file():
            continue
        try:
            with record.open(
                "r", encoding="utf-8", errors="ignore", newline=""
            ) as source:
                for row in csv.reader(source):
                    if not row or not row[0]:
                        continue
                    first = Path(row[0]).parts[0]
                    lowered = first.lower()
                    if lowered.endswith((".dist-info", ".data")):
                        continue
                    if "." in first and not lowered.endswith(".py"):
                        continue
                    add(Path(first).stem if lowered.endswith(".py") else first)
        except OSError:
            continue

    return tuple(modules)


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
            "extra_args": list(self.extra_args),
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
    group: str
    root: Path
    site_packages: Path
    packages: dict[str, str]
    owned_packages: dict[str, str]
    capabilities: tuple[str, ...]
    extra_args: tuple[str, ...]


def _core_package_names(layers: Iterable[CoreLayer]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for layer in layers:
        provided_names = set(layer.packages)
        if "onnx.dml" in layer.capabilities:
            provided_names.update({"onnxruntime", "onnxruntime-directml"})
        for name in provided_names:
            normalized = canonicalize_name(name)
            if normalized in seen:
                continue
            seen.add(normalized)
            names.append(normalized)
    return tuple(names)


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
    probe_modules: tuple[str, ...] = ()
    required_backend: str = "none"
    required_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeSelectionRef:
    logical_id: str
    revision_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "logical_id": self.logical_id,
            "revision_id": self.revision_id,
        }


@dataclass(frozen=True, slots=True)
class RuntimeComposition:
    paths: tuple[str, ...]
    records: tuple[EnvironmentRecord, ...]
    core_layer_ids: tuple[str, ...]
    probe_modules: tuple[str, ...] = ()


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
    finalized: bool = False
    _registry_snapshot: dict[str, Any] | None = None
    _committed_record: EnvironmentRecord | None = None

    def __post_init__(self) -> None:
        self.staging_root = self.manager.staging_root / f"env-{_safe_environment_id(self.logical_id)}-{self.transaction_id}"
        self.site_packages = self.staging_root / "site-packages"
        self.site_packages.mkdir(parents=True, exist_ok=False)

    @property
    def validation_paths(self) -> tuple[str, ...]:
        assert self.site_packages is not None
        return (*(str(layer.site_packages) for layer in self.core_layers), str(self.site_packages))

    @property
    def core_package_names(self) -> tuple[str, ...]:
        return _core_package_names(self.core_layers)

    @property
    def core_overrides(self) -> tuple[str, ...]:
        specs: list[str] = []
        seen: set[str] = set()
        for layer in self.core_layers:
            owned = dict(layer.packages)
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

    @property
    def core_resolver_args(self) -> tuple[str, ...]:
        return _resolver_args_for_core_layers(
            value
            for layer in self.core_layers
            for value in layer.extra_args
        )

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
        self.manager.remove_distributions(
            self.site_packages,
            self.core_package_names,
        )

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
        embedded_core = (
            sorted(set(packages) & set(self.core_package_names))
            if self.category in _AI_ENVIRONMENT_CATEGORIES and self.category != "backend"
            else []
        )
        if embedded_core:
            raise RuntimeError(
                f"Environment '{self.logical_id}' contains backend-owned distributions: "
                f"{', '.join(embedded_core)}. AI overlays must reuse distributions "
                "provided by their declared shared backend layer."
            )
        probe_modules = _distribution_probe_modules(
            self.site_packages,
            self.requested_specs,
            excluded_distributions=self.core_package_names,
        )
        required_capabilities = tuple(
            sorted(
                {
                    self.manager._runtime_capability(capability)
                    for layer in self.core_layers
                    for capability in layer.capabilities
                    if self.manager._runtime_capability(capability)
                }
            )
        )
        revision_payload = {
            "logical_id": self.logical_id,
            "requested_specs": list(self.requested_specs),
            "core_layers": [layer.layer_id for layer in self.core_layers],
            "packages": packages,
            "probe_modules": list(probe_modules),
            "required_backend": self.required_backend.value,
            "required_capabilities": list(required_capabilities),
            "python": _python_tag(),
            "platform": _platform_tag(),
        }
        revision_id = _hash_payload(revision_payload, length=20)
        final_root = self.manager.overlay_root / _safe_environment_id(self.logical_id) / revision_id
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
            "probe_modules": list(probe_modules),
            "required_backend": self.required_backend.value,
            "required_capabilities": list(required_capabilities),
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
            probe_modules=probe_modules,
            required_backend=self.required_backend.value,
            required_capabilities=required_capabilities,
        )
        self._registry_snapshot = self.manager.registry_snapshot()
        self.manager.register_installed(record)
        self.committed = True
        self._committed_record = record
        return record

    def rollback_commit(self) -> None:
        if not self.committed or self.finalized:
            return
        if self._registry_snapshot is not None:
            self.manager.restore_registration(
                self._committed_record,
                self._registry_snapshot,
            )
        if self._committed_record is not None:
            previous_entry = ((self._registry_snapshot or {}).get("environments") or {}).get(
                self._committed_record.logical_id
            )
            previous_revision = (
                str(previous_entry.get("revision_id") or "")
                if isinstance(previous_entry, dict)
                else ""
            )
            if previous_revision != self._committed_record.revision_id:
                shutil.rmtree(self._committed_record.root, ignore_errors=True)
                try:
                    self._committed_record.root.parent.rmdir()
                except OSError:
                    pass
        self.manager.cleanup_unreferenced_core_layers()
        self.committed = False
        self.aborted = True

    def finalize(self) -> None:
        if not self.committed or self.finalized:
            return
        self.finalized = True
        if not self.manager.is_runtime_selected(self.logical_id):
            self.manager.cleanup_superseded_revisions(self.logical_id)

    def abort(self) -> None:
        if self.committed or self.aborted:
            return
        self.aborted = True
        if self.staging_root is not None:
            shutil.rmtree(self.staging_root, ignore_errors=True)


class RuntimeEnvironmentManager:
    """Transactional owner of AI backend layers and feature environments.

    Backend layers are immutable and version-addressed. A CUDA torch layer also
    advertises the CPU capability, so a machine never needs a second CPU torch
    copy merely for CPU-only operations. Feature packages live in immutable
    overlays under ``Lib/environment/overlays``. ``Lib/core`` belongs to the
    main process and is never an AI backend storage location.
    """

    def __init__(self, lib_root: str | os.PathLike[str] | None = None) -> None:
        configured_root = os.environ.get("NEUROMITA_RUNTIME_ROOT")
        raw_root = Path(lib_root or configured_root or os.environ.get("NEUROMITA_LIB_DIR") or "Lib").resolve()
        if raw_root.name.lower() == "core":
            raw_root = raw_root.parent
        root = raw_root
        self.lib_root = root
        if lib_root is not None:
            self.main_core_root = (root / "core").resolve()
            self.environment_root = (root / "environment").resolve()
        else:
            self.main_core_root = Path(
                os.environ.get("NEUROMITA_CORE_DIR") or (root / "core")
            ).resolve()
            self.environment_root = Path(
                os.environ.get("NEUROMITA_ENVIRONMENT_DIR") or (root / "environment")
            ).resolve()
        self.core_root = self.environment_root / "bases"
        self.overlay_root = self.environment_root / "overlays"
        self.staging_root = self.environment_root / ".staging"
        self.lock_root = self.environment_root / ".locks"
        self.registry_path = self.environment_root / "registry.json"
        self._lock = threading.RLock()
        self._warned_distribution_conflicts: set[tuple[tuple[str, tuple[str, ...]], ...]] = set()
        for path in (
            self.main_core_root,
            self.environment_root,
            self.core_root,
            self.overlay_root,
            self.staging_root,
            self.lock_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def file_lock(self, name: str, *, timeout: float = 120.0) -> _FileLock:
        return _FileLock(self.lock_root / f"{_safe_id(name)}.lock", timeout=timeout)

    def reset_managed_storage(self) -> None:
        """Delete and recreate the AI-owned environment tree only."""
        target = self.environment_root.resolve()
        forbidden = {
            Path(target.anchor).resolve(),
            self.lib_root.resolve(),
            self.main_core_root.resolve(),
        }
        if target in forbidden or target.parent == target:
            raise RuntimeError(f"Refusing to reset unsafe AI environment path: {target}")
        for owned_path in (
            self.core_root,
            self.overlay_root,
            self.staging_root,
            self.lock_root,
            self.registry_path,
        ):
            try:
                owned_path.resolve().relative_to(target)
            except ValueError as exc:
                raise RuntimeError(
                    f"Managed path escapes AI environment root: {owned_path}"
                ) from exc

        with self._lock:
            if target.exists():
                shutil.rmtree(target)
            for path in (
                self.environment_root,
                self.core_root,
                self.overlay_root,
                self.staging_root,
                self.lock_root,
            ):
                path.mkdir(parents=True, exist_ok=True)
            self._warned_distribution_conflicts.clear()

    def _warn_distribution_conflicts(
        self,
        records: Sequence[EnvironmentRecord],
        layers: Sequence[CoreLayer],
    ) -> None:
        versions_by_distribution: dict[str, dict[str, list[str]]] = {}

        sources: list[tuple[str, Mapping[str, str]]] = [
            (
                f"overlay {record.logical_id}@{record.revision_id[:8]}",
                record.packages,
            )
            for record in records
        ]
        sources.extend(
            (f"backend {layer.layer_id}", layer.packages)
            for layer in layers
        )

        for source_name, packages in sources:
            for raw_name, raw_version in packages.items():
                distribution = canonicalize_name(str(raw_name))
                version = str(raw_version or "").strip() or "<unknown>"
                versions_by_distribution.setdefault(distribution, {}).setdefault(
                    version,
                    [],
                ).append(source_name)

        conflicts = {
            distribution: versions
            for distribution, versions in versions_by_distribution.items()
            if len(versions) > 1
        }
        if not conflicts:
            return

        conflict_key = tuple(
            (distribution, tuple(sorted(versions)))
            for distribution, versions in sorted(conflicts.items())
        )
        if conflict_key in self._warned_distribution_conflicts:
            return
        self._warned_distribution_conflicts.add(conflict_key)

        details = []
        sorted_conflicts = sorted(conflicts.items())
        for distribution, versions in sorted_conflicts[:20]:
            version_details = ", ".join(
                f"{version} [{', '.join(sorted(owners))}]"
                for version, owners in sorted(versions.items())
            )
            details.append(f"{distribution}: {version_details}")
        if len(sorted_conflicts) > 20:
            details.append(f"... and {len(sorted_conflicts) - 20} more conflicts")

        logger.warning(
            "Runtime composition contains conflicting distribution versions. "
            "Import precedence follows the configured runtime path order, so one "
            "copy will shadow the others: "
            + "; ".join(details)
        )

    @staticmethod
    def logical_id_from_meta(meta: dict[str, Any] | None) -> tuple[str, str, str]:
        data = dict(meta or {})
        category = str(data.get("category") or data.get("kind") or "component").strip().lower()
        item_id = str(data.get("item_id") or data.get("component_id") or "component").strip()
        logical_id = str(data.get("environment_id") or f"{category}:{item_id}")
        return _safe_environment_id(logical_id), category, item_id

    @staticmethod
    def should_manage(meta: dict[str, Any] | None) -> bool:
        data = dict(meta or {})
        category = str(data.get("category") or data.get("kind") or "").strip().lower()
        if category in _AI_ENVIRONMENT_CATEGORIES:
            return True
        if category in _MAIN_ENVIRONMENT_CATEGORIES:
            item_id = str(data.get("item_id") or data.get("component_id") or "").strip().lower()
            return item_id in {"opencv"}
        return False

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
            provider = service.preferred_onnx_provider(context)
            runtime_spec = ONNX_DIRECTML_SPEC if provider == "dml" else ONNX_SPEC
            capabilities = ("onnx.cpu",)
            if provider == "dml":
                capabilities += ("onnx.dml",)
            layers.append(
                CoreLayerSpec(
                    group=f"onnx-{provider}",
                    packages=(runtime_spec, service.numpy_spec()),
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
                        group=str(data.get("group") or ""),
                        root=root,
                        site_packages=root / "site-packages",
                        packages={str(k): str(v) for k, v in (data.get("packages") or {}).items()},
                        owned_packages={
                            str(k): str(v)
                            for k, v in (data.get("owned_packages") or {}).items()
                        },
                        capabilities=capabilities,
                        extra_args=tuple(str(item) for item in data.get("extra_args") or ()),
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
                group=str(data.get("group") or ""),
                root=root,
                site_packages=root / "site-packages",
                packages={str(k): str(v) for k, v in (data.get("packages") or {}).items()},
                owned_packages={
                    str(k): str(v)
                    for k, v in (data.get("owned_packages") or {}).items()
                },
                capabilities=tuple(str(item) for item in data.get("capabilities") or ()),
                extra_args=tuple(str(item) for item in data.get("extra_args") or ()),
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
            with self._lock, self.file_lock("core-layer-lifecycle"):
                layer = self.find_core_layer(required_capabilities=spec.capabilities)
                if layer is not None:
                    self.register_backend_candidates((layer.layer_id,))
                return layer

        final_root = self.core_root / spec.layer_id
        with (
            self._lock,
            self.file_lock("core-layer-lifecycle"),
            self.file_lock(f"core-{spec.layer_id}"),
        ):
            existing = self.get_core_layer(spec.layer_id)
            if existing is not None:
                self.register_backend_candidates((existing.layer_id,))
                return existing

            staging_root = self.staging_root / f"core-{spec.layer_id}-{uuid.uuid4().hex}"
            site_packages = staging_root / "site-packages"
            site_packages.mkdir(parents=True, exist_ok=False)
            installer = installer_factory(str(site_packages))
            log(f"Preparing shared AI backend layer: {spec.layer_id}")
            ok = installer.install_package_with_overrides(
                list(spec.packages),
                description=f"Installing shared AI backend layer {spec.group}...",
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
                "extra_args": list(spec.extra_args),
                "packages": packages,
                "owned_packages": owned_packages,
            }
            _atomic_json(staging_root / "manifest.json", manifest)
            final_root.parent.mkdir(parents=True, exist_ok=True)
            if final_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            else:
                os.replace(staging_root, final_root)
            layer = self.get_core_layer(spec.layer_id)
            if layer is not None:
                # A materialized base is an installed backend candidate even if
                # the model overlay later fails. Register it before releasing
                # the lifecycle lock so GC cannot delete it in the commit gap.
                self.register_backend_candidates((layer.layer_id,))
            return layer

    def _load_registry(self) -> dict[str, Any]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("layout_version", _LAYOUT_VERSION)
                data.setdefault("backend_profile", {"core_layer_ids": []})
                data.setdefault("backend_candidates", {"core_layer_ids": []})
                data.setdefault("runtime_selection", {})
                data.setdefault("environments", {})
                return data
        except Exception:
            pass
        return {
            "layout_version": _LAYOUT_VERSION,
            "backend_profile": {"core_layer_ids": []},
            "backend_candidates": {"core_layer_ids": []},
            "runtime_selection": {},
            "environments": {},
        }

    def registry_snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._load_registry()))

    def restore_registry(self, snapshot: dict[str, Any]) -> None:
        with self._lock, self.file_lock("environment-registry"):
            _atomic_json(self.registry_path, dict(snapshot or {}))

    def register_installed(self, record: EnvironmentRecord) -> None:
        """Register an immutable overlay revision as installed, not running."""
        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            environments = data.setdefault("environments", {})
            environments[record.logical_id] = {
                "revision_id": record.revision_id,
                "category": record.category,
                "item_id": record.item_id,
                "core_layer_ids": list(record.core_layer_ids),
                "required_backend": record.required_backend,
                "required_capabilities": list(record.required_capabilities),
            }
            _atomic_json(self.registry_path, data)

    def restore_registration(
        self,
        record: EnvironmentRecord | None,
        snapshot: Mapping[str, Any],
    ) -> None:
        """Undo one committed registration without discarding concurrent installs."""
        if record is None:
            return

        logical_id = _safe_environment_id(record.logical_id)
        previous_environments = (snapshot.get("environments") or {})
        previous_entry = previous_environments.get(logical_id)
        previous_selection = snapshot.get("runtime_selection") or {}

        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            environments = data.setdefault("environments", {})
            current_entry = environments.get(logical_id)
            current_revision = (
                str(current_entry.get("revision_id") or "")
                if isinstance(current_entry, dict)
                else ""
            )
            if current_revision != record.revision_id:
                return

            if isinstance(previous_entry, dict):
                environments[logical_id] = dict(previous_entry)
            else:
                environments.pop(logical_id, None)

            selection = data.setdefault("runtime_selection", {})
            for slot, value in tuple(selection.items()):
                selected = self._selection_ref(value)
                if selected is None or selected.logical_id != logical_id or selected.revision_id != record.revision_id:
                    continue
                old_value = previous_selection.get(slot)
                if old_value is None:
                    selection.pop(slot, None)
                else:
                    selection[slot] = old_value
            _atomic_json(self.registry_path, data)

    def migrate_legacy_environment_ids(self) -> tuple[str, ...]:
        """Move legacy overlay keys that collapsed `+` into their distinct IDs."""
        migrated: list[str] = []
        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            environments = data.setdefault("environments", {})
            selection = data.setdefault("runtime_selection", {})
            for legacy_id, entry in tuple(environments.items()):
                if not isinstance(entry, dict):
                    continue
                category = str(entry.get("category") or "").strip().lower()
                item_id = str(entry.get("item_id") or "").strip()
                revision_id = str(entry.get("revision_id") or "").strip()
                canonical_id = _safe_environment_id(f"{category}:{item_id}")
                if not category or not item_id or not revision_id or canonical_id == legacy_id:
                    continue

                source = self.overlay_root / legacy_id / revision_id
                destination = self.overlay_root / canonical_id / revision_id
                if source.is_dir() and not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(source, destination)
                if not destination.is_dir():
                    continue

                environments.pop(legacy_id, None)
                environments[canonical_id] = dict(entry)
                for slot, value in tuple(selection.items()):
                    selected = self._selection_ref(value)
                    if selected is None or selected.logical_id != legacy_id or selected.revision_id != revision_id:
                        continue
                    selection[slot] = RuntimeSelectionRef(canonical_id, revision_id).as_dict()
                migrated.append(canonical_id)
            if migrated:
                _atomic_json(self.registry_path, data)
        return tuple(migrated)

    def recover_unregistered_overlays(self) -> tuple[EnvironmentRecord, ...]:
        """Restore ready overlays left unregistered by an interrupted transaction."""
        recovered: list[EnvironmentRecord] = []
        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            environments = data.setdefault("environments", {})
            for logical_root in tuple(self.overlay_root.iterdir()) if self.overlay_root.is_dir() else ():
                if not logical_root.is_dir():
                    continue
                logical_id = _safe_environment_id(logical_root.name)
                if logical_id in environments:
                    continue

                candidates: list[EnvironmentRecord] = []
                for revision_root in tuple(logical_root.iterdir()):
                    if (
                        not revision_root.is_dir()
                        or (revision_root / ".pending-delete").is_file()
                        or (revision_root / ".retired").is_file()
                    ):
                        continue
                    record = self._record_for_revision(logical_id, revision_root.name)
                    if record is not None and record.site_packages.is_dir():
                        candidates.append(record)
                if not candidates:
                    continue

                record = max(candidates, key=lambda item: item.root.stat().st_mtime)
                environments[record.logical_id] = {
                    "revision_id": record.revision_id,
                    "category": record.category,
                    "item_id": record.item_id,
                    "core_layer_ids": list(record.core_layer_ids),
                    "required_backend": record.required_backend,
                    "required_capabilities": list(record.required_capabilities),
                }
                recovered.append(record)
            if recovered:
                _atomic_json(self.registry_path, data)
        return tuple(recovered)

    def remove_installed(self, logical_id: str, *, delete: bool = True) -> bool:
        normalized = _safe_environment_id(logical_id)
        logical_root = self.overlay_root / normalized
        marker_name = ".pending-delete" if delete else ".retired"
        marked_paths: list[Path] = []
        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            environments = data.get("environments") or {}
            entry = environments.get(normalized)
            if entry is None:
                return False

            for revision_root in tuple(logical_root.iterdir()) if logical_root.is_dir() else ():
                if not revision_root.is_dir():
                    continue
                marker = revision_root / marker_name
                try:
                    marker.write_text("1\n", encoding="ascii")
                    marked_paths.append(marker)
                except OSError:
                    pass

            environments.pop(normalized, None)
            selection = data.setdefault("runtime_selection", {})
            for slot, selected_value in tuple(selection.items()):
                ref = self._selection_ref(selected_value)
                if ref is not None and ref.logical_id == normalized:
                    selection.pop(slot, None)
            try:
                _atomic_json(self.registry_path, data)
            except Exception:
                for marker in marked_paths:
                    try:
                        marker.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise
        if delete:
            try:
                shutil.rmtree(logical_root)
            except OSError:
                # A stopped Windows worker can release native DLLs slightly later.
                # Mark every remaining revision of this uninstalled overlay for
                # startup cleanup; none of them is registered or selectable now.
                for revision_root in (
                    tuple(logical_root.iterdir()) if logical_root.is_dir() else ()
                ):
                    if not revision_root.is_dir():
                        continue
                    try:
                        (revision_root / ".pending-delete").write_text(
                            "1\n",
                            encoding="ascii",
                        )
                    except OSError:
                        pass
        else:
            for revision_root in tuple(logical_root.iterdir()) if logical_root.is_dir() else ():
                if not revision_root.is_dir():
                    continue
                try:
                    (revision_root / ".retired").write_text("1\n", encoding="ascii")
                except OSError:
                    pass
        return True

    def _record_required_capabilities(
        self,
        manifest: Mapping[str, Any],
        registry_entry: Mapping[str, Any],
        layer_ids: Sequence[str],
    ) -> tuple[str, ...]:
        stored = manifest.get("required_capabilities")
        if not isinstance(stored, list):
            stored = registry_entry.get("required_capabilities")
        if isinstance(stored, list):
            return tuple(
                dict.fromkeys(
                    capability
                    for item in stored
                    if (capability := self._runtime_capability(str(item)))
                )
            )

        capabilities: list[str] = []
        for layer_id in layer_ids:
            layer = self.get_core_layer(str(layer_id))
            if layer is not None:
                capabilities.extend(
                    capability
                    for item in layer.capabilities
                    if (capability := self._runtime_capability(item))
                )
        return tuple(dict.fromkeys(capabilities))

    def _record_for_revision(
        self,
        logical_id: str,
        revision_id: str,
        *,
        registry_entry: Mapping[str, Any] | None = None,
    ) -> EnvironmentRecord | None:
        normalized = _safe_environment_id(logical_id)
        normalized_revision = str(revision_id or "").strip()
        if not normalized_revision:
            return None
        root = self.overlay_root / normalized / normalized_revision
        manifest_path = root / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("state") != "ready":
                return None
            entry = dict(registry_entry or {})
            registered_layers = entry.get("core_layer_ids")
            layer_ids = (
                tuple(str(item) for item in registered_layers)
                if isinstance(registered_layers, list)
                else tuple(str(item) for item in manifest.get("core_layer_ids") or ())
            )
            stored_probe_modules = manifest.get("probe_modules")
            if isinstance(stored_probe_modules, list):
                probe_modules = tuple(
                    str(module)
                    for module in stored_probe_modules
                    if _is_probe_module(str(module))
                )
            else:
                core_layers = tuple(
                    layer
                    for layer_id in layer_ids
                    if (layer := self.get_core_layer(layer_id)) is not None
                )
                probe_modules = _distribution_probe_modules(
                    root / "site-packages",
                    manifest.get("requested_specs") or (),
                    excluded_distributions=_core_package_names(core_layers),
                )
            return EnvironmentRecord(
                logical_id=normalized,
                revision_id=normalized_revision,
                root=root,
                site_packages=root / "site-packages",
                core_layer_ids=layer_ids,
                category=str(manifest.get("category") or entry.get("category") or ""),
                item_id=str(manifest.get("item_id") or entry.get("item_id") or ""),
                packages={str(k): str(v) for k, v in (manifest.get("packages") or {}).items()},
                probe_modules=probe_modules,
                required_backend=str(
                    manifest.get("required_backend")
                    or entry.get("required_backend")
                    or "none"
                ),
                required_capabilities=self._record_required_capabilities(
                    manifest,
                    entry,
                    layer_ids,
                ),
            )
        except Exception:
            return None

    def active(self, logical_id: str) -> EnvironmentRecord | None:
        normalized = _safe_environment_id(logical_id)
        data = self._load_registry()
        entry = (data.get("environments") or {}).get(normalized)
        if not isinstance(entry, dict):
            return None
        return self._record_for_revision(
            normalized,
            str(entry.get("revision_id") or ""),
            registry_entry=entry,
        )

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

    def active_records(
        self,
        *,
        exclude_logical_ids: Iterable[str] = (),
    ) -> tuple[EnvironmentRecord, ...]:
        """Return installed immutable environment revisions.

        The historical method name is kept for compatibility. Installation and
        runtime activation are deliberately separate: a record returned here is
        installed, but it is not necessarily attached to the shared AI worker.
        """
        excluded = {_safe_environment_id(item) for item in exclude_logical_ids}
        data = self._load_registry()
        records: list[EnvironmentRecord] = []
        for logical_id in (data.get("environments") or {}):
            normalized = _safe_environment_id(logical_id)
            if normalized in excluded:
                continue
            record = self.active(normalized)
            if record is not None:
                records.append(record)
        records.sort(key=lambda item: (item.category, item.item_id, item.logical_id))
        return tuple(records)

    def _selection_ref(self, raw: Any) -> RuntimeSelectionRef | None:
        if isinstance(raw, RuntimeSelectionRef):
            return raw
        if isinstance(raw, Mapping):
            logical_id = str(raw.get("logical_id") or "").strip()
            revision_id = str(raw.get("revision_id") or "").strip()
        else:
            logical_id = str(raw or "").strip()
            revision_id = ""
        if not logical_id:
            return None
        normalized_id = _safe_environment_id(logical_id)
        if not revision_id:
            installed = self.active(normalized_id)
            if installed is None:
                return None
            revision_id = installed.revision_id
        return RuntimeSelectionRef(normalized_id, revision_id)

    def runtime_selection(self) -> dict[str, RuntimeSelectionRef]:
        raw = self._load_registry().get("runtime_selection") or {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, RuntimeSelectionRef] = {}
        for slot, value in raw.items():
            normalized_slot = str(slot or "").strip().lower()
            ref = self._selection_ref(value)
            if normalized_slot and ref is not None:
                result[normalized_slot] = ref
        return result

    def selection_with(
        self,
        slot: str,
        record: EnvironmentRecord | None,
    ) -> dict[str, RuntimeSelectionRef]:
        selection = self.runtime_selection()
        normalized_slot = str(slot or "").strip().lower()
        if not normalized_slot:
            raise ValueError("Runtime slot is required")
        if record is None:
            selection.pop(normalized_slot, None)
        else:
            selection[normalized_slot] = RuntimeSelectionRef(
                _safe_environment_id(record.logical_id),
                str(record.revision_id),
            )
        return selection

    def selected_records(
        self,
        *,
        selection: Mapping[str, Any] | None = None,
        exclude_logical_ids: Iterable[str] = (),
    ) -> tuple[EnvironmentRecord, ...]:
        excluded = {_safe_environment_id(item) for item in exclude_logical_ids}
        selected = dict(selection) if selection is not None else self.runtime_selection()
        ordered_slots: list[str] = list(_RUNTIME_SLOT_ORDER)
        ordered_slots.extend(
            sorted(slot for slot in selected if slot not in _RUNTIME_SLOT_ORDER)
        )

        records: list[EnvironmentRecord] = []
        seen: set[tuple[str, str]] = set()
        for slot in ordered_slots:
            ref = self._selection_ref(selected.get(slot))
            if ref is None or ref.logical_id in excluded:
                continue
            identity = (ref.logical_id, ref.revision_id)
            if identity in seen:
                continue
            record = self._record_for_revision(ref.logical_id, ref.revision_id)
            if record is None:
                continue
            records.append(record)
            seen.add(identity)
        return tuple(records)

    def is_runtime_selected(
        self,
        logical_id: str,
        *,
        revision_id: str | None = None,
        slot: str | None = None,
    ) -> bool:
        normalized = _safe_environment_id(logical_id)
        expected_revision = str(revision_id or "").strip()
        selection = self.runtime_selection()

        def matches(ref: RuntimeSelectionRef | None) -> bool:
            return bool(
                ref is not None
                and ref.logical_id == normalized
                and (not expected_revision or ref.revision_id == expected_revision)
            )

        if slot is not None:
            return matches(selection.get(str(slot).strip().lower()))
        return any(matches(ref) for ref in selection.values())


    def main_dependency_records(self) -> tuple[EnvironmentRecord, ...]:
        return tuple(
            record
            for record in self.active_records()
            if str(record.category or "").strip().lower() in _MAIN_ENVIRONMENT_CATEGORIES
        )

    def main_runtime_paths(self) -> tuple[str, ...]:
        return tuple(str(record.site_packages) for record in self.main_dependency_records())

    def cleanup_inactive_overlays(self) -> None:
        data = self._load_registry()
        keep_roots: set[Path] = set()
        for logical_id, entry in (data.get("environments") or {}).items():
            if not isinstance(entry, dict):
                continue
            revision_id = str(entry.get("revision_id") or "").strip()
            if revision_id:
                keep_roots.add(
                    (self.overlay_root / _safe_environment_id(logical_id) / revision_id).resolve()
                )
        for ref in self.runtime_selection().values():
            keep_roots.add(
                (self.overlay_root / ref.logical_id / ref.revision_id).resolve()
            )

        if not self.overlay_root.is_dir():
            return
        registered_ids = {
            _safe_environment_id(logical_id)
            for logical_id in (data.get("environments") or {})
        }
        for logical_root in tuple(self.overlay_root.iterdir()):
            if not logical_root.is_dir():
                continue
            logical_id = _safe_environment_id(logical_root.name)
            for revision_root in tuple(logical_root.iterdir()):
                if not revision_root.is_dir():
                    continue
                try:
                    resolved = revision_root.resolve()
                except OSError:
                    resolved = revision_root.absolute()
                should_delete = (
                    logical_id in registered_ids and resolved not in keep_roots
                ) or (
                    logical_id not in registered_ids
                    and (revision_root / ".pending-delete").is_file()
                )
                if should_delete:
                    shutil.rmtree(revision_root, ignore_errors=True)
            try:
                logical_root.rmdir()
            except OSError:
                pass

    @staticmethod
    def _layer_family(layer: CoreLayer) -> str:
        group = str(layer.group or "").lower()
        if group.startswith("torch"):
            return "torch"
        if group.startswith("onnx"):
            return "onnx"
        return group or layer.layer_id

    @staticmethod
    def _capability_family(capability: str) -> str:
        value = str(capability or "").strip().lower()
        if value.startswith("torch."):
            return "torch"
        if value.startswith("onnx."):
            return "onnx"
        return value.split(".", 1)[0] if value else ""

    @staticmethod
    def _runtime_capability(capability: str) -> str:
        """Return the stable runtime contract, without pinning a backend revision."""
        return str(capability or "").strip().lower().split("@", 1)[0]

    @classmethod
    def _layer_satisfies(
        cls,
        layer: CoreLayer,
        required_capabilities: Iterable[str],
    ) -> bool:
        required = {
            cls._runtime_capability(item)
            for item in required_capabilities
            if cls._runtime_capability(item)
        }
        if not required:
            return True
        provided = {
            cls._runtime_capability(item)
            for item in layer.capabilities
            if cls._runtime_capability(item)
        }
        return required.issubset(provided)

    @staticmethod
    def _select_family_layer(family: str, layers: Sequence[CoreLayer]) -> CoreLayer:
        if not layers:
            raise RuntimeError(f"No layers supplied for backend family '{family}'")

        def rank(layer: CoreLayer) -> tuple[int, float]:
            capabilities = set(layer.capabilities)
            if family == "torch":
                preferred = 2 if any(item.startswith("torch.cuda") for item in capabilities) else 1
            elif family == "onnx":
                preferred = 2 if "onnx.dml" in capabilities else 1
            else:
                preferred = 1
            try:
                modified = layer.root.stat().st_mtime
            except OSError:
                modified = 0.0
            return preferred, modified

        return max(layers, key=rank)

    def runtime_composition(
        self,
        *,
        records: Sequence[EnvironmentRecord] | None = None,
        selection: Mapping[str, Any] | None = None,
        exclude_logical_ids: Iterable[str] = (),
        preferred_core_layer_ids: Iterable[str] = (),
    ) -> RuntimeComposition:
        source_records = tuple(
            records
            if records is not None
            else self.selected_records(
                selection=selection,
                exclude_logical_ids=exclude_logical_ids,
            )
        )
        selected_records = tuple(
            record
            for record in source_records
            if str(record.category or "").strip().lower() in _AI_ENVIRONMENT_CATEGORIES
            and str(record.category or "").strip().lower() != "backend"
        )
        required_by_family: dict[str, set[str]] = {}
        record_layers_by_family: dict[str, list[CoreLayer]] = {}
        for record in selected_records:
            for capability in record.required_capabilities:
                family = self._capability_family(capability)
                if family:
                    required_by_family.setdefault(family, set()).add(capability)
            for layer_id in record.core_layer_ids:
                layer = self.get_core_layer(layer_id)
                if layer is None:
                    continue
                family = self._layer_family(layer)
                record_layers_by_family.setdefault(family, []).append(layer)
                if not record.required_capabilities:
                    required_by_family.setdefault(family, set()).update(layer.capabilities)

        explicit_preferred = tuple(
            dict.fromkeys(
                str(layer_id)
                for layer_id in preferred_core_layer_ids
                if str(layer_id).strip()
            )
        )
        if explicit_preferred:
            preferred_ids = explicit_preferred
        else:
            profile = self._load_registry().get("backend_profile") or {}
            preferred_ids = tuple(
                str(item) for item in profile.get("core_layer_ids") or ()
            )

        preferred_by_family: dict[str, CoreLayer] = {}
        for layer_id in preferred_ids:
            layer = self.get_core_layer(layer_id)
            if layer is None:
                continue
            family = self._layer_family(layer)
            if family not in required_by_family:
                continue
            existing = preferred_by_family.get(family)
            if existing is not None and existing.layer_id != layer.layer_id:
                raise RuntimeError(
                    f"Backend profile contains multiple authoritative layers for family '{family}'"
                )
            preferred_by_family[family] = layer

        candidate_by_family: dict[str, CoreLayer] = {}
        if not explicit_preferred:
            candidate_profile = self._load_registry().get("backend_candidates") or {}
            for layer_id in candidate_profile.get("core_layer_ids") or ():
                layer = self.get_core_layer(str(layer_id))
                if layer is None:
                    continue
                family = self._layer_family(layer)
                if family in required_by_family:
                    candidate_by_family[family] = layer

        selected_layers: list[CoreLayer] = []
        family_rank = {
            family: index for index, family in enumerate(_CORE_FAMILY_ORDER)
        }
        for family in sorted(
            required_by_family,
            key=lambda item: (family_rank.get(item, len(family_rank)), item),
        ):
            required = required_by_family[family]
            candidate = candidate_by_family.get(family)
            if candidate is not None and self._layer_satisfies(candidate, required):
                selected_layers.append(candidate)
                continue

            preferred = preferred_by_family.get(family)
            if preferred is not None and self._layer_satisfies(preferred, required):
                selected_layers.append(preferred)
                continue

            candidates = [
                layer
                for layer in record_layers_by_family.get(family, ())
                if self._layer_satisfies(layer, required)
            ]
            if not candidates:
                raise RuntimeError(
                    f"No installed backend layer satisfies family '{family}': "
                    f"{sorted(required)}"
                )
            selected_layers.append(self._select_family_layer(family, candidates))

        self._warn_distribution_conflicts(selected_records, selected_layers)

        paths = tuple(
            [str(layer.site_packages) for layer in selected_layers]
            + [str(record.site_packages) for record in selected_records]
        )
        # Candidate bootstrap validates only the shared backend layers. Importing
        # arbitrary overlay top-level modules here duplicates model initialization
        # and can execute expensive package side effects before IPC readiness. The
        # selected model is imported and validated by its service-specific
        # initialization call after the worker has become responsive.
        probe_modules = tuple(
            dict.fromkeys(
                module
                for layer in selected_layers
                for package_name in layer.packages
                if (module := _CORE_IMPORT_MODULES.get(package_name)) is not None
            )
        )
        return RuntimeComposition(
            paths=paths,
            records=selected_records,
            core_layer_ids=tuple(layer.layer_id for layer in selected_layers),
            probe_modules=probe_modules,
        )

    def register_backend_candidates(
        self,
        core_layer_ids: Iterable[str],
    ) -> None:
        """Register installed backend layers for the next runtime activation."""
        incoming: dict[str, CoreLayer] = {}
        for layer_id in core_layer_ids:
            layer = self.get_core_layer(str(layer_id))
            if layer is None:
                raise RuntimeError(f"Cannot register missing backend layer '{layer_id}'")
            incoming[self._layer_family(layer)] = layer
        if not incoming:
            return

        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            candidates = data.get("backend_candidates") or {}
            merged: dict[str, CoreLayer] = {}
            for layer_id in candidates.get("core_layer_ids") or ():
                layer = self.get_core_layer(str(layer_id))
                if layer is not None:
                    merged[self._layer_family(layer)] = layer
            merged.update(incoming)
            data["backend_candidates"] = {
                "core_layer_ids": [
                    layer.layer_id
                    for _, layer in sorted(merged.items())
                ]
            }
            _atomic_json(self.registry_path, data)

    def promote_backend_profile(
        self,
        core_layer_ids: Iterable[str],
        *,
        cleanup: bool = False,
    ) -> None:
        incoming: dict[str, CoreLayer] = {}
        for layer_id in core_layer_ids:
            layer = self.get_core_layer(str(layer_id))
            if layer is None:
                raise RuntimeError(f"Cannot promote missing backend layer '{layer_id}'")
            incoming[self._layer_family(layer)] = layer
        if not incoming:
            return

        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            profile = data.get("backend_profile") or {}
            merged: dict[str, CoreLayer] = {}
            for layer_id in profile.get("core_layer_ids") or ():
                layer = self.get_core_layer(str(layer_id))
                if layer is not None:
                    merged[self._layer_family(layer)] = layer
            merged.update(incoming)
            data["backend_profile"] = {
                "core_layer_ids": [
                    layer.layer_id
                    for _, layer in sorted(merged.items())
                ]
            }
            _atomic_json(self.registry_path, data)
        if cleanup:
            self.cleanup_unreferenced_core_layers()

    def promote_runtime_selection(
        self,
        selection: Mapping[str, Any],
        composition: RuntimeComposition,
        *,
        cleanup: bool = True,
    ) -> None:
        normalized_selection: dict[str, dict[str, str]] = {}
        for slot, raw_ref in selection.items():
            normalized_slot = str(slot or "").strip().lower()
            ref = self._selection_ref(raw_ref)
            if not normalized_slot or ref is None:
                continue
            if self._record_for_revision(ref.logical_id, ref.revision_id) is None:
                raise RuntimeError(
                    f"Cannot select missing environment revision "
                    f"'{ref.logical_id}@{ref.revision_id}' for slot '{normalized_slot}'"
                )
            normalized_selection[normalized_slot] = ref.as_dict()

        with self._lock, self.file_lock("environment-registry"):
            data = self._load_registry()
            merged: dict[str, CoreLayer] = {}
            profile = data.get("backend_profile") or {}
            for layer_id in profile.get("core_layer_ids") or ():
                layer = self.get_core_layer(str(layer_id))
                if layer is not None:
                    merged[self._layer_family(layer)] = layer
            for layer_id in composition.core_layer_ids:
                layer = self.get_core_layer(str(layer_id))
                if layer is None:
                    raise RuntimeError(
                        f"Cannot promote missing backend layer '{layer_id}'"
                    )
                merged[self._layer_family(layer)] = layer
            data["runtime_selection"] = normalized_selection
            data["backend_profile"] = {
                "core_layer_ids": [
                    layer.layer_id
                    for _, layer in sorted(merged.items())
                ]
            }

            candidate_profile = data.get("backend_candidates") or {}
            promoted_families = {
                self._layer_family(layer)
                for layer_id in composition.core_layer_ids
                if (layer := self.get_core_layer(str(layer_id))) is not None
            }
            remaining_candidates: dict[str, CoreLayer] = {}
            for layer_id in candidate_profile.get("core_layer_ids") or ():
                layer = self.get_core_layer(str(layer_id))
                if layer is None:
                    continue
                family = self._layer_family(layer)
                if family not in promoted_families:
                    remaining_candidates[family] = layer
            data["backend_candidates"] = {
                "core_layer_ids": [
                    layer.layer_id
                    for _, layer in sorted(remaining_candidates.items())
                ]
            }
            _atomic_json(self.registry_path, data)
        if cleanup:
            self.cleanup_unreferenced_core_layers()

    def cleanup_superseded_revisions(self, logical_id: str) -> None:
        normalized = _safe_environment_id(logical_id)
        installed = self.active(normalized)
        keep: set[str] = set()
        if installed is not None:
            keep.add(installed.revision_id)
        keep.update(
            ref.revision_id
            for ref in self.runtime_selection().values()
            if ref.logical_id == normalized
        )

        parent = self.overlay_root / normalized
        if not parent.is_dir():
            return
        for child in parent.iterdir():
            if child.is_dir() and child.name not in keep:
                shutil.rmtree(child, ignore_errors=True)
        try:
            parent.rmdir()
        except OSError:
            pass

    def cleanup_unreferenced_core_layers(self) -> None:
        with self._lock, self.file_lock("core-layer-lifecycle"):
            self._cleanup_unreferenced_core_layers_locked()

    def _cleanup_unreferenced_core_layers_locked(self) -> None:
        data = self._load_registry()
        referenced: set[str] = set()
        retained_by_family: dict[str, list[CoreLayer]] = {}

        profile = data.get("backend_profile") or {}
        for layer_id in profile.get("core_layer_ids") or ():
            layer = self.get_core_layer(str(layer_id))
            if layer is None:
                continue
            referenced.add(layer.layer_id)
            retained_by_family.setdefault(self._layer_family(layer), []).append(layer)

        candidates = data.get("backend_candidates") or {}
        for layer_id in candidates.get("core_layer_ids") or ():
            layer = self.get_core_layer(str(layer_id))
            if layer is None:
                continue
            referenced.add(layer.layer_id)
            retained_by_family.setdefault(self._layer_family(layer), []).append(layer)

        # An installed, but not yet selected, overlay may carry a backend
        # candidate that the current preferred profile cannot satisfy. Keep one
        # such candidate per required family until initialization either promotes
        # it or the overlay is removed. Exact historical layers are not retained
        # once the preferred profile satisfies the overlay's generic contract.
        for logical_id in (data.get("environments") or {}):
            record = self.active(str(logical_id))
            if record is None:
                continue
            required_by_family: dict[str, set[str]] = {}
            for capability in record.required_capabilities:
                family = self._capability_family(capability)
                if family:
                    required_by_family.setdefault(family, set()).add(capability)

            # Migration safety for old manifests without required_capabilities.
            if not required_by_family:
                for layer_id in record.core_layer_ids:
                    layer = self.get_core_layer(layer_id)
                    if layer is None:
                        continue
                    family = self._layer_family(layer)
                    required_by_family.setdefault(family, set()).update(
                        self._runtime_capability(item)
                        for item in layer.capabilities
                        if self._runtime_capability(item)
                    )

            for family, required in required_by_family.items():
                if any(
                    self._layer_satisfies(layer, required)
                    for layer in retained_by_family.get(family, ())
                ):
                    continue
                candidates = [
                    layer
                    for layer_id in record.core_layer_ids
                    if (layer := self.get_core_layer(layer_id)) is not None
                    and self._layer_family(layer) == family
                    and self._layer_satisfies(layer, required)
                ]
                if not candidates:
                    continue
                selected = self._select_family_layer(family, candidates)
                referenced.add(selected.layer_id)
                retained_by_family.setdefault(family, []).append(selected)

        for child in self.core_root.iterdir() if self.core_root.is_dir() else ():
            if child.is_dir() and child.name not in referenced:
                shutil.rmtree(child, ignore_errors=True)

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
            probe = self.staging_root / "status-empty" / _safe_environment_id(
                f"{normalized_category}:{normalized_item}"
            )
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
        category = str(record.category or "").strip().lower()
        if category in _AI_ENVIRONMENT_CATEGORIES and category != "backend":
            return self.runtime_composition(records=(record,)).paths

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
                stem = dist_info.name.rsplit(".dist-info", 1)[0]
                match = re.match(r"^(?P<name>.+)-(?P<version>\d.*)$", stem)
                name = match.group("name") if match is not None else stem
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
    configured = os.environ.get("NEUROMITA_RUNTIME_ROOT")
    root = Path(configured or os.environ.get("NEUROMITA_LIB_DIR") or "Lib").resolve()
    if root.name.lower() == "core":
        root = root.parent
    with _default_lock:
        if _default_manager is None or _default_manager.lib_root != root:
            _default_manager = RuntimeEnvironmentManager(root)
        return _default_manager
