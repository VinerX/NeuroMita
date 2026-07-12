from __future__ import annotations

import weakref
from collections import defaultdict
from typing import Any, Callable, Iterable

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

_MISSING = object()


class QtSettingsViewModel(QObject):
    """Qt adapter over the process-wide SettingsService.

    The registry stays GUI-agnostic. This adapter only marshals notifications
    onto the Qt thread and maintains weak widget bindings.
    """

    snapshot_ready = pyqtSignal(dict)
    changed = pyqtSignal(str, object)
    write_failed = pyqtSignal(str, object)
    _incoming = pyqtSignal(object)

    def __init__(self, settings_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings_service
        self._snapshot = self._settings.snapshot()
        self._closed = False
        self._applying: set[tuple[int, str]] = set()
        self._owners_connected: dict[int, weakref.ReferenceType[QObject]] = {}
        self._bindings: dict[
            str,
            list[
                tuple[
                    weakref.ReferenceType[QObject],
                    Callable[[Any], None],
                    Any,
                ]
            ],
        ] = defaultdict(list)
        self._write_connections: dict[int, list[tuple[Any, Callable[..., None]]]] = (
            defaultdict(list)
        )
        self._incoming.connect(self._on_incoming, Qt.ConnectionType.QueuedConnection)
        self._subscription = self._settings.subscribe(self._receive_change)

    def get(self, key: str, default: Any = None) -> Any:
        return self._snapshot.get(str(key), default)

    def set(self, key: str, value: Any) -> None:
        if self._closed:
            return
        normalized = str(key)
        if self._snapshot.get(normalized) == value:
            return
        previous = self._snapshot.get(normalized, _MISSING)
        self._snapshot[normalized] = value
        try:
            self._settings.update(normalized, value)
        except Exception as exc:
            missing = previous is _MISSING
            if missing:
                self._snapshot.pop(normalized, None)
            else:
                self._snapshot[normalized] = previous
            self._publish_value(
                normalized,
                None if missing else previous,
                missing=missing,
            )
            self.write_failed.emit(normalized, exc)
            raise

    def snapshot(self, keys: Iterable[str] | None = None) -> dict[str, Any]:
        if keys is None:
            return dict(self._snapshot)
        return {
            key: self._snapshot[key]
            for key in (str(item) for item in keys)
            if key in self._snapshot
        }

    @pyqtSlot()
    def request_snapshot(self) -> None:
        self.snapshot_ready.emit(self.snapshot())

    def bind(
        self,
        key: str,
        owner: QObject,
        apply_value: Callable[[Any], None],
        *,
        apply_current: bool = False,
        default: Any = None,
    ) -> None:
        normalized = str(key)
        self._bindings[normalized] = [
            item
            for item in self._bindings[normalized]
            if item[0]() is not None and item[0]() is not owner
        ]
        self._bindings[normalized].append((weakref.ref(owner), apply_value, default))
        owner_id = id(owner)
        if owner_id not in self._owners_connected:
            owner_ref = weakref.ref(owner)
            self._owners_connected[owner_id] = owner_ref
            try:
                owner.destroyed.connect(
                    lambda *_args, owner_id=owner_id, owner_ref=owner_ref: self._owner_destroyed(
                        owner_id,
                        owner_ref,
                    )
                )
            except Exception:
                self._owners_connected.pop(owner_id, None)
        if apply_current:
            self._apply_bound_value(normalized, owner, apply_value, self.get(normalized, default))

    def bind_two_way(
        self,
        key: str,
        owner: QObject,
        changed_signal,
        read_value: Callable[[], Any],
        apply_value: Callable[[Any], None],
        *,
        default: Any = None,
        transform: Callable[[Any], Any] | None = None,
        after_write: Callable[[Any], None] | None = None,
    ) -> None:
        normalized = str(key)
        owner_ref = weakref.ref(owner)
        token = (id(owner), normalized)

        def write_from_widget(*_args) -> None:
            current_owner = owner_ref()
            if current_owner is None or self._closed or token in self._applying:
                return
            try:
                value = read_value()
                if transform is not None:
                    value = transform(value)
                self.set(normalized, value)
                if after_write is not None:
                    after_write(value)
            except RuntimeError:
                return
            except Exception:
                return

        changed_signal.connect(write_from_widget)
        self._write_connections[id(owner)].append((changed_signal, write_from_widget))
        self.bind(
            normalized,
            owner,
            apply_value,
            apply_current=True,
            default=default,
        )

    def unbind_owner(self, owner: QObject) -> None:
        owner_id = id(owner)
        for key in tuple(self._bindings):
            kept = [
                item
                for item in self._bindings[key]
                if item[0]() is not None and item[0]() is not owner
            ]
            if kept:
                self._bindings[key] = kept
            else:
                self._bindings.pop(key, None)
        self._disconnect_owner_writes(owner_id)
        self._owners_connected.pop(owner_id, None)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        subscription = getattr(self, "_subscription", None)
        if subscription is not None:
            subscription.close()
            self._subscription = None
        for owner_id in tuple(self._write_connections):
            self._disconnect_owner_writes(owner_id)
        self._bindings.clear()
        self._owners_connected.clear()
        self._applying.clear()

    def _receive_change(self, change: Any) -> None:
        if not self._closed:
            self._incoming.emit(change)

    @pyqtSlot(object)
    def _on_incoming(self, change: Any) -> None:
        if self._closed:
            return
        if change.source == "delete":
            self._snapshot.pop(change.key, None)
            self._publish_value(change.key, None, missing=True)
        else:
            self._snapshot[change.key] = change.value
            self._publish_value(change.key, change.value, missing=False)

    def _publish_value(self, key: str, value: Any, *, missing: bool) -> None:
        self.changed.emit(key, value)
        bindings = self._bindings.get(key)
        if not bindings:
            return

        alive: list[
            tuple[weakref.ReferenceType[QObject], Callable[[Any], None], Any]
        ] = []
        for owner_ref, apply_value, default in bindings:
            owner = owner_ref()
            if owner is None:
                continue
            try:
                self._apply_bound_value(
                    key,
                    owner,
                    apply_value,
                    default if missing else value,
                )
            except RuntimeError:
                continue
            alive.append((owner_ref, apply_value, default))

        if alive:
            self._bindings[key] = alive
        else:
            self._bindings.pop(key, None)

    def _apply_bound_value(
        self,
        key: str,
        owner: QObject,
        apply_value: Callable[[Any], None],
        value: Any,
    ) -> None:
        token = (id(owner), str(key))
        self._applying.add(token)
        try:
            apply_value(value)
        finally:
            self._applying.discard(token)

    def _owner_destroyed(
        self,
        owner_id: int,
        owner_ref: weakref.ReferenceType[QObject],
    ) -> None:
        self._disconnect_owner_writes(owner_id)
        self._owners_connected.pop(owner_id, None)
        owner = owner_ref()
        if owner is not None:
            self.unbind_owner(owner)
            return
        for key in tuple(self._bindings):
            kept = [item for item in self._bindings[key] if item[0]() is not None]
            if kept:
                self._bindings[key] = kept
            else:
                self._bindings.pop(key, None)

    def _disconnect_owner_writes(self, owner_id: int) -> None:
        connections = self._write_connections.pop(owner_id, ())
        for signal, callback in connections:
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                pass
