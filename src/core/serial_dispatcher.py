from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from core.task_supervisor import task_supervisor
from main_logger import logger


@dataclass(frozen=True, slots=True)
class _DispatchItem:
    callback: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    description: str


class SerialDispatcher:
    """Striped FIFO dispatcher.

    ``capacity_per_lane=0`` means lossless/unbounded admission. Bounded lanes
    return ``False`` instead of running work inline.
    """

    _STOP = object()

    def __init__(
        self,
        name: str,
        *,
        lanes: int = 1,
        capacity_per_lane: int = 1024,
    ) -> None:
        self._name = str(name)
        self._closed = threading.Event()
        self._condition = threading.Condition()
        self._queued = 0
        self._active = 0
        self._queues: list[queue.Queue[Any]] = [
            queue.Queue(maxsize=max(0, int(capacity_per_lane)))
            for _ in range(max(1, int(lanes)))
        ]
        self._threads = [
            task_supervisor().start_thread(
                self,
                f"{self._name}-{index}",
                self._worker,
                args=(work_queue,),
            )
            for index, work_queue in enumerate(self._queues)
        ]

    def submit(
        self,
        callback: Callable[..., Any],
        *args: Any,
        key: Any = None,
        description: str = "",
        **kwargs: Any,
    ) -> bool:
        if self._closed.is_set():
            return False
        lane = self._queues[self._lane_index(key)]
        item = _DispatchItem(
            callback=callback,
            args=args,
            kwargs=kwargs,
            description=str(description or getattr(callback, "__qualname__", str(callback))),
        )
        try:
            lane.put_nowait(item)
        except queue.Full:
            return False
        with self._condition:
            self._queued += 1
            self._condition.notify_all()
        return True

    def wait_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self._queued or self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, *, drain: bool = True, timeout: float = 3.0) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        drained = bool(drain and self.wait_idle(timeout=timeout))

        for work_queue in self._queues:
            if not drained:
                self._discard_pending(work_queue)
            while True:
                try:
                    work_queue.put_nowait(self._STOP)
                    break
                except queue.Full:
                    self._discard_one(work_queue)
        task_supervisor().cancel_owner(self, timeout=timeout)

    def _discard_pending(self, work_queue: queue.Queue[Any]) -> None:
        while True:
            try:
                discarded = work_queue.get_nowait()
            except queue.Empty:
                return
            self._account_discard(discarded)

    def _discard_one(self, work_queue: queue.Queue[Any]) -> None:
        try:
            discarded = work_queue.get_nowait()
        except queue.Empty:
            return
        self._account_discard(discarded)

    def _account_discard(self, discarded: Any) -> None:
        if discarded is self._STOP:
            return
        with self._condition:
            self._queued = max(0, self._queued - 1)
            self._condition.notify_all()

    @property
    def pending(self) -> int:
        with self._condition:
            return self._queued + self._active

    def _worker(self, work_queue: queue.Queue[Any]) -> None:
        while True:
            item = work_queue.get()
            if item is self._STOP:
                return
            with self._condition:
                self._queued = max(0, self._queued - 1)
                self._active += 1
            try:
                item.callback(*item.args, **item.kwargs)
            except BaseException as exc:
                logger.error(
                    f"Serial task '{item.description}' failed in '{self._name}': {exc}",
                    exc_info=True,
                )
            finally:
                with self._condition:
                    self._active = max(0, self._active - 1)
                    self._condition.notify_all()

    def _lane_index(self, key: Any) -> int:
        if len(self._queues) == 1:
            return 0
        return hash(key) % len(self._queues)
