from __future__ import annotations

import importlib.util
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable

from main_logger import logger
from startup.startup_profiler import startup_trace
from core.services import services
from services.contracts import RuntimeFeatureService


class FeatureState(str, Enum):
    REGISTERED = "registered"
    DISABLED = "disabled"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    factory: Callable[[], Any]
    enabled: Callable[[Any], bool]
    setting_keys: tuple[str, ...] = ()
    shutdown: Callable[[Any], None] | None = None
    startup: bool = True
    priority: int = 100
    required_modules: tuple[str, ...] = ()
    stop_when_disabled: bool = True
    provided_services: tuple[type, ...] = ()


@dataclass(slots=True)
class _FeatureEntry:
    spec: FeatureSpec
    state: FeatureState = FeatureState.REGISTERED
    instance: Any = None
    future: Future | None = None
    error: BaseException | None = None
    stop_requested: bool = False


class RuntimeFeatureManager(RuntimeFeatureService):
    """Owns optional runtime controllers and initializes them once.

    A feature job contains both module import and controller construction. This
    avoids the old two-stage path where an expensive package was imported on
    startup and initialized again on first use.
    """

    def __init__(self, settings_service, *, max_workers: int = 2) -> None:
        self._settings = settings_service
        self._lock = threading.RLock()
        self._entries: dict[str, _FeatureEntry] = {}
        self._key_index: dict[str, set[str]] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="runtime-feature",
        )
        self._closed = False
        self._subscription = self._settings.subscribe(self._on_setting_changed)

    def register(self, spec: FeatureSpec) -> None:
        name = str(spec.name)
        with self._lock:
            if self._closed:
                raise RuntimeError("RuntimeFeatureManager is closed")
            if name in self._entries:
                raise ValueError(f"Feature '{name}' is already registered")
            self._entries[name] = _FeatureEntry(spec=spec)
            for key in spec.setting_keys:
                self._key_index.setdefault(str(key), set()).add(name)

    def start_enabled(self) -> dict[str, Future]:
        with self._lock:
            specs = sorted(
                (
                    entry.spec
                    for entry in self._entries.values()
                    if entry.spec.startup and self._is_enabled(entry.spec)
                ),
                key=lambda item: (item.priority, item.name),
            )
        return {spec.name: self.ensure_async(spec.name) for spec in specs}

    def ensure_async(self, name: str) -> Future:
        normalized = str(name)
        with self._lock:
            if self._closed:
                return self._failed_future(RuntimeError("RuntimeFeatureManager is closed"))
            entry = self._entries.get(normalized)
            if entry is None:
                return self._failed_future(KeyError(normalized))
            if entry.state is FeatureState.READY:
                completed = Future()
                completed.set_result(entry.instance)
                return completed
            if entry.state is FeatureState.LOADING and entry.future is not None:
                return entry.future

            missing = self._missing_modules(entry.spec)
            if missing:
                error = RuntimeError(
                    f"Feature '{normalized}' requires missing modules: {', '.join(missing)}"
                )
                entry.state = FeatureState.UNAVAILABLE
                entry.error = error
                return self._failed_future(error)

            entry.state = FeatureState.LOADING
            entry.error = None
            entry.stop_requested = False
            entry.future = self._executor.submit(self._build, normalized)
            return entry.future

    def ensure(self, name: str, *, timeout: float | None = None) -> Any:
        return self.ensure_async(name).result(timeout=timeout)

    def get(self, name: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(str(name))
            if entry is None or entry.state is not FeatureState.READY:
                return default
            return entry.instance

    def is_ready(self, name: str) -> bool:
        with self._lock:
            entry = self._entries.get(str(name))
            return bool(entry is not None and entry.state is FeatureState.READY)

    def state(self, name: str) -> FeatureState:
        with self._lock:
            entry = self._entries.get(str(name))
            if entry is None:
                raise KeyError(name)
            if entry.state is FeatureState.REGISTERED:
                if self._missing_modules(entry.spec):
                    return FeatureState.UNAVAILABLE
                if not self._is_enabled(entry.spec):
                    return FeatureState.DISABLED
            return entry.state

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            out: dict[str, dict[str, Any]] = {}
            for name, entry in self._entries.items():
                state = entry.state
                missing = self._missing_modules(entry.spec)
                if state is FeatureState.REGISTERED:
                    if missing:
                        state = FeatureState.UNAVAILABLE
                    elif not self._is_enabled(entry.spec):
                        state = FeatureState.DISABLED
                out[name] = {
                    "state": state.value,
                    "enabled": self._is_enabled(entry.spec),
                    "error": str(entry.error) if entry.error else "",
                    "missing_modules": list(missing),
                }
            return out

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscription = self._subscription
            self._subscription = None
            entries = sorted(
                self._entries.values(),
                key=lambda entry: (entry.spec.priority, entry.spec.name),
                reverse=True,
            )

        if subscription is not None:
            subscription.close()

        for entry in entries:
            if entry.state is not FeatureState.READY:
                continue
            try:
                if entry.spec.shutdown is not None:
                    entry.spec.shutdown(entry.instance)
                else:
                    self._default_shutdown(entry.instance)
            except Exception as exc:
                logger.error(
                    f"Failed to stop optional feature '{entry.spec.name}': {exc}",
                    exc_info=True,
                )
            finally:
                self._unregister_services(entry.spec)
                entry.state = FeatureState.STOPPED

        self._executor.shutdown(wait=False, cancel_futures=True)

    def _build(self, name: str) -> Any:
        with self._lock:
            entry = self._entries[name]
            spec = entry.spec
        startup_trace.mark(f"feature.{name}.start")
        try:
            instance = spec.factory()
        except BaseException as exc:
            with self._lock:
                entry.state = FeatureState.FAILED
                entry.error = exc
            startup_trace.mark(
                f"feature.{name}.failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            logger.warning(f"Optional feature '{name}' is unavailable: {exc}")
            raise
        with self._lock:
            should_stop = self._closed or entry.stop_requested
            stop_for_shutdown = self._closed

        if should_stop:
            try:
                if spec.shutdown is not None:
                    spec.shutdown(instance)
                else:
                    self._default_shutdown(instance)
            finally:
                with self._lock:
                    entry.instance = None
                    entry.future = None
                    entry.stop_requested = False
                    entry.state = (
                        FeatureState.STOPPED if stop_for_shutdown else FeatureState.DISABLED
                    )
            if stop_for_shutdown:
                raise RuntimeError(f"Feature '{name}' finished loading after shutdown")
            startup_trace.mark(f"feature.{name}.disabled_during_load")
            return None

        with self._lock:
            entry.instance = instance
            entry.state = FeatureState.READY
            entry.error = None
        for contract in spec.provided_services:
            services().register(contract, instance, replace=True)
        startup_trace.mark(f"feature.{name}.ready")
        logger.info(f"Optional feature ready: {name}")
        return instance

    def _on_setting_changed(self, change) -> None:
        with self._lock:
            names = tuple(self._key_index.get(str(change.key), ()))
            if self._closed:
                return
            to_start: list[str] = []
            to_stop: list[str] = []
            for name in names:
                entry = self._entries[name]
                enabled = self._is_enabled(entry.spec)
                if enabled and entry.state in {
                    FeatureState.REGISTERED,
                    FeatureState.DISABLED,
                    FeatureState.FAILED,
                    FeatureState.UNAVAILABLE,
                    FeatureState.STOPPED,
                }:
                    to_start.append(name)
                    continue
                if enabled or not entry.spec.stop_when_disabled:
                    continue
                if entry.state is FeatureState.LOADING:
                    entry.stop_requested = True
                elif entry.state is FeatureState.READY:
                    entry.state = FeatureState.STOPPING
                    to_stop.append(name)

        for name in to_start:
            self.ensure_async(name)
        for name in to_stop:
            self._executor.submit(self._stop_disabled_feature, name)

    def _stop_disabled_feature(self, name: str) -> None:
        with self._lock:
            entry = self._entries.get(name)
            if entry is None or entry.state is not FeatureState.STOPPING:
                return
            instance = entry.instance
            spec = entry.spec

        try:
            if spec.shutdown is not None:
                spec.shutdown(instance)
            else:
                self._default_shutdown(instance)
        except Exception as exc:
            logger.error(
                f"Failed to stop disabled feature '{name}': {exc}",
                exc_info=True,
            )
        finally:
            self._unregister_services(spec)
            with self._lock:
                entry.instance = None
                entry.future = None
                entry.error = None
                entry.state = FeatureState.DISABLED
                restart = not self._closed and self._is_enabled(spec)

        startup_trace.mark(f"feature.{name}.disabled")
        if restart:
            self.ensure_async(name)

    def _is_enabled(self, spec: FeatureSpec) -> bool:
        try:
            return bool(spec.enabled(self._settings))
        except Exception:
            return False

    @staticmethod
    def _missing_modules(spec: FeatureSpec) -> tuple[str, ...]:
        missing: list[str] = []
        for module_name in spec.required_modules:
            try:
                if importlib.util.find_spec(str(module_name)) is None:
                    missing.append(str(module_name))
            except (ImportError, AttributeError, ValueError):
                missing.append(str(module_name))
        return tuple(missing)

    @staticmethod
    def _default_shutdown(instance: Any) -> None:
        for method_name in ("shutdown", "destroy", "close", "stop"):
            method = getattr(instance, method_name, None)
            if callable(method):
                method()
                return

    @staticmethod
    def _unregister_services(spec: FeatureSpec) -> None:
        for contract in spec.provided_services:
            services().unregister(contract)

    @staticmethod
    def _failed_future(error: BaseException) -> Future:
        future = Future()
        future.set_exception(error)
        return future
