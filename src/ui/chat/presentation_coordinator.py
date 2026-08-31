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


@dataclass(slots=True)
class _StableLiveMessage:
    commands: list[tuple[int, ChatRenderCommand]] = field(default_factory=list)
    persisted_revision: int | None = None


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
        self._active_streams: set[str] = set()
        self._reload_after_stream = False

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

    def record_live(self, command: ChatRenderCommand) -> bool:
        """Record a live render command and return whether the widget should render it."""
        revision = self._next_revision()
        command = command.clone()
        message_id = self._message_key(command.message_id)
        if not message_id:
            self._ephemeral.append((revision, command))
            return True

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
        return True

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
        self._reload_after_stream = False

    def begin_stream(self, stream_id: str) -> None:
        self._active_streams.add(str(stream_id or "default"))

    def finish_stream(self, stream_id: str) -> bool:
        self._active_streams.discard(str(stream_id or "default"))
        if self._active_streams or not self._reload_after_stream:
            return False
        self._reload_after_stream = False
        return True

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

        if self._active_streams:
            self._active_history_load = None
            self._reload_after_stream = True
            return HistoryProjectionPlan(
                False,
                retry_after_stream=True,
                reason="active_stream",
            )

        target_key = projection_key or current_key
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
        )
