"""Планировщик тяжёлых (GPU/CPU-bound) секций внутри AI-worker'а.

Зачем: `_worker_loop` теперь обрабатывает команды конкурентно, иначе синтез TTS
предыдущего ответа блокировал эмбеддинг запроса следующего. Но пускать две
GPU-задачи одновременно нельзя — это VRAM-трэшинг и OOM. Поэтому доступ к
устройству сериализован, а очередь — с приоритетами:

    HOT (эмбеддинг запроса пользователя) > RERANK > TTS > BULK (индексация, warmup)

Пользователь ждёт HOT прямо сейчас; фоновая переиндексация подождёт.
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
import os
from contextlib import asynccontextmanager


class Priority:
    """Меньше — важнее."""

    HOT = 0      # эмбеддинг пользовательского запроса: его ждёт ответ Миты
    RERANK = 1   # cross-encoder в том же запросе
    TTS = 2      # синтез озвучки уже полученного ответа
    BULK = 3     # warmup, массовая индексация, sentence-level

    _NAMES = {"hot": HOT, "rerank": RERANK, "tts": TTS, "bulk": BULK}

    @classmethod
    def parse(cls, value, default: int = HOT) -> int:
        if isinstance(value, int):
            return value
        name = str(value or "").strip().lower()
        return cls._NAMES.get(name, default)


def _default_slots() -> int:
    try:
        return max(1, int(os.environ.get("NEUROMITA_AI_GPU_SLOTS", "1")))
    except Exception:
        return 1


class PriorityScheduler:
    """Семафор с приоритетной очередью. Живёт в одном event-loop воркера."""

    def __init__(self, slots: int | None = None) -> None:
        self._free = _default_slots() if slots is None else max(1, int(slots))
        self._waiters: list[tuple[int, int, asyncio.Future]] = []
        self._seq = itertools.count()

    @property
    def free_slots(self) -> int:
        return self._free

    @property
    def queue_depth(self) -> int:
        return len(self._waiters)

    async def acquire(self, priority: int) -> None:
        # Пропускаем без очереди только если никто не ждёт: иначе HOT-задача,
        # приехавшая позже, могла бы вечно обгонять уже стоящую в очереди.
        if self._free > 0 and not self._waiters:
            self._free -= 1
            return

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (int(priority), next(self._seq), future))
        try:
            await future
        except asyncio.CancelledError:
            # Нас отменили в очереди — слот не занимали, но могли уже отдать.
            if future.done() and not future.cancelled():
                self.release()
            raise

    def release(self) -> None:
        while self._waiters:
            _, _, future = heapq.heappop(self._waiters)
            if not future.done():
                future.set_result(None)
                return
        self._free += 1

    @asynccontextmanager
    async def slot(self, priority: int):
        await self.acquire(int(priority))
        try:
            yield
        finally:
            self.release()

    async def run(self, priority: int, func, /, *args, **kwargs):
        """Выполнить блокирующую функцию в потоке, удерживая слот устройства."""
        async with self.slot(priority):
            return await asyncio.to_thread(func, *args, **kwargs)


_scheduler: PriorityScheduler | None = None


def get_scheduler() -> PriorityScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = PriorityScheduler()
    return _scheduler


def reset_scheduler() -> None:
    """Только для тестов."""
    global _scheduler
    _scheduler = None
