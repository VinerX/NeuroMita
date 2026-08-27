"""Validation and application of structured GameMaster actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.game_master import GameMasterDirective
from schemas.game_master_response import GameMasterResponse
from services.game_master_directive_registry import GameMasterDirectiveRegistry
from services.dialogue_target_resolver import (
    DialogueTargetCandidate,
    dialogue_target_candidates,
    resolve_dialogue_target,
)


@dataclass(frozen=True, slots=True)
class GameMasterExecutionResult:
    actions: tuple[dict[str, Any], ...] = ()
    applied_rule_ids: tuple[str, ...] = ()
    removed_rule_ids: tuple[str, ...] = ()
    route_target_actor_id: str = ""
    route_target_character_id: str = ""
    route_instruction: str = ""
    narration: str = ""
    had_action: bool = False


class GameMasterActionExecutor:
    def __init__(self, registry: GameMasterDirectiveRegistry) -> None:
        self.registry = registry

    @staticmethod
    def _targets(participants: Any) -> tuple[DialogueTargetCandidate, ...]:
        return tuple(
            candidate
            for candidate in dialogue_target_candidates(participants)
            if candidate.actor_id
            and candidate.character_id
            and candidate.character_id.casefold() != "gamemaster"
            and candidate.is_active
            and candidate.can_speak
        )

    def apply(
        self,
        response: GameMasterResponse,
        *,
        conversation_id: str,
        participants: Any,
        turn_index: int,
        source: str,
        allow_routing: bool = True,
        allow_narration: bool = True,
    ) -> GameMasterExecutionResult:
        targets = self._targets(participants)
        applied: list[str] = []
        removed: list[str] = []
        actions: list[dict[str, Any]] = []
        route_actor = route_character = route_instruction = narration = ""
        had_action = False
        for action in response.actions:
            if action.type == "no_action":
                continue
            target = str(action.target or "").strip()
            target_item = (
                None
                if target in {"", "*"}
                else resolve_dialogue_target(target, targets)
            )
            if target and target != "*" and target_item is None:
                continue
            if action.type == "upsert_rule":
                if not target:
                    continue
                instruction = str(action.instruction or "").strip()
                if not instruction:
                    continue
                lifetime = str(action.lifetime or "scene")
                if source == "auto_corrector" and lifetime == "scene":
                    lifetime = "next_reply"
                replies = int(action.replies or 0)
                remaining = 1 if lifetime == "next_reply" else replies if lifetime == "replies" else None
                if lifetime == "replies" and remaining <= 0:
                    continue
                character = target_item.character_id if target_item else ""
                rule = GameMasterDirective(
                    directive_id="",
                    key=str(action.key or "instruction").strip() or "instruction",
                    target_scope="*" if target in {"", "*"} else character,
                    target_character_id=character,
                    instruction=instruction,
                    source=source,
                    lifetime=lifetime,
                    remaining_uses=remaining,
                    created_turn_index=max(0, int(turn_index)),
                )
                stored = self.registry.upsert(conversation_id, rule)
                if stored is None:
                    continue
                applied.append(stored.directive_id)
                actions.append(action.model_dump())
                had_action = True
            elif action.type == "remove_rule":
                rule_id = str(action.rule_id or "").strip()
                existing = next((rule for rule in self.registry.snapshot(conversation_id) if rule.directive_id == rule_id), None)
                if existing is None or (source == "auto_corrector" and existing.source == "user_director"):
                    continue
                if self.registry.remove(conversation_id, rule_id):
                    removed.append(rule_id)
                    actions.append(action.model_dump())
                    had_action = True
            elif action.type == "clear_rules":
                if not target:
                    continue
                target_character = target_item.character_id if target_item else target
                count = self.registry.clear_target(conversation_id, target_character or "*", source=None if source == "user_director" else source)
                if count:
                    actions.append(action.model_dump())
                    had_action = True
            elif action.type == "route" and allow_routing and target_item is not None:
                route_actor = target_item.actor_id
                route_character = target_item.character_id
                route_instruction = str(action.instruction or "Continue while following the active scene directive.").strip()
                actions.append(action.model_dump())
                had_action = True
            elif action.type == "narrate" and allow_narration:
                narration = str(action.instruction or action.reason or "").strip()
                if narration:
                    actions.append(action.model_dump())
                    had_action = True
        return GameMasterExecutionResult(
            actions=tuple(actions),
            applied_rule_ids=tuple(applied),
            removed_rule_ids=tuple(removed),
            route_target_actor_id=route_actor,
            route_target_character_id=route_character,
            route_instruction=route_instruction,
            narration=narration,
            had_action=had_action,
        )
