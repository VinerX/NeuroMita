# src/utils/structured_response_parser.py
"""
Parser for structured JSON responses from LLMs.

Parses the raw JSON string into a StructuredResponse model,
validates the structure, and raises on invalid JSON
(no silent fallbacks).

Repair cascade (each step tried only if the previous fails):
  1. json.loads directly
  2. _simple_text_repair   — trailing commas, unescaped newlines
  3. json_repair library   — handles most malformed JSON
  4. _close_truncated_json — bracket-counting closer for cut-off responses
  5. _schema_aware_coerce  — applied after any successful json.loads when
                             Pydantic validation fails (type coercions)
  6. _extract_partial      — regex text extraction as last resort
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
    leading/trailing whitespace, BOM, etc.), then validates against the schema.
    If direct parsing fails, a multi-level repair cascade is attempted.

    Args:
        raw_text: The raw text returned by the LLM.

    Returns:
        A validated StructuredResponse instance.

    Raises:
        StructuredResponseParseError: If all repair attempts fail.
    """
    if not raw_text or not isinstance(raw_text, str):
        raise StructuredResponseParseError("Empty or non-string response")

    cleaned = _extract_json_string(raw_text)

    # --- Level 1: direct parse ---
    data, parse_level = _try_json_loads(cleaned, level="direct")

    # --- Level 2: simple text repair ---
    if data is None:
        repaired = _simple_text_repair(cleaned)
        data, parse_level = _try_json_loads(repaired, level="simple_repair")

    # --- Level 3: json_repair library ---
    if data is None:
        data, parse_level = _try_json_repair_lib(cleaned)

    # --- Level 4: close truncated JSON ---
    if data is None:
        closed = _close_truncated_json(cleaned)
        data, parse_level = _try_json_loads(closed, level="truncation_close")

    if data is None:
        # Try json_repair on the closed version too
        data, parse_level = _try_json_repair_lib(_close_truncated_json(cleaned),
                                                  level="truncation_close+json_repair")

    if data is None:
        raise StructuredResponseParseError(
            f"All JSON repair attempts failed. "
            f"First 300 chars: {cleaned[:300]}"
        )

    if not isinstance(data, dict):
        raise StructuredResponseParseError(
            f"Expected JSON object at top level, got {type(data).__name__}"
        )

    if parse_level != "direct":
        logger.warning(f"[StructuredResponseParser] JSON repaired via: {parse_level}")

    # --- Pydantic validation (with schema-aware coerce on failure) ---
    response = _validate_with_coerce(data)

    # --- Legacy flat-JSON fallback (empty segments) ---
    if not response.segments:
        converted = _try_convert_legacy_flat_json(data)
        if converted is not None:
            logger.warning(
                "[StructuredResponseParser] Segments missing — used legacy flat-JSON fallback"
            )
            return converted

        # --- Level 5: partial extraction ---
        partial = _extract_partial_response(raw_text)
        if partial is not None:
            logger.warning(
                "[StructuredResponseParser] Segments missing — used partial text extraction"
            )
            return partial

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_json_loads(text: str, level: str = "direct") -> tuple[Optional[dict], str]:
    """Try json.loads; return (data, level) or (None, '')."""
    try:
        return json.loads(text), level
    except (json.JSONDecodeError, ValueError):
        return None, ""


def _try_json_repair_lib(text: str, level: str = "json_repair") -> tuple[Optional[dict], str]:
    """Try the json_repair library; return (data, level) or (None, '')."""
    try:
        from json_repair import repair_json  # type: ignore
        result = repair_json(text, return_objects=True)
        if isinstance(result, dict):
            return result, level
        return None, ""
    except ImportError:
        logger.debug("[StructuredResponseParser] json_repair not installed, skipping")
        return None, ""
    except Exception:
        return None, ""


def _simple_text_repair(text: str) -> str:
    """
    Level-2 text repairs:
    - Remove trailing commas before } or ]
    - Escape literal newlines inside JSON strings
    """
    # Trailing commas before closing bracket/brace
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Unescaped literal newlines inside string values (rough heuristic)
    # Replace \n that are inside strings (between quotes) with \\n
    def fix_newlines_in_string(m: re.Match) -> str:
        return m.group(0).replace('\n', '\\n').replace('\r', '\\r')
    text = re.sub(r'"(?:[^"\\]|\\.)*"', fix_newlines_in_string, text, flags=re.DOTALL)
    return text


def _close_truncated_json(text: str) -> str:
    """
    Level-4 repair: close unclosed brackets/braces and strings.

    Walks the string tracking bracket depth and string state, then
    appends whatever is needed to make the JSON structurally complete.
    """
    stack = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch in '{[':
                stack.append('}' if ch == '{' else ']')
            elif ch in '}]':
                if stack and stack[-1] == ch:
                    stack.pop()

    suffix = ""
    if in_string:
        suffix += '"'
    suffix += ''.join(reversed(stack))
    return text + suffix


