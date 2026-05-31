from __future__ import annotations

from typing import Any, Dict


_LIST_KEYS = ("order", "only", "ignore", "quantizations")
_BOOL_KEYS = ("allow_fallbacks", "require_parameters", "zdr")
_ALLOWED_SORT = {"price", "latency", "throughput"}
_ALLOWED_DATA_COLLECTION = {"allow", "deny"}
_MAX_PRICE_KEYS = ("prompt", "completion", "request", "image", "audio", "total")


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
            out[key] = float(raw)
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
