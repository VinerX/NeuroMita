from __future__ import annotations

import threading

import controllers.reminder_controller as reminder_module


class _Bus:
    is_running = True

    def __init__(self, accepted: bool = True):
        self.accepted = accepted

    def emit(self, *_args, **_kwargs):
        return None

    def try_emit(self, *_args, **_kwargs):
        return self.accepted


class _TestReminderController(reminder_module.ReminderController):
    CHECK_INTERVAL_SEC = 60

    def __init__(self, settings):
        self.checked = threading.Event()
        super().__init__(settings)

    def _check_and_fire_reminders(self):
        self.checked.set()


def test_reminder_shutdown_interrupts_sleep_and_joins_thread(monkeypatch):
    monkeypatch.setattr(reminder_module, "get_event_bus", lambda: _Bus())
    controller = _TestReminderController({"REMINDERS_ENABLED": True})
    assert controller.checked.wait(1.0)
    thread = controller._thread
    assert thread is not None and thread.is_alive()

    controller.shutdown()

    assert controller._thread is None
    assert not thread.is_alive()


def test_reminder_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(reminder_module, "get_event_bus", lambda: _Bus())
    controller = _TestReminderController({"REMINDERS_ENABLED": False})
    try:
        first = controller._thread
        controller._start_periodic_check()
        assert controller._thread is first
    finally:
        controller.shutdown()


class _ReminderSystem:
    def __init__(self):
        self.dismissed = []

    def get_due_reminders(self):
        return [{"N": 7, "text": "test"}]

    def dismiss_reminder(self, number):
        self.dismissed.append(number)


class _Resources:
    def __init__(self, reminder_system):
        self.reminder_system = reminder_system

    def reminders_for(self, _character_id):
        return self.reminder_system


class _Registry:
    def all_ids(self):
        return ("Crazy",)


def test_reminder_is_not_dismissed_when_event_queue_rejects(monkeypatch):
    bus = _Bus(accepted=False)
    reminder_system = _ReminderSystem()
    monkeypatch.setattr(reminder_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(reminder_module, "use", lambda _contract: _Registry())

    controller = reminder_module.ReminderController(
        {"REMINDERS_ENABLED": False},
        character_resources=_Resources(reminder_system),
    )
    try:
        controller._check_and_fire_reminders()
        assert reminder_system.dismissed == []
    finally:
        controller.shutdown()


def test_reminder_is_dismissed_after_event_is_queued(monkeypatch):
    bus = _Bus(accepted=True)
    reminder_system = _ReminderSystem()
    monkeypatch.setattr(reminder_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(reminder_module, "use", lambda _contract: _Registry())

    controller = reminder_module.ReminderController(
        {"REMINDERS_ENABLED": False},
        character_resources=_Resources(reminder_system),
    )
    try:
        controller._check_and_fire_reminders()
        assert reminder_system.dismissed == [7]
    finally:
        controller.shutdown()
