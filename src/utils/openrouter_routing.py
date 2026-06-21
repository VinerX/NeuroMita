from __future__ import annotations

import re
from typing import Any, Dict


_LIST_KEYS = ("order", "only", "ignore", "quantizations")
_BOOL_KEYS = ("allow_fallbacks", "require_parameters", "zdr")
_ALLOWED_SORT = {"price", "latency", "throughput"}
_ALLOWED_DATA_COLLECTION = {"allow", "deny"}
_MAX_PRICE_KEYS = ("prompt", "completion", "request", "image", "audio", "total")
_EXPLICIT_CACHE_CONTROL_MODEL_MARKERS = ("gemini", "claude", "anthropic/")


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _split_csv_like(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        raw = str(value or "")
        items = raw.replace("\n", ",").split(",")

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_max_price(value: Any) -> Dict[str, float]:
    if not isinstance(value, dict):
        return {}

    out: Dict[str, float] = {}
    for key in _MAX_PRICE_KEYS:
        raw = value.get(key)
        if raw in (None, ""):
            continue
        try:
            # Accept comma decimal separators (e.g. "0,05" from RU/EU locales).
            out[key] = float(str(raw).strip().replace(",", "."))
        except Exception:
            continue
    return out


def normalize_openrouter_routing(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    if not _to_bool(raw.get("enabled", False)):
        return {}

    # `enabled` is a local UI/preset flag. OpenRouter's provider object does not accept it.
    out: Dict[str, Any] = {}

    for key in _LIST_KEYS:
        values = _split_csv_like(raw.get(key))
        if values:
            out[key] = values

    for key in _BOOL_KEYS:
        if key in raw:
            out[key] = _to_bool(raw.get(key))

    sort_value = str(raw.get("sort") or "").strip().lower()
    if sort_value in _ALLOWED_SORT:
        out["sort"] = sort_value

    data_collection = str(raw.get("data_collection") or "").strip().lower()
    if data_collection in _ALLOWED_DATA_COLLECTION:
        out["data_collection"] = data_collection

    max_price = _normalize_max_price(raw.get("max_price"))
    if max_price:
        out["max_price"] = max_price

    return out


def build_openrouter_session_id(character_id: Any = None, character_name: Any = None) -> str:
    seed = str(character_id or character_name or "").strip()
    if not seed:
        return ""
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "-", seed).strip("-").lower()
    return f"neuromita:{normalized}" if normalized else ""


def supports_openrouter_explicit_cache_control(model_name: Any) -> bool:
    model = str(model_name or "").strip().lower()
    return any(marker in model for marker in _EXPLICIT_CACHE_CONTROL_MODEL_MARKERS)


def annotate_openrouter_prompt_cache(messages: Any, model_name: Any) -> list[dict]:
    if not isinstance(messages, list):
        return []
    if not supports_openrouter_explicit_cache_control(model_name):
        return [m for m in messages if isinstance(m, dict)]

    out: list[dict] = [dict(m) for m in messages if isinstance(m, dict)]
    target_idx = None
    for idx, message in enumerate(out):
        role = str(message.get("role") or "").strip().lower()
        if role in {"system", "developer"}:
            target_idx = idx
            break
        if role:
            break
    if target_idx is None:
        return out

    target = dict(out[target_idx])
    content = target.get("content")
    annotated = _annotate_cached_content(content)
    if annotated is content:
        return out
    target["content"] = annotated
    out[target_idx] = target
    return out


def _annotate_cached_content(content: Any) -> Any:
    if isinstance(content, str):
        if not content.strip():
            return content
        return [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]

    if not isinstance(content, list):
        return content

    out: list[Any] = []
    last_text_idx = None
    for idx, item in enumerate(content):
        if isinstance(item, dict) and str(item.get("type") or "") == "text":
            last_text_idx = idx
        out.append(dict(item) if isinstance(item, dict) else item)

    if last_text_idx is None:
        return content

    target = out[last_text_idx]
    if not isinstance(target, dict):
        return content
    if target.get("cache_control"):
        return content

    target["cache_control"] = {"type": "ephemeral"}
    out[last_text_idx] = target
    return out
