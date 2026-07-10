from __future__ import annotations

import weakref
from collections import defaultdict
from typing import Any, Callable, Iterable

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

from core.settings_registry import SettingChange


class QtSettingsViewModel(QObject):
    """Qt adapter over the process-wide SettingsService.

    The registry stays GUI-agnostic. This adapter only marshals notifications
    onto the Qt thread and maintains weak widget bindings.
    """

    snapshot_ready = pyqtSignal(dict)
    changed = pyqtSignal(str, object)
    _incoming = pyqtSignal(object)

    def __init__(self, settings_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings_service
        self._snapshot = self._settings.snapshot()
        self._bindings: dict[
            str,
            list[tuple[weakref.ReferenceType[QObject], Callable[[Any], None]]],
        ] = defaultdict(list)
        self._incoming.connect(self._on_incoming, Qt.ConnectionType.QueuedConnection)
        self._subscription = self._settings.subscribe(self._receive_change)

    def get(self, key: str, default: Any = None) -> Any:
        return self._snapshot.get(str(key), default)

    def set(self, key: str, value: Any) -> None:
        self._settings.update(key, value)

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
        self._bindings[normalized].append((weakref.ref(owner), apply_value))
        if apply_current:
            apply_value(self.get(normalized, default))

    def close(self) -> None:
        subscription = getattr(self, "_subscription", None)
        if subscription is not None:
            subscription.close()
            self._subscription = None
        self._bindings.clear()

    def _receive_change(self, change: SettingChange) -> None:
        self._incoming.emit(change)

    @pyqtSlot(object)
    def _on_incoming(self, change: SettingChange) -> None:
        if change.source == "delete":
            self._snapshot.pop(change.key, None)
        else:
            self._snapshot[change.key] = change.value
        self.changed.emit(change.key, change.value)
        bindings = self._bindings.get(change.key)
        if not bindings:
            return

        alive: list[tuple[weakref.ReferenceType[QObject], Callable[[Any], None]]] = []
        for owner_ref, apply_value in bindings:
            if owner_ref() is None:
                continue
            try:
                apply_value(change.value)
            except RuntimeError:
                continue
            alive.append((owner_ref, apply_value))

        if alive:
            self._bindings[change.key] = alive
        else:
            self._bindings.pop(change.key, None)


# Backward-compatible name used by the first registry migration.
QtSettingsBinding = QtSettingsViewModel
