"""Prompt context for the hidden GameMaster and active scene directives."""

from __future__ import annotations

from typing import Any

from services.dialogue_transcript_service import DialogueTranscriptService
from services.game_master_directive_registry import GameMasterDirectiveRegistry


class GameMasterContextBuilder:
    """Build small control-plane context without character history or memory."""

    _DEFAULT_ANCHORS = {
        "crazy": "volatile, possessive, emotionally intense, strongly attached to the Player",
        "kind": "rational, cooperative, calm, empathic, and quietly resolute",
        "cappie": "energetic, playful, musical, adventurous, and emotionally bright",
        "shorthair": "helpful, practical, explanatory, and community-minded",
        "mila": "proud, intelligent, independent, fierce, and tsundere",
        "sleepy": "gentle, slow-paced, sleepy, and easily distracted",
        "creepy": "uneasy, intense, guarded, and shaped by a threatening atmosphere",
        "ghost": "poetic, fragmented, sorrowful, traumatized, but still seeking connection",
    }

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

    def build_messages(
        self,
        *,
        dialogue: Any,
        task: str = "",
        capabilities: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        conversation_id = str(self._value(dialogue, "conversation_id", "") or "").strip()
        participants = self._value(dialogue, "participants", ()) or ()
        capabilities = capabilities or {}
        allow_routing = bool(capabilities.get("gm_allow_routing", True))
        allow_narration = bool(capabilities.get("gm_allow_narration", False))
        lines = [
            "[GAME_MASTER_CONTROL_PLANE]",
            "You are a hidden scene director for a group conversation.",
            "Return only JSON matching the GameMasterResponse schema.",
            "Use actions to update scene rules, route one present Mita, or narrate an allowed event.",
            "Do not write a normal character reply. Do not use tools, memory, RAG, or character history.",
            f"Routing actions are {'allowed' if allow_routing else 'disabled'}; do not emit route actions when disabled.",
            f"Narration actions are {'allowed' if allow_narration else 'disabled'}; do not emit narrate actions when disabled.",
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
            lines.append("[CHARACTER_ANCHORS]")
            for item in participants:
                character = str(self._value(item, "character_id", "") or "").strip()
                if not character or character.casefold() == "gamemaster":
                    continue
                anchor = str(
                    self._value(item, "character_anchor", "")
                    or self._value(item, "anchor", "")
                    or self._DEFAULT_ANCHORS.get(character.casefold(), "")
                ).strip()
                if anchor:
                    lines.append(f"- {character}: {anchor}")
            lines.append("[/CHARACTER_ANCHORS]")
        if conversation_id:
            rules = self.registry.snapshot(conversation_id)
            if rules:
                lines.append("[ACTIVE_RULES]")
                lines.extend(
                    f"- id={rule.directive_id}; target={rule.target_scope or rule.target_character_id}; "
                    f"key={rule.key}; source={rule.source}; lifetime={rule.lifetime}; "
                    f"remaining={rule.remaining_uses if rule.remaining_uses is not None else 'unlimited'}; "
                    f"instruction={rule.instruction}"
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