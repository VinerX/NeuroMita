from __future__ import annotations

from typing import Any


def settings_store(owner: Any):
    seen: set[int] = set()
    current = owner
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        binding = getattr(current, "settings_binding", None)
        if binding is None:
            binding = getattr(current, "settings_view_model", None)
        if binding is not None:
            return binding

        settings = getattr(current, "settings", None)
        if settings is not None:
            return settings

        gui = getattr(current, "gui", None)
        if gui is not None and id(gui) not in seen:
            current = gui
            continue
        try:
            current = current.parent()
        except Exception:
            current = None
    return None


def get_setting(owner: Any, key: str, default: Any = None) -> Any:
    store = settings_store(owner)
    if store is None:
        return default
    getter = getattr(store, "get", None)
    if callable(getter):
        return getter(str(key), default)
    try:
        return store[str(key)]
    except (KeyError, TypeError):
        return default


def set_setting(owner: Any, key: str, value: Any) -> None:
    store = settings_store(owner)
    if store is None:
        raise RuntimeError("Settings binding is not attached")
    setter = getattr(store, "set", None)
    if callable(setter):
        setter(str(key), value)
        return
    updater = getattr(store, "update", None)
    if callable(updater):
        updater(str(key), value)
        return
    store[str(key)] = value