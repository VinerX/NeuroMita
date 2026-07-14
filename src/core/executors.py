"""Единый реестр именованных пулов потоков.

Раньше пулы плодились по месту,
ThreadPoolExecutor(1) на каждый HTTP-вызов LLM, ad-hoc threading.Thread
в контроллерах. Считать нагрузку и вводить backpressure было негде.

Пулы:
- GENERATION    — пользовательские генерации (chat/react/idle). Ограничен,
                  переполнение отклоняется (см. try_submit) — это backpressure.
- BACKGROUND_LLM— фоновые LLM-задачи (сжатие истории, graph extraction).
                  Ровно 1 поток: они не должны конкурировать друг с другом.
- IO            — короткие блокирующие IO/сеть без GPU (диск, http-проверки).
- DB_WRITER     — сериализованная запись в SQLite.
- EVENT_BUS     — диспетчеризация подписчиков шины.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from core.daemon_executor import DaemonExecutor


class Pools:
    GENERATION = "generation"
    BACKGROUND_LLM = "background-llm"
    IO = "io"
    DB_WRITER = "db-writer"
    # Исходящие HTTP-вызовы к LLM-провайдерам. Отдельный пул, потому что
    # запрос, брошенный по таймауту, продолжает висеть в своём потоке.
    LLM_HTTP = "llm-http"
    # Дебаг-дампы запроса/ответа на диск. Один поток: порядок «запрос → ответ»
    # должен сохраняться, а hot path не должен ждать диск.
    DEBUG_DUMP = "debug-dump"
    # Асинхронная доставка подписчикам (emit).
    EVENT_BUS = "event-bus"


@dataclass(frozen=True)
class _PoolSpec:
    max_workers: int
    # Сколько задач всего допускается «в системе» (выполняются + ждут).
    # None — без ограничения (для пулов, где backpressure не нужен).
    capacity: Optional[int] = None
    daemon_workers: bool = False


_SPECS: Dict[str, _PoolSpec] = {
    Pools.GENERATION: _PoolSpec(max_workers=3, capacity=6),
    Pools.BACKGROUND_LLM: _PoolSpec(max_workers=1, capacity=4),
    Pools.IO: _PoolSpec(max_workers=6),
    Pools.LLM_HTTP: _PoolSpec(max_workers=8, capacity=8, daemon_workers=True),
    Pools.DEBUG_DUMP: _PoolSpec(max_workers=1, capacity=2),
    Pools.DB_WRITER: _PoolSpec(max_workers=1),
    Pools.EVENT_BUS: _PoolSpec(max_workers=8, capacity=512),
}


class PoolSaturated(RuntimeError):
    def __init__(self, name: str, capacity: int):
        super().__init__(f"Пул '{name}' переполнен (capacity={capacity})")
        self.pool_name = name
        self.capacity = capacity


class _BoundedPool:
    """ThreadPoolExecutor + счётчик задач «в системе» для backpressure."""

    def __init__(self, name: str, spec: _PoolSpec) -> None:
        self.name = name
        self.spec = spec
        if spec.daemon_workers:
            self._executor = DaemonExecutor(
                spec.max_workers,
                thread_name_prefix=name,
            )
        else:
            self._executor = ThreadPoolExecutor(
                max_workers=spec.max_workers,
                thread_name_prefix=name,
            )
        self._lock = threading.Lock()
        self._inflight = 0
        self._reservations: Dict[Future, bool] = {}

    @property
    def inflight(self) -> int:
        with self._lock:
            return self._inflight

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        """Ставит задачу, игнорируя capacity. Для задач, которые нельзя терять."""
        with self._lock:
            self._inflight += 1
        return self._submit_reserved(fn, args, kwargs)

    def try_submit(self, fn: Callable, *args, **kwargs) -> Future:
        """Атомарно резервирует слот или бросает PoolSaturated."""
        capacity = self.spec.capacity
        with self._lock:
            if capacity is not None and self._inflight >= capacity:
                raise PoolSaturated(self.name, capacity)
            self._inflight += 1
        return self._submit_reserved(fn, args, kwargs)

    def _submit_reserved(self, fn: Callable, args: tuple, kwargs: dict) -> Future:
        def _release(_f: Future) -> None:
            with self._lock:
                if self._reservations.pop(_f, None):
                    self._inflight -= 1

        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except BaseException:
            with self._lock:
                self._inflight -= 1
            raise
        with self._lock:
            self._reservations[future] = True
        future.add_done_callback(_release)
        return future

    def abandon(self, future: Future) -> bool:
        if not isinstance(self._executor, DaemonExecutor):
            return False
        if not self._executor.abandon(future):
            return False
        with self._lock:
            if self._reservations.pop(future, None):
                self._inflight -= 1
        return True

    def shutdown(self, wait: bool = False) -> None:
        if isinstance(self._executor, DaemonExecutor):
            self._executor.shutdown(cancel_futures=not wait)
            return
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


class ExecutorRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pools: Dict[str, _BoundedPool] = {}

    def pool(self, name: str) -> _BoundedPool:
        spec = _SPECS.get(name)
        if spec is None:
            raise KeyError(f"Неизвестный пул '{name}'. Объяви его в core/executors.py::_SPECS.")
        with self._lock:
            pool = self._pools.get(name)
            if pool is None:
                pool = _BoundedPool(name, spec)
                self._pools[name] = pool
            return pool

    def submit(self, name: str, fn: Callable, *args, **kwargs) -> Future:
        return self.pool(name).submit(fn, *args, **kwargs)

    def try_submit(self, name: str, fn: Callable, *args, **kwargs) -> Future:
        return self.pool(name).try_submit(fn, *args, **kwargs)

    def shutdown_all(self, wait: bool = False) -> None:
        with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        for pool in pools:
            try:
                pool.shutdown(wait=wait)
            except Exception:
                pass


_executors = ExecutorRegistry()


def executors() -> ExecutorRegistry:
    return _executors
