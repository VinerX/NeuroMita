from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass
from typing import Callable

from core.events import Events, get_event_bus
from services.contracts import TelegramAuthService


@dataclass(slots=True)
class _PendingPrompt:
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[str]


class DefaultTelegramAuthService(TelegramAuthService):
    """Owns Telegram auth prompt lifetimes outside EventBus payloads."""

    def __init__(
        self,
        *,
        timeout: float = 180.0,
        available: bool | Callable[[], bool] = True,
    ) -> None:
        self._timeout = max(5.0, float(timeout))
        self._available = available
        self._lock = threading.RLock()
        self._pending: dict[str, _PendingPrompt] = {}
        self._event_bus = get_event_bus()

    async def request(
        self,
        kind: str,
        *,
        error: str = "",
        attempt: int = 1,
    ) -> str:
        normalized = str(kind or "").strip().lower()
        if normalized not in {"code", "password"}:
            raise ValueError(f"Unsupported Telegram auth prompt: {kind}")
        available = self._available() if callable(self._available) else self._available
        if not available:
            raise RuntimeError("Telegram auth input is unavailable in headless mode")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        request_id = uuid.uuid4().hex
        with self._lock:
            self._pending[request_id] = _PendingPrompt(loop=loop, future=future)

        event_name = (
            Events.Telegram.PROMPT_FOR_TG_CODE
            if normalized == "code"
            else Events.Telegram.PROMPT_FOR_TG_PASSWORD
        )
        accepted = self._event_bus.try_emit(
            event_name,
            {
                "request_id": request_id,
                "kind": normalized,
                "error": str(error or ""),
                "attempt": int(attempt),
            },
        )
        if not accepted:
            self.reject(request_id, "Telegram auth UI is unavailable")

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def resolve(self, request_id: str, value: str) -> bool:
        pending = self._take(request_id)
        if pending is None:
            return False
        pending.loop.call_soon_threadsafe(
            self._set_result_if_pending,
            pending.future,
            str(value),
        )
        return True

    def reject(self, request_id: str, reason: str = "Cancelled") -> bool:
        pending = self._take(request_id)
        if pending is None:
            return False
        error = RuntimeError(str(reason or "Cancelled"))
        pending.loop.call_soon_threadsafe(
            self._set_exception_if_pending,
            pending.future,
            error,
        )
        return True

    def close(self) -> None:
        with self._lock:
            request_ids = tuple(self._pending)
        for request_id in request_ids:
            self.reject(request_id, "Application shutdown")

    def _take(self, request_id: str) -> _PendingPrompt | None:
        with self._lock:
            return self._pending.pop(str(request_id or ""), None)

    @staticmethod
    def _set_result_if_pending(future: asyncio.Future[str], value: str) -> None:
        if not future.done():
            future.set_result(value)

    @staticmethod
    def _set_exception_if_pending(
        future: asyncio.Future[str], error: BaseException
    ) -> None:
        if not future.done():
            future.set_exception(error)
