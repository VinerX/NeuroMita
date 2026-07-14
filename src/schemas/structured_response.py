# src/schemas/structured_response.py
"""
Pydantic models for LLM Structured Output.

Defines the JSON schema that the LLM must return when structured output
is enabled (protocol capability ``structured_output == True``).

Usage::

    from schemas.structured_response import StructuredResponse

    # Get JSON Schema dict for OpenAI response_format
    schema = StructuredResponse.openai_response_format()

    # Parse a raw JSON string from the LLM
    obj = StructuredResponse.model_validate_json(raw_json)
"""
from __future__ import annotations

import re
import hashlib
import json as _json
from typing import Any, Dict, List, Optional, Union, Type

from pydantic import BaseModel, Field, model_validator, create_model

def _to_gemini_schema(schema: dict) -> dict:
    """
    Convert a Pydantic-generated JSON Schema to a Gemini-compatible responseSchema.

    Gemini supports only a strict subset of OpenAPI 3.0:
      - Supported: type, description, properties, required, items, enum, nullable
      - NOT supported: $ref/$defs, anyOf/oneOf/allOf, default, title,
                       additionalProperties, $schema

    Transformations applied:
      1. Resolve all $ref / $defs inline.
      2. Strip: title, default, additionalProperties, $schema, $defs.
      3. Convert  anyOf: [{type: X}, {type: null}]  →  {type: X, nullable: true}.
      4. Recurse into properties, items, anyOf members, etc.
    """
    import copy

    defs = schema.get("$defs", {})

    _STRIP_KEYS = {"title", "default", "additionalProperties", "$schema", "$defs"}

    def convert(node):
        if not isinstance(node, dict):
            return node

        # Resolve $ref first
        if "$ref" in node:
            ref_path = node["$ref"]
            if ref_path.startswith("#/$defs/"):
                def_name = ref_path[len("#/$defs/"):]
                if def_name in defs:
                    return convert(copy.deepcopy(defs[def_name]))
            return node  # unresolvable

        # Collapse anyOf: [{type: X, ...}, {type: null}]  →  {type: X, nullable: true}
        if "anyOf" in node and isinstance(node["anyOf"], list):
            members = node["anyOf"]
            null_members = [m for m in members if m == {"type": "null"} or m.get("type") == "null"]
            non_null = [m for m in members if m not in null_members and m.get("type") != "null"]
            if null_members and len(non_null) == 1:
                merged = convert(copy.deepcopy(non_null[0]))
                merged["nullable"] = True
                # Carry over description from the outer node if present
                if "description" in node and "description" not in merged:
                    merged["description"] = node["description"]
                return merged
            # Otherwise drop anyOf entirely (unsupported) — use first non-null member
            if non_null:
                return convert(copy.deepcopy(non_null[0]))

        # Build clean result, recursing into sub-nodes
        result = {}
        for key, value in node.items():
            if key in _STRIP_KEYS or key.startswith("$"):
                continue
            if key == "anyOf":
                continue  # already handled above or skipping
            if isinstance(value, dict):
                result[key] = convert(value)
            elif isinstance(value, list):
                result[key] = [convert(item) if isinstance(item, dict) else item
                               for item in value]
            else:
                result[key] = value
        return result

    return convert(copy.deepcopy(schema))


def _remove_schema_properties(schema: dict, field_names: set[str]) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return

    for field_name in field_names:
        properties.pop(field_name, None)

    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [name for name in required if name not in field_names]


def _remove_segment_schema_properties(schema: dict, field_names: set[str]) -> None:
    """Remove selected fields from the nested ``segments.items`` schema."""
    if not field_names:
        return

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return

    segments_schema = properties.get("segments")
    if not isinstance(segments_schema, dict):
        return

    items_schema = segments_schema.get("items")
    targets: list[dict] = []
    if isinstance(items_schema, dict):
        targets.append(items_schema)

        ref = str(items_schema.get("$ref") or "")
        if ref.startswith("#/$defs/"):
            definition = schema.get("$defs", {}).get(ref[len("#/$defs/"):])
            if isinstance(definition, dict):
                targets.append(definition)

    seen: set[int] = set()
    for target in targets:
        marker = id(target)
        if marker in seen:
            continue
        seen.add(marker)
        _remove_schema_properties(target, field_names)




