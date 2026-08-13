from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .core import DialogueSimulation, PreparedTurn, SimulationError, TurnResult


class JsonTransport(Protocol):
    @property
    def connected(self) -> bool: ...

    def send(self, payload: dict[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class SessionEvent:
    kind: str
    message: str = ""
    turn: TurnResult | None = None
    payload: dict[str, Any] | None = None


@dataclass(slots=True)
class _PendingRequest:
    request_id: str
    kind: str
    turn: PreparedTurn | None


class UnityLikeDialogueSession:
    """Headless dialogue director that uses the same server contract as Unity."""

    RESPONSE_PROTOCOL_VERSION = 3

    FINAL_STATUSES = {
        "SUCCESS",
        "FAILED_ON_GENERATION",
        "FAILED_ON_VOICEOVER",
        "FAILED",
        "CANCELLED",
        "ABORTED",
    }

    def __init__(
        self,
        simulation: DialogueSimulation,
        transport: JsonTransport,
        *,
        on_event: Callable[[SessionEvent], None],
    ) -> None:
        self.simulation = simulation
        self.transport = transport
        self._on_event = on_event
        self._pending_by_request_id: dict[str, _PendingRequest] = {}
        self._request_id_by_task_uid: dict[str, str] = {}
        self._busy = False
        self._continues_used = 0
        self._gm_replies_since_check = 0

    @property
    def busy(self) -> bool:
        return self._busy

    def submit_player_message(self, message: str) -> str:
        if self._busy:
            raise SimulationError("Предыдущий Unity-ход ещё не завершён")
        if not self.transport.connected:
            raise ConnectionError("Сначала подключитесь к NeuroMita")
        player_text, target_character_id = self._resolve_player_target(message)
        turn = self.simulation.prepare_player_turn(player_text, target_character_id)
        self._continues_used = 0
        self._gm_replies_since_check = 0
        return self._dispatch_turn(turn, kind="mita")

    def _resolve_player_target(self, message: str) -> tuple[str, str | None]:
        text = str(message or "").strip()
        if not text.startswith("@"):
            return text, None

        aliases = sorted(
            (
                (alias, mita.character_id)
                for mita in self.simulation.mitas
                for alias in {mita.character_id, mita.display_name}
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        folded = text.casefold()
        for alias, character_id in aliases:
            mention = f"@{alias}"
            if not folded.startswith(mention.casefold()):
                continue
            if len(text) > len(mention) and not text[len(mention)].isspace():
                continue
            return text[len(mention):].strip(), character_id
        return text, None

    def handle_server_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")
        if message_type == "loaded_settings":
            self.simulation.policy.apply_server_payload(message)
            self._emit("settings", "Настройки NeuroMita применены", payload=message)
            return
        if message_type == "hello_ack":
            role = str(message.get("client_role") or "")
            owner = bool(message.get("owns_player_input"))
            self._emit("protocol", f"Handshake: role={role or '—'}, player_input={owner}", payload=message)
            return
        if message_type == "asr_text":
            self._emit("asr", str(message.get("text") or ""), payload=message)
            return
        if message_type == "error":
            self._emit("error", str(message.get("error") or "Ошибка сервера"), payload=message)
            return
        if message_type != "task_update":
            self._emit("protocol", f"Получено: {message_type or 'unknown'}", payload=message)
            return
        self._handle_task_update(message)

    def reset(self) -> None:
        self._pending_by_request_id.clear()
        self._request_id_by_task_uid.clear()
        self._busy = False
        self._continues_used = 0
        self._gm_replies_since_check = 0
        self.simulation.reset()

    def handle_connection_lost(self) -> None:
        if not self._busy:
            return
        self._pending_by_request_id.clear()
        self._request_id_by_task_uid.clear()
        self._busy = False
        self.simulation.pending_speaker_id = ""
        self.simulation.pending_addressed_turn = None
        self.simulation.stop_reason = "Соединение потеряно во время хода"
        self._emit("error", self.simulation.stop_reason)

    def _handle_task_update(self, message: dict[str, Any]) -> None:
        body = message.get("body") if isinstance(message.get("body"), dict) else {}
        task_uid = str(message.get("uid") or body.get("uid") or "")
        task_data = body.get("data") if isinstance(body.get("data"), dict) else {}
        request_id = str(task_data.get("req_id") or "")
        if request_id and task_uid:
            self._request_id_by_task_uid[task_uid] = request_id
        if not request_id and task_uid:
            request_id = self._request_id_by_task_uid.get(task_uid, "")
        pending = self._pending_by_request_id.get(request_id)
        if pending is None:
            return
        status = str(message.get("status") or body.get("status") or "").upper()
        if status not in self.FINAL_STATUSES:
            self._emit("status", f"{pending.turn.speaker_name if pending.turn else 'GameMaster'}: {status}")
            return
        self._pending_by_request_id.pop(request_id, None)
        if task_uid:
            self._request_id_by_task_uid.pop(task_uid, None)
        self._busy = False
        if status != "SUCCESS":
            error = str(body.get("error") or message.get("error") or status)
            self.simulation.pending_speaker_id = ""
            self.simulation.stop_reason = f"Задача завершилась: {error}"
            self._emit("error", self.simulation.stop_reason, payload=message)
            return
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        self._complete_success(pending, result)

    def _complete_success(self, pending: _PendingRequest, result: dict[str, Any]) -> None:
        if not _has_supported_response_protocol(result, self.RESPONSE_PROTOCOL_VERSION):
            self.simulation.clear_addressed_turns()
            self.simulation.stop_reason = (
                f"Unsupported or missing response_protocol_version; "
                f"expected {self.RESPONSE_PROTOCOL_VERSION}"
            )
            self._emit("error", self.simulation.stop_reason, payload=result)
            return

        response = _response_text(result)
        directives = _dialogue_directives(result)
        source_id = pending.turn.speaker_id if pending.turn is not None else "GameMaster"
        if self.simulation.can_schedule_automatic_turns():
            self.simulation.enqueue_addressed_segments(
                directives.addressed_segments,
                source_id=source_id,
                full_response=_segment_response_text(result) or response,
                address_map=directives.address_map,
                reset_pending=bool(pending.turn and pending.turn.from_player),
            )
        else:
            self.simulation.clear_addressed_turns()
        for character_id in directives.next_speakers:
            try:
                self.simulation.set_next_speaker(character_id)
            except SimulationError as exc:
                self._emit("warning", str(exc))

        if pending.kind == "game_master":
            turn_result = self.simulation.record_game_master_turn(response)
            self._emit("turn", turn=turn_result, payload=result)
            self._emit_directives(directives)
            self.simulation.plan_follow_up("GameMaster", from_player=False)
            self._dispatch_planned_turn()
            return

        turn = pending.turn
        if turn is None:
            self._emit("error", "Ответ задачи потерял контекст Unity-хода")
            return

        wants_continue = directives.continue_requested
        can_continue = wants_continue and self._continues_used < self.simulation.policy.max_continues
        turn_result = self.simulation.complete_turn(turn, response, plan_follow_up=False)
        self._emit("turn", turn=turn_result, payload=result)
        self._emit_directives(directives)

        if can_continue:
            self._continues_used += 1
            remaining = self.simulation.policy.max_continues - self._continues_used
            try:
                self._dispatch_continue(turn, remaining)
            except (ConnectionError, OSError, ValueError) as exc:
                self._fail_dispatch(exc)
            return
        if wants_continue and not can_continue:
            self._emit("warning", "Unity отклонила продолжение: лимит исчерпан")
        self._continues_used = 0

        self._gm_replies_since_check += 1
        policy = self.simulation.policy
        if (
            policy.auto_dialogue_enabled
            and policy.game_master_enabled
            and self._gm_replies_since_check >= policy.game_master_repeat
            and not self.simulation.has_pending_addressed_turns
        ):
            self._gm_replies_since_check = 0
            try:
                self._dispatch_game_master()
            except (ConnectionError, OSError, ValueError) as exc:
                self._fail_dispatch(exc)
            return

        self.simulation.plan_follow_up(turn.speaker_id, from_player=turn.from_player)
        self._dispatch_planned_turn()

    def _dispatch_planned_turn(self) -> None:
        if not self.simulation.pending_speaker_id:
            self._emit("idle", self.simulation.stop_reason)
            return
        try:
            turn = self.simulation.prepare_automatic_turn(self.simulation.last_response)
        except SimulationError as exc:
            self._emit("error", str(exc))
            return
        try:
            self._dispatch_turn(turn, kind="mita")
        except (ConnectionError, OSError, ValueError) as exc:
            self._fail_dispatch(exc)

    def _dispatch_continue(self, previous: PreparedTurn, remaining: int) -> None:
        turn = PreparedTurn(
            speaker_id=previous.speaker_id,
            speaker_name=previous.speaker_name,
            prompt=(
                "You continue your phrase or thought naturally. "
                f"You have {remaining} continuation(s) left in a row."
            ),
            event_type="continue",
            sender=previous.speaker_id,
            from_player=False,
            automatic=True,
            participant_ids=tuple(
                item.character_id for item in self.simulation.ordered_active_mitas()
            ),
        )
        self._dispatch_turn(turn, kind="continue")

    def _dispatch_game_master(self) -> None:
        request_id = uuid.uuid4().hex
        prompt = (
            "Review the active conversation. If needed, issue a concise mandatory scene directive "
            "through structured dialogue intents."
        )
        payload = self._build_payload(
            request_id=request_id,
            event_type="game_master_observe",
            character_id="GameMaster",
            sender="GameMaster",
            data={"message": prompt},
        )
        self._pending_by_request_id[request_id] = _PendingRequest(request_id, "game_master", None)
        self._busy = True
        try:
            self.transport.send(payload)
        except Exception:
            self._pending_by_request_id.pop(request_id, None)
            self._busy = False
            raise
        self._emit("dispatch", "GameMaster наблюдает за разговором", payload=payload)

    def _dispatch_turn(self, turn: PreparedTurn, *, kind: str) -> str:
        request_id = uuid.uuid4().hex
        if turn.event_type == "react":
            previous_name = self.simulation.last_speaker_id or "Player"
            if turn.addressed_message:
                address_lines = "\n".join(
                    f"- Segment {index} to {target}: <{text}>"
                    for index, (target, text) in enumerate(turn.address_map, start=1)
                )
                reason = (
                    f"[SPEAKER] {turn.addressed_source_id or previous_name} said the following full reply:\n"
                    f"<FULL_REPLY>{turn.full_response or turn.prompt}</FULL_REPLY>\n"
                    f"Segment addressing:\n{address_lines}\n"
                    f"The segment addressed specifically to you is: <{turn.addressed_message}>\n"
                    "Use the entire reply as context, but respond primarily to the segment addressed to you. "
                    "Segments addressed to other recipients are context only; do not answer as if they were addressed to you. "
                    "Now it is your turn to speak."
                )
            else:
                reason = (
                    f"[SPEAKER] {previous_name} said: <{turn.prompt}>. "
                    "Now it is your turn to speak. Respond to the previous statement."
                )
            data = {
                "message": "player_react",
                "react_level": "Answer",
                "reason_type": "DialogueAuto",
                "reason_content": reason,
                "reason": reason,
                "duration": 5.0,
            }
        else:
            data = {"message": turn.prompt}
        payload = self._build_payload(
            request_id=request_id,
            event_type=turn.event_type,
            character_id=turn.speaker_id,
            sender=turn.sender,
            data=data,
            participants=turn.participant_ids,
        )
        self._pending_by_request_id[request_id] = _PendingRequest(request_id, kind, turn)
        self._busy = True
        try:
            self.transport.send(payload)
        except Exception:
            self._pending_by_request_id.pop(request_id, None)
            self._busy = False
            raise
        self._emit("dispatch", f"Отправлен {turn.event_type}: {turn.speaker_name}", payload=payload)
        return request_id

    def _build_payload(
        self,
        *,
        request_id: str,
        event_type: str,
        character_id: str,
        sender: str,
        data: dict[str, Any],
        participants: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        active = self.simulation.ordered_active_mitas()
        distance = 0.0 if character_id == "GameMaster" else self.simulation.get_mita(character_id).distance
        runtime_context = (
            self.simulation.game_master_runtime_context()
            if character_id == "GameMaster"
            else self.simulation.get_mita(character_id).runtime_context()
        )
        context = {
            "distance": f"{distance:.2f}",
            "roomPlayer": 0,
            "roomMita": 0,
            **runtime_context,
            "image_base64_list": [],
        }
        return {
            "action": "create_task",
            "type": event_type,
            "character": character_id,
            "sender": sender,
            "participants": list(participants) or [mita.character_id for mita in active],
            "origin_message_id": None,
            "data": data,
            "context": context,
            "req_id": request_id,
        }

    def _emit_directives(self, directives: "_DialogueDirectives") -> None:
        for message in directives.system_messages:
            self._emit("directive", message)

    def _fail_dispatch(self, error: Exception) -> None:
        self._busy = False
        self.simulation.pending_speaker_id = ""
        self.simulation.pending_addressed_turn = None
        self.simulation.stop_reason = f"Не удалось отправить Unity-ход: {error}"
        self._emit("error", self.simulation.stop_reason)

    def _emit(
        self,
        kind: str,
        message: str = "",
        *,
        turn: TurnResult | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._on_event(SessionEvent(kind=kind, message=message, turn=turn, payload=payload))


@dataclass(frozen=True, slots=True)
class _DialogueDirectives:
    continue_requested: bool
    addressed_segments: tuple[tuple[str, str], ...]
    address_map: tuple[tuple[str, str], ...]
    next_speakers: tuple[str, ...]
    system_messages: tuple[str, ...]


def _dialogue_directives(result: dict[str, Any]) -> _DialogueDirectives:
    continue_requested = False
    addressed_texts: dict[str, list[str]] = {}
    addressed_order: list[str] = []
    address_map: list[tuple[str, str]] = []
    next_speakers: list[str] = []
    system_messages: list[str] = []
    segments = result.get("segments") if isinstance(result.get("segments"), list) else []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_target = str(segment.get("target") or "").strip()
        segment_text = str(segment.get("text") or "").strip()
        if segment_text:
            address_map.append((segment_target or "Player", segment_text))
        if segment_target and segment_target.casefold() != "player" and segment_text:
            if segment_target not in addressed_texts:
                addressed_texts[segment_target] = []
                addressed_order.append(segment_target)
            addressed_texts[segment_target].append(segment_text)
        intents = segment.get("intents") if isinstance(segment.get("intents"), list) else []
        for intent in intents:
            if not isinstance(intent, dict):
                continue
            intent_type = str(intent.get("type") or "").strip().casefold()
            payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
            if intent_type == "dialogue.continue":
                continue_requested = True
            elif intent_type in {"dialogue.set_next_speaker", "speaker.set_next"}:
                character = str(payload.get("character") or payload.get("target") or "").strip()
                if character:
                    next_speakers.append(character)
            elif intent_type == "dialogue.broadcast_system_message":
                text = str(payload.get("message") or "").strip()
                if text:
                    system_messages.append(f"GameMaster → всем: {text}")
            elif intent_type == "dialogue.send_system_message":
                character = str(payload.get("character") or "").strip()
                text = str(payload.get("message") or "").strip()
                if character and text:
                    system_messages.append(f"GameMaster → {character}: {text}")
    return _DialogueDirectives(
        continue_requested=continue_requested,
        addressed_segments=tuple(
            (target, " ".join(addressed_texts[target]))
            for target in addressed_order
        ),
        address_map=tuple(address_map),
        next_speakers=tuple(dict.fromkeys(next_speakers)),
        system_messages=tuple(system_messages),
    )


def _has_supported_response_protocol(result: dict[str, Any], expected: int) -> bool:
    try:
        return int(result.get("response_protocol_version")) == expected
    except (TypeError, ValueError):
        return False


def _response_text(result: dict[str, Any]) -> str:
    response = str(result.get("response") or "")
    if response.strip():
        return response.strip()
    segments = result.get("segments") if isinstance(result.get("segments"), list) else []
    texts = [str(segment.get("text") or "").strip() for segment in segments if isinstance(segment, dict)]
    return " ".join(text for text in texts if text).strip()


def _segment_response_text(result: dict[str, Any]) -> str:
    segments = result.get("segments") if isinstance(result.get("segments"), list) else []
    texts = [
        str(segment.get("text") or "").strip()
        for segment in segments
        if isinstance(segment, dict)
    ]
    return " ".join(text for text in texts if text).strip()
