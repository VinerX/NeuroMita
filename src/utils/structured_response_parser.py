# src/utils/structured_response_parser.py
from __future__ import annotations
from core.error_utils import format_exception

import json
import re
from dataclasses import dataclass
from typing import Optional, Type, Any, get_args, get_origin

from main_logger import logger
from pydantic_core import PydanticUndefined
from schemas.structured_response import (
    RESPONSE_PROTOCOL_VERSION,
    StructuredResponse,
    ResponseSegment,
)


class StructuredResponseParseError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StructuredParseOutcome:
    """Parsed response plus trust metadata for control-plane decisions."""

    response: StructuredResponse
    parse_level: str
    schema_coerced: bool = False
    fallback_kind: str = ""
    extraction_kind: str = "raw_json"

    @property
    def control_plane_trusted(self) -> bool:
        return (
            self.parse_level == "direct"
            and not self.schema_coerced
            and not self.fallback_kind
            and self.extraction_kind in {"raw_json", "markdown_json_fence"}
        )


def parse_structured_response_with_meta(
    raw_text: str,
    *,
    model_cls: Type[StructuredResponse] = StructuredResponse,
) -> StructuredParseOutcome:
    if not raw_text or not isinstance(raw_text, str):
        raise StructuredResponseParseError("Empty or non-string response")

    cleaned, extraction_kind = _extract_json_string(raw_text)

    data, parse_level = _try_json_loads(cleaned, level="direct")

    if data is None:
        repaired = _simple_text_repair(cleaned)
        data, parse_level = _try_json_loads(repaired, level="simple_repair")

    if data is None:
        escaped = _escape_inner_quotes(cleaned)
        data, parse_level = _try_json_loads(escaped, level="inner_quote_escape")

    if data is None:
        data, parse_level = _try_json_repair_lib(cleaned)

    if data is None:
        closed = _close_truncated_json(cleaned)
        data, parse_level = _try_json_loads(closed, level="truncation_close")

    if data is None:
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

    response, schema_coerced = _validate_with_coerce(data, model_cls=model_cls)

    # Control-plane schemas such as GameMasterResponse intentionally do not
    # contain character reply segments. They still use this parser so the
    # direct/repair trust metadata remains identical to Mita responses.
    if not hasattr(response, "segments"):
        return StructuredParseOutcome(response, parse_level, schema_coerced, extraction_kind=extraction_kind)

    if not response.segments:
        if response.tool_call:
            response.segments = [ResponseSegment(text="")]
            logger.debug(
                "[StructuredResponseParser] Tool call with empty segments — created default segment"
            )
            return StructuredParseOutcome(
                response,
                parse_level,
                schema_coerced,
                "synthetic_empty_tool_segment",
                extraction_kind,
            )

        converted = _try_convert_legacy_flat_json(data, model_cls=model_cls)
        if converted is not None:
            logger.warning(
                "[StructuredResponseParser] Segments missing — used legacy flat-JSON fallback"
            )
            return StructuredParseOutcome(
                response=converted,
                parse_level=parse_level,
                schema_coerced=schema_coerced,
                fallback_kind="legacy_flat",
                extraction_kind=extraction_kind,
            )

        partial = _extract_partial_response(raw_text, model_cls=model_cls)
        if partial is not None:
            logger.warning(
                "[StructuredResponseParser] Segments missing — used partial text extraction"
            )
            return StructuredParseOutcome(
                response=partial,
                parse_level=parse_level,
                schema_coerced=schema_coerced,
                fallback_kind="partial_extraction",
                extraction_kind=extraction_kind,
            )

        raise StructuredResponseParseError(
            "StructuredResponse has no segments (segments list is empty)"
        )

    logger.debug(
        f"[StructuredResponseParser] Parsed {len(response.segments)} segment(s), "
        f"attitude_change={response.attitude_change}, "
        f"boredom_change={response.boredom_change}, "
        f"stress_change={response.stress_change}"
    )

    return StructuredParseOutcome(response, parse_level, schema_coerced, extraction_kind=extraction_kind)


def parse_structured_response(
    raw_text: str,
    *,
    model_cls: Type[StructuredResponse] = StructuredResponse,
) -> StructuredResponse:
    """Compatibility wrapper for callers that only need the response model."""

    return parse_structured_response_with_meta(raw_text, model_cls=model_cls).response