def _validate_with_coerce(data: dict) -> StructuredResponse:
    """
    Validate data against StructuredResponse schema.
    On ValidationError, attempt schema-aware type coercions and retry once.

    Raises:
        StructuredResponseParseError: If validation fails even after coercion.
    """
    try:
        return StructuredResponse.model_validate(data)
    except Exception as first_error:
        # --- schema-aware coerce ---
        try:
            data = _schema_aware_coerce(data)
            return StructuredResponse.model_validate(data)
        except Exception as second_error:
            raise StructuredResponseParseError(
                f"JSON does not match StructuredResponse schema "
                f"(even after coercion): {second_error}"
            ) from first_error


def _schema_aware_coerce(data: dict) -> dict:
    """
    Attempt common type fixups that LLMs frequently produce:
    - Numeric fields sent as strings
    - List fields sent as null
    - segments missing but top-level 'text' present
    """
    import copy
    data = copy.deepcopy(data)

    # Numeric fields as strings
    for field in ("attitude_change", "boredom_change", "stress_change"):
        val = data.get(field)
        if isinstance(val, str):
            try:
                data[field] = float(val)
            except ValueError:
                data[field] = 0.0

    # List fields as null → empty list
    for field in ("memory_add", "memory_update", "memory_delete", "segments"):
        if data.get(field) is None:
            data[field] = []

    # segments is a list but items may lack 'text' — inject empty string
    if isinstance(data.get("segments"), list):
        for seg in data["segments"]:
            if isinstance(seg, dict) and "text" not in seg:
                seg["text"] = ""

    # No segments but top-level 'text' exists
    if not data.get("segments") and isinstance(data.get("text"), str):
        data["segments"] = [{"text": data["text"]}]

    return data


def _extract_partial_response(raw_text: str) -> Optional[StructuredResponse]:
    """
    Level-5 last resort: pull "text" values out of the raw string via regex
    and build a minimal StructuredResponse from them.

    Returns None if nothing useful is found.
    """
    from schemas.structured_response import ResponseSegment

    texts = re.findall(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
    texts = [t for t in texts if t.strip()]
    if not texts:
        return None

    return StructuredResponse(
        segments=[ResponseSegment(text=t) for t in texts],
        attitude_change=0.0,
        boredom_change=0.0,
        stress_change=0.0,
    )


def _try_convert_legacy_flat_json(data: dict) -> "Optional[StructuredResponse]":
    """
    Silently convert old flat-JSON format to StructuredResponse.

    Old format used top-level fields like p/love/e/a/f/text instead of segments.
    Returns None if data doesn't look like old format.
    Not mentioned in any prompt — hidden safety net only.
    """
    from schemas.structured_response import ResponseSegment

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    def _to_list(val):
        if val is None:
            return []
        return [str(val)] if isinstance(val, str) else [str(v) for v in val]

    seg = ResponseSegment(
        text=text.strip(),
        emotions=_to_list(data.get("e")),
        animations=_to_list(data.get("a")),
        commands=_to_list(data.get("c")),
        idle_animations=_to_list(data.get("ia")),
        face_params=_to_list(data.get("f") or data.get("fp")),
        music=_to_list(data.get("music")),
        visual_effects=_to_list(data.get("v")),
        movement_modes=_to_list(data.get("move")),
        clothes=_to_list(data.get("cloth")),
        interactions=_to_list(data.get("inter")),
    )

    # Parse "p" field: "attitude,boredom,stress"
    attitude, boredom, stress = 0.0, 0.0, 0.0
    p_val = data.get("p")
    if isinstance(p_val, str):
        parts = p_val.split(",")
        try:
            if len(parts) >= 1:
                attitude = float(parts[0])
            if len(parts) >= 2:
                boredom = float(parts[1])
            if len(parts) >= 3:
                stress = float(parts[2])
        except ValueError:
            pass

    # "love" overrides attitude_change if present
    love_val = data.get("love")
    if love_val is not None:
        try:
            attitude = float(love_val)
        except (TypeError, ValueError):
            pass

    # Convert memory list: [{id, operation}] → memory_delete ids
    mem_delete = []
    for m in (data.get("memory") or []):
        if isinstance(m, dict) and str(m.get("operation", "")).lower() == "delete":
            mem_delete.append(str(m.get("id", "")))

    return StructuredResponse(
        segments=[seg],
        attitude_change=attitude,
        boredom_change=boredom,
        stress_change=stress,
        memory_delete=mem_delete,
    )


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
            return text  # let repair cascade fail with a proper error
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

    tool_call_dict = None
    if response.tool_call is not None:
        tool_call_dict = {"name": response.tool_call.name, "args": response.tool_call.args or {}}

    return {
        "response": response.full_text(),
        "segments": segments_out,
        "attitude_change": response.attitude_change,
        "boredom_change": response.boredom_change,
        "stress_change": response.stress_change,
        "memory_add": list(response.memory_add),
        "memory_update": list(response.memory_update),
        "memory_delete": list(response.memory_delete),
        "reminder_add": list(response.reminder_add),
        "reminder_delete": list(response.reminder_delete),
        "tool_call": tool_call_dict,
    }
