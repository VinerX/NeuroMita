from __future__ import annotations

import threading
from typing import Callable, Any, Optional

from main_logger import logger


def bus_call_async(
    fn: Callable[[], Any],
    on_ok: Callable[[Any], None],
    on_fail: Optional[Callable[[Exception], None]] = None,
    *,
    name: str = "bus_call",
    dispatch: Optional[Callable[[Callable[[], None]], None]] = None,
) -> None:
    """
    IMPORTANT:
    Do NOT use QTimer.singleShot from worker thread to reach GUI thread.
    Use `dispatch(callable)` that posts the callable to GUI thread (via signal).
    """
    logger.info(f"[API UI] bus_call_async scheduled: {name} (dispatch={'yes' if dispatch else 'no'})")

    if dispatch is None:
        logger.error(f"[API UI] bus_call_async '{name}' has no dispatch; UI callback may never run from worker thread")

    def worker():
        try:
            res = fn()
        except Exception as e:
            logger.error(f"[API UI] worker failed in {name}: {e}", exc_info=True)
            if on_fail and dispatch:
                dispatch(lambda: _safe_call(on_fail, e, where=f"on_fail/{name}"))
            return

        if dispatch:
            dispatch(lambda: _safe_call(on_ok, res, where=f"on_ok/{name}"))

    def _safe_call(cb: Callable[[Any], None], arg: Any, *, where: str):
        try:
            cb(arg)
        except Exception as ee:
            logger.error(f"[API UI] callback crashed in {where}: {ee}", exc_info=True)

    threading.Thread(target=worker, daemon=True).start()