def _try_json_loads(text: str, level: str = "direct") -> tuple[Optional[dict], str]:
    try:
        return json.loads(text), level
    except (json.JSONDecodeError, ValueError):
        return None, ""


def _try_json_repair_lib(text: str, level: str = "json_repair") -> tuple[Optional[dict], str]:
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
    text = re.sub(r',\s*([}\]])', r'\1', text)

    def fix_newlines_in_string(m: re.Match) -> str:
        return m.group(0).replace('\n', '\\n').replace('\r', '\\r')

    text = re.sub(r'"(?:[^"\\]|\\.)*"', fix_newlines_in_string, text, flags=re.DOTALL)
    return text


def _escape_inner_quotes(text: str) -> str:
    result: list[str] = []
    i = 0
    n = len(text)
    _STRUCTURAL = frozenset(',}]:')

    while i < n:
        ch = text[i]
        if ch != '"':
            result.append(ch)
            i += 1
            continue

        result.append('"')
        i += 1

        while i < n:
            c = text[i]
            if c == '\\':
                result.append(c)
                i += 1
                if i < n:
                    result.append(text[i])
                    i += 1
            elif c == '"':
                j = i + 1
                while j < n and text[j] in ' \t\r\n':
                    j += 1
                after = text[j] if j < n else ''
                if after in _STRUCTURAL or j >= n:
                    result.append('"')
                    i += 1
                    break
                else:
                    result.append('\\"')
                    i += 1
            else:
                result.append(c)
                i += 1

    return ''.join(result)


def _clean_trailing_incomplete_json(text: str) -> str:
    text = text.rstrip()
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
    if in_string:
        return text
    for _ in range(5):
        prev = text
        text = re.sub(r",\s*\"[^\"]*\"\s*:\s*[-+]\s*$", "", text)
        text = re.sub(r",\s*\"[^\"]*\"\s*:\s*$", "", text)
        text = re.sub(r",\s*\"[^\"]*\"?$", "", text)
        text = re.sub(r":\s*[-+]\s*$", "", text)
        text = re.sub(r"\{\s*\"[^\"]*\"?\s*$", "{", text)
        text = re.sub(r",\s*\"[^\"]*\"\s*:\s*\{?\s*$", "", text)
        text = re.sub(r"[,:]\s*$", "", text)
        if text == prev:
            break
    return text


def _close_truncated_json(text: str) -> str:
    text = _clean_trailing_incomplete_json(text)
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


def _validate_with_coerce(data: dict, *, model_cls: Type[StructuredResponse]) -> tuple[StructuredResponse, bool]:
    try:
        return model_cls.model_validate(data), False
    except Exception as first_error:
        try:
            data = _schema_aware_coerce(data, model_cls=model_cls)
            return model_cls.model_validate(data), True
        except Exception as second_error:
            raise StructuredResponseParseError(
                f"JSON does not match StructuredResponse schema "
                f"(even after coercion): {format_exception(second_error)}"
            ) from first_error


def _extract_custom_field_models(model_cls: Type[StructuredResponse]) -> dict[str, Any]:
    """Returns {field_name: field_info} for custom_fields sub-model if present."""
    custom_fields = getattr(model_cls, "model_fields", {}).get("custom_fields")
    if custom_fields is None:
        return {}

    annotation = getattr(custom_fields, "annotation", None)
    if annotation is None:
        return {}

    candidates = [annotation]
    origin = get_origin(annotation)
    if origin is not None:
        candidates.extend(arg for arg in get_args(annotation) if arg is not type(None))

    for candidate in candidates:
        fields = getattr(candidate, "model_fields", None)
        if isinstance(fields, dict) and fields:
            return fields

    return {}


def _extract_custom_field_names(model_cls: Type[StructuredResponse]) -> set[str]:
    return {str(name) for name in _extract_custom_field_models(model_cls).keys()}


