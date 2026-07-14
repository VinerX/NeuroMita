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
from core.task_supervisor import task_supervisor
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
    depends_on: tuple[str, ...] = ()


@dataclass(slots=True)
class _FeatureEntry:
    spec: FeatureSpec
    state: FeatureState = FeatureState.REGISTERED
    instance: Any = None
    future: Future[Any] | None = None
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
        self._dependents: dict[str, set[str]] = {}
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
            if name in {str(dep) for dep in spec.depends_on}:
                raise ValueError(f"Feature '{name}' cannot depend on itself")
            self._entries[name] = _FeatureEntry(spec=spec)
            for dependency in spec.depends_on:
                self._dependents.setdefault(str(dependency), set()).add(name)
            for key in spec.setting_keys:
                self._key_index.setdefault(str(key), set()).add(name)

    def start_enabled(self) -> dict[str, Future[Any]]:
        with self._lock:
            self._validate_graph_locked()
            names = [
                name
                for name, entry in self._entries.items()
                if entry.spec.startup and self._is_effectively_enabled(entry.spec)
            ]
            ordered = self._topological_order_locked(names)
        return {name: self.ensure_async(name) for name in ordered}

    def ensure_async(self, name: str) -> Future[Any]:
        return self._ensure_async_internal(str(name), stack=())

    def _ensure_async_internal(self, name: str, *, stack: tuple[str, ...]) -> Future[Any]:
        normalized = str(name)
        with self._lock:
            if self._closed:
                return self._failed_future(RuntimeError("RuntimeFeatureManager is closed"))
            try:
                self._validate_graph_locked()
            except BaseException as exc:
                return self._failed_future(exc)
            if normalized in stack:
                cycle = " -> ".join((*stack, normalized))
                return self._failed_future(RuntimeError(f"Feature dependency cycle: {cycle}"))
            entry = self._entries.get(normalized)
            if entry is None:
                return self._failed_future(KeyError(normalized))
            if entry.state is FeatureState.READY:
                completed: Future[Any] = Future()
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
            public_future: Future[Any] = Future()
            entry.future = public_future
            dependencies = tuple(str(dep) for dep in entry.spec.depends_on)

        dependency_futures = [
            self._ensure_async_internal(dep, stack=(*stack, normalized))
            for dep in dependencies
        ]
        if not dependency_futures:
            self._submit_build(normalized, generation, public_future)
            return public_future

        barrier_lock = threading.Lock()
        remaining = len(dependency_futures)
        failed = False

        def dependency_done(dependency_future: Future[Any]) -> None:
            nonlocal remaining, failed
            try:
                dependency_future.result()
            except BaseException as exc:
                with barrier_lock:
                    if failed:
                        return
                    failed = True
                self._fail_dependency(normalized, generation, public_future, exc)
                return
            with barrier_lock:
                if failed:
                    return
                remaining -= 1
                ready = remaining == 0
            if ready:
                self._submit_build(normalized, generation, public_future)

        for dependency_future in dependency_futures:
            dependency_future.add_done_callback(dependency_done)
        return public_future

    def _submit_build(self, name: str, generation: int, public_future: Future[Any]) -> None:
        with self._lock:
            entry = self._entries.get(name)
            if (
                entry is None
                or entry.generation != generation
                or entry.future is not public_future
                or public_future.cancelled()
                or self._closed
            ):
                if not public_future.done():
                    if self._closed:
                        public_future.set_exception(
                            RuntimeError(
                                f"Feature '{name}' finished loading after shutdown"
                            )
                        )
                    else:
                        public_future.cancel()
                return
        internal = self._executor.submit(self._build, name, generation)

        def complete(done: Future[Any]) -> None:
            if public_future.done():
                return
            try:
                public_future.set_result(done.result())
            except BaseException as exc:
                if self._closed:
                    public_future.set_exception(
                        RuntimeError(
                            f"Feature '{name}' finished loading after shutdown"
                        )
                    )
                else:
                    public_future.set_exception(exc)

        internal.add_done_callback(complete)

    def _fail_dependency(
        self,
        name: str,
        generation: int,
        public_future: Future[Any],
        error: BaseException,
    ) -> None:
        wrapped = RuntimeError(f"Feature '{name}' dependency failed: {error}")
        with self._lock:
            entry = self._entries.get(name)
            if (
                entry is not None
                and entry.generation == generation
                and entry.future is public_future
            ):
                entry.future = None
                entry.error = wrapped
                entry.state = FeatureState.FAILED
        if not public_future.done():
            public_future.set_exception(wrapped)

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
                if not self._is_effectively_enabled(entry.spec):
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
                    elif not self._is_effectively_enabled(entry.spec):
                        state = FeatureState.DISABLED
                out[name] = {
                    "state": state.value,
                    "enabled": self._is_effectively_enabled(entry.spec),
                    "depends_on": list(entry.spec.depends_on),
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
            try:
                self._validate_graph_locked()
                shutdown_order = list(
                    reversed(self._topological_order_locked(self._entries))
                )
                entries = [self._entries[name] for name in shutdown_order]
            except RuntimeError as exc:
                logger.error(
                    f"Invalid feature graph during shutdown: {exc}",
                    exc_info=True,
                )
                entries = sorted(
                    self._entries.values(),
                    key=lambda item: (item.spec.priority, item.spec.name),
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
            should_stop = (
                stale
                or self._closed
                or entry.stop_requested
                or self._settings_require_stop(spec)
            )
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
                        restart = not self._closed and self._is_effectively_enabled(spec)
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
                or self._settings_require_stop(spec)
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
                        restart = not self._closed and self._is_effectively_enabled(spec)
            if restart:
                self.ensure_async(name)
            return None

        startup_trace.mark(f"feature.{name}.ready", generation=generation)
        logger.info(f"Optional feature ready: {name}")
        return instance

    def _on_setting_changed(self, change) -> None:
        with self._lock:
            if self._closed:
                return
            direct_names = set(self._key_index.get(str(change.key), ()))
            affected = set(direct_names)
            for name in tuple(direct_names):
                affected.update(self._collect_dependents_locked(name))

            to_start: set[str] = set()
            to_stop: set[str] = set()
            for name in affected:
                entry = self._entries[name]
                enabled = self._is_effectively_enabled(entry.spec)
                if enabled:
                    if entry.state is FeatureState.LOADING and entry.stop_requested:
                        entry.stop_requested = False
                    elif entry.state in {
                        FeatureState.REGISTERED,
                        FeatureState.DISABLED,
                        FeatureState.FAILED,
                        FeatureState.UNAVAILABLE,
                        FeatureState.STOPPED,
                    }:
                        to_start.add(name)
                    continue

                if not self._settings_require_stop(entry.spec):
                    continue
                if entry.state is FeatureState.LOADING:
                    entry.stop_requested = True
                elif entry.state is FeatureState.READY:
                    entry.state = FeatureState.STOPPING
                    to_stop.add(name)

            start_order = self._topological_order_locked(to_start)
            stop_order = list(reversed(self._topological_order_locked(to_stop)))

        for name in start_order:
            self.ensure_async(name)
        if stop_order:
            self._executor.submit(
                self._stop_features_in_order,
                tuple(stop_order),
            )

    def _stop_features_in_order(self, names: tuple[str, ...]) -> None:
        for name in names:
            self._stop_disabled_feature(name)

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
                    restart = not self._closed and self._is_effectively_enabled(spec)

        startup_trace.mark(f"feature.{name}.disabled", generation=generation)
        if restart:
            self.ensure_async(name)

    def _validate_graph_locked(self) -> None:
        for name, entry in self._entries.items():
            for dependency in entry.spec.depends_on:
                if str(dependency) not in self._entries:
                    raise RuntimeError(
                        f"Feature '{name}' depends on unknown feature '{dependency}'"
                    )
        self._topological_order_locked(self._entries)

    def _topological_order_locked(self, names) -> list[str]:
        selected = {str(name) for name in names}
        expanded = set(selected)
        stack = list(selected)
        while stack:
            name = stack.pop()
            entry = self._entries.get(name)
            if entry is None:
                continue
            for dependency in entry.spec.depends_on:
                dep = str(dependency)
                if dep not in expanded:
                    expanded.add(dep)
                    stack.append(dep)

        visiting: set[str] = set()
        visited: set[str] = set()
        ordered: list[str] = []

        def visit(name: str, path: tuple[str, ...]) -> None:
            if name in visited:
                return
            if name in visiting:
                raise RuntimeError(
                    f"Feature dependency cycle: {' -> '.join((*path, name))}"
                )
            entry = self._entries.get(name)
            if entry is None:
                raise RuntimeError(f"Unknown feature dependency '{name}'")
            visiting.add(name)
            for dependency in entry.spec.depends_on:
                visit(str(dependency), (*path, name))
            visiting.remove(name)
            visited.add(name)
            ordered.append(name)

        for name in sorted(
            expanded,
            key=lambda item: (
                self._entries[item].spec.priority if item in self._entries else 0,
                item,
            ),
        ):
            visit(name, ())
        return [name for name in ordered if name in selected]

    def _collect_dependents_locked(self, name: str) -> set[str]:
        collected: set[str] = set()
        stack = list(self._dependents.get(str(name), ()))
        while stack:
            dependent = stack.pop()
            if dependent in collected:
                continue
            collected.add(dependent)
            stack.extend(self._dependents.get(dependent, ()))
        return collected

    def _is_effectively_enabled(
        self,
        spec: FeatureSpec,
        _visited: set[str] | None = None,
    ) -> bool:
        if not self._is_enabled(spec):
            return False
        visited = set() if _visited is None else set(_visited)
        if spec.name in visited:
            return False
        visited.add(spec.name)
        for dependency in spec.depends_on:
            entry = self._entries.get(str(dependency))
            if entry is None or not self._is_effectively_enabled(entry.spec, visited):
                return False
        return True

    def _settings_require_stop(
        self,
        spec: FeatureSpec,
        _visited: set[str] | None = None,
    ) -> bool:
        """Whether settings require an already requested instance to stop.

        ``enabled`` controls automatic startup. ``stop_when_disabled=False``
        additionally allows an explicit ``ensure*`` request to keep a feature
        alive while its automatic-start predicate is false. Dependencies still
        have to satisfy their own retention policy.
        """
        visited = set() if _visited is None else set(_visited)
        if spec.name in visited:
            return True
        visited.add(spec.name)

        if spec.stop_when_disabled and not self._is_enabled(spec):
            return True

        for dependency in spec.depends_on:
            entry = self._entries.get(str(dependency))
            if entry is None or self._settings_require_stop(entry.spec, visited):
                return True
        return False

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
        task_supervisor().cancel_owner(instance, timeout=1.0)
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
    def _failed_future(error: BaseException) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_exception(error)
        # Some lifecycle callers intentionally fire-and-forget the returned
        # future. Observing the exception here prevents noisy "exception was
        # never retrieved" diagnostics without changing future.result().
        future.add_done_callback(lambda completed: completed.exception())
        return future
