from __future__ import annotations

import threading
from core.task_supervisor import task_supervisor
from typing import Any, Callable, Optional

from PyQt6.QtCore import QTimer

from main_logger import logger


Callback = Callable[[Any], None]


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
) -> threading.Thread | None:
    def _run():
        try:
            result = worker()
        except Exception as exc:
            logger.error(f"Async GUI worker failed: {name}: {exc}", exc_info=True)
            if on_error is not None:
                dispatch_to_gui(target, lambda exc=exc: on_error(exc))
            return

        if on_ok is not None:
            dispatch_to_gui(target, lambda result=result: on_ok(result))

    supervisor = task_supervisor()
    if supervisor.is_shutdown:
        return None
    try:
        return supervisor.start_thread(
            target if target is not None else run_async,
            str(name or "gui-async"),
            _run,
            replace=True,
        )
    except RuntimeError:
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

