from __future__ import annotations

import threading
import time
from unittest.mock import patch

from core.task_supervisor import TaskSupervisor
from controllers.gui.async_runner import run_async


def test_supervisor_tracks_and_cancels_owner_threads():
    supervisor = TaskSupervisor()
    owner = object()
    stop = threading.Event()
    entered = threading.Event()

    def worker():
        entered.set()
        stop.wait(2.0)

    thread = supervisor.start_thread(
        owner,
        "worker",
        worker,
        cancel_event=stop,
    )
    assert entered.wait(1.0)
    assert any(item.name == "worker" for item in supervisor.snapshot())
    assert supervisor.cancel_owner(owner, timeout=1.0) == 1
    assert stop.is_set()
    assert not thread.is_alive()
    supervisor.shutdown()


def test_supervisor_rejects_duplicate_named_task_without_replace():
    supervisor = TaskSupervisor()
    owner = object()
    stop = threading.Event()
    entered = threading.Event()

    def worker():
        entered.set()
        stop.wait(2.0)

    supervisor.start_thread(owner, "same", worker, cancel_event=stop)
    assert entered.wait(1.0)
    try:
        try:
            supervisor.start_thread(owner, "same", worker)
        except RuntimeError as exc:
            assert "already running" in str(exc)
        else:
            raise AssertionError("duplicate task was accepted")
    finally:
        stop.set()
        supervisor.cancel_owner(owner, timeout=1.0)
        supervisor.shutdown()


def test_supervisor_deadline_requests_cooperative_cancellation():
    supervisor = TaskSupervisor()
    owner = object()
    stop = threading.Event()

    def worker():
        stop.wait(2.0)

    thread = supervisor.start_thread(
        owner,
        "deadline-worker",
        worker,
        cancel_event=stop,
        timeout=0.05,
    )
    deadline = time.monotonic() + 1.0
    while not stop.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert stop.is_set()
    thread.join(1.0)
    assert not thread.is_alive()
    supervisor.shutdown()


def test_gui_async_late_notification_is_ignored_after_shutdown():
    supervisor = TaskSupervisor()
    supervisor.shutdown()

    with patch("controllers.gui.async_runner.task_supervisor", return_value=supervisor):
        thread = run_async(None, lambda: "late", name="late-gui-refresh")

    assert thread is None
