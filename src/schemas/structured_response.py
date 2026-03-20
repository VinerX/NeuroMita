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

from typing import List, Optional

from pydantic import BaseModel, Field


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


class ResponseSegment(BaseModel):
    """A single segment of the response tied to a chunk of displayed text."""

    text: str = Field(..., description="Text of this segment (required)")

    emotions: List[str] = Field(default_factory=list, description="Emotion IDs to set for this segment")
    animations: List[str] = Field(default_factory=list, description="Animations to play once during this segment")
    idle_animations: List[str] = Field(default_factory=list, description="Animations to set as looping idle")
    commands: List[str] = Field(default_factory=list, description="Game commands to execute")
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

    # Secret reveal flag — set to true when the character's secret is discovered.
    # Processed by character-specific logic (e.g. CrazyMita sets secretExposed variable).
    secret_exposed: Optional[bool] = Field(
        default=None,
        description="Set to true when the player has discovered your secret identity or hidden nature. "
                    "Only use once — when the secret is first revealed."
    )

    # Optional reasoning field — lets the model "think" inside the JSON itself.
    # Extracted as a think block in the UI, not shown in the main message.
    reasoning: Optional[str] = Field(
        default=None,
        description="Your internal reasoning / chain-of-thought before answering. "
                    "Write your analysis here, then fill the rest of the fields. "
                    "This field is never shown to the player."
    )

    # Global fields (not tied to a specific segment)
    attitude_change: float = Field(default=0.0, description="Change in attitude (-6 to 6)")
    boredom_change: float = Field(default=0.0, description="Change in boredom (-6 to 6)")
    stress_change: float = Field(default=0.0, description="Change in stress (-6 to 6)")

    memory_add: List[str] = Field(default_factory=list, description="Memories to add")
    memory_update: List[str] = Field(default_factory=list, description="Memories to update (format: 'number|new_text')")
    memory_delete: List[str] = Field(default_factory=list, description="Memories to delete (format: 'number' or 'start-end')")

    segments: List[ResponseSegment] = Field(
        default_factory=list,
        description="Ordered list of response segments with positional commands",
    )

    def full_text(self) -> str:
        """Concatenate all segment texts (for TTS and history)."""
        return " ".join(seg.text for seg in self.segments if seg.text)

    @classmethod
    def openai_response_format(cls) -> dict:
        """
        Return the ``response_format`` payload for the OpenAI API.

        Format::

            {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "strict": True,
                    "schema": { ... }
                }
            }
        """
        schema = cls.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "strict": True,
                "schema": schema,
            },
        }

    @classmethod
    def json_schema_dict(cls) -> dict:
        """Return the raw JSON Schema dict (e.g. for Gemini or other providers)."""
        return cls.model_json_schema()

    @classmethod
    def gemini_schema_dict(cls) -> dict:
        """
        Return a Gemini-compatible responseSchema dict.

        Strips all JSON Schema features Gemini doesn't support:
        $ref/$defs, anyOf/null, default, title, additionalProperties.
        Converts Optional[X] → {type: X, nullable: true}.
        """
        return _to_gemini_schema(cls.model_json_schema())
