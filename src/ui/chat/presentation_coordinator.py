from __future__ import annotations

import copy
import uuid
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ChatRenderCommand:
    role: str
    content: Any
    character_id: str = ""
    message_id: str = ""
    message_time: str = ""
    structured_data: Any = None
    sample_id: str = ""
    context_snapshot_id: str = ""
    insert_at_start: bool = False

    def clone(self) -> "ChatRenderCommand":
        return ChatRenderCommand(
            role=self.role,
            content=copy.deepcopy(self.content),
            character_id=self.character_id,
            message_id=self.message_id,
            message_time=self.message_time,
            structured_data=copy.deepcopy(self.structured_data),
            sample_id=self.sample_id,
            context_snapshot_id=self.context_snapshot_id,
            insert_at_start=self.insert_at_start,
        )


@dataclass(frozen=True, slots=True)
class HistoryLoadTicket:
    request_id: str
    character_id: str
    start_revision: int


@dataclass(frozen=True, slots=True)
class HistoryProjectionPlan:
    accepted: bool
    replay: tuple[ChatRenderCommand, ...] = ()
    retry_after_stream: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class StreamPresentationPhase:
    role: str
    speaker_name: str
    text: str


@dataclass(frozen=True, slots=True)
class StreamPresentationReplay:
    stream_id: str
    character_id: str
    phases: tuple[StreamPresentationPhase, ...]


@dataclass(slots=True)
class _StableLiveMessage:
    commands: list[tuple[int, ChatRenderCommand]] = field(default_factory=list)
    persisted_revision: int | None = None


@dataclass(slots=True)
class _StreamPhaseBuffer:
    role: str
    speaker_name: str = ""
    chunks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _ActiveStream:
    character_id: str = ""
    character_key: str = ""
    phases: list[_StreamPhaseBuffer] = field(default_factory=list)
    mounted: bool = False


