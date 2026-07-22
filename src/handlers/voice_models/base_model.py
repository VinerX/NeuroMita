import abc
import json
import os
from typing import Any, Dict, List, Optional

from core.app_paths import settings_path
from core.backends import BackendKind
from core.install_types import InstallPlan
from core.installables import (
    ComponentCategory,
    ComponentMetadata,
    ComponentStatus,
    ComponentStatusCode,
    ValidationResult,
    coerce_compatibility_spec,
    coerce_backend,
    make_component_id,
)
from core.installables.helpers import build_runtime_ctx, status_from_installed
from handlers.voice_models.context import VoiceRuntimeContext


def _voice_settings_path() -> str:
    return str(settings_path("voice_model_settings.json", create_parent=True))


def load_voice_model_settings(model_id: str) -> Dict[str, Any]:
    path = _voice_settings_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                value = payload.get(str(model_id or "").strip(), {})
                return dict(value) if isinstance(value, dict) else {}
    except Exception:
        return {}
    return {}


def save_voice_model_settings(model_id: str, values: Dict[str, Any]) -> None:
    path = _voice_settings_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    payload: dict[str, Any] = {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                payload = raw
    except Exception:
        payload = {}

    payload[str(model_id or "").strip()] = dict(values or {})
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def validate_voice_model_settings(schema: List[Dict[str, Any]], values: Dict[str, Any]) -> ValidationResult:
    if not isinstance(values, dict):
        return ValidationResult(ok=False, errors={"_": "Settings payload must be a dictionary."})

    allowed = {
        str(item.get("key") or "").strip()
        for item in (schema or [])
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    errors: dict[str, str] = {}
    for key in values.keys():
        name = str(key or "").strip()
        if name and name not in allowed:
            errors[name] = "Unknown setting."
    return ValidationResult(ok=not errors, errors=errors)


class _InstallableVoiceParent:
    def load_model_settings(self, model_id: str) -> Dict[str, Any]:
        return load_voice_model_settings(model_id)


class IVoiceModel(abc.ABC):
    """
    Абстрактный базовый класс (интерфейс) для всех моделей озвучки.
    Определяет контракт, которому должны следовать все классы моделей.
    """

    category = ComponentCategory.TTS
    legacy_kind = "voice"

    def __init__(self, parent: VoiceRuntimeContext, model_id: str):
        self.parent = parent
        self.model_id = str(model_id or "").strip()
        self.initialized = False
        self.initialized_for: Optional[str] = None

    @property
    def item_id(self) -> str:
        return self.model_id

    @property
    def id(self) -> str:
        return make_component_id(self.category, self.item_id)

    @classmethod
    def supported_model_ids(cls) -> List[str]:
        result: List[str] = []
        for item in getattr(cls, "MODEL_CONFIGS", []) or []:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id:
                result.append(model_id)
        return result

    @classmethod
    def _find_model_config(cls, model_id: str) -> Dict[str, Any]:
        target = str(model_id or "").strip()
        for item in getattr(cls, "MODEL_CONFIGS", []) or []:
            if isinstance(item, dict) and str(item.get("id") or "").strip() == target:
                return dict(item)
        return {}

    @classmethod
    def default_settings_for_model(cls, model_id: str) -> Dict[str, Any]:
        """Return the schema defaults for a model without persisting them."""
        defaults: Dict[str, Any] = {}
        config = cls._find_model_config(model_id)
        for setting in config.get("settings") or []:
            if not isinstance(setting, dict):
                continue
            key = str(setting.get("key") or "").strip()
            options = setting.get("options")
            if key and isinstance(options, dict) and "default" in options:
                defaults[key] = options["default"]
        return defaults

    @classmethod
    def resolve_settings_for_model(cls, model_id: str, values: Dict[str, Any] | None) -> Dict[str, Any]:
        """Overlay persisted settings onto the model schema defaults."""
        resolved = cls.default_settings_for_model(model_id)
        if isinstance(values, dict):
            resolved.update(values)
        return resolved

    @classmethod
    def create_installable_components(cls) -> List["IVoiceModel"]:
        return [cls(_InstallableVoiceParent(), model_id) for model_id in cls.supported_model_ids()]

    @classmethod
    def required_backend_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> BackendKind:
        return BackendKind.NONE

    @classmethod
    def is_model_installed(cls, model_id: str, ctx: Dict[str, Any]) -> bool:
        raise NotImplementedError

    @classmethod
    def build_install_plan_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> InstallPlan:
        raise NotImplementedError

    @classmethod
    def build_uninstall_plan_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> InstallPlan:
        raise NotImplementedError

    @abc.abstractmethod
    def get_display_name(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def initialize(self, init: bool = False) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def get_model_configs(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def metadata(self) -> ComponentMetadata:
        config = self._find_model_config(self.model_id)
        # Каталожный backend — статичное свойство компонента из карточки модели.
        # required_backend_for_model остаётся для install/status: он может зависеть
        # от машины (например, F5 предпочитает CUDA, но работает на CPU).
        declared_backend = config.get("backend")
        if declared_backend:
            backend = coerce_backend(declared_backend)
        else:
            runtime_ctx = build_runtime_ctx({})
            backend = coerce_backend(self.__class__.required_backend_for_model(self.model_id, runtime_ctx))

        size_value = config.get("size_gb")
        size = ""
        if isinstance(size_value, (int, float)) and float(size_value) > 0:
            size = f"~{float(size_value):g} GB"

        tags: list[str] = []
        for item in config.get("intents") or []:
            text = str(item or "").strip()
            if text:
                tags.append(text)

        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=str(config.get("name") or self.item_id),
            description=str(config.get("description") or ""),
            backend=backend,
            legacy_kind=self.legacy_kind,
            tags=tuple(tags),
            languages=tuple(str(item) for item in (config.get("languages") or []) if str(item).strip()),
            size=size,
            compatibility=coerce_compatibility_spec(config.get("compatibility")),
        )

    def status(self, ctx: Dict[str, Any] | None = None) -> ComponentStatus:
        run_ctx = build_runtime_ctx(ctx)
        backend = coerce_backend(self.__class__.required_backend_for_model(self.model_id, run_ctx))
        try:
            installed = bool(self.__class__.is_model_installed(self.model_id, run_ctx))
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
        return status_from_installed(
            component_id=self.id,
            installed=installed,
            backend=backend,
            ctx=run_ctx,
        )

    def build_install_plan(self, ctx: Dict[str, Any] | None = None) -> InstallPlan:
        return self.__class__.build_install_plan_for_model(self.model_id, build_runtime_ctx(ctx))

    def build_uninstall_plan(self, ctx: Dict[str, Any] | None = None) -> InstallPlan:
        return self.__class__.build_uninstall_plan_for_model(self.model_id, build_runtime_ctx(ctx))

    def build_initialize_plan(self, ctx: Dict[str, Any] | None = None) -> InstallPlan | None:
        return None

    def settings_schema(self) -> List[Dict[str, Any]]:
        return list(self._find_model_config(self.model_id).get("settings") or [])

    def load_settings(self) -> Dict[str, Any]:
        return self.resolve_settings_for_model(
            self.model_id,
            load_voice_model_settings(self.model_id),
        )

    def validate_settings(self, values: Dict[str, Any]) -> ValidationResult:
        return validate_voice_model_settings(self.settings_schema(), values)

    def save_settings(self, values: Dict[str, Any]) -> None:
        result = self.validate_settings(values)
        if not result.ok:
            raise ValueError(f"Invalid settings for {self.model_id}: {result.errors}")
        save_voice_model_settings(self.model_id, values)

    def cleanup_state(self) -> None:
        self.initialized = False
        self.initialized_for = None

    def load_model_settings(self) -> Dict[str, Any]:
        return self.parent.load_model_settings(self.model_id)
