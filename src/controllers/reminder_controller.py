import threading
import time

from core.events import Events, get_event_bus
from core.services import use
from main_logger import logger
from services.contracts import CharacterRegistry


class ReminderController:
    CHECK_INTERVAL_SEC = 30

    def __init__(self, settings, character_resources=None):
        self.settings = settings
        self.character_resources = character_resources
        self.event_bus = get_event_bus()
        self._start_periodic_check()

    def _start_periodic_check(self):
        def check_loop():
            while self.event_bus.is_running:
                try:
                    if self.settings.get("REMINDERS_ENABLED", True):
                        self._check_and_fire_reminders()
                except Exception as exc:
                    logger.error(
                        f"[ReminderController] Error in check loop: {exc}",
                        exc_info=True,
                    )
                for _ in range(self.CHECK_INTERVAL_SEC):
                    if not self.event_bus.is_running:
                        return
                    time.sleep(1)

        thread = threading.Thread(
            target=check_loop,
            daemon=True,
            name="ReminderController",
        )
        thread.start()
        logger.info("[ReminderController] Periodic check thread started.")

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
                logger.info(
                    f"[ReminderController] Firing reminder #{number} "
                    f"for '{character_id}': {text[:60]}"
                )
                reminder_system.dismiss_reminder(number)
                self.event_bus.emit(
                    Events.Chat.SEND_MESSAGE,
                    {
                        "character_id": character_id,
                        "user_input": "",
                        "system_input": f"[Reminder] {text}",
                        "event_type": "reminder",
                    },
                )
