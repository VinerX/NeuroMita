from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from core.backends import BackendKind, normalize_backend_kind
from core.install_types import InstallPlan


class ComponentCategory(str, Enum):
    TTS = "tts"
    ASR = "asr"
    RAG = "rag"
    BEATS = "beats"
    BACKEND = "backend"
    DEPENDENCY = "dependency"


class ComponentStatusCode(str, Enum):
    UNKNOWN = "unknown"
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    READY = "ready"
    BACKEND_MISSING = "backend_missing"
    FAILED = "failed"


@dataclass(frozen=True)
class ComponentMetadata:
    id: str
    item_id: str
    category: ComponentCategory
    title: str
    description: str = ""
    backend: BackendKind = BackendKind.NONE
    legacy_kind: str = ""
    tags: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    size: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "item_id": self.item_id,
            "category": self.category.value,
            "title": self.title,
            "description": self.description,
            "backend": self.backend.value,
            "legacy_kind": self.legacy_kind,
            "tags": list(self.tags),
            "languages": list(self.languages),
            "size": self.size,
        }


@dataclass(frozen=True)
class ComponentStatus:
    id: str
    code: ComponentStatusCode
    installed: bool
    ready: bool
    message: str = ""
    backend: BackendKind = BackendKind.NONE
    backend_ok: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code.value,
            "installed": self.installed,
            "ready": self.ready,
            "message": self.message,
            "backend": self.backend.value,
            "backend_ok": self.backend_ok,
            "details": dict(self.details or {}),
        }


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class InstallableComponent(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def item_id(self) -> str: ...

    @property
    def category(self) -> ComponentCategory: ...

    @property
    def legacy_kind(self) -> str: ...

    def metadata(self) -> ComponentMetadata: ...

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus: ...

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan: ...

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan: ...

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None: ...


@runtime_checkable
class ConfigurableComponent(Protocol):
    def settings_schema(self) -> list[dict[str, Any]]: ...

    def load_settings(self) -> dict[str, Any]: ...

    def validate_settings(self, values: dict[str, Any]) -> ValidationResult: ...

    def save_settings(self, values: dict[str, Any]) -> None: ...


def make_component_id(category: ComponentCategory | str, item_id: str) -> str:
    cat = category.value if isinstance(category, ComponentCategory) else str(category or "").strip().lower()
    return f"{cat}:{str(item_id or '').strip()}"


def coerce_backend(value: BackendKind | str | None) -> BackendKind:
    try:
        return normalize_backend_kind(value)
    except Exception:
        return BackendKind.NONE
