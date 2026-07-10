from __future__ import annotations

import importlib.util
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from core.events import get_event_bus
from core.daemon_executor import DaemonExecutor
from core.services import ServiceRegistration, services
from main_logger import logger
from services.contracts import RuntimeFeatureService
from startup.startup_profiler import startup_trace


class FeatureState(str, Enum):
    REGISTERED = "registered"
    DISABLED = "disabled"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ABANDONED = "abandoned"


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
    generation: int = 0
    service_registrations: tuple[ServiceRegistration, ...] = ()


class RuntimeFeatureManager(RuntimeFeatureService):
    """Owns optional runtime controllers and their service registrations.

    Import and construction happen in one background job. Every load receives a
    generation token, and every published service receives an owner-safe handle.
    A late completion or shutdown from an old generation therefore cannot
    resurrect a disabled feature or unregister its replacement.
    """

    def __init__(self, settings_service, *, max_workers: int = 2) -> None:
        self._settings = settings_service
        self._lock = threading.RLock()
        self._entries: dict[str, _FeatureEntry] = {}
        self._key_index: dict[str, set[str]] = {}
        self._executor = DaemonExecutor(
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
            if entry.state is FeatureState.STOPPING:
                return self._failed_future(
                    RuntimeError(f"Feature '{normalized}' is stopping")
                )

            missing = self._missing_modules(entry.spec)
            if missing:
                error = RuntimeError(
                    f"Feature '{normalized}' requires missing modules: {', '.join(missing)}"
                )
                entry.state = FeatureState.UNAVAILABLE
                entry.error = error
                return self._failed_future(error)

            entry.generation += 1
            generation = entry.generation
            entry.state = FeatureState.LOADING
            entry.error = None
            entry.stop_requested = False
            entry.future = self._executor.submit(self._build, normalized, generation)
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
                    "generation": entry.generation,
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
            ready: list[
                tuple[_FeatureEntry, FeatureSpec, Any, tuple[ServiceRegistration, ...]]
            ] = []
            for entry in entries:
                if entry.state is FeatureState.LOADING:
                    entry.stop_requested = True
                    entry.generation += 1
                    entry.state = FeatureState.ABANDONED
                    if entry.future is not None:
                        entry.future.cancel()
                elif entry.state is FeatureState.READY:
                    entry.state = FeatureState.STOPPING
                    ready.append(
                        (
                            entry,
                            entry.spec,
                            entry.instance,
                            entry.service_registrations,
                        )
                    )
                    entry.service_registrations = ()

        if subscription is not None:
            subscription.close()

        for entry, spec, instance, registrations in ready:
            self._close_registrations(registrations)
            try:
                self._shutdown_instance(spec, instance)
            except Exception as exc:
                logger.error(
                    f"Failed to stop optional feature '{spec.name}': {exc}",
                    exc_info=True,
                )
            finally:
                with self._lock:
                    entry.instance = None
                    entry.future = None
                    entry.error = None
                    entry.state = FeatureState.STOPPED

        self._executor.shutdown(cancel_futures=True)

    def _build(self, name: str, generation: int) -> Any:
        with self._lock:
            entry = self._entries[name]
            spec = entry.spec
        startup_trace.mark(f"feature.{name}.start", generation=generation)

        try:
            instance = spec.factory()
        except BaseException as exc:
            with self._lock:
                current = entry.generation == generation
                if current:
                    entry.future = None
                    if self._closed:
                        entry.state = FeatureState.STOPPED
                    elif entry.stop_requested:
                        entry.state = FeatureState.DISABLED
                        entry.stop_requested = False
                    else:
                        entry.state = FeatureState.FAILED
                        entry.error = exc
            startup_trace.mark(
                f"feature.{name}.failed",
                generation=generation,
                error=f"{type(exc).__name__}: {exc}",
            )
            if not self._closed:
                logger.warning(f"Optional feature '{name}' is unavailable: {exc}")
            raise

        with self._lock:
            stale = entry.generation != generation
            should_stop = stale or self._closed or entry.stop_requested
            stop_for_shutdown = self._closed

        if should_stop:
            try:
                self._shutdown_instance(spec, instance)
            finally:
                restart = False
                with self._lock:
                    if entry.generation == generation:
                        entry.instance = None
                        entry.future = None
                        entry.stop_requested = False
                        entry.state = (
                            FeatureState.STOPPED
                            if stop_for_shutdown
                            else FeatureState.DISABLED
                        )
                        restart = not self._closed and self._is_enabled(spec)
            if stop_for_shutdown:
                raise RuntimeError(f"Feature '{name}' finished loading after shutdown")
            startup_trace.mark(
                f"feature.{name}.disabled_during_load", generation=generation
            )
            if restart:
                self.ensure_async(name)
            return None

        registrations: list[ServiceRegistration] = []
        registration_error: BaseException | None = None
        with self._lock:
            if (
                entry.generation != generation
                or self._closed
                or entry.stop_requested
            ):
                should_stop = True
            else:
                try:
                    for contract in spec.provided_services:
                        registrations.append(
                            services().register_owned(contract, instance, replace=True)
                        )
                except BaseException as exc:
                    registration_error = exc
                else:
                    entry.instance = instance
                    entry.service_registrations = tuple(registrations)
                    entry.state = FeatureState.READY
                    entry.error = None
                    entry.future = None
                    should_stop = False

        if registration_error is not None:
            self._close_registrations(tuple(registrations))
            try:
                self._shutdown_instance(spec, instance)
            finally:
                with self._lock:
                    if entry.generation == generation:
                        entry.instance = None
                        entry.service_registrations = ()
                        entry.future = None
                        entry.error = registration_error
                        entry.state = FeatureState.FAILED
            startup_trace.mark(
                f"feature.{name}.failed",
                generation=generation,
                error=f"{type(registration_error).__name__}: {registration_error}",
            )
            raise registration_error

        if should_stop:
            self._close_registrations(tuple(registrations))
            try:
                self._shutdown_instance(spec, instance)
            finally:
                restart = False
                with self._lock:
                    if entry.generation == generation:
                        entry.instance = None
                        entry.service_registrations = ()
                        entry.future = None
                        entry.stop_requested = False
                        entry.state = (
                            FeatureState.STOPPED
                            if self._closed
                            else FeatureState.DISABLED
                        )
                        restart = not self._closed and self._is_enabled(spec)
            if restart:
                self.ensure_async(name)
            return None

        startup_trace.mark(f"feature.{name}.ready", generation=generation)
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
                if enabled:
                    if entry.state is FeatureState.LOADING and entry.stop_requested:
                        # Disable -> enable while factory is still running: keep
                        # the same generation instead of throwing it away and
                        # silently losing the re-enable request.
                        entry.stop_requested = False
                    elif entry.state in {
                        FeatureState.REGISTERED,
                        FeatureState.DISABLED,
                        FeatureState.FAILED,
                        FeatureState.UNAVAILABLE,
                        FeatureState.STOPPED,
                    }:
                        to_start.append(name)
                    continue

                if not entry.spec.stop_when_disabled:
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
            generation = entry.generation
            instance = entry.instance
            spec = entry.spec
            registrations = entry.service_registrations
            entry.service_registrations = ()

        self._close_registrations(registrations)
        try:
            self._shutdown_instance(spec, instance)
        except Exception as exc:
            logger.error(
                f"Failed to stop disabled feature '{name}': {exc}",
                exc_info=True,
            )
        finally:
            restart = False
            with self._lock:
                if entry.generation == generation:
                    entry.instance = None
                    entry.future = None
                    entry.error = None
                    entry.state = FeatureState.DISABLED
                    restart = not self._closed and self._is_enabled(spec)

        startup_trace.mark(f"feature.{name}.disabled", generation=generation)
        if restart:
            self.ensure_async(name)

    def _is_enabled(self, spec: FeatureSpec) -> bool:
        try:
            return bool(spec.enabled(self._settings))
        except Exception as exc:
            logger.error(
                f"Failed to evaluate optional feature '{spec.name}' settings: {exc}",
                exc_info=True,
            )
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

    @classmethod
    def _shutdown_instance(cls, spec: FeatureSpec, instance: Any) -> None:
        if instance is None:
            return
        # Legacy optional controllers still contain strong EventBus bound-method
        # subscriptions. Remove them centrally so disable/re-enable cannot leave
        # ghost handlers or keep the old controller alive.
        try:
            get_event_bus().unsubscribe_owner(instance)
        except Exception as exc:
            logger.error(
                f"Failed to detach EventBus subscriptions for feature "
                f"'{spec.name}': {exc}",
                exc_info=True,
            )
        if spec.shutdown is not None:
            spec.shutdown(instance)
        else:
            cls._default_shutdown(instance)

    @staticmethod
    def _default_shutdown(instance: Any) -> None:
        for method_name in ("shutdown", "destroy", "close", "stop"):
            method = getattr(instance, method_name, None)
            if callable(method):
                method()
                return

    @staticmethod
    def _close_registrations(
        registrations: tuple[ServiceRegistration, ...],
    ) -> None:
        for registration in reversed(registrations):
            try:
                registration.close()
            except Exception as exc:
                logger.error(
                    f"Failed to unregister optional service "
                    f"'{registration.contract.__name__}': {exc}",
                    exc_info=True,
                )

    @staticmethod
    def _failed_future(error: BaseException) -> Future:
        future = Future()
        future.set_exception(error)
        return future
