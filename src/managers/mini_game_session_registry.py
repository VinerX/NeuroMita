"""Read-only public summaries for active per-character mini-game sessions."""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MiniGamePublicSession:
    owner_character_id: str
    owner_name: str
    game_id: str
    last_public_event: str = ""


class MiniGameSessionRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, MiniGamePublicSession] = {}

    def start(self, owner_character_id: str, owner_name: str, game_id: str) -> None:
        owner_id = str(owner_character_id or "").strip()
        normalized_game = str(game_id or "").strip().lower()
        if not owner_id or normalized_game not in {"chess", "seabattle"}:
            return
        label = "Chess" if normalized_game == "chess" else "Sea Battle"
        name = str(owner_name or owner_id).strip()[:120]
        summary = f"The player started a {label} match with {name}."
        with self._lock:
            self._sessions[owner_id] = MiniGamePublicSession(
                owner_character_id=owner_id,
                owner_name=name,
                game_id=normalized_game,
                last_public_event=summary,
            )

    def update_public_event(self, owner_character_id: str, game_id: str, text: str) -> None:
        owner_id = str(owner_character_id or "").strip()
        normalized_game = str(game_id or "").strip().lower()
        public_text = str(text or "").strip()[:240]
        if not owner_id or not public_text:
            return
        with self._lock:
            session = self._sessions.get(owner_id)
            if session is None or session.game_id != normalized_game:
                return
            self._sessions[owner_id] = MiniGamePublicSession(
                owner_character_id=session.owner_character_id,
                owner_name=session.owner_name,
                game_id=session.game_id,
                last_public_event=public_text,
            )

    def stop(self, owner_character_id: str, game_id: str | None = None) -> None:
        owner_id = str(owner_character_id or "").strip()
        with self._lock:
            session = self._sessions.get(owner_id)
            if session is None:
                return
            if game_id and session.game_id != str(game_id).strip().lower():
                return
            self._sessions.pop(owner_id, None)

    def snapshot(self) -> tuple[MiniGamePublicSession, ...]:
        with self._lock:
            return tuple(self._sessions.values())


_registry = MiniGameSessionRegistry()


def mini_game_sessions() -> MiniGameSessionRegistry:
    return _registry
