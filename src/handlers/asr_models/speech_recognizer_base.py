from abc import ABC, abstractmethod
import os
from typing import Any, List, Optional

import numpy as np

from core.backends import BackendKind
from core.install_requirements import InstallRequirement, check_requirements
from core.install_types import DEFAULT_INSTALL_TIMEOUT_SEC, InstallAction, InstallPlan
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
from services.asr_settings_service import ensure_asr_settings_service
from utils import _


def load_asr_model_settings(engine_id: str) -> dict:
    return ensure_asr_settings_service().model_settings(engine_id)


def save_asr_model_settings(engine_id: str, values: dict) -> None:
    ensure_asr_settings_service().set_model_settings(engine_id, values)


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
        # Глоссарий движков (список моделей в UI) считается в основном GUI-процессе,
        # где зависимости движка (faster_whisper, torch, ctranslate2, …) лежат в
        # изолированном оверлее resolved-среды и НЕ видны через sys.path. Без путей
        # среды is_installed()/бэкенд-проверка ложно считают установленный движок
        # «не установленным», и он пропадает из выбора. Подставляем пути закоммиченной
        # среды этого компонента. В AI-воркере пути уже приходят через
        # NEUROMITA_RUNTIME_* (python_paths заполнен) — там ничего не трогаем.
        if not run_ctx.get("python_paths"):
            try:
                from core.runtime_environments import runtime_environments

                mgr = runtime_environments()
                category = getattr(self.category, "value", self.category)
                record = mgr.active_for(category=str(category), item_id=self.item_id)
                env_paths = mgr.runtime_paths(record) if record is not None else ()
                if env_paths:
                    run_ctx["python_paths"] = list(env_paths)
                    run_ctx.setdefault("target_dir", env_paths[0])
                    run_ctx["strict_target"] = True
            except Exception:
                pass

        settings = run_ctx.get("engine_settings") if isinstance(run_ctx.get("engine_settings"), dict) else self.load_settings()
        try:
            self.apply_settings(settings)
        except Exception:
            pass

        backend = coerce_backend(self.required_backend(run_ctx))
        try:
            installed = bool(self.is_installed(run_ctx))
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
            if self.status(run_ctx).ready and not run_ctx.get("clean"):
                return InstallPlan(actions=[], already_installed=True, already_installed_status="Already installed")
        except Exception:
            pass

        steps = self.pip_install_steps(run_ctx) or []
        required_backend = coerce_backend(self.required_backend(run_ctx))
        timeout_sec = float(run_ctx.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC) or DEFAULT_INSTALL_TIMEOUT_SEC)

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
            callbacks = _kwargs.get("callbacks")
            check_ctx = build_runtime_ctx(_kwargs.get("ctx") or run_ctx)
            try:
                installed = bool(self.is_installed(check_ctx))
            except Exception as exc:
                if callbacks is not None and hasattr(callbacks, "log"):
                    callbacks.log(f"Post-install validation crashed: {exc}")
                return False
            if not installed:
                # Раньше шаг просто возвращал False и пользователь видел только
                # «call step returned False: Finalizing...» без причины (фидбэк Артёма
                # «даже не понял что произошло»). Теперь пишем, чего не хватает.
                reason = self._diagnose_install_failure(check_ctx)
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

    def _diagnose_install_failure(self, ctx: dict | None = None) -> str:
        """Человекочитаемая причина, почему is_installed() == False после установки:
        недостающие python-модули/бэкенд из requirements() + отсутствующие файлы
        модели из install_manifest()."""
        parts: list[str] = []
        try:
            run_ctx = build_runtime_ctx(ctx)
            run_ctx.setdefault(
                "device",
                getattr(self, "gigaam_device", None) or getattr(self, "device", None),
            )
            run_ctx.setdefault("gpu_vendor", getattr(self, "_current_gpu", None) or "CPU")
            st = check_requirements(self.requirements(), ctx=run_ctx)
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
                environment_mutation=True,
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
    def cleanup(self) -> None:
        pass

    @abstractmethod
    def is_installed(self, ctx: dict | None = None) -> bool:
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
