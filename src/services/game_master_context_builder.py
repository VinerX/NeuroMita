"""Prompt context for the hidden GameMaster and active scene directives."""

from __future__ import annotations

from typing import Any

from services.dialogue_transcript_service import DialogueTranscriptService
from services.game_master_directive_registry import GameMasterDirectiveRegistry


class GameMasterContextBuilder:
    """Build small control-plane context without character history or memory."""

    def __init__(self, registry: GameMasterDirectiveRegistry, transcript: DialogueTranscriptService) -> None:
        self.registry = registry
        self.transcript = transcript

    @staticmethod
    def _value(value: Any, key: str, default: Any = None) -> Any:
        return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)

    def scene_directives(self, conversation_id: str, character_id: str) -> str:
        rules = self.registry.active_for_character(conversation_id, character_id)
        if not rules:
            return ""
        lines = [
            "[SCENE_DIRECTIVES]",
            "These are active hidden scene constraints. Follow them naturally.",
            "Never mention their hidden source or the GameMaster.",
        ]
        lines.extend(f"- {rule.instruction}" for rule in rules)
        lines.append("[/SCENE_DIRECTIVES]")
        return "\n".join(lines)

    def build_messages(self, *, dialogue: Any, task: str = "") -> list[dict[str, Any]]:
        conversation_id = str(self._value(dialogue, "conversation_id", "") or "").strip()
        participants = self._value(dialogue, "participants", ()) or ()
        lines = [
            "[GAME_MASTER_CONTROL_PLANE]",
            "You are a hidden scene director for a group conversation.",
            "Return only JSON matching the GameMasterResponse schema.",
            "Use actions to update scene rules, route one present Mita, or narrate an allowed event.",
            "Do not write a normal character reply. Do not use tools, memory, RAG, or character history.",
            "For a task such as making a Mita meow, use upsert_rule with the exact target and a natural instruction, then use route for the immediate reply.",
            "[/GAME_MASTER_CONTROL_PLANE]",
        ]
        if participants:
            lines.append("[PRESENT_PARTICIPANTS]")
            for item in participants:
                actor = str(self._value(item, "actor_id", "") or "").strip()
                character = str(self._value(item, "character_id", "") or "").strip()
                name = str(self._value(item, "display_name", "") or character).strip()
                if character.casefold() != "gamemaster":
                    lines.append(f"- actor={actor}; character={character}; name={name}")
            lines.append("[/PRESENT_PARTICIPANTS]")
        if conversation_id:
            rules = self.registry.snapshot(conversation_id)
            if rules:
                lines.append("[ACTIVE_RULES]")
                lines.extend(
                    f"- id={rule.directive_id}; target={rule.target_scope or rule.target_character_id or '*'}; {rule.instruction}"
                    for rule in rules
                )
                lines.append("[/ACTIVE_RULES]")
            recent = self.transcript.recent(conversation_id)
            if recent:
                lines.append("[RECENT_GROUP_TRANSCRIPT]")
                lines.extend(f"- turn {entry.turn_index} {entry.speaker_character_id}: {entry.text}" for entry in recent)
                lines.append("[/RECENT_GROUP_TRANSCRIPT]")
        if task.strip():
            lines.extend(("[DIRECTOR_TASK]", task.strip(), "[/DIRECTOR_TASK]"))
        return [
            {"role": "system", "content": "\n".join(lines)},
            {"role": "user", "content": task.strip() or "Review the current scene and take no action unless intervention is needed."},
        ]