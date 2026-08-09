from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from typing import Any

from core.events import Events, get_event_bus
from core.services import services, use
from services.contracts import (
    CharacterRegistry,
    DialogueParticipant,
    DialogueRuntimeSource,
    DialogueTurnContext,
    SandboxDialogueConfig,
    SandboxDialogueUiState,
    TaskService,
)
from services.dialogue_runtime_state import get_dialogue_runtime_state_service
from services.dialogue_turn_router import DialogueTurnRouter


class _SandboxRouterSettings:
    """Settings adapter owned by one sandbox session."""

    def __init__(self, config: SandboxDialogueConfig) -> None:
        self._values = {
            "MITA_DIALOGUE_AUTO": bool(config.auto_dialogue_enabled),
            "DIALOGUE_MAX_AUTO_TURNS": int(config.max_auto_turns),
            "DIALOGUE_AUTO_TURN_COUNT_MODE": str(config.auto_turn_count_mode or "fixed"),
            "DIALOGUE_AUTO_TURNS_PER_PARTICIPANT": int(config.auto_turns_per_participant),
            "DIALOGUE_MAX_CONTINUES": int(config.max_consecutive_continues),
            "GM_ON": bool(config.game_master_enabled),
            "GM_REPEAT": int(config.gm_repeat),
        }
        self.revision = 1

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