def _schema_aware_coerce(data: dict, *, model_cls: Type[StructuredResponse]) -> dict:
    import copy
    data = copy.deepcopy(data)

    segment_list_fields = (
        "emotions",
        "animations",
        "idle_animations",
        "commands",
        "movement_modes",
        "visual_effects",
        "clothes",
        "music",
        "interactions",
        "face_params",
    )

    def _coerce_string_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]

    # A hallucinated numeric secret flag must not discard valid action segments
    # or reveal the secret by truthiness. Treat ambiguous flags as unspecified.
    flag = data.get("secret_exposed")
    if flag is not None and not isinstance(flag, bool):
        if isinstance(flag, str) and flag.strip().lower() in {"true", "false"}:
            data["secret_exposed"] = flag.strip().lower() == "true"
        else:
            data["secret_exposed"] = None

    # 0. Починка перепутанных и инвертированных полей модели
    # Preserve misplaced known custom deltas, but never treat arbitrary memory
    # objects as executable memory operations.
    custom_names = _extract_custom_field_names(model_cls)
    for memory_field in ("memory_add", "memory_update"):
        if isinstance(data.get(memory_field), dict):
            misplaced = data[memory_field]
            if not isinstance(data.get("custom_fields"), dict):
                data["custom_fields"] = {}
            for key in custom_names:
                if key in misplaced and key not in data["custom_fields"]:
                    data["custom_fields"][key] = misplaced[key]
            data[memory_field] = []

    # 0b. image_description содержит список сегментов
    img_desc = data.get("image_description")
    if isinstance(img_desc, list) and img_desc:
        has_segment_like = any(isinstance(x, dict) and ("text" in x or "hint" in x) for x in img_desc)
        curr_segs = data.get("segments")
        curr_segs_are_strings = isinstance(curr_segs, list) and all(isinstance(x, str) for x in curr_segs)
        if has_segment_like and (not curr_segs or curr_segs_are_strings):
            if curr_segs_are_strings and curr_segs:
                # Если в segments были строки памяти ("normal|..."), переносим их в memory_add
                if all("|" in s for s in curr_segs) and not data.get("memory_add"):
                    data["memory_add"] = curr_segs
            data["segments"] = img_desc
        data["image_description"] = None
    elif isinstance(img_desc, dict) and ("text" in img_desc or "hint" in img_desc):
        if not data.get("segments"):
            data["segments"] = [img_desc]
        data["image_description"] = None
    elif img_desc is not None and not isinstance(img_desc, str):
        data["image_description"] = str(img_desc) if not isinstance(img_desc, (dict, list)) else None

    # 0c. segments содержит строки вместо словарей
    if isinstance(data.get("segments"), list):
        segs = data["segments"]
        if segs and all(isinstance(x, str) and "|" in x for x in segs) and not data.get("memory_add"):
            data["memory_add"] = segs
            data["segments"] = []
        else:
            new_segs = []
            for item in segs:
                if isinstance(item, str):
                    new_segs.append({"text": item})
                elif isinstance(item, dict):
                    new_segs.append(item)
                else:
                    new_segs.append({"text": str(item)})
            data["segments"] = new_segs

    # 1. Custom fields: поиск алиасов, подъем из корня/сегмента, дефолтные значения
    custom_field_models = _extract_custom_field_models(model_cls)
    if custom_field_models:
        custom_fields = data.get("custom_fields")
        if not isinstance(custom_fields, dict):
            custom_fields = {}

        seg0 = data["segments"][0] if (isinstance(data.get("segments"), list) and data["segments"] and isinstance(data["segments"][0], dict)) else {}
        candidate_sources = [custom_fields, data, seg0]

        hoisted_fields = []
        for field_name, field_info in custom_field_models.items():
            clean_name = field_name.strip()
            aliases = [clean_name, clean_name.lower(), clean_name.capitalize()]
            if clean_name.lower().endswith("_change"):
                base = clean_name.lower()[:-7]
                aliases.extend([base, base.capitalize(), base.upper(), f"{base}_change", f"{base.capitalize()}_change"])
            else:
                aliases.extend([f"{clean_name.lower()}_change", f"{clean_name}_change", f"{clean_name.capitalize()}_change"])

            val_found = False
            found_val = None
            found_src = None
            found_k = None

            for src in candidate_sources:
                if not isinstance(src, dict):
                    continue
                for alias in aliases:
                    if alias in src:
                        val_found = True
                        found_val = src[alias]
                        found_src = src
                        found_k = alias
                        break
                if val_found:
                    break
                lower_aliases = {a.lower() for a in aliases}
                for k, v in src.items():
                    if k.lower() in lower_aliases:
                        val_found = True
                        found_val = v
                        found_src = src
                        found_k = k
                        break
                if val_found:
                    break

            if val_found:
                custom_fields[field_name] = found_val
                if found_src is data and found_k in data:
                    data.pop(found_k, None)
                    hoisted_fields.append(f"{found_k}->{field_name}")
                elif found_src is seg0 and found_k in seg0:
                    seg0.pop(found_k, None)
                    hoisted_fields.append(f"seg0:{found_k}->{field_name}")
            else:
                default_val = getattr(field_info, "default", None)
                if default_val is not None and default_val is not ... and default_val is not PydanticUndefined:
                    custom_fields[field_name] = default_val
                else:
                    py_type = getattr(field_info, "annotation", None)
                    if py_type in (float, int):
                        custom_fields[field_name] = 0.0 if py_type is float else 0
                    elif py_type is bool:
                        custom_fields[field_name] = False
                    elif py_type is str:
                        custom_fields[field_name] = ""
                    else:
                        custom_fields[field_name] = 0.0

        data["custom_fields"] = custom_fields
        if hoisted_fields:
            logger.warning(
                "[StructuredResponseParser] Hoisted custom fields: %s",
                ", ".join(sorted(hoisted_fields)),
            )

    # 2. Приведение числовых статов
    for field in ("attitude_change", "boredom_change", "stress_change"):
        val = data.get(field)
        if isinstance(val, str):
            try:
                data[field] = float(val)
            except ValueError:
                data[field] = 0.0

    # 3. Исправление null в списках (добавили entities и relations)
    for field in ("memory_add", "memory_update", "memory_delete", "memory_merge",
                  "segments", "reminder_add", "reminder_delete", "entities", "relations"):
        if data.get(field) is None:
            data[field] = []

    # 4. Базовая починка сегментов
    if isinstance(data.get("segments"), list):
        for seg in data["segments"]:
            if not isinstance(seg, dict):
                continue

            if "text" not in seg or seg["text"] is None:
                seg["text"] = ""
            elif not isinstance(seg["text"], str):
                seg["text"] = str(seg["text"])

            for field in segment_list_fields:
                if field in seg:
                    seg[field] = _coerce_string_list(seg.get(field))

            for field in ("start_game", "end_game", "target", "hint"):
                if field in seg and seg[field] is not None and not isinstance(seg[field], str):
                    seg[field] = str(seg[field])

            if "allow_sleep" in seg and seg["allow_sleep"] is not None and not isinstance(seg["allow_sleep"], bool):
                value = seg["allow_sleep"]
                if isinstance(value, str):
                    lowered = value.strip().lower()
                    if lowered in {"true", "1", "yes", "on"}:
                        seg["allow_sleep"] = True
                    elif lowered in {"false", "0", "no", "off"}:
                        seg["allow_sleep"] = False
                    else:
                        seg["allow_sleep"] = None
                else:
                    seg["allow_sleep"] = bool(value)

    # 5. Если текста много, а сегментов нет — создаем сегмент
    if not data.get("segments"):
        for alt_key in ("text", "message", "response", "content", "reply"):
            if isinstance(data.get(alt_key), str) and data[alt_key].strip():
                data["segments"] = [{"text": data[alt_key]}]
                break

    # 6. Hoisting (поднятие статов и памяти из сегмента наверх)
    if isinstance(data.get("segments"), list) and data["segments"]:
        seg0 = data["segments"][0]
        if isinstance(seg0, dict):
            for stat_field in ("attitude_change", "boredom_change", "stress_change"):
                if stat_field not in data and stat_field in seg0:
                    try:
                        data[stat_field] = float(seg0.pop(stat_field))
                    except (TypeError, ValueError):
                        seg0.pop(stat_field, None)

            for field in ("memory_add", "memory_update", "memory_delete", "memory_merge",
                          "reminder_add", "reminder_delete", "entities", "relations"):
                if not data.get(field) and seg0.get(field):
                    data[field] = seg0.pop(field)

    # 7. Трансформация объектов в строки "name:type"
    if isinstance(data.get("entities"), list):
        coerced_entities = []
        for ent in data["entities"]:
            if isinstance(ent, dict):
                name = ent.get("name") or ent.get("entity") or "unknown"
                etype = ent.get("type") or "thing"
                coerced_entities.append(f"{name}:{etype}")
            else:
                coerced_entities.append(str(ent))
        data["entities"] = coerced_entities

    if isinstance(data.get("relations"), list):
        coerced_relations = []
        for rel in data["relations"]:
            if isinstance(rel, dict):
                src = rel.get("source") or rel.get("from") or rel.get("s") or "unknown"
                rtype = rel.get("type") or rel.get("p") or "related"
                dst = rel.get("target") or rel.get("to") or rel.get("o") or "unknown"
                coerced_relations.append(f"{src}:{rtype}:{dst}")
            else:
                coerced_relations.append(str(rel))
        data["relations"] = coerced_relations

    return data


