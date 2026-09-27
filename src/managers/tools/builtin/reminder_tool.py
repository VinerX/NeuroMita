# src/managers/tools/builtin/reminder_tool.py
"""
ReminderTool — позволяет Мите управлять напоминаниями:
  list   — показать все активные напоминания
  add    — добавить напоминание с датой/временем
  delete — удалить напоминание по номеру
"""
from __future__ import annotations
from core.error_utils import format_exception

import datetime
import re
from typing import Any, Dict, Optional

from managers.tools.base import Tool
from main_logger import logger


# ---------- date parsing (future-oriented) ---------------------------------

def _parse_due(s: str) -> Optional[datetime.datetime]:
    """
    Парсит строку срока напоминания (может быть в будущем):
    - "через 2 часа", "через 30 минут", "через неделю"
    - "завтра", "послезавтра", "сегодня в 18:00"
    - ISO: "2024-01-15T14:00:00"
    - Относительные прошлые тоже (на случай ошибки): "через 0 минут" → сейчас
    """
    if not s:
        return None
    s = s.strip()
    now = datetime.datetime.now()

    # "через N минут/часов/дней/недель"
    _FUTURE_RU = [
        (re.compile(r"через\s+(\d+(?:[.,]\d+)?)\s*секунд[ыу]?", re.I), lambda m, n=now: n + datetime.timedelta(seconds=float(m.group(1).replace(',', '.')))),
        (re.compile(r"через\s+(\d+)\s*минут[ыу]?", re.I), lambda m, n=now: n + datetime.timedelta(minutes=int(m.group(1)))),
        (re.compile(r"через\s+(\d+)\s*час[аов]?", re.I),  lambda m, n=now: n + datetime.timedelta(hours=int(m.group(1)))),
        (re.compile(r"через\s+(\d+)\s*дн[еёя]", re.I),   lambda m, n=now: n + datetime.timedelta(days=int(m.group(1)))),
        (re.compile(r"через\s+(\d+)\s*недел[юьи]", re.I), lambda m, n=now: n + datetime.timedelta(weeks=int(m.group(1)))),
        (re.compile(r"через\s+неделю", re.I),              lambda m, n=now: n + datetime.timedelta(weeks=1)),
        (re.compile(r"через\s+месяц", re.I),               lambda m, n=now: n + datetime.timedelta(days=30)),
        (re.compile(r"через\s+час", re.I),                 lambda m, n=now: n + datetime.timedelta(hours=1)),
        (re.compile(r"через\s+полчаса", re.I),             lambda m, n=now: n + datetime.timedelta(minutes=30)),
    ]
    _FUTURE_EN = [
        (re.compile(r"in\s+(\d+(?:\.\d+)?)\s*seconds?", re.I), lambda m, n=now: n + datetime.timedelta(seconds=float(m.group(1)))),
        (re.compile(r"in\s+(\d+)\s*minutes?", re.I), lambda m, n=now: n + datetime.timedelta(minutes=int(m.group(1)))),
        (re.compile(r"in\s+(\d+)\s*hours?", re.I),   lambda m, n=now: n + datetime.timedelta(hours=int(m.group(1)))),
        (re.compile(r"in\s+(\d+)\s*days?", re.I),    lambda m, n=now: n + datetime.timedelta(days=int(m.group(1)))),
        (re.compile(r"in\s+(\d+)\s*weeks?", re.I),   lambda m, n=now: n + datetime.timedelta(weeks=int(m.group(1)))),
        (re.compile(r"in\s+an?\s+hour", re.I),        lambda m, n=now: n + datetime.timedelta(hours=1)),
        (re.compile(r"tomorrow", re.I),                lambda m, n=now: (n + datetime.timedelta(days=1)).replace(hour=9, minute=0, second=0)),
    ]

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    _DAY_WORDS_RU: list[tuple] = [
        (re.compile(r"завтра\s+в\s+(\d{1,2})[:\.](\d{2})", re.I),
         lambda m, t=today_start: t + datetime.timedelta(days=1, hours=int(m.group(1)), minutes=int(m.group(2)))),
        (re.compile(r"завтра", re.I),
         lambda m, t=today_start: t + datetime.timedelta(days=1, hours=9)),
        (re.compile(r"послезавтра", re.I),
         lambda m, t=today_start: t + datetime.timedelta(days=2, hours=9)),
        (re.compile(r"сегодня\s+в\s+(\d{1,2})[:\.](\d{2})", re.I),
         lambda m, t=today_start: t.replace(hour=int(m.group(1)), minute=int(m.group(2)))),
    ]

    for pat, fn in _FUTURE_RU + _FUTURE_EN + _DAY_WORDS_RU:
        m = pat.fullmatch(s) or pat.search(s)
        if m:
            try:
                return fn(m)
            except Exception:
                pass

    # ISO formats
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            pass

    return None


