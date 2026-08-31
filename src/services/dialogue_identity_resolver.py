from __future__ import annotations

from collections.abc import Callable
from typing import Any

from domain.dialogue_identity import DialogueActorKind, ResolvedDialogueSpeaker
from services.contracts import (
    DialogueParticipant,
    DialogueTurnContext,
    parse_dialogue_turn_context,
)


_PLAYER_ACTOR_ID = "Player"


class DialogueIdentityResolver:
    """Single owner of dialogue speaker normalization and actor-to-character mapping."""

    def __init__(self, character_ref_resolver: Callable[[str], Any] | None = None) -> None:
        self._get_character_ref = character_ref_resolver

    @staticmethod
    def canonical_id(value: Any) -> str:
        identity = str(value or "").strip()
        if identity.casefold() == _PLAYER_ACTOR_ID.casefold():
            return _PLAYER_ACTOR_ID
        return identity

    @staticmethod
    def same_id(left: Any, right: Any) -> bool:
        left_id = DialogueIdentityResolver.canonical_id(left)
        right_id = DialogueIdentityResolver.canonical_id(right)
        return bool(left_id and right_id and left_id.casefold() == right_id.casefold())

    def classify_sender(self, sender_id: Any) -> DialogueActorKind:
        canonical_id = self.canonical_id(sender_id)
        if not canonical_id:
            return DialogueActorKind.UNKNOWN
        if self.same_id(canonical_id, _PLAYER_ACTOR_ID):
            return DialogueActorKind.PLAYER

        character = self._resolve_character_ref(canonical_id)
        if character is None:
            return DialogueActorKind.UNKNOWN
        return self._kind_from_character(character)

    def resolve(self, declared_sender: Any, dialogue: Any) -> ResolvedDialogueSpeaker:
        declared_id = self._canonical_registered_sender(declared_sender or _PLAYER_ACTOR_ID)
        context = self._normalize_dialogue(dialogue)
        if context is None or not context.speaker_actor_id:
            return ResolvedDialogueSpeaker(
                actor_id="",
                sender_id=declared_id,
                kind=self.classify_sender(declared_id),
                authoritative=False,
            )

        speaker_actor_id = self.canonical_id(context.speaker_actor_id)
        if self.same_id(speaker_actor_id, _PLAYER_ACTOR_ID):
            return ResolvedDialogueSpeaker(
                actor_id=_PLAYER_ACTOR_ID,
                sender_id=_PLAYER_ACTOR_ID,
                kind=DialogueActorKind.PLAYER,
                authoritative=True,
            )

        participant = self._find_participant(context, speaker_actor_id)
        if participant is None:
            return ResolvedDialogueSpeaker(
                actor_id=speaker_actor_id,
                sender_id=declared_id,
                kind=DialogueActorKind.UNKNOWN,
                authoritative=False,
            )

        sender_id = self._canonical_registered_sender(participant.character_id)
        if not sender_id:
            return ResolvedDialogueSpeaker(
                actor_id=speaker_actor_id,
                sender_id=declared_id,
                kind=DialogueActorKind.UNKNOWN,
                authoritative=False,
            )

        kind = self.classify_sender(sender_id)
        if kind is DialogueActorKind.UNKNOWN:
            kind = DialogueActorKind.CHARACTER

        return ResolvedDialogueSpeaker(
            actor_id=speaker_actor_id,
            sender_id=sender_id,
            kind=kind,
            authoritative=True,
        )

    def _canonical_registered_sender(self, sender_id: Any) -> str:
        canonical_id = self.canonical_id(sender_id)
        if not canonical_id or self.same_id(canonical_id, _PLAYER_ACTOR_ID):
            return canonical_id or _PLAYER_ACTOR_ID

        character = self._resolve_character_ref(canonical_id)
        if character is None:
            return canonical_id
        return self.canonical_id(getattr(character, "char_id", "") or canonical_id)

    def _resolve_character_ref(self, character_id: str) -> Any:
        if self._get_character_ref is None:
            return None
        try:
            return self._get_character_ref(character_id)
        except Exception:
            return None

    @staticmethod
    def _kind_from_character(character: Any) -> DialogueActorKind:
        raw_kind = getattr(character, "dialogue_actor_kind", DialogueActorKind.CHARACTER)
        if isinstance(raw_kind, DialogueActorKind):
            return raw_kind
        try:
            return DialogueActorKind(str(raw_kind))
        except ValueError:
            return DialogueActorKind.CHARACTER

    @staticmethod
    def _normalize_dialogue(dialogue: Any) -> DialogueTurnContext | None:
        if isinstance(dialogue, DialogueTurnContext):
            return dialogue
        if isinstance(dialogue, dict):
            return parse_dialogue_turn_context(dialogue)
        if dialogue is None:
            return None

        speaker_actor_id = str(getattr(dialogue, "speaker_actor_id", "") or "").strip()
        raw_participants = getattr(dialogue, "participants", []) or []
        participants: list[DialogueParticipant] = []
        for item in raw_participants:
            if isinstance(item, DialogueParticipant):
                participant = item
            else:
                actor_id = str(getattr(item, "actor_id", "") or "").strip()
                character_id = str(getattr(item, "character_id", "") or "").strip()
                if not actor_id:
                    continue
                participant = DialogueParticipant(actor_id=actor_id, character_id=character_id)
            participants.append(participant)

        return DialogueTurnContext(
            speaker_actor_id=speaker_actor_id,
            participants=participants,
        )

    @staticmethod
    def _find_participant(
        context: DialogueTurnContext,
        speaker_actor_id: str,
    ) -> DialogueParticipant | None:
        for participant in context.participants:
            if DialogueIdentityResolver.same_id(participant.actor_id, speaker_actor_id):
                return participant
        return None
