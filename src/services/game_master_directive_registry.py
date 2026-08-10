"""In-memory, conversation-scoped source of truth for director rules."""

from __future__ import annotations

import threading
import uuid
from dataclasses import replace

from domain.game_master import GameMasterDirective


class GameMasterDirectiveRegistry:
    """Stores active rules without putting temporary direction into memory."""

    _SOURCE_PRIORITY = {"auto_corrector": 0, "user_director": 1}

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, GameMasterDirective]] = {}

    @staticmethod
    def _slot(directive: GameMasterDirective) -> tuple[str, str]:
        target = directive.target_scope or directive.target_character_id
        return target.strip().casefold(), directive.key.strip().casefold()

    def upsert(self, conversation_id: str, directive: GameMasterDirective) -> GameMasterDirective | None:
        conversation_id = str(conversation_id or "").strip()
        if not conversation_id or not directive.instruction.strip() or not directive.key.strip():
            return None
        with self._lock:
            bucket = self._items.setdefault(conversation_id, {})
            slot = self._slot(directive)
            existing = next((item for item in bucket.values() if self._slot(item) == slot), None)
            if (
                existing is not None
                and self._SOURCE_PRIORITY.get(existing.source, 0)
                > self._SOURCE_PRIORITY.get(directive.source, 0)
            ):
                return None
            if not directive.directive_id:
                directive = replace(directive, directive_id=uuid.uuid4().hex)
            if existing is not None and existing.directive_id != directive.directive_id:
                bucket.pop(existing.directive_id, None)
            bucket[directive.directive_id] = directive
            return directive

    def remove(self, conversation_id: str, directive_id: str, *, source: str | None = None) -> bool:
        with self._lock:
            bucket = self._items.get(str(conversation_id or "").strip(), {})
            directive = bucket.get(str(directive_id or "").strip())
            if directive is None or (source and directive.source != source):
                return False
            bucket.pop(directive.directive_id, None)
            return True

    def clear_target(self, conversation_id: str, character_id: str, *, source: str | None = None) -> int:
        wanted = str(character_id or "").strip().casefold()
        with self._lock:
            bucket = self._items.get(str(conversation_id or "").strip(), {})
            clear_all = wanted in {"", "*"}
            ids = [
                item.directive_id
                for item in bucket.values()
                if (clear_all or item.target_scope == "*" or item.target_character_id.casefold() == wanted)
                and (source is None or item.source == source)
            ]
            for directive_id in ids:
                bucket.pop(directive_id, None)
            return len(ids)

    def active_for_character(self, conversation_id: str, character_id: str) -> tuple[GameMasterDirective, ...]:
        with self._lock:
            return tuple(
                item
                for item in self._items.get(str(conversation_id or "").strip(), {}).values()
                if item.for_target(character_id)
            )

    def consume_after_reply(self, conversation_id: str, character_id: str) -> None:
        with self._lock:
            bucket = self._items.get(str(conversation_id or "").strip(), {})
            for directive in tuple(bucket.values()):
                if not directive.for_target(character_id):
                    continue
                replacement = directive.consumed()
                if replacement is None:
                    bucket.pop(directive.directive_id, None)
                else:
                    bucket[directive.directive_id] = replacement

    def snapshot(self, conversation_id: str) -> tuple[GameMasterDirective, ...]:
        with self._lock:
            return tuple(self._items.get(str(conversation_id or "").strip(), {}).values())

    def clear_conversation(self, conversation_id: str) -> None:
        with self._lock:
            self._items.pop(str(conversation_id or "").strip(), None)
