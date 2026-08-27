from __future__ import annotations

import asyncio
from typing import Any, Optional


def resolve_ai_engine(event_bus=None, *, timeout: float = 1.0):
    # Через AIEngineService, а не sync EventBus RPC: get_music_beats исполняется в
    # asyncio-loop сервера, где синхронный сбор ответов шины блокирует loop и
    # запрещён guardrail'ом. event_bus/timeout — для совместимости сигнатуры.
    try:
        from core.services import use
        from services.contracts import AIEngineService
        return use(AIEngineService).get_engine()
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
