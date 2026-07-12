from __future__ import annotations

import importlib
import threading
from collections.abc import Iterable
from typing import Any, Callable

from installables.catalog_manifest import catalog_by_id, catalog_entries, entries_for_category
from main_logger import logger


class LazyInstallableRegistry:
    """Resolves installable implementations per component group on demand.

    Catalog metadata lives in ``catalog_manifest`` and is available without
    importing TTS/ASR/RAG implementations. Work modules are imported only when
    status, settings or an install action for their component is requested.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._components: dict[str, Any] = {}
        self._loaded_groups: set[str] = set()
        self._failed_groups: dict[str, BaseException] = {}
        self._loading_groups: dict[str, threading.Event] = {}

    @staticmethod
    def _resolve_loader(path: str) -> Callable[[], Iterable[Any]]:
        module_name, separator, qualname = str(path or "").partition(":")
        if not separator or not module_name or not qualname:
            raise ValueError(f"Invalid installable loader path: {path!r}")
        target: Any = importlib.import_module(module_name)
        for part in qualname.split("."):
            target = getattr(target, part)
        if not callable(target):
            raise TypeError(f"Installable loader is not callable: {path}")
        return target

    def _load_group(self, loader_path: str) -> None:
        loader_path = str(loader_path)
        with self._lock:
            if loader_path in self._loaded_groups or loader_path in self._failed_groups:
                return
            wait_event = self._loading_groups.get(loader_path)
            if wait_event is None:
                wait_event = threading.Event()
                self._loading_groups[loader_path] = wait_event
                owner = True
            else:
                owner = False

        if not owner:
            wait_event.wait()
            return

        components: list[Any] = []
        error: BaseException | None = None
        try:
            factory = self._resolve_loader(loader_path)
            components = list(factory() or ())
        except BaseException as exc:
            error = exc

        with self._lock:
            if error is not None:
                self._failed_groups[loader_path] = error
            else:
                for component in components:
                    component_id = str(getattr(component, "id", "") or "").strip()
                    if not component_id:
                        logger.warning(
                            f"Installable registry: loader '{loader_path}' returned a component without id"
                        )
                        continue
                    self._components[component_id] = component
                self._loaded_groups.add(loader_path)
            event = self._loading_groups.pop(loader_path, None)
            if event is not None:
                event.set()

        if error is not None:
            logger.error(
                f"Installable registry: failed to load '{loader_path}': {error}",
                exc_info=(type(error), error, error.__traceback__),
            )

    def get(self, component_id: str):
        component_id = str(component_id or "").strip()
        if not component_id:
            return None
        with self._lock:
            cached = self._components.get(component_id)
            if cached is not None:
                return cached
            entry = catalog_by_id().get(component_id)
        if entry is None:
            return None
        self._load_group(entry.loader)
        with self._lock:
            return self._components.get(component_id)

    def require(self, component_id: str):
        component = self.get(component_id)
        if component is None:
            entry = catalog_by_id().get(str(component_id or "").strip())
            if entry is not None:
                error = self._failed_groups.get(entry.loader)
                if error is not None:
                    raise RuntimeError(
                        f"Installable component '{component_id}' failed to load: {error}"
                    ) from error
            raise KeyError(f"Unknown installable component: {component_id}")
        return component

    def all(self) -> list[Any]:
        entries = catalog_entries()
        for entry in entries:
            self._load_group(entry.loader)
        with self._lock:
            return [
                self._components[entry.id]
                for entry in entries
                if entry.id in self._components
            ]

    def by_category(self, category) -> list[Any]:
        value = getattr(category, "value", category)
        entries = entries_for_category(str(value or ""))
        for entry in entries:
            self._load_group(entry.loader)
        with self._lock:
            return [
                self._components[entry.id]
                for entry in entries
                if entry.id in self._components
            ]

    def invalidate(self, *, component_id: str | None = None) -> None:
        with self._lock:
            if component_id:
                entry = catalog_by_id().get(str(component_id))
                if entry is None:
                    return
                loader_path = entry.loader
                self._loaded_groups.discard(loader_path)
                self._failed_groups.pop(loader_path, None)
                for spec in catalog_entries():
                    if spec.loader == loader_path:
                        self._components.pop(spec.id, None)
                return
            self._components.clear()
            self._loaded_groups.clear()
            self._failed_groups.clear()


_REGISTRY: LazyInstallableRegistry | None = None
_REGISTRY_LOCK = threading.RLock()


def build_installable_registry() -> LazyInstallableRegistry:
    return LazyInstallableRegistry()


def get_installable_registry() -> LazyInstallableRegistry:
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = build_installable_registry()
        return _REGISTRY


def refresh_installable_registry() -> LazyInstallableRegistry:
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = build_installable_registry()
        return _REGISTRY
