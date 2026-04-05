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
            while True:
                try:
                    if self.settings.get("REMINDERS_ENABLED", True):
                        self._check_and_fire_reminders()
                except Exception as e:
                    logger.error(f"[ReminderController] Error in check loop: {e}", exc_info=True)
                time.sleep(self.CHECK_INTERVAL_SEC)

        thread = threading.Thread(target=check_loop, daemon=True, name="ReminderController")
        thread.start()
        logger.info("[ReminderController] Periodic check thread started.")

    def _check_and_fire_reminders(self):
        """Check all characters for due reminders and emit chat events."""
        try:
            all_ids_res = self.event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
            all_ids = all_ids_res[0] if all_ids_res and isinstance(all_ids_res[0], list) else []
        except Exception as e:
            logger.warning(f"[ReminderController] Could not get character list: {e}")
            return

        for cid in all_ids:
            try:
                char_res = self.event_bus.emit_and_wait(
                    Events.Character.GET, {"character_id": cid}, timeout=1.0
                )
                char = char_res[0] if char_res else None
            except Exception as e:
                logger.warning(f"[ReminderController] Could not get character '{cid}': {e}")
                continue

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