class ToolCall(BaseModel):
    """Describes a tool the LLM wants to invoke during its response."""

    name: str = Field(..., description="Exact name of the tool to call, chosen from the available tools list in the prompt")
    # Union allows Gemini to return args as a JSON string (Gemini can't freely use object type)
    args: Union[Dict[str, Any], str] = Field(
        default_factory=dict,
        description='Tool arguments as key-value pairs, e.g. {"query": "search term"}'
    )

    @model_validator(mode="after")
    def _coerce_args(self) -> "ToolCall":
        """If Gemini returned args as a JSON string, parse it into a dict."""
        if isinstance(self.args, str):
            try:
                parsed = _json.loads(self.args)
                self.args = parsed if isinstance(parsed, dict) else {}
            except Exception:
                self.args = {}
        return self


class ResponseSegment(BaseModel):
    """A single segment of the response tied to a chunk of displayed text."""

    text: str = Field(..., description="Text of this segment (required)")

    emotions: List[str] = Field(default_factory=list, description="Emotion IDs to set for this segment")
    animations: List[str] = Field(default_factory=list, description="Animations to play once during this segment")
    idle_animations: List[str] = Field(default_factory=list, description="Animations to set as looping idle")
    commands: List[str] = Field(default_factory=list, description="Game commands to execute (supports prefix routing: light:*, music:*, eye:*)")
    movement_modes: List[str] = Field(default_factory=list, description="Movement mode changes")
    visual_effects: List[str] = Field(default_factory=list, description="Visual effects to trigger")
    clothes: List[str] = Field(default_factory=list, description="Clothing/outfit changes")
    music: List[str] = Field(default_factory=list, description="Music changes")
    interactions: List[str] = Field(default_factory=list, description="Interaction commands")
    face_params: List[str] = Field(default_factory=list, description="Face parameter adjustments")

    start_game: Optional[str] = Field(default=None, description="Game ID to start")
    end_game: Optional[str] = Field(default=None, description="Game ID to end")
    target: Optional[str] = Field(default=None, description="Target character name for this segment")
    hint: Optional[str] = Field(default=None, description="Hint text to display")
    allow_sleep: Optional[bool] = Field(default=None, description="Whether to allow sleep")


