import json
import logging
import os
import datetime
import threading

logger = logging.getLogger(__name__)


class ReminderManager:
    def __init__(self, character_name: str):
        self.character_name = character_name
        self.history_dir = f"Histories\\{character_name}"
        os.makedirs(self.history_dir, exist_ok=True)

        self.filename = os.path.join(self.history_dir, f"{character_name}_reminders.json")
        self.reminders: list = []
        self.last_reminder_number = 1
        self._lock = threading.Lock()

        self.load_reminders()

    def load_reminders(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    self.reminders = json.load(f)
                    if self.reminders:
                        self.last_reminder_number = max(r['N'] for r in self.reminders) + 1
                    else:
                        self.last_reminder_number = 1
            except Exception as e:
                logger.error(f"[ReminderManager] Failed to load {self.filename}: {e}")
                self.reminders = []
                self.save_reminders()
        else:
            self.reminders = []
            self.save_reminders()
            logger.info(f"[ReminderManager] Created new reminders file: {self.filename}")

    def save_reminders(self):
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.reminders, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"[ReminderManager] Failed to save {self.filename}: {e}")

    def add_reminder(self, text: str, due_iso: str) -> int:
        """Parse due_iso, create reminder record, save. Returns new N."""
        try:
            datetime.datetime.fromisoformat(due_iso)
        except ValueError as e:
            logger.warning(f"[ReminderManager] Bad due_iso format '{due_iso}': {e}")
            raise

        with self._lock:
            new_id = self.last_reminder_number
            self.last_reminder_number += 1
            record = {
                "N": new_id,
                "text": text,
                "due_iso": due_iso,
                "created_iso": datetime.datetime.now().isoformat("T", "seconds"),
            }
            self.reminders.append(record)
            self.save_reminders()
            logger.info(f"[ReminderManager] Added reminder #{new_id}, due={due_iso}: {text[:60]}")
            return new_id

    def delete_reminder(self, n: int) -> bool:
        """Delete reminder by N. Returns True if found and deleted."""
        with self._lock:
            for i, r in enumerate(self.reminders):
                if r["N"] == n:
                    del self.reminders[i]
                    self.save_reminders()
                    logger.info(f"[ReminderManager] Deleted reminder #{n}")
                    return True
            logger.warning(f"[ReminderManager] Reminder #{n} not found for deletion")
            return False

    def get_due_reminders(self) -> list:
        """Return all reminders whose due_iso <= now. Does NOT remove them."""
        now = datetime.datetime.now()
        due = []
        with self._lock:
            for r in self.reminders:
                try:
                    due_dt = datetime.datetime.fromisoformat(r["due_iso"])
                    if due_dt <= now:
                        due.append(r.copy())
                except Exception as e:
                    logger.warning(f"[ReminderManager] Bad due_iso in reminder #{r.get('N')}: {e}")
        return due

    def dismiss_reminder(self, n: int) -> bool:
        """Remove a fired reminder (call after firing it to the chat)."""
        return self.delete_reminder(n)

    def get_reminders_formatted(self) -> str:
        """Return a [Pending Reminders] block or '' if empty."""
        with self._lock:
            if not self.reminders:
                return ""
            lines = ["[Pending Reminders]"]
            for r in self.reminders:
                try:
                    due_dt = datetime.datetime.fromisoformat(r["due_iso"])
                    due_str = due_dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    due_str = r.get("due_iso", "?")
                lines.append(f"N:{r['N']}, Due: {due_str}, Text: {r['text']}")
            lines.append('To set: reminder_add "YYYY-MM-DDTHH:MM:SS|text". To delete: reminder_delete "N".')
            lines.append("[/Pending Reminders]")
            return "\n".join(lines)
