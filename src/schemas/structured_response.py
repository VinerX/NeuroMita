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


def _inline_refs(schema: dict) -> dict:
    """
    Resolve all $ref/$defs in a JSON Schema dict, returning a fully inlined copy.

    Gemini's response_schema only accepts a flat OpenAPI-subset schema with no
    references — every type must be spelled out inline.
    """
    import copy

    defs = schema.get("$defs", {})

    def resolve(node):
        if not isinstance(node, dict):
            return node

        # Resolve $ref
        if "$ref" in node:
            ref_path = node["$ref"]  # e.g. "#/$defs/ResponseSegment"
            if ref_path.startswith("#/$defs/"):
                def_name = ref_path[len("#/$defs/"):]
                if def_name in defs:
                    return resolve(copy.deepcopy(defs[def_name]))
            return node  # unresolvable ref — leave as-is

        # Recurse into object
        result = {}
        for key, value in node.items():
            if key == "$defs":
                continue  # strip out the definitions block
            if isinstance(value, dict):
                result[key] = resolve(value)
            elif isinstance(value, list):
                result[key] = [resolve(item) if isinstance(item, dict) else item
                               for item in value]
            else:
                result[key] = value
        return result

    return resolve(copy.deepcopy(schema))


class ResponseSegment(BaseModel):
    """A single segment of the response tied to a chunk of displayed text."""

    text: str = Field(..., description="Text of this segment (required)")

    emotions: List[str] = Field(default_factory=list, description="Emotion IDs to set for this segment")
    animations: List[str] = Field(default_factory=list, description="Animations to play during this segment")
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
        Return a Gemini-compatible schema with all $ref/$defs inlined.

        Gemini's response_schema does not support JSON Schema $ref or $defs —
        all nested types must be fully inlined.
        """
        schema = cls.model_json_schema()
        return _inline_refs(schema)
