from __future__ import annotations

import threading
import time

from core.daemon_executor import DaemonExecutor


def test_shutdown_cancels_queued_work_and_uses_daemon_threads() -> None:
    executor = DaemonExecutor(1, thread_name_prefix="test-daemon")
    gate = threading.Event()
    running = executor.submit(gate.wait, 2.0)
    queued = executor.submit(lambda: "must-not-run")

    deadline = time.monotonic() + 1.0
    while not running.running() and time.monotonic() < deadline:
        time.sleep(0.01)

    executor.shutdown(cancel_futures=True)
    assert queued.cancelled()
    assert all(thread.daemon for thread in executor._threads)
    gate.set()
    assert running.result(timeout=1.0) is True
