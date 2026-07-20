from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

from core.backends import BackendKind, get_backend_service
from core.events import Events, get_event_bus
from core.install_requirements import InstallRequirement, check_requirements
from core.install_types import InstallAction, InstallPlan
from core.installables import ComponentCategory, ComponentMetadata, coerce_backend, make_component_id
from core.installables.helpers import build_runtime_ctx, noop_plan, status_from_installed
from handlers.embedding_presets import resolve_full_config
from managers.rag.pipeline.config import resolve_ce_model
try:
    from managers.settings_manager import SettingsManager
except Exception:
    class SettingsManager:
        instance = None

        @staticmethod
        def get(_key, default=None):
            return default
from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider


TARGET_EMBEDDINGS = "embeddings"
TARGET_RERANKER = "reranker"
TARGET_CURRENT = "current"

TRANSFORMERS_SPEC = "transformers>=4.45.2"
HF_HUB_SPEC = "huggingface-hub"
BITSANDBYTES_SPEC = "bitsandbytes>=0.43.0"

_LM_RERANKER_PATTERNS = (
    "qwen3-reranker",
    "qwen/qwen3-reranker",
)

# Windows cannot pass arbitrarily large timeouts to the thread wait used by
# subprocess.communicate().  Keep each individual wait comfortably below that
# platform limit while preserving the installation's overall timeout.
_SUBPROCESS_WAIT_SLICE_SEC = 86_400.0


def _target_title(target: str) -> str:
    normalized = str(target or "").strip().lower()
    if normalized == TARGET_EMBEDDINGS:
        model_name = _local_embed_model_name()
        return model_name or "RAG embeddings"
    if normalized == TARGET_RERANKER:
        model_name = resolve_ce_model()
        return model_name or "RAG reranker"
    return str(target or "rag")


def _detect_gpu_vendor(ctx: dict[str, Any] | None = None) -> str:
    if ctx and ctx.get("gpu_vendor"):
        return str(ctx.get("gpu_vendor") or "CPU")
    try:
        return str(check_gpu_provider() or "CPU")
    except Exception:
        return "CPU"


