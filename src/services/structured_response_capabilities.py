"""Request-scoped policy for structured response fields and execution."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from services.contracts import RuntimeCapabilities


@dataclass(frozen=True, slots=True)
class StructuredResponseCapabilities:
    runtime_connected: bool | None
    remote_only: bool | None
    runtime_segment_exclusions: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    excluded_segment_fields: tuple[str, ...]
    request_segment_exclusions: tuple[str, ...]
    required_fields: tuple[str, ...]
    has_custom_params: bool
    schema_reasoning: bool
    images_available: bool
    inline_image_description_enabled: bool
    tools_enabled: bool
    enabled_tools: tuple[str, ...]
    tool_depth: int
    tool_max_depth: int
    prompt_intents: bool | None = None
    sparse_enabled: bool = False

    def with_context_images(self, messages: Iterable[Mapping[str, Any]]) -> "StructuredResponseCapabilities":
        has_images = self.images_available or context_has_images(messages)
        has_image_description = has_images and self.inline_image_description_enabled
        excluded = set(self.excluded_fields)
        if has_image_description:
            excluded.discard("image_description")
        else:
            excluded.add("image_description")
        return replace(
            self,
            images_available=has_images,
            excluded_fields=tuple(sorted(excluded)),
        )

    def with_prompt_intents(self, enabled: bool) -> "StructuredResponseCapabilities":
        excluded = set(self.request_segment_exclusions)
        if not enabled:
            excluded.add("intents")
        return replace(
            self,
            prompt_intents=bool(enabled),
            excluded_segment_fields=tuple(sorted(excluded)),
        )

    def at_tool_depth(self, depth: int) -> "StructuredResponseCapabilities":
        depth = max(0, int(depth))
        excluded = set(self.excluded_fields)
        if not self.tools_enabled or depth >= self.tool_max_depth:
            excluded.add("tool_call")
        else:
            excluded.discard("tool_call")
        return replace(
            self,
            tool_depth=depth,
            excluded_fields=tuple(sorted(excluded)),
        )

    @property
    def can_call_tools(self) -> bool:
        return (
            self.tools_enabled
            and bool(self.enabled_tools)
            and self.tool_depth < self.tool_max_depth
        )

    def prompt_features(self) -> dict[str, bool]:
        fields = set(self.excluded_fields)
        segments = set(self.excluded_segment_fields)
        return {
            "response_has_reasoning": "reasoning" not in fields,
            "response_has_working_state": "working_state" not in fields,
            "response_has_custom_fields": "custom_fields" not in fields,
            "response_has_secret": "secret_exposed" not in fields,
            "response_has_graph": not ({"entities", "relations"} & fields),
            "response_has_tools": "tool_call" not in fields,
            "response_has_reminders": not ({"reminder_add", "reminder_delete"} & fields),
            "response_has_timers": "timer_add" not in fields,
            "response_has_image_description": "image_description" not in fields,
            "response_has_intents": "intents" not in segments,
            **{
                f"response_segment_{name}": name not in segments
                for name in (
                    "emotions", "animations", "idle_animations", "commands",
                    "movement_modes", "visual_effects", "clothes", "music",
                    "interactions", "face_params", "start_game", "end_game",
                    "target", "hint", "allow_sleep",
                )
            },
        }

    def schema_options(self) -> dict[str, set[str]]:
        return {
            "exclude_fields": set(self.excluded_fields),
            "exclude_segment_fields": set(self.excluded_segment_fields),
            "require_fields": set(self.required_fields),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_connected": self.runtime_connected,
            "remote_only": self.remote_only,
            "excluded_fields": list(self.excluded_fields),
            "excluded_segment_fields": list(self.excluded_segment_fields),
            "required_fields": list(self.required_fields),
            "images_available": self.images_available,
            "tools_enabled": self.tools_enabled,
            "enabled_tools": list(self.enabled_tools),
            "tool_depth": self.tool_depth,
            "tool_max_depth": self.tool_max_depth,
            "prompt_intents": self.prompt_intents,
            "sparse_enabled": self.sparse_enabled,
        }

    def sanitize_response(self, response: Any) -> None:
        excluded = set(self.excluded_fields)
        if not self.can_call_tools:
            excluded.add("tool_call")
        tool_call = getattr(response, "tool_call", None)
        if tool_call is not None and str(getattr(tool_call, "name", "")) not in self.enabled_tools:
            excluded.add("tool_call")

        for name in excluded:
            if hasattr(response, name):
                setattr(response, name, None)

        for segment in getattr(response, "segments", ()) or ():
            for name in self.excluded_segment_fields:
                if not hasattr(segment, name):
                    continue
                current = getattr(segment, name)
                setattr(segment, name, [] if isinstance(current, list) else None)


def _setting(settings: Any, name: str, default: Any) -> Any:
    getter = getattr(settings, "get", None)
    if callable(getter):
        try:
            return getter(name, default)
        except Exception:
            return default
    return default


def context_has_images(messages: Iterable[Mapping[str, Any]]) -> bool:
    """Detect image parts recursively in the exact history sent to a provider."""
    def contains(value: Any) -> bool:
        if isinstance(value, Mapping):
            if "inline_data" in value or "image_url" in value or value.get("type") in {
                "image", "image_url", "input_image"
            }:
                return True
            return any(contains(child) for child in value.values())
        if isinstance(value, (list, tuple)):
            return any(contains(child) for child in value)
        if isinstance(value, str):
            return value.lstrip().lower().startswith("data:image/")
        return False

    return contains(messages)


def resolve_structured_response_capabilities(
    *,
    settings: Any,
    runtime: RuntimeCapabilities,
    character: Any,
    structured_output: bool,
    tools_enabled: bool,
    enabled_tools: Iterable[str],
    tools_mode: str,
    tool_depth: int,
    tool_max_depth: int,
    images_available: bool,
    has_custom_params: bool,
    schema_reasoning: bool,
    sparse_enabled: bool = False,
) -> StructuredResponseCapabilities:
    excluded = set()
    segment_excluded = set(runtime.structured_segment_exclude_fields)
    if not bool(_setting(settings, "ENABLE_GAMES", False)):
        segment_excluded.update(("start_game", "end_game"))

    if not (bool(_setting(settings, "RAG_ENABLED", False)) and bool(
        _setting(settings, "GRAPH_EXTRACTION_ENABLED", False)
    )):
        excluded.update(("entities", "relations"))

    reminders_enabled = bool(_setting(settings, "REMINDERS_ENABLED", True))
    if not reminders_enabled:
        excluded.update(("reminder_add", "reminder_delete"))
    if not reminders_enabled:
        excluded.add("timer_add")

    active_tools = tuple(sorted({str(name).strip() for name in enabled_tools if str(name).strip()}))
    tools_enabled = bool(
        structured_output
        and tools_enabled
        and str(tools_mode or "native").strip().lower() != "off"
        and active_tools
        and int(tool_depth) < int(tool_max_depth)
    )
    if not tools_enabled:
        excluded.add("tool_call")

    inline_image_description_enabled = bool(
        _setting(settings, "IMAGE_INLINE_DESCRIPTION", False)
    )
    if not (images_available and inline_image_description_enabled):
        excluded.add("image_description")

    secret_capable = bool(getattr(character, "secret_capable", False))
    secret_revealed = bool(getattr(character, "secret_revealed", False))
    if not secret_capable or secret_revealed:
        excluded.add("secret_exposed")
    required = ("secret_exposed",) if secret_capable and not secret_revealed else ()

    if not schema_reasoning:
        excluded.add("reasoning")
    if not (
        bool(_setting(settings, "ENABLE_WORKING_STATE", False))
        and structured_output
    ):
        excluded.add("working_state")
    if not has_custom_params:
        excluded.add("custom_fields")

    return StructuredResponseCapabilities(
        runtime_connected=runtime.connected,
        remote_only=runtime.remote_only,
        runtime_segment_exclusions=tuple(runtime.structured_segment_exclude_fields),
        excluded_fields=tuple(sorted(excluded)),
        excluded_segment_fields=tuple(sorted(segment_excluded)),
        request_segment_exclusions=tuple(sorted(segment_excluded)),
        required_fields=required,
        has_custom_params=bool(has_custom_params),
        schema_reasoning=bool(schema_reasoning),
        images_available=bool(images_available),
        inline_image_description_enabled=inline_image_description_enabled,
        tools_enabled=tools_enabled,
        enabled_tools=active_tools,
        tool_depth=max(0, int(tool_depth)),
        tool_max_depth=max(0, int(tool_max_depth)),
        sparse_enabled=bool(sparse_enabled),
    )


def provider_schema_options(capabilities: Mapping[str, Any]) -> dict[str, set[str]]:
    """Return common wire-schema options, retaining legacy caller support."""
    profile = capabilities.get("structured_response_profile")
    if isinstance(profile, StructuredResponseCapabilities):
        return profile.schema_options()

    excluded = set(capabilities.get("structured_exclude_fields") or ())
    if not (capabilities.get("has_custom_params") or capabilities.get("custom_params")):
        excluded.add("custom_fields")
    if not capabilities.get("schema_reasoning", True):
        excluded.add("reasoning")
    segment_excluded = set(capabilities.get("structured_segment_exclude_fields") or ())
    if not capabilities.get("schema_intents", True):
        segment_excluded.add("intents")
    return {
        "exclude_fields": excluded,
        "exclude_segment_fields": segment_excluded,
        "require_fields": set(capabilities.get("structured_required_fields") or ()),
    }


__all__ = [
    "StructuredResponseCapabilities",
    "context_has_images",
    "provider_schema_options",
    "resolve_structured_response_capabilities",
]
