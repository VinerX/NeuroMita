from abc import ABC, abstractmethod
import json
import os
from typing import Any, List, Optional

import numpy as np

from core.app_paths import settings_path
from core.backends import BackendKind
from core.install_requirements import InstallRequirement, check_requirements
from core.install_types import InstallAction, InstallPlan
from core.installables import (
    ComponentCategory,
    ComponentMetadata,
    ComponentStatus,
    ComponentStatusCode,
    ValidationResult,
    coerce_backend,
    make_component_id,
)
from core.installables.helpers import build_runtime_ctx, noop_plan, status_from_installed
from utils import _


def _asr_settings_path() -> str:
    return str(settings_path("asr_settings.json", create_parent=True))


def load_asr_model_settings(engine_id: str) -> dict:
    path = _asr_settings_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                models = payload.get("models", {})
                if isinstance(models, dict):
                    value = models.get(str(engine_id or "").strip(), {})
                    return dict(value) if isinstance(value, dict) else {}
    except Exception:
        return {}
    return {}


def save_asr_model_settings(engine_id: str, values: dict) -> None:
    path = _asr_settings_path()
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

    models = payload.get("models")
    if not isinstance(models, dict):
        models = {}
    models[str(engine_id or "").strip()] = dict(values or {})
    payload["models"] = models

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def validate_asr_model_settings(schema: List[dict], values: dict) -> ValidationResult:
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