class StructuredResponse(BaseModel):
    """Top-level structured response from the LLM."""

    # Optional reasoning field — lets the model "think" inside the JSON itself.
    # Extracted as a think block in the UI, not shown in the main message.
    # Must be first so the model reasons before writing segments.
    reasoning: Optional[str] = Field(
        default=None,
        description="Your internal reasoning / chain-of-thought before answering. "
                    "Write your analysis here, then fill the rest of the fields. "
                    "This field is never shown to the player."
    )

    image_description: Optional[str] = Field(
        default=None,
        description="If the user sent one or more images, briefly describe what you see "
                    "before composing your segments. This description is stored in memory "
                    "and never shown to the player. Omit if no images were received."
    )

    segments: List[ResponseSegment] = Field(
        default_factory=list,
        description="Ordered list of response segments with positional commands",
    )

    # Secret reveal flag — set to true when the character's secret is discovered.
    # Processed by character-specific logic (e.g. CrazyMita sets secretExposed variable).
    secret_exposed: Optional[bool] = Field(
        default=None,
        description="Set to true when the player has discovered your secret identity or hidden nature. "
                    "Only use once — when the secret is first revealed."
    )

    # Global fields (not tied to a specific segment)
    attitude_change: float = Field(default=0.0, description="Change in attitude (-6 to 6)")
    boredom_change: float = Field(default=0.0, description="Change in boredom (-6 to 6)")
    stress_change: float = Field(default=0.0, description="Change in stress (-6 to 6)")

    memory_add: Optional[List[str]] = Field(default=None, description="Memories to add. Format: 'priority|content' (priority: low/normal/high/critical). Example: ['high|Player prefers tea', 'normal|Cat name is Barsik']")
    memory_update: Optional[List[str]] = Field(default=None, description="Memories to update. Format: 'number|priority|content' (priority: low/normal/high/critical). Example: ['4|high|Updated content here']")
    memory_delete: Optional[List[str]] = Field(default=None, description="Memories to delete. Format: 'number', range 'start-end', or comma-separated 'n1,n2'. Example: ['2', '5-8']")
    memory_merge: Optional[List[str]] = Field(default=None, description="Merge memories into the first ID. Format: 'id1,id2,...' or 'id1,id2,...:merged content'. All IDs after the first are deleted; first is updated with merged content. Example: ['3,7', '5,9,12:Combined fact text']")

    reminder_add: Optional[List[str]] = Field(
        default=None,
        description="Reminders to set. Format: 'YYYY-MM-DDTHH:MM:SS|reminder text'. Example: '2026-04-03T15:00:00|Remind player about the meeting'."
    )
    reminder_delete: Optional[List[str]] = Field(
        default=None,
        description="Reminder IDs to delete. Format: 'N' (number). Example: '3'."
    )

    entities: Optional[List[str]] = Field(
        default=None,
        description="Notable named entities. Format: 'name:type'. Types: person|place|thing|concept. "
                    "Example: ['player:person', 'cats:thing']. Fill only when instructed. Omit if not needed."
    )

    relations: Optional[List[str]] = Field(
        default=None,
        description="Relation triples. Format: 'subject|predicate|object'. "
                    "Example: ['player|likes|cats', 'mita|is afraid of|darkness']. Fill only when instructed. Omit if not needed."
    )

    tool_call: Optional[ToolCall] = Field(
        default=None,
        description=(
            "Use this field when you need to call an external tool (web search, calculator, etc.). "
            "In 'segments', write a natural acknowledgement ('Let me check that'). "
            "You will receive the tool result in the next message and can then answer fully. "
            "Leave null (omit) if no tool is needed."
        )
    )

    custom_fields: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Custom character-specific parameters defined by the prompter. "
            "Keys and their meaning are described in the response format instructions."
        )
    )

    def full_text(self) -> str:
        """Concatenate all segment texts (for TTS and history)."""
        parts = [seg.text for seg in self.segments if seg.text is not None]
        return " ".join(p for p in parts if p).strip()

    @classmethod
    def openai_response_format(
        cls,
        exclude_fields: set = None,
        custom_params: list = None,
        exclude_segment_fields: set = None,
    ) -> dict:
        """
        Return the ``response_format`` payload for the OpenAI API.

        ``exclude_segment_fields`` removes fields from the nested segment
        schema while keeping the internal Pydantic model backward-compatible.

        Format::

            {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "strict": False,
                    "schema": { ... }
                }
            }
        """
        schema = cls.model_json_schema()
        if custom_params and "properties" in schema and "custom_fields" in schema["properties"]:
            _type_map = {"float": "number", "double": "number", "int": "integer",
                         "bool": "boolean", "str": "string", "string": "string"}
            cf_props = {}
            for p in custom_params:
                key = p.get("change_command") or p["name"]
                cf_props[key] = {"type": _type_map.get(p.get("type", "string"), "string")}
            schema["properties"]["custom_fields"]["properties"] = cf_props
        if exclude_fields:
            _remove_schema_properties(schema, exclude_fields)
        if exclude_segment_fields:
            _remove_segment_schema_properties(schema, exclude_segment_fields)
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "strict": False,
                "schema": schema,
            },
        }

    @classmethod
    def json_schema_dict(cls) -> dict:
        """Return the raw JSON Schema dict (e.g. for Gemini or other providers)."""
        return cls.model_json_schema()

    @classmethod
    def gemini_schema_dict(
        cls,
        exclude_fields: set = None,
        custom_params: list = None,
        exclude_segment_fields: set = None,
    ) -> dict:
        """
        Return a Gemini-compatible responseSchema dict.

        Strips all JSON Schema features Gemini doesn't support:
        $ref/$defs, anyOf/null, default, title, additionalProperties.
        Converts Optional[X] → {type: X, nullable: true}.

        Special case: tool_call.args is patched to type=string so Gemini
        can freely write JSON arguments instead of being constrained to an
        empty object (Gemini doesn't support free-form additionalProperties).

        Args:
            exclude_fields: optional set of top-level field names to remove
                from the schema (e.g. {"custom_fields"} when no custom_params).
            exclude_segment_fields: optional set of fields to remove from the
                nested ``segments`` item schema.
            custom_params: list of custom param dicts from config.json; when
                provided, patches custom_fields.properties so Gemini allows
                the declared keys (without this Gemini strips all keys from
                a free-form object and returns {}).
        """
        schema = _to_gemini_schema(cls.model_json_schema())
        # Patch tool_call.args: object without properties → string
        try:
            tc_props = schema["properties"]["tool_call"]["properties"]
            tc_props["args"] = {
                "type": "string",
                "description": 'JSON-encoded tool arguments, e.g. {"query": "search term"}',
            }
        except (KeyError, TypeError):
            pass
        # Patch custom_fields: inject explicit per-param properties so Gemini
        # doesn't strip keys the model writes into a free-form object.
        if custom_params and "custom_fields" in schema.get("properties", {}):
            _type_map = {
                "float": "number", "double": "number",
                "int": "integer", "bool": "boolean",
                "str": "string", "string": "string",
            }
            cf_props = {}
            for p in custom_params:
                key = p.get("change_command") or p["name"]
                gemini_type = _type_map.get(p.get("type", "string"), "string")
                cf_props[key] = {"type": gemini_type, "nullable": True}
            schema["properties"]["custom_fields"]["properties"] = cf_props
        if exclude_fields:
            _remove_schema_properties(schema, exclude_fields)
        if exclude_segment_fields:
            _remove_segment_schema_properties(schema, exclude_segment_fields)
        return schema


