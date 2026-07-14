from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Generic, TypeVar

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

from core.events import get_event_bus
from core.task_supervisor import task_supervisor
from main_logger import logger


StateT = TypeVar("StateT")


class IntentViewModel(QObject, Generic[StateT]):
    """Base for intent-driven Qt presentation models.

    Work executes on supervised daemon threads. Results are applied on the Qt
    thread only while the view model is alive and the operation generation is
    still current. Running Python threads are never treated as cancellable.
    """

    state_changed = pyqtSignal(object)
    effect_emitted = pyqtSignal(object)
    _ui_requested = pyqtSignal(object)

    def __init__(self, initial_state: StateT, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = initial_state
        self._closed = False
        self._generations: dict[str, int] = {}
        self._inflight: set[str] = set()
        self._coalesced_pending: set[str] = set()
        self._coalesced_specs: dict[
            str,
            tuple[
                Callable[[], Any],
                Callable[[Any], None] | None,
                Callable[[Exception], None] | None,
            ],
        ] = {}
        self._subscriptions: list[Any] = []
        self._ui_requested.connect(
            self._execute_ui_callback,
            Qt.ConnectionType.QueuedConnection,
        )

    @property
    def state(self) -> StateT:
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._closed

    def dispatch(self, intent: Any) -> None:
        raise NotImplementedError

    def emit_state(self) -> None:
        if not self._closed:
            self.state_changed.emit(self._state)

    def update_state(self, **changes: Any) -> StateT:
        if self._closed:
            return self._state
        self._state = replace(self._state, **changes)
        self.state_changed.emit(self._state)
        return self._state

    def set_state(self, state: StateT) -> None:
        if self._closed:
            return
        self._state = state
        self.state_changed.emit(state)

    def emit_effect(self, effect: Any) -> None:
        if not self._closed:
            self.effect_emitted.emit(effect)

    def track_subscription(self, subscription: Any) -> Any:
        if subscription is not None:
            self._subscriptions.append(subscription)
        return subscription

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for name in tuple(self._generations):
            self._generations[name] += 1
        subscriptions = self._subscriptions
        self._subscriptions = []
        for subscription in subscriptions:
            try:
                subscription.close()
            except Exception:
                logger.debug("Failed to close presentation subscription", exc_info=True)
        try:
            get_event_bus().unsubscribe_owner(self)
        except Exception:
            logger.debug("Failed to unsubscribe view model from EventBus", exc_info=True)
        # Closing a Qt object must never join worker threads on the GUI thread.
        # Results are already generation-gated and `_closed` rejects queued
        # callbacks, so cooperative cancellation is sufficient here. The
        # application shutdown path performs the bounded wait centrally.
        task_supervisor().cancel_owner(self, timeout=0.0)
        self._inflight.clear()
        self._coalesced_pending.clear()
        self._coalesced_specs.clear()

    def run_latest(
        self,
        name: str,
        worker: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        if self._closed:
            return False
        generation = self._next_generation(name)

        def execute() -> None:
            try:
                result = worker()
            except Exception as exc:
                logger.error(f"ViewModel task failed: {name}: {exc}", exc_info=True)
                self._post_ui(
                    lambda exc=exc: self._apply_latest_error(
                        name, generation, exc, on_error
                    )
                )
                return
            self._post_ui(
                lambda result=result: self._apply_latest_success(
                    name,
                    generation,
                    result,
                    on_success,
                    on_error,
                )
            )

        try:
            task_supervisor().start_thread(
                self,
                f"{name}:{generation}",
                execute,
                allow_overlap=True,
            )
        except Exception as exc:
            logger.error(f"Failed to start ViewModel task: {name}: {exc}", exc_info=True)
            self._post_ui(
                lambda exc=exc: self._apply_latest_error(
                    name,
                    generation,
                    exc,
                    on_error,
                )
            )
            return False
        return True

    def run_exclusive(
        self,
        name: str,
        worker: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        if self._closed or name in self._inflight:
            return False
        self._inflight.add(name)
        generation = self._next_generation(name)

        def execute() -> None:
            try:
                result = worker()
            except Exception as exc:
                logger.error(f"ViewModel operation failed: {name}: {exc}", exc_info=True)
                self._post_ui(
                    lambda exc=exc: self._finish_exclusive(
                        name, generation, None, exc, on_success, on_error
                    )
                )
                return
            self._post_ui(
                lambda result=result: self._finish_exclusive(
                    name, generation, result, None, on_success, on_error
                )
            )

        try:
            task_supervisor().start_thread(self, name, execute, replace=False)
        except Exception as exc:
            self._inflight.discard(name)
            logger.error(
                f"Failed to start ViewModel operation: {name}: {exc}",
                exc_info=True,
            )
            self._post_ui(
                lambda exc=exc: self._finish_exclusive(
                    name,
                    generation,
                    None,
                    exc,
                    on_success,
                    on_error,
                )
            )
            return False
        return True

    def run_coalesced(
        self,
        name: str,
        worker: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        if self._closed:
            return False
        self._coalesced_specs[name] = (worker, on_success, on_error)
        if name in self._inflight:
            self._coalesced_pending.add(name)
            return False
        self._start_coalesced(name)
        return True

    def _start_coalesced(self, name: str) -> None:
        if self._closed:
            return
        spec = self._coalesced_specs.get(name)
        if spec is None:
            return
        worker, on_success, on_error = spec
        self._inflight.add(name)
        generation = self._next_generation(name)

        def execute() -> None:
            result: Any = None
            error: Exception | None = None
            try:
                result = worker()
            except Exception as exc:
                error = exc
                logger.error(f"ViewModel refresh failed: {name}: {exc}", exc_info=True)
            self._post_ui(
                lambda result=result, error=error: self._finish_coalesced(
                    name,
                    generation,
                    result,
                    error,
                    on_success,
                    on_error,
                )
            )

        try:
            task_supervisor().start_thread(self, f"{name}:{generation}", execute)
        except Exception as exc:
            self._inflight.discard(name)
            logger.error(
                f"Failed to start coalesced ViewModel refresh: {name}: {exc}",
                exc_info=True,
            )
            self._post_ui(
                lambda exc=exc: self._finish_coalesced(
                    name,
                    generation,
                    None,
                    exc,
                    on_success,
                    on_error,
                )
            )

    def _finish_coalesced(
        self,
        name: str,
        generation: int,
        result: Any,
        error: Exception | None,
        on_success: Callable[[Any], None] | None,
        on_error: Callable[[Exception], None] | None,
    ) -> None:
        self._inflight.discard(name)
        current = self._generations.get(name, 0) == generation
        rerun = name in self._coalesced_pending
        self._coalesced_pending.discard(name)
        if not rerun:
            # Спека хранит замыкания worker/колбэков со всеми захваченными
            # данными — без очистки они жили бы до close() view model.
            self._coalesced_specs.pop(name, None)
        if not self._closed and current and not rerun:
            if error is None:
                self._invoke_success(on_success, result, on_error)
            else:
                self._invoke_error(on_error, error)
        if not self._closed and rerun:
            self._start_coalesced(name)

    def _finish_exclusive(
        self,
        name: str,
        generation: int,
        result: Any,
        error: Exception | None,
        on_success: Callable[[Any], None] | None,
        on_error: Callable[[Exception], None] | None,
    ) -> None:
        self._inflight.discard(name)
        if self._closed or self._generations.get(name, 0) != generation:
            return
        if error is None:
            self._invoke_success(on_success, result, on_error)
        else:
            self._invoke_error(on_error, error)

    def _apply_latest_success(
        self,
        name: str,
        generation: int,
        result: Any,
        callback: Callable[[Any], None] | None,
        error_callback: Callable[[Exception], None] | None,
    ) -> None:
        if self._closed or self._generations.get(name, 0) != generation:
            return
        self._invoke_success(callback, result, error_callback)

    def _apply_latest_error(
        self,
        name: str,
        generation: int,
        error: Exception,
        callback: Callable[[Exception], None] | None,
    ) -> None:
        if self._closed or self._generations.get(name, 0) != generation:
            return
        self._invoke_error(callback, error)

    @staticmethod
    def _invoke_success(
        callback: Callable[[Any], None] | None,
        result: Any,
        error_callback: Callable[[Exception], None] | None,
    ) -> None:
        if callback is None:
            return
        try:
            callback(result)
        except Exception as exc:
            logger.error("ViewModel result application failed", exc_info=True)
            IntentViewModel._invoke_error(error_callback, exc)

    @staticmethod
    def _invoke_error(
        callback: Callable[[Exception], None] | None,
        error: Exception,
    ) -> None:
        if callback is None:
            return
        try:
            callback(error)
        except Exception:
            logger.error("ViewModel error application failed", exc_info=True)

    def _next_generation(self, name: str) -> int:
        generation = self._generations.get(name, 0) + 1
        self._generations[name] = generation
        return generation

    def _post_ui(self, callback: Callable[[], None]) -> None:
        if not self._closed:
            self._ui_requested.emit(callback)

    @pyqtSlot(object)
    def _execute_ui_callback(self, callback: Any) -> None:
        if self._closed or not callable(callback):
            return
        try:
            callback()
        except Exception:
            logger.error("ViewModel UI callback failed", exc_info=True)