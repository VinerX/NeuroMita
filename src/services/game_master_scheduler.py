"""Simple periodic GameMaster check scheduler."""

from __future__ import annotations

import threading


class GameMasterScheduler:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counts: dict[str, int] = {}

    def note_mita_reply(self, conversation_id: str, *, interval: int) -> bool:
        key = str(conversation_id or "").strip()
        if not key:
            return False
        with self._lock:
            count = self._counts.get(key, 0) + 1
            threshold = max(1, min(100, int(interval)))
            if count < threshold:
                self._counts[key] = count
                return False
            self._counts[key] = 0
            return True

    def reset_conversation(self, conversation_id: str) -> None:
        with self._lock:
            self._counts.pop(str(conversation_id or "").strip(), None)
