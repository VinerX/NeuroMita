from core.error_utils import format_exception
import datetime
import threading

from core.events import Events, get_event_bus
from core.services import use
from core.task_supervisor import task_supervisor
from main_logger import logger
from services.contracts import CharacterRegistry, GenerationActivityService


class ReminderController:
    """Dispatch persisted reminders and precise short timers.

    The worker sleeps until the nearest saved deadline.  A persistence-change
    notification interrupts that sleep, so a newly added ten-second timer is
    not delayed by the long-reminder fallback interval.
    """
    CHECK_INTERVAL_SEC = 30

    def __init__(self, settings, character_resources=None):
        self.settings = settings
        self.character_resources = character_resources
        self.event_bus = get_event_bus()
        self._shutdown_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._subscriptions = []
        subscribe = getattr(self.event_bus, "subscribe", None)
        if callable(subscribe):
            self._subscriptions.extend(
                subscription
                for subscription in (
                    subscribe(Events.Reminder.CHANGED, self._on_schedule_changed, weak=False),
                    subscribe(Events.Chat.GENERATION_ACTIVITY_CHANGED, self._on_generation_activity_changed, weak=False),
                )
                if subscription is not None
            )
        self._start_periodic_check()

    def _start_periodic_check(self):
        if self._thread is not None and self._thread.is_alive():
            return

        def check_loop():
            while self.event_bus.is_running and not self._shutdown_event.is_set():
                try:
                    if self.settings.get("REMINDERS_ENABLED", True):
                        self._check_and_fire_reminders()
                except Exception as exc:
                    logger.error(
                        f"[ReminderController] Error in check loop: {format_exception(exc)}",
                        exc_info=True,
                    )
                if self._wait_for_next_schedule():
                    return

        self._thread = task_supervisor().start_thread(
            self,
            "reminder-loop",
            check_loop,
            cancel_event=self._shutdown_event,
        )
        logger.info("[ReminderController] Scheduler thread started.")

    def _on_schedule_changed(self, _event) -> None:
        self._wake_event.set()

    def _on_generation_activity_changed(self, _event) -> None:
        # A due timer deferred behind its character's current generation can
        # now be reconsidered immediately when that generation finishes.
        self._wake_event.set()

    def _wait_for_next_schedule(self) -> bool:
        self._wake_event.clear()
        timeout = self._seconds_until_next_due()
        if self._shutdown_event.wait(0):
            return True
        self._wake_event.wait(timeout)
        return self._shutdown_event.is_set()

    def _seconds_until_next_due(self) -> float:
        now = datetime.datetime.now()
        earliest = None
        try:
            registry = use(CharacterRegistry)
            for character_id in registry.all_ids():
                reminder_system = self._reminder_system_for(character_id)
                if reminder_system is None:
                    continue
                due_at = reminder_system.get_next_due_at()
                if due_at is not None and (earliest is None or due_at < earliest):
                    earliest = due_at
        except Exception:
            return max(0.1, float(self.CHECK_INTERVAL_SEC))

        if earliest is None:
            return max(0.1, float(self.CHECK_INTERVAL_SEC))
        seconds = (earliest - now).total_seconds()
        # A due timer that is waiting for an in-flight generation is retried
        # by GENERATION_ACTIVITY_CHANGED; avoid spinning while it waits.
        if seconds <= 0:
            return max(0.1, float(self.CHECK_INTERVAL_SEC))
        return seconds

    def shutdown(self) -> None:
        self._shutdown_event.set()
        self._wake_event.set()
        for subscription in self._subscriptions:
            try:
                subscription.close()
            except Exception:
                pass
        self._subscriptions.clear()
        thread = self._thread
        self._thread = None
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)

    def _reminder_system_for(self, character_id: str):
        resources = self.character_resources
        if resources is not None:
            return resources.reminders_for(character_id)

        registry = use(CharacterRegistry)
        character = registry.get(character_id)
        return getattr(character, "reminder_system", None) if character else None

    def _check_and_fire_reminders(self):
        registry = use(CharacterRegistry)
        for character_id in registry.all_ids():
            reminder_system = self._reminder_system_for(character_id)
            if reminder_system is None:
                continue

            due_reminders = reminder_system.get_due_reminders()
            for reminder in due_reminders:
                number = reminder.get("N")
                text = reminder.get("text", "")
                if self._is_character_generating(character_id):
                    logger.info(
                        f"[ReminderController] Deferring scheduled item #{number} "
                        f"for '{character_id}' until its current generation finishes."
                    )
                    continue
                is_timer = reminder.get("kind") == "timer"
                label = "timer" if is_timer else "reminder"
                logger.info(
                    f"[ReminderController] Firing {label} #{number} "
                    f"for '{character_id}': {text[:60]}"
                )
                accepted = self.event_bus.try_emit(
                    Events.Chat.SEND_MESSAGE,
                    {
                        "character_id": character_id,
                        "user_input": "",
                        "system_input": f"[Timer fired] {text}" if is_timer else f"[Reminder] {text}",
                        "event_type": "timer" if is_timer else "reminder",
                    },
                )
                if accepted:
                    reminder_system.dismiss_reminder(number)
                else:
                    logger.warning(
                        f"[ReminderController] Reminder #{number} for "
                        f"'{character_id}' was not queued and remains pending."
                    )

    @staticmethod
    def _is_character_generating(character_id: str) -> bool:
        try:
            activity = use(GenerationActivityService)
            return activity.active_generation_count(character_id) > 0
        except Exception:
            # The scheduler also operates in early-startup and isolated tests,
            # before the chat service is registered.
            return False
