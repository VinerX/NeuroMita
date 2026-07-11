from __future__ import annotations

import threading
import time
import uuid
import weakref
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

from main_logger import logger


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    task_id: str
    owner: str
    name: str
    kind: str
    started_at: float
    running: bool
    cancellation_requested: bool
    deadline_at: float | None
    overdue: bool


@dataclass(slots=True)
class _TaskRecord:
    task_id: str
    owner_key: int
    owner_ref: Callable[[], object | None]
    owner_name: str
    name: str
    kind: str
    started_at: float
    cancel_event: threading.Event
    deadline_at: float | None = None
    timed_out: bool = False
    thread: threading.Thread | None = None
    future: Future[Any] | None = None


class TaskSupervisor:
    """Application-wide owner registry for background threads and futures."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._replacement_lock = threading.Lock()
        self._closed = False
        self._records: dict[str, _TaskRecord] = {}
        self._owner_index: dict[int, set[str]] = {}
        self._named_index: dict[tuple[int, str], str] = {}
        self._watchdog_wake = threading.Event()
        self._watchdog_thread = self._start_watchdog()

    def start_thread(
        self,
        owner: object,
        name: str,
        target: Callable[..., Any],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        cancel_event: threading.Event | None = None,
        replace: bool = False,
        replace_timeout: float = 2.0,
        allow_overlap: bool = False,
        daemon: bool = True,
        timeout: float | None = None,
    ) -> threading.Thread:
        normalized_name = str(name or getattr(target, "__name__", "task"))
        owner_key = id(owner)
        owner_name = self._owner_name(owner)
        cancellation = cancel_event or threading.Event()
        task_id = uuid.uuid4().hex
        key = (owner_key, normalized_name)

        def runner() -> None:
            try:
                target(*args, **(kwargs or {}))
            except BaseException as exc:
                logger.error(
                    f"Background task '{owner_name}:{normalized_name}' failed: {exc}",
                    exc_info=True,
                )
            finally:
                self._finish(task_id)

        with self._replacement_lock:
            previous = self._running_named_record(key, owner)
            if previous is not None:
                if not replace:
                    raise RuntimeError(
                        f"Task '{owner_name}:{normalized_name}' is already running"
                    )
                self._request_stop(previous)
                if not allow_overlap and not self._wait_record(
                    previous, timeout=replace_timeout
                ):
                    raise RuntimeError(
                        f"Task '{owner_name}:{normalized_name}' did not stop "
                        f"within {replace_timeout:.2f}s; replacement was not started"
                    )

            with self._lock:
                if self._closed:
                    raise RuntimeError("TaskSupervisor is shut down")
                started_at = time.monotonic()
                record = _TaskRecord(
                    task_id=task_id,
                    owner_key=owner_key,
                    owner_ref=self._make_owner_ref(owner),
                    owner_name=owner_name,
                    name=normalized_name,
                    kind="thread",
                    started_at=started_at,
                    cancel_event=cancellation,
                    deadline_at=(
                        started_at + max(0.0, float(timeout))
                        if timeout is not None
                        else None
                    ),
                )
                thread = threading.Thread(
                    target=runner,
                    name=normalized_name,
                    daemon=bool(daemon),
                )
                record.thread = thread
                self._register_locked(record)
            try:
                thread.start()
            except BaseException:
                self._finish(task_id)
                raise
            return thread

    def submit(
        self,
        owner: object,
        name: str,
        fn: Callable[..., Any],
        *args: Any,
        pool: str,
        replace: bool = False,
        replace_timeout: float = 2.0,
        allow_overlap: bool = False,
        cancel_event: threading.Event | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Future[Any]:
        from core.executors import executors

        normalized_name = str(name or getattr(fn, "__name__", "task"))
        owner_key = id(owner)
        owner_name = self._owner_name(owner)
        cancellation = cancel_event or threading.Event()
        task_id = uuid.uuid4().hex
        key = (owner_key, normalized_name)

        def guarded() -> Any:
            if cancellation.is_set():
                raise RuntimeError(
                    f"Task '{owner_name}:{normalized_name}' was cancelled before start"
                )
            return fn(*args, **kwargs)

        with self._replacement_lock:
            previous = self._running_named_record(key, owner)
            if previous is not None:
                if not replace:
                    future: Future[Any] = Future()
                    future.set_exception(
                        RuntimeError(
                            f"Task '{owner_name}:{normalized_name}' is already running"
                        )
                    )
                    return future
                self._request_stop(previous)
                if not allow_overlap and not self._wait_record(
                    previous, timeout=replace_timeout
                ):
                    future = Future()
                    future.set_exception(
                        RuntimeError(
                            f"Task '{owner_name}:{normalized_name}' did not stop "
                            f"within {replace_timeout:.2f}s; replacement was not started"
                        )
                    )
                    return future

            with self._lock:
                if self._closed:
                    future = Future()
                    future.set_exception(RuntimeError("TaskSupervisor is shut down"))
                    return future
                started_at = time.monotonic()
                record = _TaskRecord(
                    task_id=task_id,
                    owner_key=owner_key,
                    owner_ref=self._make_owner_ref(owner),
                    owner_name=owner_name,
                    name=normalized_name,
                    kind="future",
                    started_at=started_at,
                    cancel_event=cancellation,
                    deadline_at=(
                        started_at + max(0.0, float(timeout))
                        if timeout is not None
                        else None
                    ),
                )
                self._register_locked(record)
            try:
                future = executors().submit(pool, guarded)
            except BaseException:
                self._finish(task_id)
                raise
            record.future = future
            future.add_done_callback(lambda _future: self._finish(task_id))
            return future

    def _running_named_record(
        self,
        key: tuple[int, str],
        owner: object,
    ) -> _TaskRecord | None:
        with self._lock:
            task_id = self._named_index.get(key)
            record = self._records.get(task_id) if task_id else None
            if record is not None and record.owner_ref() is not owner:
                # Python may reuse id(owner) after GC. The live task belongs to
                # another owner and must not block or be cancelled by this one.
                self._named_index.pop(key, None)
                return None
            if record is None or not self._record_running(record):
                return None
            return record

    @staticmethod
    def _make_owner_ref(owner: object) -> Callable[[], object | None]:
        try:
            return weakref.ref(owner)
        except TypeError:
            # Strings and some extension objects cannot be weak-referenced. A
            # strong fallback prevents their id from being reused while tasks
            # are registered.
            return lambda owner=owner: owner

    @staticmethod
    def _request_stop(record: _TaskRecord) -> None:
        record.cancel_event.set()
        if record.future is not None:
            record.future.cancel()

    @staticmethod
    def _wait_record(record: _TaskRecord, *, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        thread = record.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        future = record.future
        while future is not None and not future.done():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.02, remaining))
        return not TaskSupervisor._record_running(record)

    def cancel_owner(self, owner: object, *, timeout: float = 2.0) -> int:
        owner_key = id(owner)
        with self._lock:
            records = [
                self._records[task_id]
                for task_id in tuple(self._owner_index.get(owner_key, ()))
                if task_id in self._records
                and self._records[task_id].owner_ref() is owner
            ]
        for record in records:
            record.cancel_event.set()
            if record.future is not None:
                record.future.cancel()

        deadline = time.monotonic() + max(0.0, float(timeout))
        for record in records:
            thread = record.thread
            if (
                thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        return len(records)

    def cancellation_event(self, owner: object, name: str) -> threading.Event | None:
        with self._lock:
            task_id = self._named_index.get((id(owner), str(name)))
            record = self._records.get(task_id) if task_id else None
            if record is None or record.owner_ref() is not owner:
                return None
            return record.cancel_event

    def snapshot(self) -> tuple[TaskSnapshot, ...]:
        self._cancel_expired()
        now = time.monotonic()
        with self._lock:
            records = tuple(self._records.values())
        return tuple(
            TaskSnapshot(
                task_id=record.task_id,
                owner=record.owner_name,
                name=record.name,
                kind=record.kind,
                started_at=record.started_at,
                running=self._record_running(record),
                cancellation_requested=record.cancel_event.is_set(),
                deadline_at=record.deadline_at,
                overdue=bool(
                    record.timed_out
                    or (
                        record.deadline_at is not None
                        and record.deadline_at <= now
                        and self._record_running(record)
                    )
                ),
            )
            for record in records
        )

    @property
    def is_shutdown(self) -> bool:
        with self._lock:
            return self._closed

    def shutdown(self, *, timeout: float = 3.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            records = tuple(self._records.values())
            watchdog = self._watchdog_thread
        self._watchdog_wake.set()
        for record in records:
            record.cancel_event.set()
            if record.future is not None:
                record.future.cancel()

        deadline = time.monotonic() + max(0.0, float(timeout))
        for record in records:
            thread = record.thread
            if (
                thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if (
            watchdog is not None
            and watchdog.is_alive()
            and watchdog is not threading.current_thread()
        ):
            watchdog.join(timeout=max(0.0, deadline - time.monotonic()))

    def reset_for_tests(self) -> None:
        self.shutdown(timeout=0.5)
        with self._lock:
            self._closed = False
            self._records.clear()
            self._owner_index.clear()
            self._named_index.clear()
            self._watchdog_wake = threading.Event()
            self._watchdog_thread = self._start_watchdog()

    def _register_locked(self, record: _TaskRecord) -> None:
        self._records[record.task_id] = record
        self._owner_index.setdefault(record.owner_key, set()).add(record.task_id)
        self._named_index[(record.owner_key, record.name)] = record.task_id
        self._watchdog_wake.set()

    def _finish(self, task_id: str) -> None:
        with self._lock:
            record = self._records.pop(task_id, None)
            if record is None:
                return
            owner_tasks = self._owner_index.get(record.owner_key)
            if owner_tasks is not None:
                owner_tasks.discard(task_id)
                if not owner_tasks:
                    self._owner_index.pop(record.owner_key, None)
            key = (record.owner_key, record.name)
            if self._named_index.get(key) == task_id:
                self._named_index.pop(key, None)
        self._watchdog_wake.set()

    def _start_watchdog(self) -> threading.Thread:
        thread = threading.Thread(
            target=self._watchdog_loop,
            name="task-supervisor-watchdog",
            daemon=True,
        )
        thread.start()
        return thread

    def _watchdog_loop(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    return
                deadlines = [
                    record.deadline_at
                    for record in self._records.values()
                    if record.deadline_at is not None and not record.timed_out
                ]
            self._cancel_expired()
            with self._lock:
                if self._closed:
                    return
                deadlines = [
                    record.deadline_at
                    for record in self._records.values()
                    if record.deadline_at is not None and not record.timed_out
                ]
            now = time.monotonic()
            wait_for = 1.0
            if deadlines:
                wait_for = max(0.02, min(1.0, min(deadlines) - now))
            self._watchdog_wake.wait(wait_for)
            self._watchdog_wake.clear()

    def _cancel_expired(self) -> int:
        now = time.monotonic()
        expired: list[_TaskRecord] = []
        with self._lock:
            for record in self._records.values():
                if (
                    record.deadline_at is None
                    or record.timed_out
                    or record.deadline_at > now
                    or not self._record_running(record)
                ):
                    continue
                record.timed_out = True
                expired.append(record)
        for record in expired:
            record.cancel_event.set()
            if record.future is not None:
                record.future.cancel()
            logger.error(
                f"Background task deadline exceeded: "
                f"'{record.owner_name}:{record.name}'"
            )
        return len(expired)

    @staticmethod
    def _record_running(record: _TaskRecord) -> bool:
        if record.thread is not None:
            return record.thread.is_alive()
        if record.future is not None:
            return not record.future.done()
        return True

    @staticmethod
    def _owner_name(owner: object) -> str:
        if isinstance(owner, str):
            return owner
        return type(owner).__name__


_supervisor = TaskSupervisor()


def task_supervisor() -> TaskSupervisor:
    return _supervisor