class ChatPresentationCoordinator:
    """Reconciles persisted history snapshots with live chat presentation events.

    History and live UI are independent projections of the same conversation.  A
    history refresh therefore must not treat the widget tree as authoritative and
    destructively replace messages that arrived after (or have not yet reached)
    the snapshot.  Stable live messages are tracked by message_id until persistence
    is observed.  Snapshot ids are also remembered so a late live event for a row
    that the snapshot already rendered is suppressed instead of duplicated.
    """

    def __init__(self, *, max_stable_messages: int = 256, max_ephemeral_events: int = 256) -> None:
        self._revision = 0
        self._max_stable_messages = max(16, int(max_stable_messages))
        self._stable: OrderedDict[tuple[str, str], _StableLiveMessage] = OrderedDict()
        self._persisted_acks: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._ephemeral: deque[tuple[int, ChatRenderCommand]] = deque(
            maxlen=max(16, int(max_ephemeral_events))
        )
        self._history_projected: dict[tuple[str, str], set[tuple[Any, ...]]] = {}
        self._active_history_load: HistoryLoadTicket | None = None
        self._active_streams: dict[str, _ActiveStream] = {}
        self._reload_after_stream: set[str] = set()

    @staticmethod
    def _character_key(character_id: str | None) -> str:
        return str(character_id or "").strip().casefold()

    @staticmethod
    def _message_key(message_id: str | None) -> str:
        return str(message_id or "").strip()

    @staticmethod
    def _content_components(content: Any) -> tuple[tuple[str, str], ...]:
        if isinstance(content, str):
            return (("text", content.strip()),)
        if isinstance(content, list):
            visible: list[tuple[str, str]] = []
            for item in content:
                if not isinstance(item, dict):
                    visible.append(("value", str(item)))
                    continue
                item_type = str(item.get("type") or "")
                if item_type == "meta":
                    continue
                if item_type == "text":
                    visible.append(("text", str(item.get("text") or item.get("content") or "").strip()))
                elif item_type == "image_url":
                    image_url = item.get("image_url")
                    url = image_url.get("url") if isinstance(image_url, dict) else ""
                    visible.append(("image_url", str(url or "")))
                else:
                    visible.append((item_type or "item", repr(sorted(item.items()))))
            return tuple(visible)
        return (("value", repr(content)),)

    @classmethod
    def _content_signature(cls, role: str, content: Any) -> tuple[Any, ...]:
        role_key = str(role or "").strip().casefold()
        return (role_key, cls._content_components(content))

    @staticmethod
    def _signature_covers(snapshot_signature: tuple[Any, ...], live_signature: tuple[Any, ...]) -> bool:
        if not snapshot_signature or not live_signature:
            return snapshot_signature == live_signature
        if snapshot_signature[0] != live_signature[0]:
            return False
        snapshot_components = Counter(snapshot_signature[1])
        live_components = Counter(live_signature[1])
        return all(snapshot_components[component] >= count for component, count in live_components.items())

    @classmethod
    def _is_projected(
        cls,
        projected_signatures: Iterable[tuple[Any, ...]],
        command: ChatRenderCommand,
    ) -> bool:
        live_signature = cls._content_signature(command.role, command.content)
        return any(
            cls._signature_covers(snapshot_signature, live_signature)
            for snapshot_signature in projected_signatures
        )

    def _next_revision(self) -> int:
        self._revision += 1
        return self._revision

    @property
    def has_active_streams(self) -> bool:
        return bool(self._active_streams)

    @classmethod
    def belongs_to_surface(cls, character_id: str | None, current_character_id: str | None) -> bool:
        """Return whether an event belongs to the currently projected chat surface.

        Empty ids are intentionally treated as unscoped for compatibility with
        legacy/global UI events. Stable conversation events should carry a
        character id, so a concrete mismatch is never allowed to leak into the
        active character's widget tree.
        """
        event_key = cls._character_key(character_id)
        current_key = cls._character_key(current_character_id)
        return not (event_key and current_key and event_key != current_key)

    def record_live(
        self,
        command: ChatRenderCommand,
        *,
        current_character_id: str | None = None,
    ) -> bool:
        """Record a live command and decide whether the active widget should render it.

        Inactive-character events are still retained for reconciliation. This is
        important when a response completes after the user switches characters:
        it must not appear in the new chat, but it still has to be available for
        replay if persistence/history has not caught up when the user switches
        back.
        """
        revision = self._next_revision()
        command = command.clone()
        message_id = self._message_key(command.message_id)
        if not message_id:
            self._ephemeral.append((revision, command))
            return self.belongs_to_surface(command.character_id, current_character_id)

        key = (self._character_key(command.character_id), message_id)
        projected_signatures = self._history_projected.get(key)
        if projected_signatures and self._is_projected(projected_signatures, command):
            return False

        state = self._stable.get(key)
        if state is None:
            state = _StableLiveMessage(persisted_revision=self._persisted_acks.get(key))
            self._stable[key] = state
        else:
            self._stable.move_to_end(key)

        if state.commands and state.commands[-1][1] == command:
            return False

        state.commands.append((revision, command))
        while len(self._stable) > self._max_stable_messages:
            self._stable.popitem(last=False)
        return self.belongs_to_surface(command.character_id, current_character_id)

    def acknowledge_persisted(self, *, message_ids: Iterable[str], character_ids: Iterable[str]) -> None:
        ids = {self._message_key(value) for value in message_ids if self._message_key(value)}
        if not ids:
            return
        character_keys = {
            self._character_key(value)
            for value in character_ids
            if self._character_key(value)
        }
        revision = self._next_revision()

        target_keys: list[tuple[str, str]] = []
        if character_keys:
            target_keys.extend(
                (character_key, message_id)
                for character_key in character_keys
                for message_id in ids
            )
        else:
            target_keys.extend(key for key in self._stable if key[1] in ids)

        for key in target_keys:
            self._persisted_acks[key] = revision
            self._persisted_acks.move_to_end(key)
            state = self._stable.get(key)
            if state is not None:
                state.persisted_revision = revision

        while len(self._persisted_acks) > self._max_stable_messages * 2:
            self._persisted_acks.popitem(last=False)

    def begin_history_load(self, character_id: str) -> HistoryLoadTicket:
        ticket = HistoryLoadTicket(
            request_id=uuid.uuid4().hex,
            character_id=str(character_id or "").strip(),
            start_revision=self._revision,
        )
        self._active_history_load = ticket
        return ticket

    def cancel_history_load(self, request_id: str | None = None) -> None:
        ticket = self._active_history_load
        if ticket is None:
            return
        if request_id and ticket.request_id != str(request_id):
            return
        self._active_history_load = None

    def reset(self) -> None:
        self._stable.clear()
        self._persisted_acks.clear()
        self._ephemeral.clear()
        self._history_projected.clear()
        self._active_history_load = None
        self._active_streams.clear()
        self._reload_after_stream.clear()

    @staticmethod
    def _stream_key(stream_id: str | None) -> str:
        return str(stream_id or "default")

    def _stream_state(
        self,
        stream_id: str,
        *,
        character_id: str = "",
    ) -> _ActiveStream:
        stream_key = self._stream_key(stream_id)
        incoming_character_id = str(character_id or "").strip()
        incoming_character_key = self._character_key(incoming_character_id)
        state = self._active_streams.get(stream_key)
        if state is None or (
            incoming_character_key
            and state.character_key
            and state.character_key != incoming_character_key
        ):
            state = _ActiveStream(
                character_id=incoming_character_id,
                character_key=incoming_character_key,
            )
            self._active_streams[stream_key] = state
        elif incoming_character_key:
            state.character_id = incoming_character_id
            if not state.character_key:
                state.character_key = incoming_character_key
        return state

    @staticmethod
    def _prepare_stream_phase(
        state: _ActiveStream,
        *,
        role: str,
        speaker_name: str = "",
    ) -> None:
        role_key = str(role or "assistant").strip() or "assistant"
        speaker = str(speaker_name or "").strip()
        if state.phases and state.phases[-1].role == role_key:
            if speaker and not state.phases[-1].speaker_name:
                state.phases[-1].speaker_name = speaker
            return
        state.phases.append(_StreamPhaseBuffer(role=role_key, speaker_name=speaker))

    def begin_stream(
        self,
        stream_id: str,
        *,
        character_id: str = "",
        role: str = "assistant",
        speaker_name: str = "",
    ) -> None:
        state = self._stream_state(stream_id, character_id=character_id)
        self._prepare_stream_phase(state, role=role, speaker_name=speaker_name)

    def record_stream_chunk(
        self,
        stream_id: str,
        chunk: Any,
        *,
        role: str = "assistant",
        character_id: str = "",
    ) -> None:
        if chunk is None:
            return
        text = str(chunk)
        if not text:
            return
        state = self._stream_state(stream_id, character_id=character_id)
        self._prepare_stream_phase(state, role=role)
        state.phases[-1].chunks.append(text)

    def stream_replay(self, stream_id: str) -> StreamPresentationReplay | None:
        stream_key = self._stream_key(stream_id)
        state = self._active_streams.get(stream_key)
        if state is None:
            return None
        return StreamPresentationReplay(
            stream_id=stream_key,
            character_id=state.character_id,
            phases=tuple(
                StreamPresentationPhase(
                    role=phase.role,
                    speaker_name=phase.speaker_name,
                    text="".join(phase.chunks),
                )
                for phase in state.phases
            ),
        )

    def mark_stream_mounted(self, stream_id: str) -> None:
        state = self._active_streams.get(self._stream_key(stream_id))
        if state is not None:
            state.mounted = True

    def mark_streams_unmounted(self) -> None:
        for state in self._active_streams.values():
            state.mounted = False

    def is_stream_mounted(self, stream_id: str) -> bool:
        state = self._active_streams.get(self._stream_key(stream_id))
        return bool(state and state.mounted)

    def stream_character_key(self, stream_id: str) -> str:
        state = self._active_streams.get(self._stream_key(stream_id))
        return state.character_key if state is not None else ""

    def should_render_stream(
        self,
        stream_id: str,
        *,
        current_character_id: str | None,
        character_id: str | None = None,
    ) -> bool:
        owner_key = self.stream_character_key(stream_id) or self._character_key(character_id)
        current_key = self._character_key(current_character_id)
        return not (owner_key and current_key and owner_key != current_key)

    def _has_active_stream_for(self, character_key: str) -> bool:
        if not self._active_streams:
            return False
        if not character_key:
            return True
        return any(
            not state.character_key or state.character_key == character_key
            for state in self._active_streams.values()
        )

    def _has_mounted_stream_for(self, character_key: str) -> bool:
        if not self._active_streams:
            return False
        if not character_key:
            return any(state.mounted for state in self._active_streams.values())
        return any(
            state.mounted
            and (not state.character_key or state.character_key == character_key)
            for state in self._active_streams.values()
        )

    def finish_stream(self, stream_id: str, *, current_character_id: str | None = None) -> bool:
        stream_key = self._stream_key(stream_id)
        state = self._active_streams.pop(stream_key, None)
        if state is None:
            return False
        owner_key = state.character_key
        if not owner_key:
            current_key = self._character_key(current_character_id)
            ready_keys = {
                key
                for key in self._reload_after_stream
                if not self._has_active_stream_for(key)
            }
            self._reload_after_stream.difference_update(ready_keys)
            return bool(ready_keys and (not current_key or current_key in ready_keys or "" in ready_keys))

        if owner_key not in self._reload_after_stream:
            return False
        if self._has_active_stream_for(owner_key):
            return False

        self._reload_after_stream.discard(owner_key)
        current_key = self._character_key(current_character_id)
        return not current_key or current_key == owner_key

    def plan_history_projection(
        self,
        *,
        request_id: str,
        response_character_id: str,
        current_character_id: str,
        history_messages: Iterable[dict],
    ) -> HistoryProjectionPlan:
        ticket = self._active_history_load
        if ticket is None or ticket.request_id != str(request_id or ""):
            return HistoryProjectionPlan(False, reason="stale_request")

        response_key = self._character_key(response_character_id)
        current_key = self._character_key(current_character_id)
        ticket_key = self._character_key(ticket.character_id)
        if ticket_key and response_key and ticket_key != response_key:
            self._active_history_load = None
            return HistoryProjectionPlan(False, reason="response_character_mismatch")

        projection_key = response_key or ticket_key
        if current_key and projection_key and current_key != projection_key:
            self._active_history_load = None
            return HistoryProjectionPlan(False, reason="inactive_character")

        target_key = projection_key or current_key
        refresh_after_stream = self._has_active_stream_for(target_key)
        if refresh_after_stream:
            self._reload_after_stream.add(target_key)
            if self._has_mounted_stream_for(target_key):
                self._active_history_load = None
                return HistoryProjectionPlan(
                    False,
                    retry_after_stream=True,
                    reason="active_stream",
                )

        history_rows = [message for message in history_messages if isinstance(message, dict)]
        snapshot_signatures: dict[tuple[str, str], set[tuple[Any, ...]]] = {}
        for message in history_rows:
            message_id = self._message_key(message.get("message_id"))
            if not message_id:
                continue
            key = (target_key, message_id)
            snapshot_signatures.setdefault(key, set()).add(
                self._content_signature(
                    str(message.get("role") or ""),
                    message.get("content", ""),
                )
            )
            thinking = str(message.get("thinking") or "").strip()
            if thinking:
                snapshot_signatures[key].add(self._content_signature("think", thinking))

        replay: list[tuple[int, ChatRenderCommand]] = []
        keys_to_remove: list[tuple[str, str]] = []
        for key, state in list(self._stable.items()):
            character_key, _message_id = key
            if target_key and character_key and character_key != target_key:
                continue

            projected = snapshot_signatures.get(key, set())
            if projected:
                uncovered = [
                    item
                    for item in state.commands
                    if not self._is_projected(projected, item[1])
                ]
                replay.extend(uncovered)
                if uncovered:
                    state.commands = uncovered
                else:
                    keys_to_remove.append(key)
                continue

            if state.persisted_revision is None or state.persisted_revision > ticket.start_revision:
                replay.extend(state.commands)
            else:
                # The message was already durable before this snapshot started and
                # is absent from the current history page. Treat it as outside the
                # page/filter rather than resurrecting an old live bubble.
                keys_to_remove.append(key)

        retained_ephemeral: deque[tuple[int, ChatRenderCommand]] = deque(
            maxlen=self._ephemeral.maxlen
        )
        for revision, command in self._ephemeral:
            command_key = self._character_key(command.character_id)
            if target_key and command_key and command_key != target_key:
                retained_ephemeral.append((revision, command))
                continue
            if revision > ticket.start_revision:
                replay.append((revision, command))
        self._ephemeral = retained_ephemeral

        for key in keys_to_remove:
            self._stable.pop(key, None)
            self._persisted_acks.pop(key, None)

        if target_key:
            self._history_projected = {
                key: signatures
                for key, signatures in self._history_projected.items()
                if key[0] != target_key
            }
            self._history_projected.update(snapshot_signatures)

        self._active_history_load = None
        replay.sort(key=lambda item: item[0])
        return HistoryProjectionPlan(
            True,
            replay=tuple(command.clone() for _, command in replay),
            retry_after_stream=refresh_after_stream,
        )