class SpeechRecognizerInterface(ABC):
    MODEL_CONFIGS: List[dict] = []
    category = ComponentCategory.ASR
    legacy_kind = "asr"

    def get_model_configs(self) -> List[dict]:
        return list(getattr(self, "MODEL_CONFIGS", []) or [])

    def __init__(self, pip_installer, logger):
        self.pip_installer = pip_installer
        self.logger = logger
        self._is_initialized = False

    @property
    def item_id(self) -> str:
        configs = self.get_model_configs()
        if configs:
            value = str(configs[0].get("id") or "").strip()
            if value:
                return value
        return self.__class__.__name__.lower()

    @property
    def id(self) -> str:
        return make_component_id(self.category, self.item_id)

    def requirements(self) -> List[InstallRequirement]:
        return []

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        return []

    def required_backend(self, ctx: dict) -> BackendKind:
        return BackendKind.NONE

    def install_manifest(self) -> list[dict]:
        return []

    def metadata(self) -> ComponentMetadata:
        cfg = self.get_model_configs()[0] if self.get_model_configs() else {}
        settings = self.load_settings()
        run_ctx = build_runtime_ctx({"engine_settings": settings})
        try:
            self.apply_settings(settings)
        except Exception:
            pass
        backend = coerce_backend(self.required_backend(run_ctx))
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=str(cfg.get("name") or self.item_id),
            description=str(cfg.get("description") or ""),
            backend=backend,
            legacy_kind=self.legacy_kind,
            tags=tuple(str(item) for item in (cfg.get("tags") or []) if str(item).strip()),
            languages=tuple(str(item) for item in (cfg.get("languages") or []) if str(item).strip()),
        )

    def status(self, ctx: dict | None = None) -> ComponentStatus:
        run_ctx = build_runtime_ctx(ctx)
        settings = run_ctx.get("engine_settings") if isinstance(run_ctx.get("engine_settings"), dict) else self.load_settings()
        try:
            self.apply_settings(settings)
        except Exception:
            pass

        backend = coerce_backend(self.required_backend(run_ctx))
        try:
            installed = bool(self.is_installed())
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

    def build_install_plan(self, ctx: dict | None = None) -> InstallPlan:
        run_ctx = build_runtime_ctx(ctx)
        settings = run_ctx.get("engine_settings") if isinstance(run_ctx.get("engine_settings"), dict) else self.load_settings()
        try:
            self.apply_settings(settings)
        except Exception:
            pass

        try:
            # Clean reinstall skips this shortcut so a broken/partial install
            # is actually re-fetched instead of being reported "already installed".
            if self.is_installed() and not run_ctx.get("clean"):
                return InstallPlan(actions=[], already_installed=True, already_installed_status="Already installed")
        except Exception:
            pass

        steps = self.pip_install_steps(run_ctx) or []
        required_backend = coerce_backend(self.required_backend(run_ctx))
        timeout_sec = float(run_ctx.get("timeout_sec", 3600.0) or 3600.0)

        actions: list[InstallAction] = []
        for step in steps:
            pr = int(step.get("progress", 10) or 10)
            desc = str(step.get("description", "Installing...") or "Installing...")
            pkgs = step.get("packages")
            extra = step.get("extra_args")

            if isinstance(pkgs, str):
                packages = [pkgs]
            elif pkgs:
                packages = list(pkgs)
            else:
                packages = []

            actions.append(
                InstallAction(
                    type="pip",
                    description=desc,
                    progress=pr,
                    packages=packages,
                    extra_args=extra,
                )
            )

        manifest = self.install_manifest() or []
        if manifest:
            actions.append(
                InstallAction(
                    type="download_http",
                    description="Downloading model files...",
                    progress=75,
                    progress_to=99,
                    files=list(manifest),
                )
            )
        else:
            async def _install_artifacts_async(**_kwargs) -> bool:
                return bool(await self.install())

            actions.append(
                InstallAction(
                    type="call_async",
                    description="Downloading model files...",
                    progress=75,
                    fn=_install_artifacts_async,
                    timeout_sec=timeout_sec,
                )
            )

        def _final_check(**_kwargs) -> bool:
            try:
                installed = bool(self.is_installed())
            except Exception:
                # Не валим установку из-за сбоя самой проверки — считаем успешной.
                return True
            if not installed:
                # Раньше шаг просто возвращал False и пользователь видел только
                # «call step returned False: Finalizing...» без причины (фидбэк Артёма
                # «даже не понял что произошло»). Теперь пишем, чего не хватает.
                callbacks = _kwargs.get("callbacks")
                reason = self._diagnose_install_failure()
                if callbacks is not None and hasattr(callbacks, "log"):
                    try:
                        callbacks.log(
                            _("Проверка после установки не пройдена — не хватает: {reason}",
                              "Post-install check failed — missing: {reason}").format(reason=reason)
                        )
                    except Exception:
                        pass
            return installed

        actions.append(
            InstallAction(
                type="call",
                description="Finalizing...",
                progress=99,
                fn=_final_check,
            )
        )

        return InstallPlan(
            actions=actions,
            already_installed=False,
            ok_status="Done",
            required_backend=required_backend,
            backend_context=dict(run_ctx),
        )

    def _diagnose_install_failure(self) -> str:
        """Человекочитаемая причина, почему is_installed() == False после установки:
        недостающие python-модули/бэкенд из requirements() + отсутствующие файлы
        модели из install_manifest()."""
        parts: list[str] = []
        try:
            ctx = {
                "device": getattr(self, "gigaam_device", None) or getattr(self, "device", None),
                "gpu_vendor": getattr(self, "_current_gpu", None) or "CPU",
            }
            st = check_requirements(self.requirements(), ctx=ctx)
            for missing in (st.get("missing_required") or []):
                parts.append(str(missing))
        except Exception:
            pass
        try:
            for item in (self.install_manifest() or []):
                dest = str(item.get("dest") or "").strip()
                if dest and (not os.path.exists(dest) or os.path.getsize(dest) <= 0):
                    parts.append(os.path.basename(dest) or dest)
        except Exception:
            pass
        if not parts:
            return _("неизвестно (см. строки лога выше)", "unknown (see log lines above)")
        return "; ".join(dict.fromkeys(parts))  # dedup, сохраняя порядок

    def uninstall_pip_packages(self) -> list[str]:
        """Pip-пакеты для удаления при uninstall — ТОЛЬКО эксклюзивные для этого
        движка. Общие (transformers/pyyaml/sounddevice/silero-vad и т.п.) не
        перечисляем: они нужны другим компонентам. Удаляются некаскадно."""
        return []

    def uninstall_paths(self) -> list[str]:
        """Каталоги/файлы модели (кэш весов) для удаления при uninstall."""
        return []

    def build_uninstall_plan(self, ctx: dict | None = None) -> InstallPlan:
        import shutil

        pkgs = [str(p).strip() for p in (self.uninstall_pip_packages() or []) if str(p).strip()]
        paths = [str(p).strip() for p in (self.uninstall_paths() or []) if str(p).strip()]

        actions: List[InstallAction] = []

        if pkgs:
            def _do_uninstall_pkgs(*, pip_installer=None, callbacks=None, **_kwargs) -> bool:
                if pip_installer is None:
                    return True
                try:
                    # include_dependencies=False: сносим только эти пакеты, без их
                    # дерева зависимостей — иначе снесли бы общие с transformers/RAG.
                    return bool(pip_installer.uninstall_packages(
                        pkgs,
                        _("Удаление пакетов движка...", "Removing engine packages..."),
                        include_dependencies=False,
                    ))
                except Exception as exc:
                    if callbacks is not None:
                        try:
                            callbacks.log(str(exc))
                        except Exception:
                            pass
                    return False

            actions.append(InstallAction(
                type="call",
                description=_("Удаление пакетов движка...", "Removing engine packages..."),
                progress=20,
                fn=_do_uninstall_pkgs,
            ))

        if paths:
            def _do_remove_paths(*, callbacks=None, **_kwargs) -> bool:
                for p in paths:
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        elif os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                return True

            actions.append(InstallAction(
                type="call",
                description=_("Удаление файлов модели...", "Removing model files..."),
                progress=85,
                fn=_do_remove_paths,
            ))

        if not actions:
            return noop_plan("Nothing to uninstall for this ASR engine.")
        return InstallPlan(actions=actions, ok_status=_("Удалено", "Uninstalled"))

    def build_initialize_plan(self, ctx: dict | None = None) -> InstallPlan | None:
        return None

    @abstractmethod
    async def install(self) -> bool:
        pass

    @abstractmethod
    async def init(self, **kwargs) -> bool:
        pass

    @abstractmethod
    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        pass

    @abstractmethod
    async def live_recognition(self, microphone_index: int, handle_voice_callback,
                               vad_model, active_flag, **kwargs) -> None:
        pass

    @abstractmethod
    def cleanup(self) -> None:
        pass

    @abstractmethod
    def is_installed(self) -> bool:
        pass

    def settings_spec(self) -> List[dict]:
        return []

    def get_default_settings(self) -> dict:
        return {}

    def apply_settings(self, settings: dict) -> None:
        return

    def settings_schema(self) -> List[dict]:
        return list(self.settings_spec() or [])

    def load_settings(self) -> dict:
        data = load_asr_model_settings(self.item_id)
        if data:
            return data
        return dict(self.get_default_settings() or {})

    def validate_settings(self, values: dict) -> ValidationResult:
        return validate_asr_model_settings(self.settings_schema(), values)

    def save_settings(self, values: dict) -> None:
        result = self.validate_settings(values)
        if not result.ok:
            raise ValueError(f"Invalid settings for {self.item_id}: {result.errors}")
        save_asr_model_settings(self.item_id, values)

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized
