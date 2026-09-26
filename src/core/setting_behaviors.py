from __future__ import annotations

from typing import Any


def evaluate_setting_behaviors(
    schema: list[dict[str, Any]], values: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for setting in schema:
        if not isinstance(setting, dict):
            continue
        behavior = setting.get("behavior")
        if not isinstance(behavior, dict) or behavior.get("kind") != "source_allowlist":
            continue
        key = str(setting.get("key") or "")
        source = str(behavior.get("source") or "")
        if not key or not source:
            continue
        selected = str(values.get(source) or "").strip().lower()
        if selected == "cuda":
            selected = "cuda:0"
        supported = {
            str(value).strip().lower()
            for value in behavior.get("supported_values") or []
        }
        allowed = selected in supported
        states[key] = {
            "enabled": allowed and not bool(setting.get("locked", False)),
            "value": None if allowed else str(behavior.get("unsupported_value", "False")),
        }
    return states


def normalize_setting_behaviors(
    schema: list[dict[str, Any]], values: dict[str, Any]
) -> dict[str, Any]:
    normalized = dict(values or {})
    for key, state in evaluate_setting_behaviors(schema, normalized).items():
        if state.get("value") is not None:
            normalized[key] = state["value"]
    return normalized
