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


def test_abandonment_is_bounded_and_exposes_live_retired_worker_count() -> None:
    executor = DaemonExecutor(
        1,
        thread_name_prefix="test-bounded-daemon",
        max_retired_workers=1,
    )
    first_gate = threading.Event()
    second_gate = threading.Event()
    first = executor.submit(first_gate.wait, 2.0)

    deadline = time.monotonic() + 1.0
    while not first.running() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert executor.abandon(first)
    assert executor.retired_workers == 1

    second = executor.submit(second_gate.wait, 2.0)
    deadline = time.monotonic() + 1.0
    while not second.running() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not executor.abandon(second)
    assert executor.retired_workers == 1

    first_gate.set()
    second_gate.set()
    assert first.result(timeout=1.0) is True
    assert second.result(timeout=1.0) is True
    executor.shutdown(cancel_futures=True)
