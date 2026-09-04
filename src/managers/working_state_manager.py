"""Ephemeral per-character cognitive context for the next model turn.

This is deliberately separate from dialogue history, long-term memory and the
objective Unity ``GameState``.  It is an in-process session cache: clearing a
chat clears it, and restarting the application starts a fresh session.
"""
from __future__ import annotations

import threading
from typing import Any

from managers.character_scoped_service import CharacterScopedService


class WorkingStateManager(CharacterScopedService):
    """Own compact, per-character working state without persisting it as history."""

    _FIELDS = (
        ("focus", "Focus"),
        ("situation", "Current understanding"),
        ("assumptions", "Tentative assumptions"),
        ("open_loops", "Open loops"),
        ("next_steps", "Immediate next steps"),
    )

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _clean_text(value: Any, *, limit: int) -> str:
        text = " ".join(str(value or "").split()).strip()
        return text[:limit].rstrip() if limit > 0 else ""

    def update(self, value: Any, *, max_chars: int = 2000) -> bool:
        """Replace the state with a bounded, normalized model-produced snapshot."""
        if hasattr(value, "model_dump"):
            value = value.model_dump(exclude_none=True)
        if not isinstance(value, dict):
            return False

        max_chars = max(200, int(max_chars or 2000))
        remaining = max_chars
        cleaned: dict[str, Any] = {}
        for field, _label in self._FIELDS:
            raw = value.get(field)
            if field == "focus":
                text = self._clean_text(raw, limit=min(600, remaining))
                if text:
                    cleaned[field] = text
                    remaining -= len(text)
                continue

            if not isinstance(raw, list):
                continue
            entries: list[str] = []
            for item in raw[:6]:
                text = self._clean_text(item, limit=min(400, remaining))
                if not text:
                    continue
                entries.append(text)
                remaining -= len(text)
                if remaining <= 0:
                    break
            if entries:
                cleaned[field] = entries
            if remaining <= 0:
                break

        with self._lock:
            key = self.storage_key
            if cleaned:
                self._states[key] = cleaned
            else:
                self._states.pop(key, None)
        return bool(cleaned)

    def clear(self) -> None:
        with self._lock:
            self._states.pop(self.storage_key, None)

    def format_for_prompt(self) -> str:
        with self._lock:
            state = dict(self._states.get(self.storage_key, {}))
        if not state:
            return ""

        lines = ["[WORKING STATE]", "Temporary interpretation from the previous turn."]
        for field, label in self._FIELDS:
            value = state.get(field)
            if isinstance(value, str) and value:
                lines.append(f"{label}: {value}")
            elif isinstance(value, list) and value:
                lines.append(f"{label}:")
                lines.extend(f"- {item}" for item in value)
        lines.append("[/WORKING STATE]")
        return "\n".join(lines)
