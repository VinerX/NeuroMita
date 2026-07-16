from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from core.backends import BackendKind, normalize_backend_kind
from core.install_types import InstallPlan


class ComponentCategory(str, Enum):
    TTS = "tts"
    VOICES = "voices"
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
class CompatibilityRule:
    code: str
    effect: str = "warning"
    vendors: tuple[str, ...] = ()
    minimum_compute_capability: int | None = None
    tag: str = ""
    tag_variant: str = "danger"
    warning_ru: str = ""
    warning_en: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "effect": self.effect,
            "vendors": list(self.vendors),
            "minimum_compute_capability": self.minimum_compute_capability,
            "tag": self.tag,
            "tag_variant": self.tag_variant,
            "warning_ru": self.warning_ru,
            "warning_en": self.warning_en,
        }


@dataclass(frozen=True)
class CompatibilitySpec:
    supported_vendors: tuple[str, ...] = ()
    rules: tuple[CompatibilityRule, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "supported_vendors": list(self.supported_vendors),
            "rules": [rule.as_dict() for rule in self.rules],
        }


def coerce_compatibility_spec(value: CompatibilitySpec | dict[str, Any] | None) -> CompatibilitySpec:
    if isinstance(value, CompatibilitySpec):
        return value
    data = value if isinstance(value, dict) else {}
    rules: list[CompatibilityRule] = []
    for item in data.get("rules") or ():
        if not isinstance(item, dict):
            continue
        minimum = item.get("minimum_compute_capability")
        try:
            minimum = int(minimum) if minimum is not None else None
        except (TypeError, ValueError):
            minimum = None
        rules.append(
            CompatibilityRule(
                code=str(item.get("code") or "compatibility_warning"),
                effect=str(item.get("effect") or "warning").strip().lower(),
                vendors=tuple(
                    str(vendor).strip().upper()
                    for vendor in (item.get("vendors") or ())
                    if str(vendor).strip()
                ),
                minimum_compute_capability=minimum,
                tag=str(item.get("tag") or "").strip(),
                tag_variant=str(item.get("tag_variant") or "danger").strip().lower(),
                warning_ru=str(item.get("warning_ru") or "").strip(),
                warning_en=str(item.get("warning_en") or "").strip(),
            )
        )
    return CompatibilitySpec(
        supported_vendors=tuple(
            str(vendor).strip().upper()
            for vendor in (data.get("supported_vendors") or ())
            if str(vendor).strip()
        ),
        rules=tuple(rules),
    )


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
    compatibility: CompatibilitySpec = field(default_factory=CompatibilitySpec)

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
            "compatibility": self.compatibility.as_dict(),
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
