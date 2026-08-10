"""Bounded, non-persistent transcript for the current group conversation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading


@dataclass(frozen=True, slots=True)
class DialogueTranscriptEntry:
    conversation_id: str
    turn_index: int
    speaker_character_id: str
    speaker_actor_id: str
    text: str
    event_type: str


class DialogueTranscriptService:
    def __init__(self, *, max_entries_per_conversation: int = 64) -> None:
        self._max_entries = max(1, int(max_entries_per_conversation))
        self._lock = threading.RLock()
        self._items: dict[str, deque[DialogueTranscriptEntry]] = {}

    def record(
        self,
        conversation_id: str,
        *,
        turn_index: int,
        speaker_character_id: str,
        speaker_actor_id: str = "",
        text: str,
        event_type: str,
    ) -> None:
        conversation_id = str(conversation_id or "").strip()
        text = str(text or "").strip()
        speaker_character_id = str(speaker_character_id or "").strip()
        if not conversation_id or not text or not speaker_character_id:
            return
        if speaker_character_id.casefold() == "gamemaster":
            return
        entry = DialogueTranscriptEntry(
            conversation_id=conversation_id,
            turn_index=max(0, int(turn_index)),
            speaker_character_id=speaker_character_id,
            speaker_actor_id=str(speaker_actor_id or "").strip(),
            text=text,
            event_type=str(event_type or "dialogue").strip(),
        )
        with self._lock:
            bucket = self._items.setdefault(conversation_id, deque(maxlen=self._max_entries))
            bucket.append(entry)

    def record_player_message(self, conversation_id: str, *, turn_index: int, text: str) -> None:
        self.record(
            conversation_id,
            turn_index=turn_index,
            speaker_character_id="Player",
            text=text,
            event_type="player_message",
        )

    def record_mita_reply(self, conversation_id: str, *, turn_index: int, character_id: str, actor_id: str, text: str) -> None:
        self.record(
            conversation_id,
            turn_index=turn_index,
            speaker_character_id=character_id,
            speaker_actor_id=actor_id,
            text=text,
            event_type="mita_reply",
        )

    def recent(self, conversation_id: str, *, max_entries: int = 12, max_chars: int = 12000) -> tuple[DialogueTranscriptEntry, ...]:
        with self._lock:
            entries = list(self._items.get(str(conversation_id or "").strip(), ()))
        selected: list[DialogueTranscriptEntry] = []
        total = 0
        for entry in reversed(entries[-max(1, int(max_entries)):]):
            if total + len(entry.text) > max_chars and selected:
                break
            selected.append(entry)
            total += len(entry.text)
        return tuple(reversed(selected))

    def clear_conversation(self, conversation_id: str) -> None:
        with self._lock:
            self._items.pop(str(conversation_id or "").strip(), None)
