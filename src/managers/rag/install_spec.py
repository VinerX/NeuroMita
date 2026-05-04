from __future__ import annotations

import os
import sys
from typing import Any

from core.events import Events, get_event_bus
from core.install_requirements import InstallRequirement, check_requirements
from core.install_types import InstallAction, InstallPlan
from handlers.embedding_presets import resolve_full_config
from handlers.voice_models.install_plan_helpers import torch_install_action
from managers.rag.pipeline.config import resolve_ce_model
from managers.settings_manager import SettingsManager
from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider
from utils.torch_install_utils import decide_torch_install


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


def _current_targets() -> list[str]:
    if not SettingsManager.get("RAG_ENABLED", False):
        return []

    targets: list[str] = []
    if _local_provider_enabled() and SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", True):
        targets.append(TARGET_EMBEDDINGS)

    ce_model = resolve_ce_model()
    if SettingsManager.get("RAG_CROSS_ENCODER_ENABLED", False) and ce_model:
        targets.append(TARGET_RERANKER)

    return targets


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


def _torch_status(ctx: dict[str, Any]) -> dict[str, Any]:
    plan = decide_torch_install(str(ctx.get("gpu_vendor") or "CPU"), target_dir=os.environ.get("NEUROMITA_LIB_DIR"))
    ok = str(plan.get("action") or "skip") == "skip"
    reason = str(plan.get("reason") or plan.get("description") or "")
    return {
        "id": "torch_runtime",
        "kind": "torch_runtime",
        "required": True,
        "ok": ok,
        "extra": {
            "action": plan.get("action"),
            "reason": reason,
            "gpu_vendor": ctx.get("gpu_vendor"),
        },
    }


def _embed_requirements() -> list[InstallRequirement]:
    return [
        InstallRequirement(id="transformers", kind="python_dist", spec=TRANSFORMERS_SPEC, required=True),
        InstallRequirement(id="huggingface_hub", kind="python_dist", spec=HF_HUB_SPEC, required=True),
    ]


def _reranker_requirements(ctx: dict[str, Any]) -> list[InstallRequirement]:
    reqs = [
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
        "gpu_vendor": ctx.get("gpu_vendor"),
    }

    torch_added = False

    for item in resolved_targets:
        if item == TARGET_EMBEDDINGS:
            if not _local_provider_enabled():
                continue

            summary["required"] = True
            summary["needs_local_runtime"] = True

            if not torch_added:
                tstatus = _torch_status(ctx)
                summary["details"].append(tstatus)
                if not tstatus.get("ok"):
                    summary["missing_required"].append("torch_runtime")
                    summary["ok"] = False
                torch_added = True

            checked = check_requirements(_embed_requirements(), ctx=ctx)
            _merge_requirement_status(summary, checked)
            if not checked.get("ok"):
                summary["ok"] = False

        elif item == TARGET_RERANKER:
            ce_model = resolve_ce_model()
            if not ce_model:
                continue

            summary["required"] = True
            summary["needs_local_runtime"] = True

            if not torch_added:
                tstatus = _torch_status(ctx)
                summary["details"].append(tstatus)
                if not tstatus.get("ok"):
                    summary["missing_required"].append("torch_runtime")
                    summary["ok"] = False
                torch_added = True

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
    status = get_install_status(target, ctx=ctx)
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
    def _fn(*, callbacks=None, **_kwargs) -> bool:
        from huggingface_hub import snapshot_download

        token = str(SettingsManager.get("HF_TOKEN", "") or "").strip() or None
        cache_dir = _checkpoints_dir()
        if callbacks is not None:
            try:
                callbacks.log(f"snapshot_download: {repo_id}")
            except Exception:
                pass

        snapshot_download(repo_id=repo_id, cache_dir=cache_dir, token=token)
        return True

    return InstallAction(
        type="call",
        description=description,
        progress=int(progress),
        fn=_fn,
    )


def _restart_rag_worker_action(*, progress: int = 96) -> InstallAction:
    def _fn(*, callbacks=None, **_kwargs) -> bool:
        try:
            res = get_event_bus().emit_and_wait(Events.AI.GET_ENGINE, timeout=1.0)
            engine = res[0] if res else None
        except Exception:
            engine = None

        if engine is None:
            return True

        if callbacks is not None:
            try:
                callbacks.log("Restarting AI engine worker for RAG...")
            except Exception:
                pass

        try:
            restart_worker = getattr(engine, "restart_worker_for_service", None)
            if callable(restart_worker):
                return bool(restart_worker("rag", timeout=20.0))

            restart_service = getattr(engine, "restart_service", None)
            if callable(restart_service):
                return bool(restart_service("rag", timeout=20.0))
        except Exception as exc:
            if callbacks is not None:
                try:
                    callbacks.log(f"AI engine restart skipped: {exc}")
                except Exception:
                    pass
            return False

        return True

    return InstallAction(
        type="call",
        description=_("Restarting RAG runtime...", "Restarting RAG runtime..."),
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
        actions.append(torch_install_action(ctx, progress=10))
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

    actions.append(_restart_rag_worker_action(progress=95))

    def _final_check(**_kwargs) -> bool:
        return bool(get_install_status(target, ctx=ctx).get("ok"))

    actions.append(
        InstallAction(
            type="call",
            description=_("Finalizing RAG backend...", "Finalizing RAG backend..."),
            progress=99,
            fn=_final_check,
        )
    )

    return InstallPlan(actions=actions, ok_status=_("Done", "Done"))


def make_install_runner(target: str, timeout_sec: float = 3600.0):
    def _runner(*args, **kwargs):
        pip_installer = kwargs.get("pip_installer") if isinstance(kwargs, dict) else None
        callbacks = kwargs.get("callbacks") if isinstance(kwargs, dict) else None

        if pip_installer is None and len(args) >= 1:
            pip_installer = args[0]
        if callbacks is None and len(args) >= 2:
            callbacks = args[1]

        return build_install_plan(
            target,
            pip_installer=pip_installer,
            callbacks=callbacks,
            timeout_sec=float(timeout_sec or 3600.0),
        )

    return _runner


def start_install(target: str, *, with_ui: bool = True, timeout_sec: float = 3600.0) -> None:
    normalized = str(target or "").strip().lower()
    if normalized not in (TARGET_EMBEDDINGS, TARGET_RERANKER, TARGET_CURRENT):
        raise ValueError(f"Unknown RAG install target: {target}")

    title_map = {
        TARGET_EMBEDDINGS: _("Installing RAG embeddings backend", "Installing RAG embeddings backend"),
        TARGET_RERANKER: _("Installing RAG reranker backend", "Installing RAG reranker backend"),
        TARGET_CURRENT: _("Installing current RAG backend", "Installing current RAG backend"),
    }

    payload = {
        "kind": "rag",
        "item_id": normalized,
        "task_id": f"rag:{normalized}",
        "title": title_map[normalized],
        "initial_status": _("Preparing...", "Preparing..."),
        "timeout_sec": float(timeout_sec or 3600.0),
        "meta": {
            "kind": "rag",
            "item_id": normalized,
            "target": normalized,
        },
        "runner": make_install_runner(normalized, timeout_sec=float(timeout_sec or 3600.0)),
    }

    get_event_bus().emit(
        Events.Install.RUN_WITH_UI if with_ui else Events.Install.RUN_HEADLESS,
        payload,
    )
