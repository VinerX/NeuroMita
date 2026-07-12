from __future__ import annotations

import threading
import weakref
from core.task_supervisor import task_supervisor
from typing import Any, Callable, Optional


from main_logger import logger


Callback = Callable[[Any], None]


_state_lock = threading.RLock()
_generations: dict[tuple[int, str], int] = {}
_exclusive: set[tuple[int, str]] = set()


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

    try:
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, fn)
        return True
    except Exception:
        try:
            fn()
            return True
        except Exception:
            logger.error("Failed to dispatch callable to GUI", exc_info=True)
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
    with _state_lock:
        if normalized_policy == "exclusive":
            if key in _exclusive:
                return None
            _exclusive.add(key)
            generation = _generations.get(key, 0) + 1
            _generations[key] = generation
        else:
            generation = _generations.get(key, 0) + 1
            _generations[key] = generation

    def current() -> bool:
        current_owner = owner_ref()
        if current_owner is None or _target_closed(current_owner):
            return False
        with _state_lock:
            return _generations.get(key, 0) == generation

    def finish() -> None:
        if normalized_policy != "exclusive":
            return
        with _state_lock:
            _exclusive.discard(key)

    def _run():
        try:
            result = worker()
        except Exception as exc:
            logger.error(f"Async GUI worker failed: {name}: {exc}", exc_info=True)
            if on_error is not None:
                dispatch_to_gui(
                    target,
                    lambda exc=exc: on_error(exc) if current() else None,
                )
            finish()
            return

        if on_ok is not None:
            dispatch_to_gui(
                target,
                lambda result=result: on_ok(result) if current() else None,
            )
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

