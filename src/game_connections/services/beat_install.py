from __future__ import annotations

from typing import Optional

from core.events import Events, get_event_bus
from core.install_types import InstallAction, InstallPlan


_BEAT_INSTALL_PACKAGES = [
    "beat-this",
    "tqdm",
    "einops",
    "soxr",
    "rotary-embedding-torch",
]


def build_beat_install_plan() -> InstallPlan:
    return InstallPlan(
        actions=[
            InstallAction(
                type="pip",
                description="Installing beat-this backend...",
                progress=10,
                packages=list(_BEAT_INSTALL_PACKAGES),
            ),
            InstallAction(
                type="call",
                description="Restarting beat backend...",
                progress=85,
                fn=_restart_beats_service,
            ),
            InstallAction(
                type="call",
                description="Warming up beat backend...",
                progress=95,
                fn=_warmup_beats_service,
            ),
        ],
        already_installed=False,
        ok_status="Done",
    )


def run_beat_install_blocking(*, timeout_sec: float = 3600.0) -> bool:
    event_bus = get_event_bus()
    payload = {
        "kind": "beats",
        "item_id": "beat_this",
        "task_id": "beats:beat_this",
        "timeout_sec": float(timeout_sec or 3600.0),
        "meta": {
            "kind": "beats",
            "item_id": "beat_this",
        },
        "runner": _install_runner,
    }
    results = event_bus.emit_and_wait(
        Events.Install.RUN_BLOCKING,
        payload,
        timeout=float(timeout_sec or 3600.0) + 30.0,
    )
    return bool(results and results[0])


def _install_runner(*_args, **_kwargs):
    return build_beat_install_plan()


def _resolve_engine(event_bus=None):
    eb = event_bus or get_event_bus()
    try:
        res = eb.emit_and_wait(Events.AI.GET_ENGINE, timeout=1.0)
        return res[0] if res else None
    except Exception:
        return None


def _restart_beats_service(*_args, **kwargs) -> bool:
    ctx = kwargs.get("ctx") if isinstance(kwargs, dict) else None
    event_bus = ctx.get("event_bus") if isinstance(ctx, dict) else None
    eng = _resolve_engine(event_bus)
    if eng is None:
        return True
    return bool(eng.restart_service("beats", timeout=15.0))


def _warmup_beats_service(*_args, **kwargs) -> bool:
    ctx = kwargs.get("ctx") if isinstance(kwargs, dict) else None
    event_bus = ctx.get("event_bus") if isinstance(ctx, dict) else None
    eng = _resolve_engine(event_bus)
    if eng is None:
        return False

    fut = eng.call("beats", "warmup", {"auto_install": False})
    return bool(fut.result(timeout=120.0))
