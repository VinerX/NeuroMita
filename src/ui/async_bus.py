from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PyQt6.QtCore import QTimer

from core.events import get_event_bus
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
) -> threading.Thread:
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

    thread = threading.Thread(target=_run, name=str(name or "gui-async"), daemon=True)
    thread.start()
    return thread


def emit_and_wait_async(
    target: Any,
    event_name: str,
    data: Any = None,
    *,
    timeout: float = 1.0,
    on_ok: Optional[Callback] = None,
    on_error: Optional[Callback] = None,
    name: Optional[str] = None,
) -> threading.Thread:
    bus = _event_bus_from(target)
    call_name = name or f"emit:{event_name}"

    def _worker():
        return bus.emit_and_wait(event_name, data, timeout=timeout)

    return run_async(target, _worker, on_ok, on_error, name=call_name)


def _event_bus_from(target: Any):
    bus = getattr(target, "event_bus", None)
    if bus is not None:
        return bus
    view = getattr(target, "view", None)
    bus = getattr(view, "event_bus", None)
    if bus is not None:
        return bus
    return get_event_bus()


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

