from __future__ import annotations

import datetime
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field

from managers.character_scoped_service import CharacterScopedService

logger = logging.getLogger(__name__)


@dataclass
class _ReminderState:
    filename: str
    reminders: list[dict] = field(default_factory=list)
    last_reminder_number: int = 1
    loaded: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)


class ReminderManager(CharacterScopedService):
    """One reminder service with isolated state per character id."""

    def __init__(self, character_name: str = ""):
        super().__init__(
            default_character_id=str(character_name or ""),
            default_character_name=str(character_name or ""),
        )
        self._states: dict[str, _ReminderState] = {}
        if character_name:
            self.load_reminders()

    def _state(self) -> _ReminderState:
        key = self.character_id
        state = self._states.get(key)
        if state is None:
            histories_dir = os.environ.get(
                "NEUROMITA_HISTORIES_DIR",
                os.path.join(os.getcwd(), "Histories"),
            )
            history_dir = os.path.join(histories_dir, key)
            os.makedirs(history_dir, exist_ok=True)
            state = _ReminderState(
                filename=os.path.join(history_dir, f"{key}_reminders.json")
            )
            self._states[key] = state
        if not state.loaded:
            self._load_state(state)
        return state

    @property
    def history_dir(self) -> str:
        return os.path.dirname(self._state().filename)

    @property
    def filename(self) -> str:
        return self._state().filename

    @property
    def reminders(self) -> list[dict]:
        return self._state().reminders

    @reminders.setter
    def reminders(self, value: list[dict]) -> None:
        self._state().reminders = list(value or [])

    @property
    def last_reminder_number(self) -> int:
        return self._state().last_reminder_number

    @last_reminder_number.setter
    def last_reminder_number(self, value: int) -> None:
        self._state().last_reminder_number = max(1, int(value or 1))

    @property
    def _lock(self) -> threading.RLock:
        return self._state().lock

    def _load_state(self, state: _ReminderState) -> None:
        with state.lock:
            if state.loaded:
                return
            if os.path.exists(state.filename):
                try:
                    with open(state.filename, "r", encoding="utf-8") as source:
                        loaded = json.load(source)
                    state.reminders = list(loaded) if isinstance(loaded, list) else []
                except Exception as exc:
                    logger.error(
                        f"[ReminderManager] Failed to load {state.filename}: {exc}"
                    )
                    state.reminders = []
            else:
                state.reminders = []

            valid_ids = [
                int(item.get("N", 0) or 0)
                for item in state.reminders
                if isinstance(item, dict)
            ]
            state.last_reminder_number = max(valid_ids, default=0) + 1
            state.loaded = True

            if not os.path.exists(state.filename):
                self._save_state(state)
                logger.info(
                    f"[ReminderManager] Created new reminders file: {state.filename}"
                )

    def _save_state(self, state: _ReminderState) -> None:
        directory = os.path.dirname(state.filename)
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".reminders-",
            suffix=".json.tmp",
            dir=directory,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(state.reminders, target, ensure_ascii=False, indent=4)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, state.filename)
        except Exception as exc:
            logger.error(
                f"[ReminderManager] Failed to save {state.filename}: {exc}"
            )
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def load_reminders(self):
        state = self._state()
        return list(state.reminders)

    def save_reminders(self):
        state = self._state()
        with state.lock:
            self._save_state(state)

    def add_reminder(self, text: str, due_iso: str) -> int:
        try:
            datetime.datetime.fromisoformat(due_iso)
        except ValueError as exc:
            logger.warning(f"[ReminderManager] Bad due_iso format '{due_iso}': {exc}")
            raise

        state = self._state()
        with state.lock:
            new_id = state.last_reminder_number
            state.last_reminder_number += 1
            state.reminders.append(
                {
                    "N": new_id,
                    "text": text,
                    "due_iso": due_iso,
                    "created_iso": datetime.datetime.now().isoformat("T", "seconds"),
                }
            )
            self._save_state(state)
            logger.info(
                f"[ReminderManager] Added reminder #{new_id}, due={due_iso}: {text[:60]}"
            )
            return new_id

    def delete_reminder(self, n: int) -> bool:
        state = self._state()
        with state.lock:
            for index, reminder in enumerate(state.reminders):
                if int(reminder.get("N", -1)) == int(n):
                    del state.reminders[index]
                    self._save_state(state)
                    logger.info(f"[ReminderManager] Deleted reminder #{n}")
                    return True
            logger.warning(
                f"[ReminderManager] Reminder #{n} not found for deletion"
            )
            return False

    def get_due_reminders(self) -> list[dict]:
        now = datetime.datetime.now()
        due: list[dict] = []
        state = self._state()
        with state.lock:
            for reminder in state.reminders:
                try:
                    due_dt = datetime.datetime.fromisoformat(reminder["due_iso"])
                    if due_dt <= now:
                        due.append(reminder.copy())
                except Exception as exc:
                    logger.warning(
                        f"[ReminderManager] Bad due_iso in reminder #{reminder.get('N')}: {exc}"
                    )
        return due

    def dismiss_reminder(self, n: int) -> bool:
        return self.delete_reminder(n)

    def clear_reminders(self) -> None:
        state = self._state()
        with state.lock:
            state.reminders.clear()
            state.last_reminder_number = 1
            self._save_state(state)

    def get_reminders_formatted(self) -> str:
        state = self._state()
        with state.lock:
            if not state.reminders:
                return ""
            lines = ["[Pending Reminders]"]
            for reminder in state.reminders:
                try:
                    due_dt = datetime.datetime.fromisoformat(reminder["due_iso"])
                    due_str = due_dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    due_str = reminder.get("due_iso", "?")
                lines.append(
                    f"N:{reminder['N']}, Due: {due_str}, Text: {reminder['text']}"
                )
            lines.append(
                'To set: reminder_add "YYYY-MM-DDTHH:MM:SS|text". '
                'To delete: reminder_delete "N".'
            )
            lines.append("[/Pending Reminders]")
            return "\n".join(lines)
