# src/utils/structured_response_parser.py
"""
Parser for structured JSON responses from LLMs.

Parses the raw JSON string into a StructuredResponse model,
validates the structure, and raises on invalid JSON
(no silent fallbacks).
"""
from __future__ import annotations

import json
import re
from typing import Optional

from main_logger import logger
from schemas.structured_response import StructuredResponse


class StructuredResponseParseError(Exception):
    """Raised when the LLM response cannot be parsed as a valid StructuredResponse."""
    pass


def parse_structured_response(raw_text: str) -> StructuredResponse:
    """
    Parse a raw LLM response string as a StructuredResponse.

    Attempts to extract valid JSON from the text (handles markdown fences,
    leading/trailing whitespace, etc.), then validates against the schema.

    Args:
        raw_text: The raw text returned by the LLM.

    Returns:
        A validated StructuredResponse instance.

    Raises:
        StructuredResponseParseError: If parsing or validation fails.
    """
    if not raw_text or not isinstance(raw_text, str):
        raise StructuredResponseParseError("Empty or non-string response")

    cleaned = _extract_json_string(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise StructuredResponseParseError(
            f"Invalid JSON in LLM response: {e}. "
            f"First 200 chars: {cleaned[:200]}"
        ) from e

    if not isinstance(data, dict):
        raise StructuredResponseParseError(
            f"Expected JSON object at top level, got {type(data).__name__}"
        )

    try:
        response = StructuredResponse.model_validate(data)
    except Exception as e:
        raise StructuredResponseParseError(
            f"JSON does not match StructuredResponse schema: {e}"
        ) from e

    if not response.segments:
        raise StructuredResponseParseError(
            "StructuredResponse has no segments (segments list is empty)"
        )

    logger.debug(
        f"[StructuredResponseParser] Parsed {len(response.segments)} segment(s), "
        f"attitude_change={response.attitude_change}, "
        f"boredom_change={response.boredom_change}, "
        f"stress_change={response.stress_change}"
    )

    return response


def _extract_json_string(text: str) -> str:
    """
    Extract the JSON object from the raw text, handling common LLM quirks:
    - Markdown code fences (```json ... ```)
    - Leading/trailing whitespace
    - BOM characters
    """
    text = text.strip()

    # Remove BOM if present
    if text.startswith("\ufeff"):
        text = text[1:]

    # Strip markdown code fences
    if text.startswith("```json"):
        text = text[len("```json"):]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    # Try to find the outermost { ... } if there's extra text around it
    if not text.startswith("{"):
        brace_start = text.find("{")
        if brace_start == -1:
            return text  # let json.loads fail with a proper error
        text = text[brace_start:]

    if not text.endswith("}"):
        brace_end = text.rfind("}")
        if brace_end != -1:
            text = text[:brace_end + 1]

    return text


def structured_response_to_result_dict(response: StructuredResponse) -> dict:
    """
    Convert a StructuredResponse into the dict format expected by the
    Unity communication pipeline (task result).

    Returns a dict with:
    - "response": full concatenated text (for TTS)
    - "segments": list of segment dicts (for Unity processing)
    - "attitude_change", "boredom_change", "stress_change"
    - "memory_add", "memory_update", "memory_delete"
    """
    segments_out = []
    for seg in response.segments:
        seg_dict = {"text": seg.text}

        # Only include non-empty optional fields
        if seg.emotions:
            seg_dict["emotions"] = seg.emotions
        if seg.animations:
            seg_dict["animations"] = seg.animations
        if seg.idle_animations:
            seg_dict["idle_animations"] = seg.idle_animations
        if seg.commands:
            seg_dict["commands"] = seg.commands
        if seg.movement_modes:
            seg_dict["movement_modes"] = seg.movement_modes
        if seg.visual_effects:
            seg_dict["visual_effects"] = seg.visual_effects
        if seg.clothes:
            seg_dict["clothes"] = seg.clothes
        if seg.music:
            seg_dict["music"] = seg.music
        if seg.interactions:
            seg_dict["interactions"] = seg.interactions
        if seg.face_params:
            seg_dict["face_params"] = seg.face_params
        if seg.start_game is not None:
            seg_dict["start_game"] = seg.start_game
        if seg.end_game is not None:
            seg_dict["end_game"] = seg.end_game
        if seg.target is not None:
            seg_dict["target"] = seg.target
        if seg.hint is not None:
            seg_dict["hint"] = seg.hint
        if seg.allow_sleep is not None:
            seg_dict["allow_sleep"] = seg.allow_sleep

        segments_out.append(seg_dict)

    return {
        "response": response.full_text(),
        "segments": segments_out,
        "attitude_change": response.attitude_change,
        "boredom_change": response.boredom_change,
        "stress_change": response.stress_change,
        "memory_add": list(response.memory_add),
        "memory_update": list(response.memory_update),
        "memory_delete": list(response.memory_delete),
    }