def _extract_partial_response(raw_text: str, *, model_cls: Type[StructuredResponse]) -> Optional[StructuredResponse]:
    texts = re.findall(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
    texts = [json.loads('"' + t + '"', strict=False) for t in texts if t.strip()]
    if not texts:
        return None

    try:
        return model_cls(
            segments=[ResponseSegment(text=t) for t in texts],
            attitude_change=0.0,
            boredom_change=0.0,
            stress_change=0.0,
        )
    except Exception:
        return StructuredResponse(
            segments=[ResponseSegment(text=t) for t in texts],
            attitude_change=0.0,
            boredom_change=0.0,
            stress_change=0.0,
        )


def _try_convert_legacy_flat_json(data: dict, *, model_cls: Type[StructuredResponse]) -> "Optional[StructuredResponse]":
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

    love_val = data.get("love")
    if love_val is not None:
        try:
            attitude = float(love_val)
        except (TypeError, ValueError):
            pass

    mem_delete = []
    for m in (data.get("memory") or []):
        if isinstance(m, dict) and str(m.get("operation", "")).lower() == "delete":
            mem_delete.append(str(m.get("id", "")))

    try:
        return model_cls(
            segments=[seg],
            attitude_change=attitude,
            boredom_change=boredom,
            stress_change=stress,
            memory_delete=mem_delete,
        )
    except Exception:
        return StructuredResponse(
            segments=[seg],
            attitude_change=attitude,
            boredom_change=boredom,
            stress_change=stress,
            memory_delete=mem_delete,
        )


def _extract_json_string(text: str) -> tuple[str, str]:
    text = text.strip()
    extraction_kind = "raw_json"

    if text.startswith("\ufeff"):
        text = text[1:]

    if text.startswith("```json"):
        extraction_kind = "markdown_json_fence"
        text = text[len("```json"):]
    elif text.startswith("```"):
        extraction_kind = "markdown_json_fence"
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    if not text.startswith("{"):
        extraction_kind = "embedded_json"
        brace_start = text.find("{")
        if brace_start == -1:
            return text, extraction_kind
        text = text[brace_start:]

    if not text.endswith("}"):
        if text.count("{") <= text.count("}"):
            brace_end = text.rfind("}")
            if brace_end != -1:
                if text[brace_end + 1:].strip():
                    extraction_kind = "embedded_json"
                text = text[:brace_end + 1]
        else:
            extraction_kind = "truncated_json"

    return text, extraction_kind


def structured_response_to_result_dict(response: StructuredResponse) -> dict:
    segments_out = []
    for seg in response.segments:
        seg_dict = {"text": seg.text}

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
        if seg.intents:
            seg_dict["intents"] = [
                {"type": intent.type, "payload": dict(intent.payload or {})}
                for intent in seg.intents
            ]
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

    custom_fields_out = None
    try:
        cf = getattr(response, "custom_fields", None)
        if cf is not None:
            if hasattr(cf, "model_dump"):
                custom_fields_out = cf.model_dump(exclude_none=True)
            elif isinstance(cf, dict):
                custom_fields_out = dict(cf)
    except Exception:
        custom_fields_out = None

    return {
        "response_protocol_version": RESPONSE_PROTOCOL_VERSION,
        "segments": segments_out,
        "response": response.full_text(),
        "attitude_change": response.attitude_change,
        "boredom_change": response.boredom_change,
        "stress_change": response.stress_change,
        "memory_add": list(response.memory_add or []),
        "memory_update": list(response.memory_update or []),
        "memory_delete": list(response.memory_delete or []),
        "memory_merge": list(response.memory_merge or []),
        "reminder_add": list(response.reminder_add or []),
        "reminder_delete": list(response.reminder_delete or []),
        "tool_call": tool_call_dict,
        "secret_exposed": response.secret_exposed,
        "custom_fields": custom_fields_out,
        "entities": list(response.entities) if response.entities else [],
        "relations": list(response.relations) if response.relations else [],
    }
