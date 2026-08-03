"""Authoritative Python routing for multi-Mita dialogue turns.

The model produces the current character's reply.  This module owns the
control-plane decision about what happens after that reply.  Unity receives
the resulting route as transport data and is limited to live validation and
execution against the current scene.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, replace
from typing import Any, Optional

from main_logger import logger
from services.contracts import (
    DialogueParticipant,
    DialogueTurnContext,
    SettingsService,
    dialogue_auto_turns_remaining,
    parse_dialogue_turn_context,
)


ROUTE_MITA_FOLLOW_UP = "mita_follow_up"
ROUTE_CONTINUE = "continue"
ROUTE_GAME_MASTER = "game_master"
ROUTE_GAME_MASTER_DIRECTIVE = "game_master_directive"
ROUTE_STOP = "stop"


@dataclass(frozen=True, slots=True)
class RoutedDialogueRoute:
    """One Python-owned transport route sent to the Unity executor."""

    route_kind: str
    event_type: str
    target_actor_id: str = ""
    target_character_id: str = ""
    input_text: str = ""
    reason: str = ""
    delay_ms: int = 650
    conversation_id: str = ""
    epoch: int = 0


@dataclass(slots=True)
class _ConversationRouterState:
    epoch: int = 0
    mita_responses_since_gm: int = 0
    consecutive_continues: int = 0


class DialogueTurnRouter:
    """Deterministic round-robin router with Python-owned settings.

    ``dialogue.auto_dialogue_enabled`` and the other settings mirrored by
    Unity are treated as diagnostics only.  The authoritative values come
    from ``SettingsService``.
    """

    _GM_TARGET_RE = re.compile(
        r"(?:^|[,\s])speaker\s*[,=:]\s*([A-Za-z][A-Za-z0-9_]*)",
        re.IGNORECASE,
    )

    def __init__(self, settings: SettingsService | Any | None = None) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._states: dict[str, _ConversationRouterState] = {}

    def _get_setting(self, key: str, default: Any = None) -> Any:
        settings = self._settings
        if settings is None:
            return default
        try:
            return settings.get(key, default)
        except Exception:
            return default

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _server_settings(self) -> dict[str, Any]:
        max_auto = self._as_int(
            self._get_setting(
                "DIALOGUE_MAX_AUTO_TURNS",
                self._get_setting("MITA_DIALOGUE_AUTO_LIMIT", 6),
            ),
            6,
        )
        max_auto = max(0, min(24, max_auto))
        gm_repeat = max(1, min(100, self._as_int(self._get_setting("GM_REPEAT", 2), 2)))
        continue_limit = self._as_int(
            self._get_setting(
                "DIALOGUE_MAX_CONTINUES",
                self._get_setting("CONTINUE_MAX_CONSECUTIVE", 3),
            ),
            3,
        )
        continue_limit = max(0, min(24, continue_limit))
        revision = self._as_int(
            getattr(self._settings, "revision", None)
            if self._settings is not None
            else 0,
            0,
        )
        if not revision and self._settings is not None:
            registry = getattr(self._settings, "registry", None)
            revision = self._as_int(getattr(registry, "revision", 0), 0)
        return {
            "auto": self._as_bool(self._get_setting("MITA_DIALOGUE_AUTO", False)),
            "max_auto": max_auto,
            "gm_on": self._as_bool(self._get_setting("GM_ON", False)),
            "gm_repeat": gm_repeat,
            "continue_limit": continue_limit,
            "revision": revision,
        }

    def authoritative_context(
        self,
        dialogue: DialogueTurnContext | dict[str, Any] | None,
        *,
        log_mismatch: bool = True,
    ) -> DialogueTurnContext | None:
        """Apply server settings to a Unity snapshot and report mirror drift."""
        context = parse_dialogue_turn_context(dialogue)
        if context is None:
            return None

        settings = self._server_settings()
        client_values = {
            "auto": getattr(context, "client_auto_dialogue_enabled", None),
            "max_auto": getattr(context, "client_auto_turn_limit", None),
            "gm_on": getattr(context, "client_gm_enabled", None),
            "gm_repeat": getattr(context, "client_gm_repeat", None),
            "revision": getattr(context, "client_settings_revision", None),
        }
        mismatches: list[str] = []
        if client_values["auto"] is not None and client_values["auto"] != settings["auto"]:
            mismatches.append(f"auto server={settings['auto']} client={client_values['auto']}")
        if client_values["max_auto"] is not None and client_values["max_auto"] != settings["max_auto"]:
            mismatches.append(f"limit server={settings['max_auto']} client={client_values['max_auto']}")
        if client_values["gm_on"] is not None and client_values["gm_on"] != settings["gm_on"]:
            mismatches.append(f"gm server={settings['gm_on']} client={client_values['gm_on']}")
        if client_values["gm_repeat"] is not None and client_values["gm_repeat"] != settings["gm_repeat"]:
            mismatches.append(f"gm_repeat server={settings['gm_repeat']} client={client_values['gm_repeat']}")
        if (
            client_values["revision"] is not None
            and settings["revision"]
            and client_values["revision"] != settings["revision"]
        ):
            mismatches.append(
                f"revision server={settings['revision']} client={client_values['revision']}"
            )
        if mismatches and log_mismatch:
            logger.warning(
                "[DialogueSettings] Client setting mismatch; using Python server values: %s",
                "; ".join(mismatches),
            )

        return replace(
            context,
            auto_dialogue_enabled=settings["auto"],
            max_auto_turns=settings["max_auto"],
        )

    @staticmethod
    def _has_structured_response(structured: Any) -> bool:
        if not isinstance(structured, dict):
            return False
        segments = structured.get("segments")
        return isinstance(segments, list) and bool(segments)

    @staticmethod
    def _eligible_participants(dialogue: DialogueTurnContext) -> list[DialogueParticipant]:
        result: list[DialogueParticipant] = []
        seen: set[str] = set()
        current = str(dialogue.responder_actor_id or "").strip()
        for participant in dialogue.participants:
            actor_id = str(participant.actor_id or "").strip()
            character_id = str(participant.character_id or "").strip()
            if not actor_id or actor_id in seen or actor_id == current:
                continue
            if character_id.casefold() == "gamemaster":
                continue
            if not bool(getattr(participant, "can_speak", False)):
                continue
            if not bool(getattr(participant, "can_hear_speaker", False)):
                continue
            if getattr(participant, "is_active", True) is False:
                continue
            seen.add(actor_id)
            result.append(participant)
        return result

    def _select_from_context(
        self,
        dialogue: DialogueTurnContext,
        *,
        reason: str = "python_round_robin",
        input_text: str = "Continue the current group conversation naturally.",
    ) -> Optional[RoutedDialogueRoute]:
        if not dialogue.conversation_id or not dialogue.responder_actor_id:
            return None
        if dialogue_auto_turns_remaining(dialogue) <= 0:
            return None

        eligible = self._eligible_participants(dialogue)
        if not eligible:
            return None

        ordered = list(dialogue.participants)
        current_index = next(
            (
                index
                for index, participant in enumerate(ordered)
                if str(participant.actor_id or "").strip() == dialogue.responder_actor_id
            ),
            -1,
        )
        spoken = {
            str(actor_id).strip()
            for actor_id in dialogue.spoken_actor_ids
            if str(actor_id).strip()
        }

        def cyclic_candidates() -> list[DialogueParticipant]:
            if not ordered:
                return eligible
            start = (current_index + 1) % len(ordered) if current_index >= 0 else 0
            by_actor = {item.actor_id: item for item in eligible}
            candidates: list[DialogueParticipant] = []
            for offset in range(len(ordered)):
                item = ordered[(start + offset) % len(ordered)]
                actor_id = str(item.actor_id or "").strip()
                selected = by_actor.get(actor_id)
                if selected is not None:
                    candidates.append(selected)
            # A malformed/reduced snapshot can contain eligible participants
            # outside the ordered list. Keep their input order as a fallback.
            candidates.extend(item for item in eligible if item not in candidates)
            return candidates

        candidates = cyclic_candidates()
        selected = next((item for item in candidates if item.actor_id not in spoken), None)
        if selected is None:
            selected = candidates[0] if candidates else None
        if selected is None:
            return None

        return RoutedDialogueRoute(
            route_kind=ROUTE_MITA_FOLLOW_UP,
            event_type="answer",
            target_actor_id=selected.actor_id,
            target_character_id=selected.character_id,
            input_text=input_text,
            reason=reason,
            conversation_id=dialogue.conversation_id,
            epoch=max(0, int(dialogue.epoch)),
        )

    def select_next_turn(
        self,
        dialogue: DialogueTurnContext | dict[str, Any] | None,
    ) -> Optional[RoutedDialogueRoute]:
        """Select one deterministic Mita follow-up, or ``None``."""
        context = self.authoritative_context(dialogue)
        if context is None:
            return None
        return self._select_from_context(context)

    def _state_for(self, conversation_id: str, epoch: int) -> _ConversationRouterState:
        state = self._states.get(conversation_id)
        if state is None or state.epoch != epoch:
            state = _ConversationRouterState(epoch=epoch)
            self._states[conversation_id] = state
        return state

    @staticmethod
    def _participant_by_character(
        dialogue: DialogueTurnContext,
        character_id: str,
    ) -> DialogueParticipant | None:
        wanted = str(character_id or "").strip().casefold()
        if not wanted or wanted == "gamemaster":
            return None
        for participant in dialogue.participants:
            if str(participant.character_id or "").strip().casefold() == wanted:
                return participant
        return None

    def _extract_gm_control(
        self,
        structured: dict[str, Any],
        dialogue: DialogueTurnContext,
    ) -> tuple[str, DialogueParticipant | None]:
        target_character = ""
        for segment in structured.get("segments", []) or []:
            if not isinstance(segment, dict):
                continue
            for intent in segment.get("intents", []) or []:
                if not isinstance(intent, dict):
                    continue
                intent_type = str(intent.get("type") or "").strip().casefold()
                payload = intent.get("payload")
                payload = payload if isinstance(payload, dict) else {}
                if intent_type in {"dialogue.stop", "dialogue.stop_chain", "dialogue.end"}:
                    return "stop", None
                if intent_type in {
                    "dialogue.send_system_message",
                    "dialogue.direct_system_message",
                }:
                    target_character = str(
                        payload.get("character") or payload.get("target") or ""
                    ).strip()
                    if target_character:
                        break
            if target_character:
                break

            for command in segment.get("commands", []) or []:
                match = self._GM_TARGET_RE.search(str(command or ""))
                if match:
                    target_character = match.group(1).strip()
                    break
            if target_character:
                break

        return target_character, self._participant_by_character(dialogue, target_character)

    def _route_after_game_master(
        self,
        context: DialogueTurnContext,
        structured: dict[str, Any],
    ) -> Optional[RoutedDialogueRoute]:
        target_character, target = self._extract_gm_control(structured, context)
        if target_character == "stop":
            return RoutedDialogueRoute(
                route_kind=ROUTE_STOP,
                event_type="stop",
                reason="game_master_stop",
                conversation_id=context.conversation_id,
                epoch=max(0, int(context.epoch)),
            )

        if target is not None:
            eligible_ids = {
                item.actor_id for item in self._eligible_participants(
                    replace(
                        context,
                        responder_actor_id="",
                    )
                )
            }
            if target.actor_id in eligible_ids and dialogue_auto_turns_remaining(context) > 0:
                return RoutedDialogueRoute(
                    route_kind=ROUTE_GAME_MASTER_DIRECTIVE,
                    event_type="answer",
                    target_actor_id=target.actor_id,
                    target_character_id=target.character_id,
                    input_text="Carry out the current GameMaster directive naturally.",
                    reason="game_master_directive",
                    conversation_id=context.conversation_id,
                    epoch=max(0, int(context.epoch)),
                )

        return self._select_from_context(
            context,
            reason="python_round_robin_after_game_master",
            input_text="Continue the current conversation after the GameMaster directive.",
        )

    def route_after_response(
        self,
        dialogue: DialogueTurnContext | dict[str, Any] | None,
        *,
        structured: dict[str, Any] | None,
        character_id: str,
        event_type: str,
    ) -> Optional[RoutedDialogueRoute]:
        """Route one successful structured response through Python control state."""
        context = self.authoritative_context(dialogue)
        if context is None or not self._has_structured_response(structured):
            return None
        if not context.conversation_id or context.epoch < 0:
            return None

        event = str(event_type or "").strip().lower()
        character = str(character_id or "").strip()
        is_game_master = character.casefold() == "gamemaster" or event == "game_master_observe"

        with self._lock:
            state = self._state_for(context.conversation_id, int(context.epoch))
            if context.speaker_actor_id.casefold() == "player":
                state.mita_responses_since_gm = 0
                state.consecutive_continues = 0
            elif event != "continue":
                state.consecutive_continues = 0

            if is_game_master:
                return self._route_after_game_master(context, structured or {})

            if event not in {"answer", "chat", "continue"}:
                return None

            settings = self._server_settings()
            if not settings["gm_on"]:
                state.mita_responses_since_gm = 0
            else:
                state.mita_responses_since_gm += 1
                if state.mita_responses_since_gm >= settings["gm_repeat"]:
                    state.mita_responses_since_gm = 0
                    return RoutedDialogueRoute(
                        route_kind=ROUTE_GAME_MASTER,
                        event_type="game_master_observe",
                        target_character_id="GameMaster",
                        input_text=(
                            "Review the active conversation and issue one Python-validated "
                            "GameMaster directive when intervention is needed."
                        ),
                        reason="game_master_cadence",
                        conversation_id=context.conversation_id,
                        epoch=max(0, int(context.epoch)),
                    )

            return self._select_from_context(context)

    def authorize_continue(
        self,
        dialogue: DialogueTurnContext | dict[str, Any] | None,
        *,
        character_id: str,
    ) -> bool:
        """Validate and reserve one central Python ``continue`` request."""
        context = self.authoritative_context(dialogue)
        if context is None or not context.conversation_id or not context.responder_actor_id:
            return False
        if context.epoch <= 0:
            return False
        current = next(
            (
                item
                for item in context.participants
                if item.actor_id == context.responder_actor_id
            ),
            None,
        )
        if current is None or str(current.character_id).casefold() != str(character_id or "").casefold():
            return False
        if not current.can_speak:
            return False

        with self._lock:
            state = self._state_for(context.conversation_id, int(context.epoch))
            limit = self._server_settings()["continue_limit"]
            if limit <= 0 or state.consecutive_continues >= limit:
                logger.warning(
                    "[DialogueRouter] Continue rejected for %s: central continuation limit reached.",
                    context.conversation_id,
                )
                return False
            state.consecutive_continues += 1
            return True

    def reset_conversation(self, conversation_id: str) -> None:
        with self._lock:
            self._states.pop(str(conversation_id or ""), None)


def route_to_transport(route: RoutedDialogueRoute | None) -> dict[str, Any] | None:
    if route is None:
        return None
    return {
        "route_kind": route.route_kind,
        "event_type": route.event_type,
        "target_actor_id": route.target_actor_id,
        "target_character_id": route.target_character_id,
        "input_text": route.input_text,
        "reason": route.reason,
        "delay_ms": max(0, min(5000, int(route.delay_ms))),
        "conversation_id": route.conversation_id,
        "epoch": max(0, int(route.epoch)),
    }


_DEFAULT_ROUTER: DialogueTurnRouter | None = None
_DEFAULT_ROUTER_LOCK = threading.Lock()


def get_dialogue_turn_router(settings: SettingsService | Any | None = None) -> DialogueTurnRouter:
    global _DEFAULT_ROUTER
    with _DEFAULT_ROUTER_LOCK:
        if _DEFAULT_ROUTER is None or settings is not None and _DEFAULT_ROUTER._settings is not settings:
            _DEFAULT_ROUTER = DialogueTurnRouter(settings)
        return _DEFAULT_ROUTER


__all__ = [
    "DialogueTurnRouter",
    "RoutedDialogueRoute",
    "ROUTE_MITA_FOLLOW_UP",
    "ROUTE_CONTINUE",
    "ROUTE_GAME_MASTER",
    "ROUTE_GAME_MASTER_DIRECTIVE",
    "ROUTE_STOP",
    "get_dialogue_turn_router",
    "route_to_transport",
]
