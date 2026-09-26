from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass
from typing import Any, Callable


class IPCMethodNotAllowed(LookupError):
    pass


class IPCInvalidParams(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IPCMethod:
    name: str
    callback: Callable[..., Any]
    description: str


def ipc_allowed(name: str, *, description: str = ""):
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("IPC method name must not be empty")

    def decorate(callback: Callable[..., Any]) -> Callable[..., Any]:
        if not callable(callback):
            raise TypeError("@ipc_allowed can only decorate callables")
        setattr(callback, "__ipc_allowed__", True)
        setattr(callback, "__ipc_name__", normalized)
        setattr(callback, "__ipc_description__", str(description or "").strip())
        return callback

    return decorate


class IPCRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._methods: dict[str, IPCMethod] = {}

    def register_object(self, instance: Any) -> tuple[str, ...]:
        registered: list[str] = []
        for attribute_name in dir(type(instance)):
            descriptor = getattr(type(instance), attribute_name, None)
            if not bool(getattr(descriptor, "__ipc_allowed__", False)):
                continue
            callback = getattr(instance, attribute_name)
            name = str(getattr(descriptor, "__ipc_name__", "") or "").strip()
            description = str(
                getattr(descriptor, "__ipc_description__", "") or ""
            ).strip()
            with self._lock:
                if name in self._methods:
                    raise ValueError(f"IPC method is already registered: {name}")
                self._methods[name] = IPCMethod(name, callback, description)
            registered.append(name)
        return tuple(sorted(registered))

    def methods(self) -> tuple[dict[str, str], ...]:
        with self._lock:
            records = tuple(self._methods.values())
        return tuple(
            {"name": record.name, "description": record.description}
            for record in sorted(records, key=lambda item: item.name)
        )

    def invoke(self, method: str, params: Any = None) -> Any:
        normalized = str(method or "").strip()
        with self._lock:
            record = self._methods.get(normalized)
        if record is None:
            raise IPCMethodNotAllowed(f"IPC method is not allowed: {normalized}")

        if params is None:
            result = record.callback()
        elif isinstance(params, dict):
            result = record.callback(**params)
        elif isinstance(params, list):
            result = record.callback(*params)
        else:
            raise IPCInvalidParams("params must be an object, an array, or null")

        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result
