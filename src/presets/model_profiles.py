"""Declarative model capability profile resolution.

Profiles are data owned by API templates and user presets.  Transport code uses
the resolved profile but never needs to know a provider model identifier.
"""

from __future__ import annotations

from copy import deepcopy
from fnmatch import fnmatchcase
from typing import Any, Iterable, Mapping


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge a user override without mutating either source mapping."""
    result = deepcopy(dict(base or {}))
    for key, value in (override or {}).items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _profile_score(model: str, profile: Mapping[str, Any]) -> int:
    match = str(profile.get("match") or "").strip()
    if not match:
        return 0
    if model == match:
        return 3
    if str(profile.get("match_mode") or "").strip().lower() == "glob" and fnmatchcase(model, match):
        return 2
    return 0


def resolve_model_profile(
    model: str,
    profiles: Iterable[Mapping[str, Any]] | None,
    overrides: Mapping[str, Any] | None = None,
    *,
    default_safe: bool = False,
) -> dict[str, Any]:
    """Resolve the most specific profile and apply a preset-local override.

    Unknown models deliberately receive an empty safe profile when
    ``default_safe`` is enabled.  This prevents a newly released model from
    inheriting legacy optional parameters accidentally.
    """
    model_id = str(model or "").strip()
    selected: Mapping[str, Any] | None = None
    selected_score = 0
    for profile in profiles or ():
        if not isinstance(profile, Mapping):
            continue
        score = _profile_score(model_id, profile)
        if score > selected_score:
            selected = profile
            selected_score = score

    if selected is None:
        if isinstance(overrides, Mapping) and overrides:
            selected = {}
        elif default_safe:
            selected = {
                "id": "safe-compatibility",
                "parameters": [],
                "thinking": {"transport": "none"},
                "native_structured_output": False,
                "safe_mode": True,
            }
        else:
            return {}

    result = deep_merge(selected, overrides if isinstance(overrides, Mapping) else {})
    result["parameters"] = [
        str(name).strip()
        for name in (result.get("parameters") or [])
        if str(name).strip()
    ]
    thinking = result.get("thinking")
    result["thinking"] = dict(thinking) if isinstance(thinking, Mapping) else {"transport": "none"}
    result["safe_mode"] = bool(result.get("safe_mode", False))
    return result