class SandboxDialogueController:
    """Debug executor for the production Python protocol-v3 route contract."""

    def __init__(self) -> None:
        self._bus = get_event_bus()
        self._runtime_state = get_dialogue_runtime_state_service()
        self._lock = threading.RLock()
        self._session_id = ""
        self._config = SandboxDialogueConfig()
        self._router: DialogueTurnRouter | None = None
        self._participants: tuple[DialogueParticipant, ...] = ()
        self._conversation_id = ""
        self._epoch = 0
        self._turn_index = 0
        self._auto_turns_used = 0
        self._speaker_actor_id = "player"
        self._responder_actor_id = ""
        self._spoken_actor_ids: list[str] = []
        self._pending_task_uid = ""
        self._pending_route: dict[str, Any] | None = None
        self._consumed_route_ids: set[str] = set()
        self._active = False
        self._ui_status_code = "inactive"
        self._ui_status_detail = ""
        self._bus.subscribe(Events.Task.TASK_STATUS_CHANGED, self._on_task_status, weak=False)

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def session_id(self) -> str:
        with self._lock:
            return self._session_id

    def ui_state(self) -> SandboxDialogueUiState:
        """Return a stable snapshot for UI consumers without exposing internals."""
        with self._lock:
            pending_route = self._pending_route if isinstance(self._pending_route, dict) else {}
            return SandboxDialogueUiState(
                active=bool(self._active),
                session_id=self._session_id if self._active else "",
                busy=bool(self._pending_task_uid),
                manual_step_mode=bool(self._config.manual_step_mode),
                auto_dialogue_enabled=bool(self._config.auto_dialogue_enabled),
                has_pending_route=bool(pending_route),
                pending_route_kind=str(pending_route.get("route_kind") or ""),
                pending_target_actor_id=str(pending_route.get("target_actor_id") or ""),
                status_code=self._ui_status_code if self._active else "inactive",
                status_detail=self._ui_status_detail if self._active else "",
            )
    def start_session(self, config: SandboxDialogueConfig | None = None) -> bool:
        current = self._runtime_state.snapshot()
        if current.source is DialogueRuntimeSource.UNITY:
            return False
        selected = config or self._default_config()
        seen_character_ids: set[str] = set()
        normalized_character_ids: list[str] = []
        for value in selected.participant_character_ids:
            item = str(value).strip()
            if item and item not in seen_character_ids:
                seen_character_ids.add(item)
                normalized_character_ids.append(item)
        character_ids = tuple(normalized_character_ids)
        if len(character_ids) < 2:
            return False
        initial_character_id = str(selected.initial_character_id or "").strip() or character_ids[0]
        if initial_character_id not in character_ids:
            return False
        with self._lock:
            self.stop_session()
            self._session_id = uuid.uuid4().hex
            self._config = replace(selected, participant_character_ids=character_ids)
            self._router = DialogueTurnRouter(_SandboxRouterSettings(self._config))
            self._participants = tuple(
                DialogueParticipant(
                    actor_id=f"sandbox:{character_id}:0",
                    character_id=character_id,
                    display_name=self._display_name(character_id),
                )
                for character_id in character_ids
            )
            self._conversation_id = f"sandbox:{self._session_id}"
            self._epoch = 1
            self._turn_index = 0
            self._auto_turns_used = 0
            self._speaker_actor_id = "player"
            self._responder_actor_id = self._actor_id(initial_character_id)
            self._spoken_actor_ids = []
            self._pending_task_uid = ""
            self._pending_route = None
            self._consumed_route_ids.clear()
            self._active = True
            self._ui_status_code = "ready"
            self._ui_status_detail = ""
            context = self._build_context()
        self._runtime_state.update_from_context(
            context,
            DialogueRuntimeSource.SANDBOX,
            game_master_enabled=self._config.game_master_enabled,
        )
        return True

    def stop_session(self) -> None:
        with self._lock:
            conversation_id = self._conversation_id
            self._active = False
            self._pending_task_uid = ""
            self._pending_route = None
            self._conversation_id = ""
            self._ui_status_code = "inactive"
            self._ui_status_detail = ""
            self._consumed_route_ids.clear()
            router = self._router
            self._router = None
        if router is not None and conversation_id:
            router.reset_conversation(conversation_id)
        self._runtime_state.reset(DialogueRuntimeSource.SANDBOX)

    def reset_session(self) -> None:
        self.stop_session()

    def send_player_message(self, text: str, image_data: list[bytes] | None = None) -> bool:
        message = str(text or "").strip()
        with self._lock:
            if not self._active or not message or self._pending_task_uid:
                return False
            self._begin_player_turn_locked()
            target = self._responder_actor_id
            character_id = self._character_id_for_actor(target)
            context = self._build_context()
        return self._emit_request(
            user_input=message,
            character_id=character_id,
            sender="Player",
            context=context,
            image_data=image_data or [],
            event_type="chat",
        )

    def step_once(self) -> bool:
        with self._lock:
            if (
                not self._active
                or self._pending_task_uid
                or not self._config.manual_step_mode
                or not self._pending_route
            ):
                return False
            route = dict(self._pending_route)
        return self.execute_route(route)

    def _emit_request(
        self,
        *,
        user_input: str,
        character_id: str,
        sender: str,
        context: dict[str, Any],
        image_data: list[bytes],
        event_type: str,
    ) -> bool:
        task_service = services().get_optional(TaskService)
        if task_service is None:
            with self._lock:
                self._ui_status_code = "task_failed"
                self._ui_status_detail = "The sandbox task service is unavailable."
            return False
        task = task_service.create_task(
            "sandbox_dialogue",
            {"sandbox_session_id": self._session_id},
        )
        with self._lock:
            if not self._active:
                return False
            self._pending_task_uid = str(task.uid)
            self._ui_status_code = "waiting_model"
            target = character_id or "the model"
            self._ui_status_detail = f"Waiting for {target}..."
            router = self._router
        self._bus.emit(
            Events.Chat.SEND_MESSAGE,
            {
                "task_uid": task.uid,
                "user_input": user_input,
                "image_data": image_data,
                "character_id": character_id,
                "sender": sender,
                "participants": [item.character_id for item in self._participants],
                "event_type": event_type,
                "dialogue": context,
                "dialogue_source": DialogueRuntimeSource.SANDBOX.value,
                "_dialogue_router": router,
                "gm_instruction_override": (
                    self._config.gm_instruction
                    if character_id.casefold() == "gamemaster"
                    else None
                ),
            },
        )
        return True

    def _on_task_status(self, event: Any) -> None:
        task = (getattr(event, "data", None) or {}).get("task")
        if task is None:
            return
        with self._lock:
            if not self._active or str(task.uid) != self._pending_task_uid:
                return
            status = str(
                getattr(getattr(task, "status", None), "value", getattr(task, "status", ""))
                or ""
            ).strip().upper()
            if status in {"PENDING", "QUEUED", "RUNNING", "STARTED", "VOICING"}:
                self._ui_status_code = "waiting_model"
                return

            self._pending_task_uid = ""
            scope = {
                "source": DialogueRuntimeSource.SANDBOX,
                "conversation_id": self._conversation_id,
                "epoch": self._epoch,
                "source_turn_index": self._turn_index,
            }
            if status not in {"SUCCESS", "COMPLETED"}:
                self._pending_route = None
                self._ui_status_code = "task_failed"
                self._ui_status_detail = "The model response could not be completed."
                route = None
                should_clear = True
            else:
                result = task.result if isinstance(task.result, dict) else {}
                routes = result.get("next_turns") or []
                route = routes[0] if routes else None
                if self._config.manual_step_mode and isinstance(route, dict):
                    self._pending_route = dict(route)
                    self._ui_status_code = "manual_route_ready"
                    target = str(route.get("target_character_id") or route.get("target_actor_id") or "").strip()
                    self._ui_status_detail = f"Next turn is ready: {target}" if target else "Next turn is ready."
                    return
                self._pending_route = None
                if route is None:
                    if not bool(result.get("control_plane_trusted", True)):
                        self._ui_status_code = "route_rejected"
                        self._ui_status_detail = "The model response could not authorize automatic routing."
                    elif not self._config.auto_dialogue_enabled:
                        self._ui_status_code = "auto_disabled"
                        self._ui_status_detail = "Automatic dialogue is disabled."
                    elif self._auto_turns_used >= self._effective_auto_turn_limit_locked():
                        self._ui_status_code = "budget_exhausted"
                        limit = self._effective_auto_turn_limit_locked()
                        self._ui_status_detail = f"Automatic dialogue finished: {self._auto_turns_used}/{limit} turns used."
                    else:
                        self._ui_status_code = "no_next_route"
                        self._ui_status_detail = "No additional turn requested."
                should_clear = route is None

        if route is not None:
            with self._lock:
                self._ui_status_code = "automatic_running"
                self._ui_status_detail = ""
            if not self.execute_route(route):
                with self._lock:
                    self._ui_status_code = "route_rejected"
                    self._ui_status_detail = "The next route was rejected by the active session."
                self._runtime_state.clear_pending_route(**scope)
        elif should_clear:
            self._runtime_state.clear_pending_route(**scope)

    def execute_route(self, route: dict[str, Any]) -> bool:
        if not isinstance(route, dict):
            return False
        with self._lock:
            if not self._active:
                return False
            try:
                route_epoch = int(route.get("epoch", 0))
                source_turn_index = int(route.get("source_turn_index", -1))
            except (TypeError, ValueError):
                return False
            if str(route.get("conversation_id") or "") != self._conversation_id:
                return False
            if route_epoch != self._epoch or source_turn_index != self._turn_index:
                return False

            route_id = str(route.get("route_id") or "").strip()
            if not route_id or route_id in self._consumed_route_ids:
                return False
            route_kind = str(route.get("route_kind") or "").strip().lower()

            if route_kind == "stop":
                self._consumed_route_ids.add(route_id)
                self._active = False
                self._ui_status_code = "inactive"
                self._ui_status_detail = ""
                self._pending_task_uid = ""
                self._pending_route = None
                self._runtime_state.reset(DialogueRuntimeSource.SANDBOX)
                return True

            if route_kind not in {
                "continue",
                "mita_follow_up",
                "game_master",
                "game_master_directive",
            }:
                return False
            if not self._config.auto_dialogue_enabled:
                return False
            if self._auto_turns_used >= self._effective_auto_turn_limit_locked():
                return False
            if route_kind == "continue":
                if not bool(route.get("continue_route_reserved")):
                    return False
                if str(route.get("target_actor_id") or "").strip() != self._responder_actor_id:
                    return False

            target_actor = str(route.get("target_actor_id") or "").strip()
            target_character = ""
            target_participant = None
            if route_kind == "game_master":
                target_actor = "sandbox:GameMaster:0"
                provided_character = str(route.get("target_character_id") or "").strip()
                if provided_character and provided_character.casefold() != "gamemaster":
                    return False
                target_character = "GameMaster"
            else:
                target_participant = next(
                    (item for item in self._participants if item.actor_id == target_actor),
                    None,
                )
                if (
                    target_participant is None
                    or not target_participant.is_active
                    or not target_participant.can_speak
                ):
                    return False
                provided_character = str(route.get("target_character_id") or "").strip()
                if (
                    provided_character
                    and provided_character.casefold() != target_participant.character_id.casefold()
                ):
                    return False
                target_character = target_participant.character_id

            input_text = str(route.get("input_text") or "").strip()
            if not target_actor or not input_text:
                return False

            route_id = str(route_id)
            self._consumed_route_ids.add(route_id)
            source_actor = self._responder_actor_id
            previous_turn_index = self._turn_index
            previous_auto_turns = self._auto_turns_used
            previous_speaker_actor = self._speaker_actor_id
            previous_responder_actor = self._responder_actor_id
            previous_spoken_count = len(self._spoken_actor_ids)
            previous_pending_route = self._pending_route
            self._pending_route = None
            self._turn_index += 1
            self._auto_turns_used += 1
            self._speaker_actor_id = source_actor
            self._responder_actor_id = target_actor
            self._spoken_actor_ids.append(target_actor)
            context = self._build_context()

        self._runtime_state.update_from_context(
            context,
            DialogueRuntimeSource.SANDBOX,
            game_master_enabled=self._config.game_master_enabled,
        )
        accepted = self._emit_request(
            user_input=input_text,
            character_id=target_character,
            sender=self._character_id_for_actor(source_actor) or "Player",
            context=context,
            image_data=[],
            event_type=str(route.get("event_type") or "answer"),
        )
        if accepted:
            return True

        with self._lock:
            self._turn_index = previous_turn_index
            self._auto_turns_used = previous_auto_turns
            self._speaker_actor_id = previous_speaker_actor
            self._responder_actor_id = previous_responder_actor
            self._pending_route = previous_pending_route
            del self._spoken_actor_ids[previous_spoken_count:]
            self._consumed_route_ids.discard(route_id)
            rollback_context = self._build_context()
        self._runtime_state.update_from_context(
            rollback_context,
            DialogueRuntimeSource.SANDBOX,
            game_master_enabled=self._config.game_master_enabled,
        )
        return False

    def _begin_player_turn_locked(self) -> None:
        self._epoch += 1
        self._turn_index += 1
        self._auto_turns_used = 0
        self._speaker_actor_id = "player"
        self._spoken_actor_ids.clear()
        self._consumed_route_ids.clear()
        self._pending_route = None
        self._ui_status_code = "waiting_model"
        self._ui_status_detail = ""
        if self._router is not None and self._conversation_id:
            self._router.reset_conversation(self._conversation_id)

    def _effective_auto_turn_limit_locked(self) -> int:
        mode = str(self._config.auto_turn_count_mode or "fixed").strip().lower()
        if mode == "per_participant":
            participant_count = sum(
                1
                for participant in self._participants
                if (
                    participant.character_id.casefold() != "gamemaster"
                    and participant.is_active
                    and participant.can_speak
                )
            )
            turns_per_participant = max(
                1,
                min(24, int(self._config.auto_turns_per_participant)),
            )
            return min(24, participant_count * turns_per_participant)
        return max(0, int(self._config.max_auto_turns))

    def _build_context(self) -> dict[str, Any]:
        return {
            "conversation_id": self._conversation_id,
            "epoch": self._epoch,
            "turn_index": self._turn_index,
            "speaker_actor_id": self._speaker_actor_id,
            "responder_actor_id": self._responder_actor_id,
            "auto_dialogue_enabled": self._config.auto_dialogue_enabled,
            "auto_turns_since_player": self._auto_turns_used,
            "max_auto_turns": self._effective_auto_turn_limit_locked(),
            "spoken_actor_ids": list(self._spoken_actor_ids),
            "participants": [item.__dict__ if hasattr(item, "__dict__") else {
                "actor_id": item.actor_id,
                "character_id": item.character_id,
                "display_name": item.display_name,
                "can_hear_player": item.can_hear_player,
                "can_hear_speaker": item.can_hear_speaker,
                "can_speak": item.can_speak,
                "is_active": item.is_active,
            } for item in self._participants],
        }

    def _default_config(self) -> SandboxDialogueConfig:
        registry = services().get_optional(CharacterRegistry)
        ids = tuple(str(item) for item in (registry.all_ids() if registry else ()) if str(item).strip())
        return SandboxDialogueConfig(participant_character_ids=ids[:3])

    def _display_name(self, character_id: str) -> str:
        registry = services().get_optional(CharacterRegistry)
        if registry is None:
            return character_id
        return str(registry.name_of(character_id) or character_id)

    def _actor_id(self, character_id: str) -> str:
        return f"sandbox:{character_id}:0"

    def _character_id_for_actor(self, actor_id: str) -> str:
        for participant in self._participants:
            if participant.actor_id == actor_id:
                return participant.character_id
        return "GameMaster" if "GameMaster" in actor_id else ""


_CONTROLLER: SandboxDialogueController | None = None
_CONTROLLER_LOCK = threading.RLock()


def get_sandbox_dialogue_controller() -> SandboxDialogueController:
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        if _CONTROLLER is None:
            _CONTROLLER = SandboxDialogueController()
        return _CONTROLLER
