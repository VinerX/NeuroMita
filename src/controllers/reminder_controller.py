import time
import threading

from core.events import get_event_bus, Events
from main_logger import logger


class ReminderController:
    CHECK_INTERVAL_SEC = 30

    def __init__(self, settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self._start_periodic_check()

    def _start_periodic_check(self):
        def check_loop():
            # Выходим, как только шина событий остановлена (закрытие приложения):
            # иначе демон-поток продолжает emit во время teardown → access violation.
            while self.event_bus.is_running:
                try:
                    if self.settings.get("REMINDERS_ENABLED", True):
                        self._check_and_fire_reminders()
                except Exception as e:
                    logger.error(f"[ReminderController] Error in check loop: {e}", exc_info=True)
                # Сон дробим, чтобы быстро реагировать на остановку шины.
                for _ in range(self.CHECK_INTERVAL_SEC):
                    if not self.event_bus.is_running:
                        return
                    time.sleep(1)

        thread = threading.Thread(target=check_loop, daemon=True, name="ReminderController")
        thread.start()
        logger.info("[ReminderController] Periodic check thread started.")

    def _check_and_fire_reminders(self):
        """Check all characters for due reminders and emit chat events."""
        registry = use(CharacterRegistry)

        for cid in registry.all_ids():
            char = registry.get(cid)

            if not char or not getattr(char, "reminder_system", None):
                continue

            due_reminders = char.reminder_system.get_due_reminders()
            for reminder in due_reminders:
                n = reminder.get("N")
                text = reminder.get("text", "")
                logger.info(f"[ReminderController] Firing reminder #{n} for '{cid}': {text[:60]}")
                # Dismiss first to avoid double-firing on slow event delivery
                char.reminder_system.dismiss_reminder(n)
                self.event_bus.emit(Events.Chat.SEND_MESSAGE, {
                    "character_id": cid,
                    "user_input": "",
                    "system_input": f"[Reminder] {text}",
                    "event_type": "reminder",
                })
