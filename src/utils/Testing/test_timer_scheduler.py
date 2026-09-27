from __future__ import annotations

import datetime
import threading

import controllers.reminder_controller as reminder_module
import managers.reminder_manager as reminder_manager_module
from core.cancellation import CancellationToken
from core.events import Event, Events
from controllers.chat_controller import ChatController
from managers.reminder_manager import ReminderManager
from managers.tools.builtin.reminder_tool import ReminderTool, _parse_due
from services.contracts import CharacterRegistry, GenerationActivityService


class _Bus:
    is_running = True

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.subscribers: dict[str, list] = {}

    def subscribe(self, name, callback, **_kwargs):
        self.subscribers.setdefault(name, []).append(callback)

    def emit(self, name, data=None, **_kwargs):
        self.events.append((name, data or {}))
        for callback in self.subscribers.get(name, []):
            callback(Event(name, data or {}))

    def try_emit(self, name, data=None, **kwargs):
        self.emit(name, data, **kwargs)
        return True


class _Registry:
    def all_ids(self):
        return ("Mita",)


class _Resources:
    def __init__(self, reminders) -> None:
        self.reminders = reminders

    def reminders_for(self, _character_id):
        return self.reminders


class _ReminderSystem:
    def __init__(self, item: dict, due_at: datetime.datetime | None = None) -> None:
        self.item = item
        self.due_at = due_at
        self.dismissed: list[int] = []

    def get_due_reminders(self):
        return [self.item]

    def get_next_due_at(self):
        return self.due_at

    def dismiss_reminder(self, number):
        self.dismissed.append(number)


class _Activity:
    def __init__(self, active: int = 0) -> None:
        self.active = active

    def active_generation_count(self, _character_id=None) -> int:
        return self.active


def _controller(monkeypatch, reminder_system, activity=None):
    bus = _Bus()
    monkeypatch.setattr(reminder_module, "get_event_bus", lambda: bus)
    activity = activity or _Activity()
    registry = _Registry()
    monkeypatch.setattr(
        reminder_module,
        "use",
        lambda contract: registry if contract is CharacterRegistry else activity,
    )
    controller = reminder_module.ReminderController(
        {"REMINDERS_ENABLED": False},
        character_resources=_Resources(reminder_system),
    )
    return controller, bus


def test_due_timer_starts_an_autonomous_timer_turn(monkeypatch):
    reminders = _ReminderSystem({"N": 3, "text": "Try again", "kind": "timer"})
    controller, bus = _controller(monkeypatch, reminders)
    try:
        controller._check_and_fire_reminders()
        assert reminders.dismissed == [3]
        assert bus.events[-1] == (
            Events.Chat.SEND_MESSAGE,
            {
                "character_id": "Mita",
                "user_input": "",
                "system_input": "[Timer fired] Try again",
                "event_type": "timer",
            },
        )
    finally:
        controller.shutdown()


def test_due_timer_waits_for_its_character_generation(monkeypatch):
    activity = _Activity(active=1)
    reminders = _ReminderSystem({"N": 4, "text": "Continue", "kind": "timer"})
    controller, bus = _controller(monkeypatch, reminders, activity)
    try:
        controller._check_and_fire_reminders()
        assert reminders.dismissed == []
        assert not bus.events

        activity.active = 0
        controller._check_and_fire_reminders()
        assert reminders.dismissed == [4]
    finally:
        controller.shutdown()


def test_scheduler_uses_nearest_deadline_instead_of_poll_interval(monkeypatch):
    due_at = datetime.datetime.now() + datetime.timedelta(seconds=0.2)
    reminders = _ReminderSystem({"N": 5, "text": "Later"}, due_at=due_at)
    controller, _bus = _controller(monkeypatch, reminders)
    try:
        assert 0 < controller._seconds_until_next_due() < 1
    finally:
        controller.shutdown()


def test_reminder_manager_persists_timer_kind_and_precise_deadline(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROMITA_HISTORIES_DIR", str(tmp_path))
    manager = ReminderManager("Mita")
    number = manager.add_timer("Check result", 0.5)
    saved = manager.reminders[0]

    assert saved["N"] == number
    assert saved["kind"] == "timer"
    assert datetime.datetime.fromisoformat(saved["due_iso"]) > datetime.datetime.now()
    assert manager.get_next_due_at() is not None

    reloaded = ReminderManager("Mita")
    assert reloaded.reminders == [saved]
    assert reloaded.get_next_due_at() == datetime.datetime.fromisoformat(saved["due_iso"])


def test_saved_timer_wakes_scheduler_without_waiting_for_poll_interval(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROMITA_HISTORIES_DIR", str(tmp_path))
    bus = _Bus()
    timer_fired = threading.Event()
    original_try_emit = bus.try_emit

    def observe_timer(name, data=None, **kwargs):
        accepted = original_try_emit(name, data, **kwargs)
        if name == Events.Chat.SEND_MESSAGE and (data or {}).get("event_type") == "timer":
            timer_fired.set()
        return accepted

    bus.try_emit = observe_timer
    reminders = ReminderManager("Mita")
    registry = _Registry()
    activity = _Activity()
    monkeypatch.setattr(reminder_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(reminder_manager_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(
        reminder_module,
        "use",
        lambda contract: registry if contract is CharacterRegistry else activity,
    )
    controller = reminder_module.ReminderController(
        {"REMINDERS_ENABLED": True},
        character_resources=_Resources(reminders),
    )
    try:
        reminders.add_timer("Wake up", 0.05)
        assert timer_fired.wait(1.0)
    finally:
        controller.shutdown()


def test_timer_tool_and_relative_seconds_are_supported():
    class _ToolReminders:
        def __init__(self) -> None:
            self.calls = []

        def add_timer(self, instruction, delay_seconds):
            self.calls.append((instruction, delay_seconds))
            return 8

    reminders = _ToolReminders()
    tool = ReminderTool()
    tool._get_reminder_system = lambda: reminders

    assert "Таймер #8" in tool.run("timer", delay_seconds=10, instruction="Try again")
    assert reminders.calls == [("Try again", 10.0)]
    parsed = _parse_due("через 0.1 секунды")
    assert parsed is not None
    assert 0 < (parsed - datetime.datetime.now()).total_seconds() < 1


def test_chat_controller_tracks_active_generations_per_character():
    controller = ChatController({})
    first = CancellationToken()
    second = CancellationToken()

    controller._register_generation("one", first, "Mita")
    controller._register_generation("two", second, "Other")
    assert controller.active_generation_count() == 2
    assert controller.active_generation_count("Mita") == 1
    assert controller.active_generation_count("Other") == 1

    controller._finish_generation("one")
    controller._finish_generation("two")
    assert controller.active_generation_count() == 0
