from __future__ import annotations
from core.error_utils import format_exception

import base64
import datetime
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from main_logger import logger
from domain.dialogue_identity import DialogueActorKind
from domain.conversation_message_ids import ConversationMessageIds
from services.dialogue_identity_resolver import DialogueIdentityResolver


@dataclass(frozen=True, slots=True)
class ConversationWriteResult:
    user_message_id: str
    assistant_message_id: str
    committed_recipient_ids: tuple[str, ...]
    failed_recipient_ids: tuple[str, ...]

    @property
    def history_committed(self) -> bool:
        return bool(self.committed_recipient_ids) and not self.failed_recipient_ids


class ConversationEventWriter:
    def __init__(self, character_ref_resolver: Callable[[str], Any]):
        self._get_character_ref = character_ref_resolver
        self._identity_resolver = DialogueIdentityResolver(character_ref_resolver)

    def normalize_participants(self, participants: Any) -> list[str]:
        if not participants:
            return []
        if isinstance(participants, str):
            participants = [p.strip() for p in participants.split(",") if p.strip()]
        if not isinstance(participants, list):
            return []

        out: list[str] = []
        seen = set()
        for p in participants:
            s = str(p or "").strip()
            if not s:
                continue
            s = self._identity_resolver.canonical_id(s)
            key = s.casefold()
            if key in seen:
                continue
            out.append(s)
            seen.add(key)
        return out

    @staticmethod
    def _dialogue_value(value: Any, key: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)

    def _history_recipient_ids(
        self,
        participants: list[str],
        *,
        dialogue: Any,
        responder_character_id: str,
    ) -> list[str]:
        """Resolve history owners from Unity's actor roster, not transport aliases."""
        roster_ids = [
            str(self._dialogue_value(participant, "character_id", "") or "").strip()
            for participant in self._dialogue_value(dialogue, "participants", []) or []
        ]
        source_ids = [character_id for character_id in roster_ids if character_id]
        if not source_ids:
            source_ids = list(participants)

        resolved: list[str] = []
        seen: set[str] = set()
        for participant_id in [*source_ids, responder_character_id]:
            character_id = str(participant_id or "").strip()
            if not character_id:
                continue
            actor_kind = self._identity_resolver.classify_sender(character_id)
            if actor_kind in {DialogueActorKind.PLAYER, DialogueActorKind.GAME_MASTER}:
                continue

            character = self._get_character_ref(character_id)
            if character is None:
                continue

            canonical_id = str(getattr(character, "char_id", "") or character_id).strip()
            key = canonical_id.casefold()
            if not canonical_id or key in seen:
                continue
            seen.add(key)
            resolved.append(canonical_id)
        return resolved

    def _append_history_message(self, ch_ref, msg: dict) -> bool:
        if ch_ref is None or not isinstance(msg, dict):
            return False

        try:
            mid = str(msg.get("message_id") or "")
            if mid and ch_ref.history_manager.contains_message_id(mid):
                return False

            #messages.append(msg)
            #ch_ref.save_character_state_to_history(messages)
            ch_ref.add_message_to_history(msg)
            return True
        except Exception as e:
            logger.warning(
                f"[ConversationEventWriter] append failed for {getattr(ch_ref,'char_id','?')}: {format_exception(e)}",
                exc_info=True
            )
            return False

    def _append_history_messages(self, ch_ref, messages: list[dict]) -> bool:
        """Append a completed turn through the character's atomic batch API."""
        if ch_ref is None:
            return False
        payload = [dict(msg) for msg in messages or [] if isinstance(msg, dict)]
        if not payload:
            return False

        try:
            batch_append = getattr(ch_ref, "add_messages_to_history", None)
            if not callable(batch_append):
                history_manager = getattr(ch_ref, "history_manager", None)
                batch_append = getattr(history_manager, "add_messages", None)
            if not callable(batch_append):
                logger.warning(
                    f"[ConversationEventWriter] atomic history API is unavailable for "
                    f"{getattr(ch_ref, 'char_id', '?')}; turn was not written"
                )
                return False

            # Never split a completed turn into independent row commits.
            row_ids = batch_append(payload)
            if not isinstance(row_ids, (list, tuple)) or len(row_ids) != len(payload):
                logger.error(
                    f"[ConversationEventWriter] atomic history API did not commit the complete "
                    f"turn for {getattr(ch_ref, 'char_id', '?')}: "
                    f"expected {len(payload)} rows, got "
                    f"{len(row_ids) if isinstance(row_ids, (list, tuple)) else 'no result'}"
                )
                return False
            return True
        except Exception as exc:
            logger.warning(
                f"[ConversationEventWriter] batch append failed for "
                f"{getattr(ch_ref, 'char_id', '?')}: {format_exception(exc)}",
                exc_info=True,
            )
            return False

    def _fanout_event(self, event_msg: dict, participants: list[str]) -> None:
        speaker = str(event_msg.get("speaker") or "")
        if not speaker:
            return

        for pid in participants:
            if not pid or self._identity_resolver.classify_sender(pid) is DialogueActorKind.PLAYER:
                continue

            ch = self._get_character_ref(pid)
            if ch is None:
                continue

            local = dict(event_msg)
            local["role"] = "assistant" if self._identity_resolver.same_id(pid, speaker) else "user"
            local.setdefault("sender", speaker)

            self._append_history_message(ch, local)

    def _fanout_turn(
        self,
        user_event: dict | None,
        assistant_event: dict,
        participants: list[str],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Persist both sides of the completed turn in one batch per recipient."""
        committed: list[str] = []
        failed: list[str] = []
        for pid in participants:
            if not pid or self._identity_resolver.classify_sender(pid) is DialogueActorKind.PLAYER:
                continue

            ch = self._get_character_ref(pid)
            if ch is None:
                failed.append(pid)
                continue

            local_messages: list[dict] = []
            for event_msg in (user_event, assistant_event):
                if not isinstance(event_msg, dict):
                    continue
                local = dict(event_msg)
                speaker = str(local.get("speaker") or "")
                local["role"] = "assistant" if self._identity_resolver.same_id(pid, speaker) else "user"
                local.setdefault("sender", speaker)
                local_messages.append(local)

            if self._append_history_messages(ch, local_messages):
                committed.append(pid)
            else:
                failed.append(pid)

        return tuple(committed), tuple(failed)

    def _build_user_event_message(
        self,
        *,
        speaker: str,
        target: str,
        participants: list[str],
        user_input: str,
        image_data: list[Any],
        image_source: str,
        image_descriptions: dict[str, str] | None,
        event_type: str,
        req_id: str | None,
        turn_id: str,
    ) -> Optional[dict]:
        has_text = bool(str(user_input or "").strip())
        has_images = bool(image_data)

        if not has_text and not has_images:
            return None

        chunks: list[dict] = []

        if has_text:
            chunks.append({"type": "text", "text": str(user_input)})

        for img in image_data or []:
            if isinstance(img, bytes):
                b64 = base64.b64encode(img).decode("utf-8")
            else:
                b64 = str(img)
            image_chunk = {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            }
            if image_source == "mita_camera":
                image_chunk["display_role"] = "assistant"
            elif image_source == "easel":
                image_chunk["display_role"] = "user"
            chunks.append(image_chunk)

        msg = {
            "message_id": ConversationMessageIds.incoming(req_id),
            "role": "user",
            "speaker": speaker,
            "sender": speaker,
            "target": target,
            "participants": list(participants),
            "event_type": event_type,
            "turn_id": turn_id,
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "content": chunks,
        }
        if image_source:
            msg["image_source"] = image_source
        if image_descriptions:
            msg["image_descriptions"] = image_descriptions
        return msg

    def _build_assistant_event_message(
        self,
        *,
        speaker: str,
        target: str,
        participants: list[str],
        final_text: str,
        event_type: str,
        task_uid: str | None,
        structured_data: dict | None = None,
        thinking: str | None = None,
        llm_usage: dict | None = None,
        sample_id: str | None = None,
        turn_id: str,
    ) -> dict:
        msg = {
            "message_id": ConversationMessageIds.assistant(task_uid),
            "role": "assistant",
            "speaker": speaker,
            "sender": speaker,
            "target": target,
            "participants": list(participants),
            "event_type": event_type,
            "turn_id": turn_id,
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "content": final_text,
        }
        if structured_data:
            msg["structured_data"] = structured_data
        if thinking:
            msg["thinking"] = thinking
        if llm_usage:
            msg.update(llm_usage)
        if sample_id:
            msg["sample_id"] = sample_id
        return msg

    def _save_drawings_to_disk(self, image_data: list[Any], character_id: str) -> None:
        """Save easel drawing bytes to Histories/{char}/Drawings/ for permanent storage."""
        try:
            ch_ref = self._get_character_ref(character_id)
            if ch_ref is None or not hasattr(ch_ref, "history_manager"):
                return
            char_name = getattr(ch_ref.history_manager, "character_name", None) or character_id
            histories_dir = os.environ.get(
                "NEUROMITA_HISTORIES_DIR", os.path.join(os.getcwd(), "Histories")
            )
            drawings_dir = os.path.join(histories_dir, char_name, "Drawings")
            os.makedirs(drawings_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            for i, img in enumerate(image_data):
                if not isinstance(img, bytes):
                    continue
                fname = f"drawing_{ts}_{i}.jpg"
                fpath = os.path.join(drawings_dir, fname)
                with open(fpath, "wb") as fh:
                    fh.write(img)
                logger.info(f"[ConversationEventWriter] Easel drawing saved: {fpath}")
        except Exception as e:
            logger.warning(f"[ConversationEventWriter] Failed to save easel drawing: {format_exception(e)}")

    @staticmethod
    def _dialogue_metadata(dialogue: Any) -> dict:
        if dialogue is None:
            return {}
        participants = ConversationEventWriter._dialogue_value(dialogue, "participants", []) or []
        return {
            "conversation_id": str(ConversationEventWriter._dialogue_value(dialogue, "conversation_id", "") or ""),
            "conversation_epoch": int(ConversationEventWriter._dialogue_value(dialogue, "epoch", 0) or 0),
            "turn_index": int(ConversationEventWriter._dialogue_value(dialogue, "turn_index", 0) or 0),
            "speaker_actor_id": str(ConversationEventWriter._dialogue_value(dialogue, "speaker_actor_id", "") or ""),
            "responder_actor_id": str(ConversationEventWriter._dialogue_value(dialogue, "responder_actor_id", "") or ""),
            "participant_actor_ids": [
                str(ConversationEventWriter._dialogue_value(item, "actor_id", "") or "")
                for item in participants
                if str(ConversationEventWriter._dialogue_value(item, "actor_id", "") or "")
            ],
        }

    def write_turn(
        self,
        *,
        responder_character_id: str,
        sender: str,
        participants: Any,
        user_input: str,
        image_data: list[Any],
        image_source: str = "",
        image_descriptions: dict[str, str] | None = None,
        req_id: str | None,
        origin_message_id: str | None,
        assistant_text: str,
        assistant_target: str,
        event_type: str,
        task_uid: str | None,
        structured_data: dict | None = None,
        thinking: str | None = None,
        llm_usage: dict | None = None,
        sample_id: str | None = None,
        dialogue: Any = None,
    ) -> ConversationWriteResult:
        resolved_speaker = self._identity_resolver.resolve(sender, dialogue)
        sender = resolved_speaker.sender_id
        responder_character_id = str(responder_character_id or "").strip()
        assistant_target = str(assistant_target or "Player")
        image_source = str(image_source or "").strip().lower()
        origin_message_id = str(origin_message_id or "").strip() or None

        # Persist player's easel drawings to a dedicated folder immediately on receipt.
        if event_type == "easel_drawing" and image_data:
            self._save_drawings_to_disk(image_data, responder_character_id)

        dialogue_metadata = self._dialogue_metadata(dialogue)
        pts = self.normalize_participants(participants)
        if responder_character_id and responder_character_id not in pts:
            pts.append(responder_character_id)
        history_recipients = self._history_recipient_ids(
            pts,
            dialogue=dialogue,
            responder_character_id=responder_character_id,
        )

        turn_id = ConversationMessageIds.turn(task_uid or req_id)

        user_event = None
        if resolved_speaker.kind is DialogueActorKind.PLAYER or not origin_message_id:
            user_event = self._build_user_event_message(
                speaker=sender,
                target=responder_character_id,
                participants=pts,
                user_input=user_input,
                image_data=image_data,
                image_source=image_source,
                image_descriptions=image_descriptions,
                event_type=event_type,
                req_id=req_id,
                turn_id=turn_id,
            )

        assistant_event = self._build_assistant_event_message(
            speaker=responder_character_id,
            target=assistant_target,
            participants=pts,
            final_text=str(assistant_text or ""),
            event_type=event_type,
            task_uid=task_uid,
            structured_data=structured_data,
            thinking=thinking,
            llm_usage=llm_usage,
            sample_id=sample_id,
            turn_id=turn_id,
        )

        if dialogue_metadata:
            if isinstance(user_event, dict):
                user_metadata = dict(dialogue_metadata)
                user_metadata["speaker_actor_id"] = str(
                    self._dialogue_value(dialogue, "speaker_actor_id", "") or ""
                )
                user_event.update(user_metadata)

            # The assistant event is authored by the responder. Keep the
            # triggering actor separately so consumers can distinguish the
            # source of the turn from the actor whose text was persisted.
            assistant_metadata = dict(dialogue_metadata)
            assistant_metadata["source_actor_id"] = str(
                self._dialogue_value(dialogue, "speaker_actor_id", "") or ""
            )
            assistant_metadata["speaker_actor_id"] = str(
                self._dialogue_value(dialogue, "responder_actor_id", "") or ""
            )
            assistant_event.update(assistant_metadata)

        committed, failed = self._fanout_turn(user_event, assistant_event, history_recipients)
        return ConversationWriteResult(
            user_message_id=str((user_event or {}).get("message_id") or ""),
            assistant_message_id=str(assistant_event.get("message_id") or ""),
            committed_recipient_ids=committed,
            failed_recipient_ids=failed,
        )
