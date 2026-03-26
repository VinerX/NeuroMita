"""
Parse entity-extraction JSON from an LLM provider response and store in GraphStore.

Expected LLM output format:
    {"entities": [{"name": "...", "type": "person|place|thing|concept"}],
     "relations": [{"s": "...", "p": "...", "o": "..."}]}
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from main_logger import logger

# Matches individual top-level {...} blocks (non-greedy per block).
_JSON_BLOCK_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def parse_extraction_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a (possibly dirty) LLM response into an extraction dict.

    Handles common local-model failures:
    - Clean JSON (ideal case).
    - JSON wrapped in markdown code fences.
    - Two separate objects {"entities":[...]} {"relations":[...]} split across lines.
    - Malformed relations array (items outside the []).

    Returns dict with keys ``entities`` and ``relations``, or ``None`` on failure.
    """
    if not text or not text.strip():
        return None

    clean = text.strip()

    # Strip markdown code fences if present.
    fence_m = re.search(r"```(?:json)?\s*([\s\S]*?)```", clean)
    if fence_m:
        clean = fence_m.group(1).strip()

    # 1. Try direct parse (clean JSON).
    try:
        data = json.loads(clean)
        if _validate(data):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Try merging multiple top-level JSON objects (e.g. model split entities/relations).
    merged = _try_merge_objects(clean)
    if merged is not None:
        return merged

    # 3. Fallback: scan for the longest parseable {...} block.
    best = _try_largest_block(clean)
    if best is not None:
        return best

    logger.debug("entity_extractor: could not parse JSON from LLM response")
    return None


def _try_merge_objects(text: str) -> Optional[Dict[str, Any]]:
    """
    Find all top-level JSON objects in text and merge their keys.
    Useful when a model outputs {"entities":[...]} then {"relations":[...]} separately.
    """
    merged: Dict[str, Any] = {}
    found_any = False

    # Scan for {...} blocks at the top level using a brace-depth counter.
    depth = 0
    start = None
    blocks = []
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                blocks.append(text[start:i + 1])
                start = None

    for block in blocks:
        try:
            obj = json.loads(block)
            if isinstance(obj, dict):
                # Keep entities/relations lists; merge by extending.
                for key in ("entities", "relations"):
                    if isinstance(obj.get(key), list):
                        existing = merged.setdefault(key, [])
                        existing.extend(obj[key])
                        found_any = True
        except (json.JSONDecodeError, ValueError):
            # Block itself might be malformed — try extracting arrays from it.
            for key in ("entities", "relations"):
                arr = _extract_array_for_key(block, key)
                if arr:
                    merged.setdefault(key, []).extend(arr)
                    found_any = True

    if found_any and _validate(merged):
        return merged
    return None


def _extract_array_for_key(text: str, key: str) -> List[Any]:
    """
    Try to extract a JSON array value for a given key from a text fragment,
    even if the surrounding object is malformed.
    """
    # Find  "key": [
    pattern = re.compile(r'"' + re.escape(key) + r'"\s*:\s*(\[)', )
    m = pattern.search(text)
    if not m:
        return []
    # Extract the array by counting brackets.
    start = m.start(1)
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                arr_str = text[start:i + 1]
                try:
                    result = json.loads(arr_str)
                    if isinstance(result, list):
                        return result
                except (json.JSONDecodeError, ValueError):
                    pass
                break
    return []


def _try_largest_block(text: str) -> Optional[Dict[str, Any]]:
    """Last-resort: try each {...} block from largest to smallest."""
    # Collect all {...} substrings.
    candidates = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start:i + 1])
                start = None
    candidates.sort(key=len, reverse=True)
    for block in candidates:
        try:
            data = json.loads(block)
            if _validate(data):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _validate(data: Any) -> bool:
    """Minimal structural check."""
    if not isinstance(data, dict):
        return False
    ents = data.get("entities")
    rels = data.get("relations")
    if ents is not None and not isinstance(ents, list):
        return False
    if rels is not None and not isinstance(rels, list):
        return False
    return True


