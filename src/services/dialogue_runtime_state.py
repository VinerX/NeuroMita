from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Any

from core.events import Events, get_event_bus
from services.contracts import (
    DialogueRuntimeSnapshot,
    DialogueRuntimeSource,
    DialogueTurnContext,
    parse_dialogue_turn_context,
)


class DialogueRuntimeStateService:
    """Owns only ephemeral UI observation state, never routing authority."""

    def __init__(self, event_bus=None) -> None:
        self._bus = event_bus or get_event_bus()
        self._lock = RLock()
        self._snapshot = DialogueRuntimeSnapshot()
        self._bus.subscribe(
            Events.Server.CLIENT_DISCONNECTED,
            self._on_client_disconnected,
            weak=False,
        )

    def snapshot(self) -> DialogueRuntimeSnapshot:
        with self._lock:
            return self._snapshot

    def update_from_context(
        self,
        context: DialogueTurnContext | dict[str, Any] | None,
        source: DialogueRuntimeSource | str,
        *,
        game_master_enabled: bool | None = None,
    ) -> DialogueRuntimeSnapshot:
        normalized = parse_dialogue_turn_context(context)
        source_value = self._source(source)
        if normalized is None or not normalized.conversation_id:
            return self.snapshot()
        with self._lock:
            if (
                source_value is DialogueRuntimeSource.SANDBOX
                and self._snapshot.source is DialogueRuntimeSource.UNITY
            ):
                return self._snapshot
            participants = tuple(
                self._participant_view(item) for item in normalized.participants
            )
            self._snapshot = DialogueRuntimeSnapshot(
                source=source_value,
                conversation_id=normalized.conversation_id,
                epoch=int(normalized.epoch),
                turn_index=int(normalized.turn_index),
                auto_dialogue_enabled=bool(normalized.auto_dialogue_enabled),
                auto_turns_used=int(normalized.auto_turns_since_player),
                auto_turns_max=int(normalized.max_auto_turns),
                speaker_actor_id=normalized.speaker_actor_id,
                responder_actor_id=normalized.responder_actor_id,
                participants=participants,
                game_master_enabled=(
                    bool(game_master_enabled)
                    if game_master_enabled is not None
                    else self._snapshot.game_master_enabled
                ),
            )
            snapshot = self._snapshot
        self._publish(snapshot)
        return snapshot

    def set_pending_route(
        self,
        route: Any,
        *,
        control_plane_trusted: bool = False,
    ) -> DialogueRuntimeSnapshot:
        with self._lock:
            if route is None:
                self._snapshot = replace(
                    self._snapshot,
                    pending_route_kind="",
                    pending_route_target_actor_id="",
                    pending_route_id="",
                    pending_route_source_turn_index=0,
                    control_plane_trusted=bool(control_plane_trusted),
                )
            else:
                get = route.get if isinstance(route, dict) else lambda key, default=None: getattr(route, key, default)
                self._snapshot = replace(
                    self._snapshot,
                    pending_route_kind=str(get("route_kind", "") or ""),
                    pending_route_target_actor_id=str(get("target_actor_id", "") or ""),
                    pending_route_id=str(get("route_id", "") or ""),
                    pending_route_source_turn_index=int(get("source_turn_index", 0) or 0),
                    control_plane_trusted=bool(control_plane_trusted),
                )
            snapshot = self._snapshot
        self._publish(snapshot)
        return snapshot

    def clear_pending_route(self) -> DialogueRuntimeSnapshot:
        return self.set_pending_route(None)

    def reset(self, source: DialogueRuntimeSource | str | None = None) -> DialogueRuntimeSnapshot:
        source_value = self._source(source) if source is not None else None
        with self._lock:
            if source_value is not None and self._snapshot.source is not source_value:
                return self._snapshot
            self._snapshot = DialogueRuntimeSnapshot()
            snapshot = self._snapshot
        self._publish(snapshot)
        return snapshot

    def _on_client_disconnected(self, _event: Any) -> None:
        self.reset(DialogueRuntimeSource.UNITY)

    @staticmethod
    def _source(value: DialogueRuntimeSource | str | None) -> DialogueRuntimeSource:
        if isinstance(value, DialogueRuntimeSource):
            return value
        normalized = str(value or "none").strip().lower()
        try:
            return DialogueRuntimeSource(normalized)
        except ValueError:
            return DialogueRuntimeSource.NONE

    @staticmethod
    def _participant_view(item) -> Any:
        from services.contracts import DialogueParticipantView

        return DialogueParticipantView(
            actor_id=str(item.actor_id or ""),
            character_id=str(item.character_id or ""),
            display_name=str(item.display_name or item.character_id or ""),
            is_active=bool(item.is_active),
            can_speak=bool(item.can_speak),
            can_hear_speaker=bool(item.can_hear_speaker),
        )

    def _publish(self, snapshot: DialogueRuntimeSnapshot) -> None:
        self._bus.emit(Events.Dialogue.RUNTIME_STATE_CHANGED, snapshot)


_RUNTIME_STATE: DialogueRuntimeStateService | None = None
_RUNTIME_LOCK = RLock()


def get_dialogue_runtime_state_service() -> DialogueRuntimeStateService:
    global _RUNTIME_STATE
    with _RUNTIME_LOCK:
        if _RUNTIME_STATE is None:
            _RUNTIME_STATE = DialogueRuntimeStateService()
        return _RUNTIME_STATE
