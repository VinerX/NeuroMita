from __future__ import annotations

import asyncio
from typing import Any, Optional

from core.events import Events, get_event_bus


def resolve_ai_engine(event_bus=None, *, timeout: float = 1.0):
    eb = event_bus or get_event_bus()
    try:
        res = eb.emit_and_wait(Events.AI.GET_ENGINE, timeout=float(timeout))
        return res[0] if res else None
    except Exception:
        return None


async def call_beats_worker_async(
    method: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    timeout: float = 30.0,
    event_bus=None,
):
    eng = resolve_ai_engine(event_bus)
    if eng is None:
        raise RuntimeError("AI engine not available")
    fut = eng.call("beats", method, payload or {})
    return await asyncio.wait_for(asyncio.wrap_future(fut), timeout=float(timeout))


def call_beats_worker_sync(
    method: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    timeout: float = 30.0,
    event_bus=None,
):
    eng = resolve_ai_engine(event_bus)
    if eng is None:
        raise RuntimeError("AI engine not available")
    fut = eng.call("beats", method, payload or {})
    return fut.result(timeout=float(timeout))


def restart_beats_worker(*, timeout: float = 15.0, event_bus=None) -> bool:
    eng = resolve_ai_engine(event_bus)
    if eng is None:
        return True
    return bool(eng.restart_service("beats", timeout=float(timeout)))
