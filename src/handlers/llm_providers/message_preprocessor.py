# src/handlers/llm_providers/message_preprocessor.py
from __future__ import annotations

import json
from typing import Any, Dict, List

from handlers.llm_providers.base import LLMRequest, BaseProvider


def _prefix_text(text: str, prefix: str) -> str:
    t = text or ""
    if not t.strip():
        return prefix
    return f"{prefix} {t}"


def _convert_event_content_to_user(content: Any, prefix: str) -> Any:
    if isinstance(content, str):
        return _prefix_text(content, prefix)

    if isinstance(content, list):
        chunks: List[Dict[str, Any]] = []
        inserted = False

        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and not inserted:
                chunks.append({"type": "text", "text": _prefix_text(str(item.get("text", "")), prefix)})
                inserted = True
            else:
                chunks.append(item)

        if not inserted:
            chunks.insert(0, {"type": "text", "text": prefix})

        return chunks

    try:
        s = json.dumps(content, ensure_ascii=False)
    except Exception:
        s = str(content)

    return _prefix_text(s, prefix)


def preprocess_messages_for_provider(req: LLMRequest, provider: BaseProvider) -> None:
    """
    По умолчанию: role=event -> role=user с префиксом [SYSTEM]
    Если provider.uses_custom_messages_handler=True -> ничего не делаем.
    """
    if not req or not isinstance(req.messages, list):
        return

    if isinstance(req.extra, dict) and req.extra.get("_msg_roles_preprocessed"):
        return

    if getattr(provider, "uses_custom_messages_handler", False):
        return

    prefix = "[SYSTEM]"

    new_messages: List[Dict[str, Any]] = []
    for msg in req.messages:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role")
        if role != "event":
            new_messages.append(msg)
            continue

        new_msg = dict(msg)
        new_msg["role"] = "user"
        new_msg["content"] = _convert_event_content_to_user(new_msg.get("content"), prefix)
        new_messages.append(new_msg)

    req.messages = new_messages
    if isinstance(req.extra, dict):
        req.extra["_msg_roles_preprocessed"] = True