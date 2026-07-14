from __future__ import annotations

import itertools
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator, MutableMapping
from dataclasses import dataclass
from typing import Any

from core.serial_dispatcher import SerialDispatcher
from main_logger import logger


@dataclass(frozen=True, slots=True)
class SettingChange:
    key: str
    value: Any
    previous: Any
    revision: int
    source: str


class SettingsSubscription:
    def __init__(self, registry: "SettingsRegistry", token: int) -> None:
        self._registry = registry
        self._token = token
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._registry._unsubscribe(self._token)

    def __enter__(self) -> "SettingsSubscription":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class SettingsRegistry(MutableMapping[str, Any]):
    """Thread-safe in-memory source of truth for application settings.

    Disk persistence and transport adapters are deliberately kept outside this
    class. Readers get values synchronously; subscribers receive immutable
    change records after a successful mutation.
    """

    def __init__(
        self,
        initial: dict[str, Any] | None = None,
        *,
        on_mutated: Callable[[], None] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._values: dict[str, Any] = dict(initial or {})
        self._revision = 0
        self._listener_ids = itertools.count(1)
        self._listeners: dict[
            int,
            tuple[frozenset[str] | None, Callable[[SettingChange], None]],
        ] = {}
        self._on_mutated = on_mutated
        self._dispatcher = SerialDispatcher(
            f"settings-observers-{id(self):x}",
            lanes=4,
            capacity_per_lane=0,
        )
        self._pending_listener_changes: dict[int, deque[SettingChange]] = {}
        self._scheduled_listeners: set[int] = set()
        self._closed = False

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(str(key), default)

    def require(self, key: str) -> Any:
        normalized = str(key)
        with self._lock:
            if normalized not in self._values:
                raise KeyError(normalized)
            return self._values[normalized]

    def snapshot(self, keys: Iterable[str] | None = None) -> dict[str, Any]:
        with self._lock:
            if keys is None:
                return dict(self._values)
            return {
                normalized: self._values[normalized]
                for normalized in (str(key) for key in keys)
                if normalized in self._values
            }

    def set(
        self,
        key: str,
        value: Any,
        *,
        source: str = "runtime",
        notify: bool = True,
    ) -> bool:
        normalized = str(key)
        missing = object()
        with self._lock:
            previous = self._values.get(normalized, missing)
            if previous is not missing and previous == value:
                return False
            self._values[normalized] = value
            self._revision += 1
            change = SettingChange(
                key=normalized,
                value=value,
                previous=None if previous is missing else previous,
                revision=self._revision,
                source=str(source or "runtime"),
            )
            listeners = self._matching_listeners_locked(normalized) if notify else []

        self._notify_mutated()
        self._notify_listeners(change, listeners)
        return True

    def update_many(
        self,
        values: dict[str, Any],
        *,
        source: str = "runtime",
        notify: bool = True,
    ) -> tuple[SettingChange, ...]:
        changes: list[SettingChange] = []
        listener_batches: list[
            tuple[SettingChange, list[tuple[int, Callable[[SettingChange], None]]]]
        ] = []
        missing = object()

        with self._lock:
            for raw_key, value in dict(values or {}).items():
                key = str(raw_key)
                previous = self._values.get(key, missing)
                if previous is not missing and previous == value:
                    continue
                self._values[key] = value
                self._revision += 1
                change = SettingChange(
                    key=key,
                    value=value,
                    previous=None if previous is missing else previous,
                    revision=self._revision,
                    source=str(source or "runtime"),
                )
                changes.append(change)
                if notify:
                    listener_batches.append(
                        (change, self._matching_listeners_locked(key))
                    )

        if not changes:
            return ()
        self._notify_mutated()
        for change, listeners in listener_batches:
            self._notify_listeners(change, listeners)
        return tuple(changes)

    def replace_all(
        self,
        values: dict[str, Any],
        *,
        source: str = "reload",
        notify: bool = False,
    ) -> None:
        with self._lock:
            self._values = dict(values or {})
            self._revision += 1
            revision = self._revision
            listeners = dict(self._listeners) if notify else {}

        if notify:
            snapshot = self.snapshot()
            for key, value in snapshot.items():
                change = SettingChange(
                    key=key,
                    value=value,
                    previous=None,
                    revision=revision,
                    source=str(source or "reload"),
                )
                callbacks = [
                    (token, callback)
                    for token, (keys, callback) in listeners.items()
                    if keys is None or key in keys
                ]
                self._notify_listeners(change, callbacks)

    def subscribe(
        self,
        callback: Callable[[SettingChange], None],
        *,
        keys: Iterable[str] | None = None,
        replay: bool = False,
    ) -> SettingsSubscription:
        if not callable(callback):
            raise TypeError("callback must be callable")
        normalized_keys = None if keys is None else frozenset(str(key) for key in keys)
        token = next(self._listener_ids)
        with self._lock:
            self._listeners[token] = (normalized_keys, callback)
            revision = self._revision
            replay_values = (
                dict(self._values)
                if replay and normalized_keys is None
                else {
                    key: self._values[key]
                    for key in (normalized_keys or ())
                    if key in self._values
                }
                if replay
                else {}
            )

        for key, value in replay_values.items():
            self._notify_listeners(
                SettingChange(
                    key=key,
                    value=value,
                    previous=None,
                    revision=revision,
                    source="replay",
                ),
                ((token, callback),),
            )
        return SettingsSubscription(self, token)

    def _unsubscribe(self, token: int) -> None:
        with self._lock:
            self._listeners.pop(token, None)
            self._pending_listener_changes.pop(token, None)
            self._scheduled_listeners.discard(token)

    def _matching_listeners_locked(
        self,
        key: str,
    ) -> list[tuple[int, Callable[[SettingChange], None]]]:
        return [
            (token, callback)
            for token, (keys, callback) in self._listeners.items()
            if keys is None or key in keys
        ]

    def _notify_mutated(self) -> None:
        callback = self._on_mutated
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            logger.error(
                f"Settings persistence callback failed: {exc}",
                exc_info=True,
            )

    def _notify_listeners(
        self,
        change: SettingChange,
        listeners: Iterable[tuple[int, Callable[[SettingChange], None]]],
    ) -> None:
        for token, callback in tuple(listeners):
            with self._lock:
                current = self._listeners.get(token)
                if current is None or current[1] != callback or self._closed:
                    continue
                self._pending_listener_changes.setdefault(token, deque()).append(change)
                if token in self._scheduled_listeners:
                    continue
                self._scheduled_listeners.add(token)
            accepted = self._dispatcher.submit(
                self._drain_listener,
                token,
                callback,
                key=token,
                description=f"settings-observer:{token}",
            )
            if not accepted:
                with self._lock:
                    self._scheduled_listeners.discard(token)
                logger.error(
                    f"Settings observer dispatcher is closed; revision "
                    f"{change.revision} for key '{change.key}' could not be scheduled"
                )

    def _drain_listener(
        self,
        token: int,
        callback: Callable[[SettingChange], None],
    ) -> None:
        while True:
            with self._lock:
                current = self._listeners.get(token)
                if current is None or current[1] != callback:
                    self._pending_listener_changes.pop(token, None)
                    self._scheduled_listeners.discard(token)
                    return
                pending = self._pending_listener_changes.pop(token, deque())
                if not pending:
                    self._scheduled_listeners.discard(token)
                    return
            for change in pending:
                self._invoke_listener(token, callback, change)

    def _invoke_listener(
        self,
        token: int,
        callback: Callable[[SettingChange], None],
        change: SettingChange,
    ) -> None:
        with self._lock:
            current = self._listeners.get(token)
            if current is None or current[1] != callback:
                return
        try:
            callback(change)
        except Exception as exc:
            callback_name = getattr(callback, "__qualname__", None) or getattr(
                callback, "__name__", None
            ) or repr(callback)
            logger.error(
                f"Settings observer '{callback_name}' failed for "
                f"key '{change.key}' at revision {change.revision}: {exc}",
                exc_info=True,
            )

    def flush_notifications(self, timeout: float = 5.0) -> bool:
        return self._dispatcher.wait_idle(timeout=timeout)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._dispatcher.close(drain=True, timeout=2.0)

    def __getitem__(self, key: str) -> Any:
        return self.require(str(key))

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(str(key), value)

    def __delitem__(self, key: str) -> None:
        normalized = str(key)
        with self._lock:
            if normalized not in self._values:
                raise KeyError(normalized)
            previous = self._values.pop(normalized)
            self._revision += 1
            change = SettingChange(
                key=normalized,
                value=None,
                previous=previous,
                revision=self._revision,
                source="delete",
            )
            listeners = self._matching_listeners_locked(normalized)
        self._notify_mutated()
        self._notify_listeners(change, listeners)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(self._values.keys()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)