def _with_gpu_ctx(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(ctx or {})
    data["gpu_vendor"] = _detect_gpu_vendor(data)
    return data


def _checkpoints_dir() -> str:
    val = os.environ.get("NEUROMITA_CHECKPOINTS_DIR")
    if val:
        return val
    base = os.environ.get("NEUROMITA_BASE_DIR")
    if base:
        return os.path.join(base, "checkpoints")
    return os.path.join(os.path.dirname(sys.executable), "checkpoints")


def _cache_marker_path(repo_id: str) -> str:
    return os.path.join(_checkpoints_dir(), "models--" + str(repo_id or "").replace("/", "--"))


def _is_lm_reranker_model(model_name: str) -> bool:
    lower = str(model_name or "").strip().lower()
    return any(p in lower for p in _LM_RERANKER_PATTERNS)


def _local_embed_model_name() -> str:
    cfg = resolve_full_config()
    return str(cfg.get("hf_name") or cfg.get("model") or "").strip()


def _local_provider_enabled() -> bool:
    cfg = resolve_full_config()
    return str(cfg.get("provider_name") or "local").strip().lower() == "local"


def _setting_value(settings: Any | None, key: str, default: Any = None) -> Any:
    if settings is not None:
        try:
            return settings.get(key, default)
        except Exception:
            pass
    return SettingsManager.get(key, default)


def _setting_enabled(settings: Any | None, key: str, default: bool = False) -> bool:
    value = _setting_value(settings, key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def required_model_targets(settings: Any | None = None) -> list[str]:
    """Return the model targets required by the effective RAG configuration.

    The optional settings service is used by UI callers; installation and
    status paths without an explicit service retain the SettingsManager-backed
    application behavior. Keeping this decision here prevents the UI and
    installer from developing different interpretations of enabled RAG.
    """
    if not _setting_enabled(settings, "RAG_ENABLED"):
        return []

    targets: list[str] = []
    if _local_provider_enabled() and _setting_enabled(
        settings, "RAG_VECTOR_SEARCH_ENABLED"
    ):
        targets.append(TARGET_EMBEDDINGS)

    ce_model = resolve_ce_model()
    if _setting_enabled(settings, "RAG_CROSS_ENCODER_ENABLED") and ce_model:
        targets.append(TARGET_RERANKER)

    return targets


def missing_model_targets(
    settings: Any | None = None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return enabled RAG targets whose model files are still missing.

    Python/package requirements intentionally do not participate in this
    result. The caller uses it only to offer downloads for concrete model
    artifacts selected by the effective RAG configuration.
    """

    missing: list[tuple[str, tuple[str, ...]]] = []
    for target in required_model_targets(settings=settings):
        status = get_install_status(target)
        models = tuple(
            str(model)
            for model in status.get("download_models", ())
            if str(model).strip()
        )
        if models:
            missing.append((str(target), models))
    return tuple(missing)


def _current_targets() -> list[str]:
    return required_model_targets()


def _resolve_targets(target: str) -> list[str]:
    normalized = str(target or "").strip().lower()
    if normalized == TARGET_CURRENT:
        return _current_targets()
    if normalized in (TARGET_EMBEDDINGS, TARGET_RERANKER):
        return [normalized]
    raise ValueError(f"Unknown RAG install target: {target}")


def _merge_requirement_status(summary: dict[str, Any], checked: dict[str, Any]) -> None:
    known_ids = {str(d.get("id") or "") for d in summary["details"]}
    for detail in checked.get("details") or []:
        req_id = str(detail.get("id") or "")
        if req_id and req_id in known_ids:
            continue
        summary["details"].append(detail)
        if req_id:
            known_ids.add(req_id)

    for req_id in checked.get("missing_required") or []:
        if req_id not in summary["missing_required"]:
            summary["missing_required"].append(req_id)


def _required_backend(ctx: dict[str, Any]) -> BackendKind:
    return get_backend_service().preferred_torch_kind(ctx)


def _backend_requirement(ctx: dict[str, Any]) -> InstallRequirement:
    backend_kind = _required_backend(ctx)
    return InstallRequirement(
        id=f"backend_{backend_kind.value}",
        kind="backend",
        backend_kind=backend_kind,
        required=True,
    )


def _embed_requirements(ctx: dict[str, Any]) -> list[InstallRequirement]:
    return [
        _backend_requirement(ctx),
        InstallRequirement(id="transformers", kind="python_dist", spec=TRANSFORMERS_SPEC, required=True),
        InstallRequirement(id="huggingface_hub", kind="python_dist", spec=HF_HUB_SPEC, required=True),
    ]


def _reranker_requirements(ctx: dict[str, Any], ce_model: str | None = None) -> list[InstallRequirement]:
    ce_model = str(ce_model or "").strip() or resolve_ce_model()
    reqs = [
        _backend_requirement(ctx),
        InstallRequirement(id="transformers", kind="python_dist", spec=TRANSFORMERS_SPEC, required=True),
        InstallRequirement(id="huggingface_hub", kind="python_dist", spec=HF_HUB_SPEC, required=True),
    ]

    use_int8 = bool(SettingsManager.get("RAG_CE_INT8", False))
    if use_int8 and ce_model and (not _is_lm_reranker_model(ce_model)) and str(ctx.get("gpu_vendor") or "").upper() == "NVIDIA":
        reqs.append(
            InstallRequirement(
                id="bitsandbytes",
                kind="python_dist",
                spec=BITSANDBYTES_SPEC,
                required=True,
            )
        )
    return reqs


def get_install_status(target: str, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = _with_gpu_ctx(ctx)
    resolved_targets = _resolve_targets(target)

    summary: dict[str, Any] = {
        "target": str(target or ""),
        "resolved_targets": list(resolved_targets),
        "required": False,
        "ok": True,
        "missing_required": [],
        "details": [],
        "download_models": [],
        "needs_local_runtime": False,
        "needs_bitsandbytes": False,
        "required_backend": None,
        "gpu_vendor": ctx.get("gpu_vendor"),
    }

    for item in resolved_targets:
        if item == TARGET_EMBEDDINGS:
            if not _local_provider_enabled():
                continue

            summary["required"] = True
            summary["needs_local_runtime"] = True
            summary["required_backend"] = _required_backend(ctx).value
            embed_model = _local_embed_model_name()
            if embed_model and not os.path.isdir(_cache_marker_path(embed_model)):
                summary["ok"] = False
                if "embedding_model" not in summary["missing_required"]:
                    summary["missing_required"].append("embedding_model")
                if embed_model not in summary["download_models"]:
                    summary["download_models"].append(embed_model)

            checked = check_requirements(_embed_requirements(ctx), ctx=ctx)
            _merge_requirement_status(summary, checked)
            if not checked.get("ok"):
                summary["ok"] = False

        elif item == TARGET_RERANKER:
            ce_model = resolve_ce_model()
            if not ce_model:
                continue

            summary["required"] = True
            summary["needs_local_runtime"] = True
            summary["required_backend"] = _required_backend(ctx).value
            if not os.path.isdir(_cache_marker_path(ce_model)):
                summary["ok"] = False
                if "reranker_model" not in summary["missing_required"]:
                    summary["missing_required"].append("reranker_model")
                if ce_model not in summary["download_models"]:
                    summary["download_models"].append(ce_model)

            checked = check_requirements(_reranker_requirements(ctx), ctx=ctx)
            _merge_requirement_status(summary, checked)
            if not checked.get("ok"):
                summary["ok"] = False

            use_int8 = bool(SettingsManager.get("RAG_CE_INT8", False))
            if use_int8 and (not _is_lm_reranker_model(ce_model)) and str(ctx.get("gpu_vendor") or "").upper() == "NVIDIA":
                summary["needs_bitsandbytes"] = True

    if not summary["required"]:
        summary["ok"] = True

    return summary


def ensure_runtime_ready(target: str, *, ctx: dict[str, Any] | None = None) -> None:
    # Проверка готовности выполняется внутри worker-процесса, где реальные
    # пакеты бэкенда лежат в разделённом runtime-слое (NEUROMITA_RUNTIME_*),
    # а не в NEUROMITA_LIB_DIR (Lib/core). Без build_runtime_ctx проверка
    # смотрела в core и ложно сообщала «backend_cuda is not installed».
    status = get_install_status(target, ctx=build_runtime_ctx(ctx))
    if not status.get("required"):
        return
    if status.get("ok"):
        return

    missing = list(status.get("missing_required") or [])
    detail = ", ".join(missing) if missing else "unknown"
    raise RuntimeError(
        _("RAG backend is not installed: {items}", "RAG backend is not installed: {items}").format(items=detail)
    )


def _snapshot_download_action(repo_id: str, *, description: str, progress: int) -> InstallAction:
    def _fn(*, pip_installer=None, callbacks=None, ctx=None, **_kwargs) -> bool:
        runtime_ctx = dict(ctx or {})
        python_paths = [
            os.path.abspath(str(path))
            for path in (runtime_ctx.get("python_paths") or [])
            if str(path).strip()
        ]
        python_executable = str(
            runtime_ctx.get("python_executable")
            or getattr(pip_installer, "script_path", None)
            or os.environ.get("NEUROMITA_PYTHON")
            or sys.executable
        )
        token = str(SettingsManager.get("HF_TOKEN", "") or "").strip() or None
        cache_dir = _checkpoints_dir()
        os.makedirs(cache_dir, exist_ok=True)
        if callbacks is not None:
            try:
                callbacks.log(f"snapshot_download: {repo_id}")
            except Exception:
                pass

        script = (
            "import json, os, sys\n"
            "sys.path[:0] = json.loads(sys.argv[1])\n"
            "from huggingface_hub import snapshot_download\n"
            "snapshot_download(repo_id=sys.argv[2], cache_dir=sys.argv[3], "
            "token=(os.environ.get('HF_TOKEN') or None))\n"
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        if token:
            env["HF_TOKEN"] = token
        else:
            env.pop("HF_TOKEN", None)

        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                python_executable,
                "-c",
                script,
                json.dumps(python_paths),
                str(repo_id),
                str(cache_dir),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
        )
        register = getattr(pip_installer, "_set_active_process", None)
        terminate = getattr(pip_installer, "_terminate_process", None)
        clear = getattr(pip_installer, "_clear_active_process", None)
        if callable(register) and callable(terminate):
            register(
                process,
                lambda: terminate(process, "RAG model download cancelled."),
            )
        try:
            timeout = max(1.0, float(runtime_ctx.get("timeout_sec", 3600.0) or 3600.0))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if callable(terminate):
                        terminate(process, "RAG model download timed out.")
                    else:
                        process.kill()
                    output, _ = process.communicate()
                    if callbacks is not None:
                        callbacks.log("RAG model download timed out.")
                    return False

                try:
                    output, _ = process.communicate(
                        timeout=min(remaining, _SUBPROCESS_WAIT_SLICE_SEC)
                    )
                    break
                except subprocess.TimeoutExpired:
                    # A slice elapsed, but the overall installation timeout has
                    # not: keep waiting without passing an oversized timeout to
                    # the Windows thread primitive.
                    continue

            if output and callbacks is not None:
                for line in output.splitlines():
                    if line.strip():
                        callbacks.log(line)
            return process.returncode == 0
        finally:
            if callable(clear):
                clear(process)

    return InstallAction(
        type="call",
        description=description,
        progress=int(progress),
        fn=_fn,
    )


def build_install_plan(
    target: str,
    *,
    pip_installer=None,
    callbacks=None,
    timeout_sec: float = 3600.0,
) -> InstallPlan:
    ctx = _with_gpu_ctx({
        "timeout_sec": float(timeout_sec or 3600.0),
        "libs_dir": os.environ.get("NEUROMITA_LIB_DIR"),
    })
    status = get_install_status(target, ctx=ctx)

    if not status.get("required"):
        return InstallPlan(
            actions=[],
            already_installed=True,
            already_installed_status=_("Not required", "Not required"),
        )

    if status.get("ok"):
        return InstallPlan(
            actions=[],
            already_installed=True,
            already_installed_status=_("Already installed", "Already installed"),
        )

    actions: list[InstallAction] = []

    if status.get("needs_local_runtime"):
        actions.append(
            InstallAction(
                type="pip",
                description=_("Installing local RAG dependencies...", "Installing local RAG dependencies..."),
                progress=35,
                packages=[TRANSFORMERS_SPEC, HF_HUB_SPEC],
            )
        )

    if status.get("needs_bitsandbytes"):
        actions.append(
            InstallAction(
                type="pip",
                description=_("Installing INT8 reranker support...", "Installing INT8 reranker support..."),
                progress=50,
                packages=[BITSANDBYTES_SPEC],
            )
        )

    downloads = list(status.get("download_models") or [])
    total_downloads = max(1, len(downloads))
    for idx, repo_id in enumerate(downloads):
        start_progress = 65 + int((idx * 25) / total_downloads)
        actions.append(
            _snapshot_download_action(
                repo_id,
                description=_("Downloading model: {name}", "Downloading model: {name}").format(name=repo_id),
                progress=start_progress,
            )
        )

    def _final_check(*, ctx=None, **_kwargs) -> bool:
        return bool(get_install_status(target, ctx=_with_gpu_ctx(dict(ctx or {}))).get("ok"))

    actions.append(
        InstallAction(
            type="call",
            description=_("Finalizing RAG backend...", "Finalizing RAG backend..."),
            progress=99,
            fn=_final_check,
        )
    )

    required_backend = None
    if status.get("needs_local_runtime"):
        required_backend = _required_backend(ctx)

    return InstallPlan(
        actions=actions,
        ok_status=_("Done", "Done"),
        required_backend=required_backend,
        backend_context=dict(ctx),
    )


# ---------------------------------------------------------------------------
# Per-model install path (AI Hub «список моделей»).
#
# В отличие от target-based пути (который резолвит АКТИВНУЮ модель из настроек
# RAG), эти функции работают с ЯВНО заданной моделью — карточка в AI Hub ставит
# именно ту модель, что на ней написана. Все embed/reranker модели используют
# общее окружение (torch + transformers), а веса лежат в отдельном кэше
# checkpoints, поэтому item_id окружения остаётся "embeddings"/"reranker".
# ---------------------------------------------------------------------------


def model_install_status(kind: str, hf_id: str, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = _with_gpu_ctx(ctx)
    kind = str(kind or "").strip().lower()
    hf_id = str(hf_id or "").strip()

    summary: dict[str, Any] = {
        "target": kind,
        "model": hf_id,
        "required": bool(hf_id),
        "ok": True,
        "missing_required": [],
        "details": [],
        "download_models": [],
        "needs_local_runtime": bool(hf_id),
        "needs_bitsandbytes": False,
        "required_backend": _required_backend(ctx).value if hf_id else None,
        "gpu_vendor": ctx.get("gpu_vendor"),
    }
    if not hf_id:
        return summary

    if not os.path.isdir(_cache_marker_path(hf_id)):
        summary["ok"] = False
        marker = "reranker_model" if kind == TARGET_RERANKER else "embedding_model"
        summary["missing_required"].append(marker)
        summary["download_models"].append(hf_id)

    if kind == TARGET_RERANKER:
        checked = check_requirements(_reranker_requirements(ctx, ce_model=hf_id), ctx=ctx)
        use_int8 = bool(SettingsManager.get("RAG_CE_INT8", False))
        if use_int8 and (not _is_lm_reranker_model(hf_id)) and str(ctx.get("gpu_vendor") or "").upper() == "NVIDIA":
            summary["needs_bitsandbytes"] = True
    else:
        checked = check_requirements(_embed_requirements(ctx), ctx=ctx)

    _merge_requirement_status(summary, checked)
    if not checked.get("ok"):
        summary["ok"] = False

    return summary


def build_model_install_plan(
    kind: str,
    hf_id: str,
    *,
    pip_installer=None,
    callbacks=None,
    timeout_sec: float = 3600.0,
) -> InstallPlan:
    ctx = _with_gpu_ctx({
        "timeout_sec": float(timeout_sec or 3600.0),
        "libs_dir": os.environ.get("NEUROMITA_LIB_DIR"),
    })
    status = model_install_status(kind, hf_id, ctx=ctx)

    if not status.get("required"):
        return InstallPlan(actions=[], already_installed=True,
                           already_installed_status=_("Not required", "Not required"))
    if status.get("ok"):
        return InstallPlan(actions=[], already_installed=True,
                           already_installed_status=_("Already installed", "Already installed"))

    actions: list[InstallAction] = []
    if status.get("needs_local_runtime"):
        actions.append(
            InstallAction(
                type="pip",
                description=_("Installing local RAG dependencies...", "Installing local RAG dependencies..."),
                progress=35,
                packages=[TRANSFORMERS_SPEC, HF_HUB_SPEC],
            )
        )
    if status.get("needs_bitsandbytes"):
        actions.append(
            InstallAction(
                type="pip",
                description=_("Installing INT8 reranker support...", "Installing INT8 reranker support..."),
                progress=50,
                packages=[BITSANDBYTES_SPEC],
            )
        )

    downloads = list(status.get("download_models") or [])
    total_downloads = max(1, len(downloads))
    for idx, repo_id in enumerate(downloads):
        start_progress = 65 + int((idx * 25) / total_downloads)
        actions.append(
            _snapshot_download_action(
                repo_id,
                description=_("Downloading model: {name}", "Downloading model: {name}").format(name=repo_id),
                progress=start_progress,
            )
        )

    def _final_check(*, ctx=None, **_kwargs) -> bool:
        return bool(model_install_status(kind, hf_id, ctx=_with_gpu_ctx(dict(ctx or {}))).get("ok"))

    actions.append(
        InstallAction(
            type="call",
            description=_("Finalizing RAG backend...", "Finalizing RAG backend..."),
            progress=99,
            fn=_final_check,
        )
    )

    required_backend = _required_backend(ctx) if status.get("needs_local_runtime") else None
    return InstallPlan(
        actions=actions,
        ok_status=_("Done", "Done"),
        required_backend=required_backend,
        backend_context=dict(ctx),
    )


class RagModelInstallableComponent:
    """AI Hub карточка конкретной RAG-модели (embed или reranker).

    id уникален на модель (`rag:embeddings:<slug>`), но item_id = вид
    ("embeddings"/"reranker"), чтобы все модели вида делили одно runtime-
    окружение (torch/transformers). Отличается только скачиваемая модель.
    """

    category = ComponentCategory.RAG
    legacy_kind = "rag"

    def __init__(self, kind: str, hf_id: str, display: str = "") -> None:
        from managers.rag.model_catalog import component_id_for, slugify_model

        self.kind = str(kind or "").strip().lower()
        self.hf_id = str(hf_id or "").strip()
        self.display = str(display or self.hf_id)
        self.item_id = self.kind
        self.slug = slugify_model(self.hf_id)
        self.id = component_id_for(self.kind, self.slug)

    def metadata(self) -> ComponentMetadata:
        # Каталожный backend — статичное свойство компонента (HF-модели работают
        # и на CPU). Машинно-зависимый required_backend остаётся в status().
        backend = BackendKind.CPU
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=self.hf_id,
            description=self.display,
            backend=backend,
            legacy_kind=self.legacy_kind,
            tags=("rag", self.kind),
        )

    def status(self, ctx: dict[str, Any] | None = None):
        run_ctx = build_runtime_ctx(ctx)
        data = model_install_status(self.kind, self.hf_id, ctx=run_ctx)
        backend = coerce_backend(data.get("required_backend"))
        installed = bool(data.get("ok", False))
        return status_from_installed(
            component_id=self.id,
            installed=installed,
            backend=backend,
            ctx=run_ctx,
            details=dict(data or {}),
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        run_ctx = build_runtime_ctx(ctx)
        return build_model_install_plan(
            self.kind,
            self.hf_id,
            pip_installer=run_ctx.get("pip_installer"),
            callbacks=run_ctx.get("callbacks"),
            timeout_sec=float(run_ctx.get("timeout_sec", 3600.0) or 3600.0),
        )

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        return noop_plan("RAG uninstall is not implemented yet.")

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


class RagInstallableComponent:
    category = ComponentCategory.RAG
    legacy_kind = "rag"

    def __init__(self, target: str) -> None:
        self.item_id = str(target or "").strip().lower()
        self.id = make_component_id(self.category, self.item_id)

    def metadata(self) -> ComponentMetadata:
        # Каталожный backend — статичное свойство компонента (см. комментарий выше).
        backend = BackendKind.CPU
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=_target_title(self.item_id),
            description="Local RAG model artifacts.",
            backend=backend,
            legacy_kind=self.legacy_kind,
            tags=("rag",),
        )

    def status(self, ctx: dict[str, Any] | None = None):
        run_ctx = build_runtime_ctx(ctx)
        data = get_install_status(self.item_id, ctx=run_ctx)
        backend = coerce_backend(data.get("required_backend"))
        required = bool(data.get("required", True))
        installed = bool(data.get("ok", False)) or not required
        return status_from_installed(
            component_id=self.id,
            installed=installed,
            backend=backend,
            ctx=run_ctx,
            details=dict(data or {}),
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        run_ctx = build_runtime_ctx(ctx)
        return build_install_plan(
            self.item_id,
            pip_installer=run_ctx.get("pip_installer"),
            callbacks=run_ctx.get("callbacks"),
            timeout_sec=float(run_ctx.get("timeout_sec", 3600.0) or 3600.0),
        )

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        return noop_plan("RAG uninstall is not implemented yet.")

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


def create_rag_installable_components() -> list[Any]:
    # Агрегатные компоненты (rag:embeddings / rag:reranker) остаются для
    # settings-driven установки АКТИВНОЙ (в т.ч. кастомной) модели. Плюс
    # по компоненту на каждую конкретную модель пресета — их AI Hub выводит
    # отдельными карточками (что написано, то и качается).
    components: list[Any] = [
        RagInstallableComponent(TARGET_EMBEDDINGS),
        RagInstallableComponent(TARGET_RERANKER),
    ]
    try:
        from managers.rag.model_catalog import all_model_specs, custom_active_model_specs

        seen_ids: set[str] = set()
        for spec in list(all_model_specs()) + list(custom_active_model_specs()):
            if spec["id"] in seen_ids:
                continue
            seen_ids.add(spec["id"])
            components.append(
                RagModelInstallableComponent(spec["kind"], spec["hf_id"], spec["display"])
            )
    except Exception:
        # Список моделей — необязательная надстройка над агрегатами: если
        # пресеты не читаются, AI Hub просто не покажет карточки моделей, но
        # settings-путь и рантайм продолжат работать.
        pass
    return components


def start_install(target: str, *, with_ui: bool = True, timeout_sec: float = 3600.0) -> None:
    normalized = str(target or "").strip().lower()
    if normalized not in (TARGET_EMBEDDINGS, TARGET_RERANKER, TARGET_CURRENT):
        raise ValueError(f"Unknown RAG install target: {target}")

    from core.installables import ComponentCategory, make_component_id

    title_map = {
        TARGET_EMBEDDINGS: _("Installing RAG embeddings backend", "Installing RAG embeddings backend"),
        TARGET_RERANKER: _("Installing RAG reranker backend", "Installing RAG reranker backend"),
        TARGET_CURRENT: _("Installing current RAG backend", "Installing current RAG backend"),
    }

    # По возможности ставим карточку КОНКРЕТНОЙ активной модели (что выбрано в
    # настройках RAG), а не агрегат — тогда заголовок окна и то, что качается,
    # совпадают. Кастомные модели (нет в пресетах) идут через агрегат.
    component_id = make_component_id(ComponentCategory.RAG, normalized)
    if normalized in (TARGET_EMBEDDINGS, TARGET_RERANKER):
        try:
            from managers.rag.model_catalog import spec_for_hf

            active_hf = _local_embed_model_name() if normalized == TARGET_EMBEDDINGS else resolve_ce_model()
            spec = spec_for_hf(normalized, active_hf) if active_hf else None
            if spec:
                component_id = spec["id"]
        except Exception:
            pass

    payload = {
        "component_id": component_id,
        "kind": "rag",
        "item_id": normalized,
        "task_id": f"rag:install:{normalized}",
        "title": title_map[normalized],
        "initial_status": _("Preparing...", "Preparing..."),
        "timeout_sec": float(timeout_sec or 3600.0),
        "with_ui": bool(with_ui),
        # The request originates from RAG settings but uses the same visual
        # language as the AI Hub install flow.
        "install_style_variant": "ai_hub",
        "meta": {
            "kind": "rag",
            "item_id": normalized,
            "target": normalized,
            "op": "install",
        },
    }

    get_event_bus().emit(Events.Installable.INSTALL, payload)
