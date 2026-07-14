from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass
from core.task_supervisor import task_supervisor
from typing import Any, Callable, Optional


from main_logger import logger
from controllers.gui.qt_dispatch import dispatch_to_qt


Callback = Callable[[Any], None]


_state_lock = threading.RLock()
@dataclass(slots=True)
class _OperationState:
    next_generation: int = 0
    current_generation: int = 0
    active_count: int = 0
    exclusive: bool = False


_operations: dict[tuple[int, str], _OperationState] = {}
_tracked_owner_ids: set[int] = set()


def _purge_owner_state(owner_id: int) -> None:
    """Убрать все записи владельца: id() переиспользуется после GC, и без
    очистки новый объект унаследовал бы чужие счётчики поколений."""
    with _state_lock:
        _tracked_owner_ids.discard(owner_id)
        for key in [k for k in _operations if k[0] == owner_id]:
            del _operations[key]


def _track_owner(owner: Any) -> None:
    owner_id = id(owner)
    with _state_lock:
        if owner_id in _tracked_owner_ids:
            return
        _tracked_owner_ids.add(owner_id)
    try:
        weakref.finalize(owner, _purge_owner_state, owner_id)
    except TypeError:
        # Не-weakref-able владелец (например, сам модульный fallback) живёт
        # до конца процесса — его записи чистить не нужно.
        pass


def _target_closed(target: Any) -> bool:
    if target is None:
        return False
    marker = getattr(target, "is_closed", False)
    try:
        return bool(marker() if callable(marker) else marker)
    except Exception:
        return True


def _owner_ref(target: Any):
    try:
        return weakref.ref(target)
    except TypeError:
        return lambda target=target: target


def dispatch_to_gui(target: Any, fn: Callable[[], None]) -> bool:
    if not callable(fn):
        return False

    for obj in _dispatch_candidates(target):
        sig = getattr(obj, "run_ui_task_signal", None)
        if sig is None:
            sig = getattr(obj, "dispatch_to_gui", None)
        if sig is None:
            continue
        try:
            sig.emit(fn)
            return True
        except Exception:
            continue

    if dispatch_to_qt(fn):
        return True

    logger.debug("Dropped GUI callback because the Qt dispatcher is unavailable")
    return False


def run_async(
    target: Any,
    worker: Callable[[], Any],
    on_ok: Optional[Callback] = None,
    on_error: Optional[Callback] = None,
    *,
    name: str = "gui-async",
    policy: Any = "latest",
) -> threading.Thread | None:
    normalized_policy = str(getattr(policy, "value", policy) or "latest").strip().lower()
    owner = target if target is not None else run_async
    key = (id(owner), str(name or "gui-async"))
    owner_ref = _owner_ref(owner)
    _track_owner(owner)
    with _state_lock:
        state = _operations.setdefault(key, _OperationState())
        if normalized_policy == "exclusive":
            if state.exclusive or state.active_count:
                return None
            state.exclusive = True
        state.next_generation += 1
        generation = state.next_generation
        state.current_generation = generation
        state.active_count += 1

    def current() -> bool:
        current_owner = owner_ref()
        if current_owner is None or _target_closed(current_owner):
            return False
        with _state_lock:
            state = _operations.get(key)
            return state is not None and state.current_generation == generation

    def finish() -> None:
        with _state_lock:
            state = _operations.get(key)
            if state is None:
                return
            state.active_count = max(0, state.active_count - 1)
            if normalized_policy == "exclusive":
                state.exclusive = False
            if state.active_count == 0:
                _operations.pop(key, None)

    def _run():
        # Для policy="exclusive" слот освобождается только после того, как
        # колбэк реально выполнен в GUI-потоке (или отброшен): иначе следующий
        # «эксклюзивный» запуск мог бы стартовать, пока прежний on_ok ещё
        # висит в очереди Qt, и их колбэки перемешались бы.
        try:
            result = worker()
        except Exception as exc:
            logger.error(f"Async GUI worker failed: {name}: {exc}", exc_info=True)
            if on_error is None:
                finish()
                return

            def _apply_error(exc=exc) -> None:
                try:
                    if current():
                        on_error(exc)
                finally:
                    finish()

            if not dispatch_to_gui(target, _apply_error):
                finish()
            return

        if on_ok is None:
            finish()
            return

        def _apply_result(result=result) -> None:
            try:
                if current():
                    on_ok(result)
            finally:
                finish()

        if not dispatch_to_gui(target, _apply_result):
            finish()

    supervisor = task_supervisor()
    if supervisor.is_shutdown:
        finish()
        return None
    try:
        return supervisor.start_thread(
            owner,
            f"{str(name or 'gui-async')}:{generation}",
            _run,
            allow_overlap=True,
        )
    except RuntimeError:
        finish()
        # A Qt timer/signal may fire while the application is between
        # controller shutdown and widget destruction. That is a normal late
        # notification, not an uncaught application error.
        if supervisor.is_shutdown:
            return None
        raise



def _dispatch_candidates(target: Any):
    seen: set[int] = set()
    current = target
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        view = getattr(current, "view", None)
        if view is not None and id(view) not in seen:
            seen.add(id(view))
            yield view
        gui = getattr(current, "gui", None)
        if gui is not None and id(gui) not in seen:
            seen.add(id(gui))
            yield gui
        try:
            current = current.parent()
        except Exception:
            current = None

