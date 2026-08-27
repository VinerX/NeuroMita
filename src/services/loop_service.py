from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import Coroutine

from services.contracts import LoopService


class AsyncioLoopService(LoopService):
    """LoopService поверх фонового asyncio-loop. Владелец — LoopController."""

    def __init__(self, loop_provider) -> None:
        # loop_provider() -> asyncio.AbstractEventLoop | None
        self._loop_provider = loop_provider

    def loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop_provider()
        if loop is None or loop.is_closed():
            raise RuntimeError("asyncio loop не запущен")
        return loop

    def is_running(self) -> bool:
        loop = self._loop_provider()
        return bool(loop and not loop.is_closed() and loop.is_running())

    def run(self, coro: Coroutine) -> Future:
        loop = self.loop()
        if not loop.is_running():
            coro.close()
            raise RuntimeError("asyncio loop не крутится")
        return asyncio.run_coroutine_threadsafe(coro, loop)


class NoLoopService(LoopService):
    """GUI-only режим: asyncio-loop не поднимается вовсе."""

    _MSG = "asyncio loop недоступен: приложение запущено в GUI-only режиме"

    def loop(self) -> asyncio.AbstractEventLoop:
        raise RuntimeError(self._MSG)

    def is_running(self) -> bool:
        return False

    def run(self, coro: Coroutine) -> Future:
        coro.close()
        raise RuntimeError(self._MSG)