def build_structured_response_model(custom_params: list[dict] | None) -> Type[StructuredResponse]:
    custom_params = custom_params or []
    key_s = ""
    try:
        import json as _json
        key_s = _json.dumps(custom_params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        key_s = str(custom_params)

    h = hashlib.md5(key_s.encode("utf-8", errors="ignore")).hexdigest()[:12]
    cache_key = f"sr:{h}"

    _cache = getattr(build_structured_response_model, "_cache", None)
    if not isinstance(_cache, dict):
        _cache = {}
        setattr(build_structured_response_model, "_cache", _cache)
    if cache_key in _cache:
        return _cache[cache_key]

    type_map = {
        "float": float,
        "double": float,
        "number": float,
        "int": int,
        "integer": int,
        "bool": bool,
        "boolean": bool,
        "str": str,
        "string": str,
    }

    def infer_default(py_t: type):
        if py_t is float:
            return 0.0
        if py_t is int:
            return 0
        if py_t is bool:
            return False
        return ""

    fields: Dict[str, tuple[Any, Any]] = {}
    any_required = False

    for p in custom_params:
        if not isinstance(p, dict):
            continue
        # Имя поля в JSON-ответе нейронки — change_command (по умолчанию = name)
        field_key = str(p.get("change_command") or p.get("name") or "").strip()
        if not field_key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_key):
            continue

        tname = str(p.get("type") or "string").strip().lower()
        py_t = type_map.get(tname, str)

        required = bool(p.get("required", True))
        nullable = bool(p.get("nullable", False))

        desc = str(p.get("description") or "").strip()

        default = p.get("default", None)
        if default is None and not required:
            default = infer_default(py_t)
        if default is None and required:
            default = ...

        anno = Optional[py_t] if nullable else py_t

        f_kwargs: Dict[str, Any] = {}
        if desc:
            f_kwargs["description"] = desc

        # Ограничения на входное значение от нейронки (change_min/change_max)
        if py_t in (int, float):
            mn = p.get("change_min", None)
            mx = p.get("change_max", None)
            if mn is not None:
                f_kwargs["ge"] = mn
            if mx is not None:
                f_kwargs["le"] = mx

        fields[field_key] = (anno, Field(default, **f_kwargs))
        if required:
            any_required = True

    if not fields:
        _cache[cache_key] = StructuredResponse
        return StructuredResponse

    CustomFieldsModel = create_model(f"CustomFields_{h}", **fields)

    custom_fields_default = ... if any_required else None
    Extended = create_model(
        f"ExtendedStructuredResponse_{h}",
        __base__=StructuredResponse,
        custom_fields=(Optional[CustomFieldsModel], Field(custom_fields_default)),
    )

    _cache[cache_key] = Extended
    return Extended
