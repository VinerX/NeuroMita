from __future__ import annotations

import base64
import datetime
import os
import uuid
from typing import Any, Callable, Optional

from main_logger import logger


class ConversationEventWriter:
    def __init__(self, character_ref_resolver: Callable[[str], Any]):
        self._get_character_ref = character_ref_resolver

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
            if s.lower() == "player":
                s = "Player"
            if s in seen:
                continue
            out.append(s)
            seen.add(s)
        return out

    def _make_message_id(self, prefix: str, base: str | None = None) -> str:
        base_s = str(base or "").strip()
        if base_s:
            return f"{prefix}:{base_s}"
        return f"{prefix}:{uuid.uuid4().hex}"

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
                f"[ConversationEventWriter] append failed for {getattr(ch_ref,'char_id','?')}: {e}",
                exc_info=True
            )
            return False

    def _append_history_messages(self, ch_ref, messages: list[dict]) -> bool:
        if ch_ref is None:
            return False
        payload = [dict(msg) for msg in messages or [] if isinstance(msg, dict)]
        if not payload:
            return False

        try:
            batch_append = getattr(ch_ref, "add_messages_to_history", None)
            if callable(batch_append):
                batch_append(payload)
                return True

            for msg in payload:
                self._append_history_message(ch_ref, msg)
            return True
        except Exception as exc:
            logger.warning(
                f"[ConversationEventWriter] batch append failed for "
                f"{getattr(ch_ref, 'char_id', '?')}: {exc}",
                exc_info=True,
            )
            return False

    def _fanout_event(self, event_msg: dict, participants: list[str]) -> None:
        speaker = str(event_msg.get("speaker") or "")
        if not speaker:
            return

        for pid in participants:
            if not pid or pid == "Player":
                continue

            ch = self._get_character_ref(pid)
            if ch is None:
                continue

            local = dict(event_msg)
            local["role"] = "assistant" if pid == speaker else "user"
            local.setdefault("sender", speaker)

            self._append_history_message(ch, local)

    def _fanout_turn(
        self,
        user_event: dict | None,
        assistant_event: dict,
        participants: list[str],
    ) -> None:
        for pid in participants:
            if not pid or pid == "Player":
                continue

            ch = self._get_character_ref(pid)
            if ch is None:
                continue

            local_messages: list[dict] = []
            for event_msg in (user_event, assistant_event):
                if not isinstance(event_msg, dict):
                    continue
                local = dict(event_msg)
                speaker = str(local.get("speaker") or "")
                local["role"] = "assistant" if pid == speaker else "user"
                local.setdefault("sender", speaker)
                local_messages.append(local)

            self._append_history_messages(ch, local_messages)

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
            "message_id": self._make_message_id("in", req_id),
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
            "message_id": self._make_message_id("out", task_uid),
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
            logger.warning(f"[ConversationEventWriter] Failed to save easel drawing: {e}")

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
    ) -> str:
        sender = str(sender or "Player")
        responder_character_id = str(responder_character_id or "").strip()
        assistant_target = str(assistant_target or "Player")
        image_source = str(image_source or "").strip().lower()
        origin_message_id = str(origin_message_id or "").strip() or None

        # Persist player's easel drawings to a dedicated folder immediately on receipt.
        if event_type == "easel_drawing" and image_data:
            self._save_drawings_to_disk(image_data, responder_character_id)

        pts = self.normalize_participants(participants)
        if responder_character_id and responder_character_id not in pts:
            pts.append(responder_character_id)

        turn_id = self._make_message_id("turn", task_uid or req_id)

        user_event = None
        if not (sender != "Player" and origin_message_id):
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

        self._fanout_turn(user_event, assistant_event, pts)
        return str(assistant_event.get("message_id") or "")
