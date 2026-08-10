"""Domain objects for scene-local GameMaster directives."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class GameMasterDirective:
    directive_id: str
    key: str
    target_scope: str
    target_character_id: str
    instruction: str
    source: str
    lifetime: str
    remaining_uses: int | None
    created_turn_index: int
    created_from_command_id: str = ""
    enabled: bool = True

    def for_target(self, character_id: str) -> bool:
        wanted = str(character_id or "").strip().casefold()
        return self.enabled and (
            self.target_scope == "*"
            or self.target_character_id.strip().casefold() == wanted
        )

    def consumed(self) -> "GameMasterDirective | None":
        if self.remaining_uses is None:
            return self
        remaining = self.remaining_uses - 1
        if remaining <= 0:
            return None
        return replace(self, remaining_uses=remaining)
