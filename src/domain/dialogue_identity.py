from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DialogueActorKind(str, Enum):
    """Stable application-level identity kind for dialogue routing decisions."""

    PLAYER = "player"
    CHARACTER = "character"
    GAME_MASTER = "game_master"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResolvedDialogueSpeaker:
    """Canonical speaker identity resolved from one dialogue turn boundary."""

    actor_id: str
    sender_id: str
    kind: DialogueActorKind
    authoritative: bool
