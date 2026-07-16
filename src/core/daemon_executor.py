from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, Protocol, TypeVar


_T = TypeVar("_T")
_default_supervisor: "_ThreadSupervisor | None" = None


class _ThreadSupervisor(Protocol):
    def start_thread(self, owner, name, target, **kwargs) -> threading.Thread: ...

    def cancel_owner(self, owner, *, timeout: float = 0.0) -> None: ...


def configure_default_supervisor(supervisor: _ThreadSupervisor) -> None:
    global _default_supervisor
    _default_supervisor = supervisor


class DaemonExecutor:
    """Small daemon-thread executor with cancellable queued work.

    Python cannot safely kill a running thread. This executor therefore gives
    deterministic cancellation for queued tasks and guarantees that an
    uncooperative native import cannot keep interpreter shutdown alive. Owners
    must still reject late results with their generation/lifecycle tokens.
    """

    def __init__(
        self,
        max_workers: int,
        *,
        thread_name_prefix: str,
        max_retired_workers: int | None = None,
        supervisor: _ThreadSupervisor | None = None,
    ) -> None:
        self._queue: queue.Queue[Any] = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._stop_event = threading.Event()
        self._thread_name_prefix = str(thread_name_prefix)
        self._next_worker_index = 0
        self._threads: list[threading.Thread] = []
        self._worker_by_future: dict[Future[Any], threading.Thread] = {}
        self._retired_threads: set[threading.Thread] = set()
        self._max_retired_workers = (
            None
            if max_retired_workers is None
            else max(0, int(max_retired_workers))
        )
        self._supervisor = supervisor or _default_supervisor
        for index in range(max(1, int(max_workers))):
            self._start_worker()

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
            threads = tuple(self._threads)
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
        self._stop_event.set()
        for _ in threads:
            self._queue.put(None)
        if self._supervisor is not None:
            self._supervisor.cancel_owner(self, timeout=1.0)

    def abandon(self, future: Future[Any]) -> bool:
        """Detach a running task and replace its worker.

        Python cannot kill the underlying call. The abandoned worker therefore
        remains daemonized until the call returns, while a fresh worker keeps
        the executor capacity available for subsequent requests.
        """
        with self._lock:
            if self._closed:
                return False
            thread = self._worker_by_future.get(future)
            if thread is None or thread in self._retired_threads:
                return False
            if (
                self._max_retired_workers is not None
                and len(self._retired_threads) >= self._max_retired_workers
            ):
                return False
            self._retired_threads.add(thread)
        if self._start_worker():
            return True
        with self._lock:
            self._retired_threads.discard(thread)
        return False

    @property
    def retired_workers(self) -> int:
        with self._lock:
            return len(self._retired_threads)

    @property
    def max_retired_workers(self) -> int | None:
        return self._max_retired_workers

    def _start_worker(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            index = self._next_worker_index
            self._next_worker_index += 1
            try:
                if self._supervisor is not None:
                    thread = self._supervisor.start_thread(
                        self,
                        f"{self._thread_name_prefix}-{index}",
                        self._worker,
                        cancel_event=self._stop_event,
                    )
                else:
                    thread = threading.Thread(
                        target=self._worker,
                        name=f"{self._thread_name_prefix}-{index}",
                        daemon=True,
                    )
                    thread.start()
            except Exception:
                return False
            self._threads.append(thread)
        return True

    def _worker(self) -> None:
        current_thread = threading.current_thread()
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            with self._lock:
                self._worker_by_future[future] = current_thread
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)
            finally:
                with self._lock:
                    self._worker_by_future.pop(future, None)
                    retired = current_thread in self._retired_threads
                    if retired:
                        self._retired_threads.discard(current_thread)
                        try:
                            self._threads.remove(current_thread)
                        except ValueError:
                            pass
                if retired:
                    return