# ---------- tool -----------------------------------------------------------

class ReminderTool(Tool):
    """Управление напоминаниями и короткими таймерами."""

    name = "reminder"
    description = (
        "Manage reminders. "
        "list — show all pending reminders; "
        "add — add a reminder (requires text and due date/time); "
        "delete — remove a reminder by its number N; "
        "timer — after delay_seconds, autonomously start a new LLM turn with instruction. "
        "Due examples: 'через 10 секунд', 'через 2 часа', 'in 30 seconds', '2024-12-01T10:00:00'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "delete", "timer"],
                "description": "Action to perform.",
            },
            "text": {
                "type": "string",
                "description": "Reminder text (required for 'add').",
            },
            "due": {
                "type": "string",
                "description": (
                    "When to fire the reminder (required for 'add'). "
                    "Relative: 'через 2 часа', 'завтра', 'in 30 minutes'. "
                    "Absolute ISO: '2024-12-01T14:00:00'."
                ),
            },
            "n": {
                "type": "integer",
                "description": "Reminder number N (required for 'delete').",
            },
            "delay_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Delay before timer fires (required for 'timer').",
            },
            "instruction": {
                "type": "string",
                "description": "System instruction for the autonomous turn (required for 'timer').",
            },
        },
        "required": ["action"],
    }

    def __init__(self):
        self._char_id: Optional[str] = None

    def set_char_id(self, char_id: str) -> None:
        self._char_id = char_id

    def _get_reminder_system(self):
        if not self._char_id:
            return None
        from core.services import use
        from services.contracts import CharacterRegistry

        char = use(CharacterRegistry).get(self._char_id)
        return getattr(char, "reminder_system", None)

    def run(self, action: str, text: str = None, due: str = None, n: int = None, delay_seconds: float = None, instruction: str = None, **_) -> Any:
        rs = self._get_reminder_system()
        if rs is None:
            return "[reminder] Ошибка: система напоминаний недоступна."

        action = str(action or "list").lower().strip()

        if action == "list":
            result = rs.get_reminders_formatted()
            return result if result else "Нет активных напоминаний."

        elif action == "add":
            if not text:
                return "[reminder] Для добавления укажи текст напоминания (параметр text)."
            if not due:
                return "[reminder] Для добавления укажи дату/время (параметр due)."
            dt = _parse_due(str(due))
            if dt is None:
                return (
                    f"[reminder] Не удалось распознать дату '{due}'. "
                    f"Используй формат 'через 2 часа', 'завтра в 18:00', или ISO '2024-12-01T14:00:00'."
                )
            due_iso = dt.isoformat(timespec="seconds")
            try:
                new_n = rs.add_reminder(str(text), due_iso)
                return f"Напоминание #{new_n} добавлено: «{text}» — {dt.strftime('%Y-%m-%d %H:%M')}."
            except Exception as e:
                return f"[reminder] Ошибка при добавлении: {format_exception(e)}"

        elif action == "timer":
            if not instruction:
                return "[timer] Для таймера укажи instruction для следующего хода."
            if delay_seconds is None:
                return "[timer] Для таймера укажи delay_seconds."
            try:
                new_n = rs.add_timer(str(instruction), float(delay_seconds))
                return f"Таймер #{new_n} установлен на {float(delay_seconds):g} сек.: «{instruction}»."
            except (TypeError, ValueError) as exc:
                return f"[timer] Некорректный delay_seconds: {format_exception(exc)}"
            except Exception as exc:
                return f"[timer] Ошибка при добавлении: {format_exception(exc)}"

        elif action == "delete":
            if n is None:
                return "[reminder] Для удаления укажи номер напоминания (параметр n)."
            ok = rs.delete_reminder(int(n))
            if ok:
                return f"Напоминание #{n} удалено."
            else:
                return f"[reminder] Напоминание #{n} не найдено."

        else:
            return f"[reminder] Неизвестное действие '{action}'. Используй: list, add, delete."
