from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, TypeVar


_T = TypeVar("_T")


class DaemonExecutor:
    """Small daemon-thread executor with cancellable queued work.

    Python cannot safely kill a running thread. This executor therefore gives
    deterministic cancellation for queued tasks and guarantees that an
    uncooperative native import cannot keep interpreter shutdown alive. Owners
    must still reject late results with their generation/lifecycle tokens.
    """

    def __init__(self, max_workers: int, *, thread_name_prefix: str) -> None:
        self._queue: queue.Queue[Any] = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._threads: list[threading.Thread] = []
        for index in range(max(1, int(max_workers))):
            thread = threading.Thread(
                target=self._worker,
                name=f"{thread_name_prefix}-{index}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def submit(self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> Future[_T]:
        future: Future[_T] = Future()
        with self._lock:
            if self._closed:
                future.set_exception(RuntimeError("Executor is shut down"))
                return future
            self._queue.put((future, fn, args, kwargs))
        return future

    def shutdown(self, *, cancel_futures: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if cancel_futures:
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    continue
                future = item[0]
                future.cancel()
        for _ in self._threads:
            self._queue.put(None)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)
