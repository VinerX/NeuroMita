"""Deterministic, model-facing projection of structured requested actions."""
from __future__ import annotations

import json
from typing import Any


_SEGMENT_ACTION_FIELDS = (
    ("emotions", "emotion"),
    ("animations", "animation"),
    ("idle_animations", "idle_animation"),
    ("commands", "command"),
    ("movement_modes", "movement_mode"),
    ("visual_effects", "visual_effect"),
    ("clothes", "outfit"),
    ("music", "music"),
    ("interactions", "interaction"),
    ("face_params", "face_param"),
)


def requested_actions_from_structured(structured_data: Any) -> list[str]:
    """Return stable, compact action records from persisted ``structured_data``.

    The records intentionally say *requested*: Python sees the model's command,
    but does not know whether Unity resolved or executed it.
    """
    if not isinstance(structured_data, dict):
        return []
    result: list[str] = []
    for segment in structured_data.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for field, label in _SEGMENT_ACTION_FIELDS:
            values = segment.get(field) or []
            if not isinstance(values, list):
                values = [values]
            for value in values:
                text = " ".join(str(value or "").split()).strip()
                if text:
                    result.append(f"{label}: {text}")
        for field, label in (("start_game", "start_game"), ("end_game", "end_game")):
            value = " ".join(str(segment.get(field) or "").split()).strip()
            if value:
                result.append(f"{label}: {value}")
        for intent in segment.get("intents") or []:
            if not isinstance(intent, dict):
                continue
            intent_type = " ".join(str(intent.get("type") or "").split()).strip()
            if not intent_type:
                continue
            payload = intent.get("payload")
            try:
                payload_text = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            except (TypeError, ValueError):
                payload_text = "{}"
            result.append(f"intent: {intent_type} {payload_text}")
    return result


def requested_actions_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    records: list[str] = []
    for message in messages or []:
        if isinstance(message, dict) and message.get("role") == "assistant":
            records.extend(requested_actions_from_structured(message.get("structured_data")))
    return records


def render_requested_actions(records: list[str]) -> str:
    clean = [str(record).strip() for record in records or [] if str(record).strip()]
    if not clean:
        return ""
    return "[REQUESTED ACTIONS BY YOU]\n" + "\n".join(f"- {record}" for record in clean) + "\n[/REQUESTED ACTIONS BY YOU]"