# ---------------------------------------------------------------------------
# Blocklists — reject LLM hallucinations before storing
# ---------------------------------------------------------------------------

# Entity names that are JSON template artifacts, grammar roles, pronouns,
# ultra-generic words, or Unity game-action tags — never real knowledge.
_ENTITY_BLOCKLIST: frozenset[str] = frozenset({
    # JSON template artifacts (model copies the example literally)
    "subject", "object", "predicate", "verb", "action",
    # Grammar / generic
    "character", "person", "thing", "concept", "place",
    "it", "they", "he", "she", "we", "you", "i", "this", "that",
    "at", "to", "is", "pc", "tv", "not",
    # Unity emotion / animation tags
    "trytoque", "smileteeth", "magiceye", "smilestrange",
    "discontent", "continue",
    # Russian interjections / fillers
    "ау", "эм", "эх", "хм", "ай", "ой", "эй", "во", "го",
    "бы", "не", "бд",
})

# Predicates that are clearly JSON field names or animation codes.
_PREDICATE_BLOCKLIST: frozenset[str] = frozenset({
    "subject", "verb", "predicate", "object", "action",
    "trytoque", "smileteeth", "magiceye", "smilestrange",
})


def _is_blocked_entity(name: str) -> bool:
    """Return True if the entity name should be discarded."""
    n = name.strip().lower()
    if not n or len(n) <= 1:
        return True
    return n in _ENTITY_BLOCKLIST


def _is_blocked_predicate(pred: str) -> bool:
    """Return True if the predicate should be discarded."""
    p = pred.strip().lower()
    if not p:
        return True
    return p in _PREDICATE_BLOCKLIST


def _normalize_entity_name(raw: str) -> str:
    return raw.strip().lower()


def store_extraction(
    graph_store,
    extraction: Dict[str, Any],
    source_message_id: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Persist parsed extraction into the GraphStore.

    Returns (entities_stored, relations_stored).
    """
    entities_stored = 0
    relations_stored = 0

    # --- entities -----------------------------------------------------------
    name_to_id: Dict[str, int] = {}
    for ent in extraction.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        raw_name = str(ent.get("name") or "").strip()
        if not raw_name:
            continue
        etype = str(ent.get("type") or "thing").strip().lower()
        if etype not in ("person", "place", "thing", "concept"):
            etype = "thing"

        name = _normalize_entity_name(raw_name)
        if _is_blocked_entity(name):
            logger.debug(f"entity_extractor: skipping blocked entity {name!r}")
            continue
        try:
            eid = graph_store.upsert_entity(name, etype)
            name_to_id[name] = eid
            entities_stored += 1
        except Exception as e:
            logger.warning(f"entity_extractor: upsert_entity({name!r}) failed: {e}")

    # --- relations ----------------------------------------------------------
    for rel in extraction.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        subj = _normalize_entity_name(str(rel.get("s") or ""))
        pred = str(rel.get("p") or "").strip().lower()
        obj_ = _normalize_entity_name(str(rel.get("o") or ""))
        if not (subj and pred and obj_):
            continue
        if _is_blocked_entity(subj) or _is_blocked_entity(obj_) or _is_blocked_predicate(pred):
            logger.debug(f"entity_extractor: skipping blocked relation {subj!r}-{pred!r}->{obj_!r}")
            continue

        # Ensure both endpoints exist.
        if subj not in name_to_id:
            try:
                name_to_id[subj] = graph_store.upsert_entity(subj)
            except Exception:
                continue
        if obj_ not in name_to_id:
            try:
                name_to_id[obj_] = graph_store.upsert_entity(obj_)
            except Exception:
                continue

        try:
            graph_store.upsert_relation(
                subject_id=name_to_id[subj],
                predicate=pred,
                object_id=name_to_id[obj_],
                source_message_id=source_message_id,
            )
            relations_stored += 1
        except Exception as e:
            logger.warning(f"entity_extractor: upsert_relation({subj}->{pred}->{obj_}) failed: {e}")

    return entities_stored, relations_stored
