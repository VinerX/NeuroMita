from __future__ import annotations

from copy import deepcopy

from presets.model_profiles import resolve_model_profile
from presets.api_protocols import API_PROTOCOLS_DATA


_LEGACY_FIELDS = {
    "temperature": ("MODEL_TEMPERATURE", "USE_MODEL_TEMPERATURE", True),
    "max_tokens": ("MODEL_MAX_RESPONSE_TOKENS", "USE_MODEL_MAX_RESPONSE_TOKENS", True),
    "top_p": ("MODEL_TOP_P", "USE_MODEL_TOP_P", False),
    "top_k": ("MODEL_TOP_K", "USE_MODEL_TOP_K", False),
    "presence_penalty": ("MODEL_PRESENCE_PENALTY", "USE_MODEL_PRESENCE_PENALTY", False),
    "frequency_penalty": ("MODEL_FREQUENCY_PENALTY", "USE_MODEL_FREQUENCY_PENALTY", False),
}


def migrate_generation_settings(service, preset, dialect, settings=None):
    """Read the old contract once; subsequent requests use native JSON paths."""
    suggested = str(preset.get("settings_schema_id") or "")
    protocol = next((item for item in API_PROTOCOLS_DATA if item["id"] == preset.get("protocol_id")), {})
    suggested = suggested or str(protocol.get("settings_schema_id") or "")
    control = str((protocol.get("capabilities") or {}).get("reasoning_control") or "")
    control = str(((preset.get("protocol_overrides") or {}).get("capabilities") or {}).get("reasoning_control", control))
    if not suggested and control in {"openrouter", "reasoning_effort"}:
        suggested = "openrouter" if control == "openrouter" else "local-openai"
    identifier = service.default_id(dialect, suggested)
    state = service.create(identifier)
    overrides = preset.get("generation_overrides") or {}
    legacy = settings if settings is not None else {}
    profile = resolve_model_profile(
        str(preset.get("default_model") or ""), preset.get("model_profiles"),
        preset.get("model_profile_overrides"), default_safe=dialect == "gemini_generate_content",
    )
    thinking = profile.get("thinking") or {}
    if dialect == "gemini_generate_content" and thinking.get("transport") == "budget":
        if thinking.get("min_budget") == 128:
            identifier = "google-budget-pro"
        elif thinking.get("min_budget") == 512:
            identifier = "google-budget-lite"
        else:
            identifier = "google-budget"
        state = service.create(identifier)
    schema = service.repository.get(identifier)
    if dialect == "gemini_generate_content" and profile and not profile.get("native_structured_output", True):
        state["support_overrides"] = {"structured_output": False}
    if profile.get("safe_mode"):
        state["support_overrides"] = {"structured_output": False, "tools_native": False, "streaming": False}
    state["enabled"] = []
    for field in schema.fields:
        key = field["id"]
        spec = overrides.get(key) or {}
        if key in _LEGACY_FIELDS:
            setting, toggle, default_enabled = _LEGACY_FIELDS[key]
            enabled = bool(spec.get("enabled")) or bool(legacy.get(toggle, default_enabled))
            value = spec.get("value") if spec.get("enabled") else legacy.get(setting, field["default"])
            if value is None or value == "":
                value = field["default"]
            if dialect == "gemini_generate_content" and profile and key not in profile.get("parameters", []):
                enabled = False
            if key == "top_k" and str(value) == "0":
                enabled = False
            state["values"][key] = value
            if enabled:
                state["enabled"].append(key)
    et = overrides.get("enable_thinking") or {}
    enabled_thinking = et.get("value") if et.get("enabled") else legacy.get("ENABLE_THINKING")
    if isinstance(enabled_thinking, str):
        normalized = enabled_thinking.strip().lower()
        enabled_thinking = {"true": True, "yes": True, "1": True, "false": False, "no": False, "0": False}.get(normalized)
    effort_spec = overrides.get("reasoning_effort") or {}
    effort = effort_spec.get("value") if effort_spec.get("enabled") else legacy.get("MODEL_REASONING_EFFORT", "medium")
    if type(enabled_thinking) is bool:
        if dialect == "gemini_generate_content":
            if thinking.get("transport") == "level":
                value = effort if enabled_thinking else thinking.get("disabled_level")
                if value:
                    custom = deepcopy(schema.data)
                    levels = thinking.get("allowed_levels") or ["low", "medium", "high"]
                    for field in custom["fields"]:
                        if field["id"] == "thinking_level":
                            field["enum"] = levels
                            field["default"] = thinking.get("default_level") or levels[0]
                    default_levels = next(field["enum"] for field in schema.fields if field["id"] == "thinking_level")
                    if levels != default_levels:
                        state["schema_override"] = custom
                    state["values"]["thinking_level"] = value
                    state["enabled"].append("thinking_level")
            elif thinking.get("transport") == "budget":
                budget_spec = overrides.get("gemini_thinking_budget") or {}
                value = budget_spec.get("value") if budget_spec.get("enabled") else (
                    legacy.get("GEMINI_THINKING_BUDGET", -1) if legacy.get("USE_GEMINI_THINKING_BUDGET") else -1
                )
                if not enabled_thinking:
                    value = thinking.get("disabled_budget", 0)
                state["values"]["thinking_budget"] = value
                state["enabled"].append("thinking_budget")
            if enabled_thinking and "include_thoughts" in state["values"] and thinking.get("include_thoughts"):
                state["values"]["include_thoughts"] = True
                state["enabled"].append("include_thoughts")
        elif identifier == "openrouter":
            state["values"]["reasoning_enabled"] = enabled_thinking
            state["enabled"].append("reasoning_enabled")
            if enabled_thinking:
                budget_spec = overrides.get("thinking_budget") or {}
                budget = budget_spec.get("value") if budget_spec.get("enabled") else (
                    legacy.get("MODEL_THINKING_BUDGET", 0) if legacy.get("USE_MODEL_THINKING_BUDGET") else 0
                )
                try:
                    budget = int(float(budget or 0))
                except (ValueError, TypeError, OverflowError):
                    budget = 0
                allowed = thinking.get("allowed_levels") or []
                if effort and (not allowed or effort in allowed):
                    state["values"]["reasoning_effort"] = str(effort)
                    state["enabled"].append("reasoning_effort")
                elif budget > 0:
                    state["values"]["reasoning_max_tokens"] = budget
                    state["enabled"].append("reasoning_max_tokens")
        elif identifier == "local-openai":
            state["values"]["reasoning_effort"] = str(effort) if enabled_thinking else "none"
            state["enabled"].append("reasoning_effort")
        elif control == "deepseek":
            custom = deepcopy(schema.data)
            value = {"type": "enabled" if enabled_thinking else "disabled"}
            budget_spec = overrides.get("thinking_budget") or {}
            budget = budget_spec.get("value") if budget_spec.get("enabled") else (
                legacy.get("MODEL_THINKING_BUDGET", 0) if legacy.get("USE_MODEL_THINKING_BUDGET") else 0
            )
            try:
                budget = int(float(budget or 0))
            except (ValueError, TypeError, OverflowError):
                budget = 0
            if enabled_thinking and budget > 0:
                value["budget_tokens"] = budget
            custom["fields"].append({"id": "thinking", "type": "object", "path": ["thinking"], "default": value, "title": {"ru": "Режим мышления", "en": "Thinking mode"}})
            state["schema_override"] = custom
            state["values"]["thinking"] = value
            state["enabled"].append("thinking")
        elif dialect == "g4f":
            custom = deepcopy(schema.data)
            custom["fields"].append({"id": "enable_thinking", "type": "boolean", "path": ["enable_thinking"], "default": enabled_thinking, "title": {"ru": "Режим мышления", "en": "Thinking mode"}})
            state["schema_override"] = custom
            state["values"]["enable_thinking"] = enabled_thinking
            state["enabled"].append("enable_thinking")
    return state
