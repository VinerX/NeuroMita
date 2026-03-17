# src/handlers/llm_providers/message_transforms.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _as_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return ""


def _summarize_messages(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    roles = [m.get("role") for m in msgs if m.get("role")]

    total_chars = 0
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            total_chars += len(c)
        elif isinstance(c, list):
            for chunk in c:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    total_chars += len(_as_text(chunk.get("text", "")))

    return {
        "count": len(msgs),
        "roles": roles[:24],
        "last_role": roles[-1] if roles else None,
        "approx_text_chars": total_chars,
    }


def merge_system_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    system_parts: List[str] = []
    rest: List[Dict[str, Any]] = []

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "system":
            c = m.get("content", "")
            t = _as_text(c).strip()
            if t:
                system_parts.append(t)
        else:
            rest.append(m)

    if not system_parts:
        return list(rest)

    merged = {"role": "system", "content": "\n\n".join(system_parts)}
    return [merged] + rest


def ensure_last_message_user(messages: List[Dict[str, Any]], fallback_user_text: str = ".") -> List[Dict[str, Any]]:
    out = list(messages or [])
    if not out:
        return [{"role": "user", "content": fallback_user_text}]

    last = out[-1]
    if isinstance(last, dict) and last.get("role") == "assistant":
        out.append({"role": "user", "content": fallback_user_text})
    return out


def ensure_alternating_roles(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge consecutive messages with the same role so user/assistant strictly alternate.

    System messages at the very beginning (before the first user message) are
    kept as-is and never merged with non-system messages.  Two adjacent system
    messages are merged together.

    For user/assistant runs: all consecutive messages of the same role are
    collapsed into one by joining their text content with "\\n\\n".
    """

    def _to_list(content: Any) -> list:
        if not content and content != 0:
            return []
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        if isinstance(content, list):
            return content
        return [{"type": "text", "text": _as_text(content)}]

    def _merge_two(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        content_a = a.get("content", "")
        content_b = b.get("content", "")

        # Both plain strings — keep simple string output
        if isinstance(content_a, str) and isinstance(content_b, str):
            merged_content: Any = "\n\n".join(t for t in [content_a, content_b] if t)
        else:
            # At least one is a list (multimodal) — concatenate block arrays
            # so non-text blocks (images, files) are never lost
            merged_content = _to_list(content_a) + _to_list(content_b)

        merged = dict(a)
        merged["content"] = merged_content

        # Preserve tool_calls from both messages
        tc_a = a.get("tool_calls") or []
        tc_b = b.get("tool_calls") or []
        if tc_a or tc_b:
            merged["tool_calls"] = tc_a + tc_b

        return merged

    out: List[Dict[str, Any]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if not out:
            out.append(dict(msg))
            continue
        if out[-1].get("role") == msg.get("role"):
            out[-1] = _merge_two(out[-1], msg)
        else:
            out.append(dict(msg))
    return out


def system_to_user_prefix(messages: List[Dict[str, Any]], tag: str = "[SYSTEM CONTEXT]") -> List[Dict[str, Any]]:
    system_texts: List[str] = []
    out: List[Dict[str, Any]] = []

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "system":
            c = m.get("content", "")
            t = _as_text(c).strip()
            if t:
                system_texts.append(t)
            continue
        out.append(m)

    if not system_texts:
        return out

    prefix = "\n\n".join(f"{tag} {t}" for t in system_texts).strip()

    for m in out:
        if m.get("role") != "user":
            continue

        content = m.get("content")

        if isinstance(content, list):
            inserted = False
            for chunk in content:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    chunk["text"] = f"{prefix}\n\n{_as_text(chunk.get('text', ''))}"
                    inserted = True
                    break
            if not inserted:
                content.insert(0, {"type": "text", "text": prefix})
            return out

        if isinstance(content, str):
            m["content"] = f"{prefix}\n\n{content}"
            return out

        m["content"] = f"{prefix}\n\n{_as_text(content)}"
        return out

    out.append({"role": "user", "content": prefix})
    return out


# --- Catalog (for UI) ---
_TRANSFORM_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "merge_system_messages",
        "title": "Merge system messages",
        "description": "Combine all system messages into a single system message at the top.",
        "params_schema": None,
    },
    {
        "id": "ensure_last_message_user",
        "title": "Ensure last message is user",
        "description": "If last message is assistant, append a dummy user message ('.').",
        "params_schema": {"fallback_user_text": "str"},
    },
    {
        "id": "system_to_user_prefix",
        "title": "System → user prefix",
        "description": "Move system messages into the first user message as a text prefix.",
        "params_schema": {"tag": "str"},
    },
    {
        "id": "ensure_alternating_roles",
        "title": "Ensure alternating roles",
        "description": "Merge consecutive messages with the same role so user/assistant strictly alternate.",
        "params_schema": None,
    },
]


def get_transform_catalog() -> List[Dict[str, Any]]:
    return list(_TRANSFORM_CATALOG)


_TRANSFORMS = {
    "merge_system_messages": lambda msgs, params: merge_system_messages(msgs),
    "ensure_last_message_user": lambda msgs, params: ensure_last_message_user(
        msgs, fallback_user_text=str((params or {}).get("fallback_user_text", "."))
    ),
    "system_to_user_prefix": lambda msgs, params: system_to_user_prefix(
        msgs, tag=str((params or {}).get("tag", "[SYSTEM CONTEXT]"))
    ),
    "ensure_alternating_roles": lambda msgs, params: ensure_alternating_roles(msgs),
}


def apply_transforms(
    messages: List[Dict[str, Any]],
    specs: Optional[List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    out = list(messages or [])
    trace: List[Dict[str, Any]] = []

    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        tid = spec.get("id")
        params = spec.get("params") or {}
        fn = _TRANSFORMS.get(tid)
        if not fn:
            trace.append({"id": tid, "skipped": True, "reason": "unknown_transform"})
            continue

        before = _summarize_messages(out)
        out2 = fn(out, params)
        after = _summarize_messages(out2)

        trace.append({"id": tid, "params": params, "before": before, "after": after, "changed": before != after})
        out = out2

    return out, trace