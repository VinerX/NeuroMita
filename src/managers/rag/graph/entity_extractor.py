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

# Regex to extract the first JSON object from a potentially messy LLM response.
_JSON_RE = re.compile(r"\{[\s\S]*\}")


def parse_extraction_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a (possibly dirty) LLM response into an extraction dict.

    Returns dict with keys ``entities`` and ``relations``, or ``None`` on failure.
    """
    if not text or not text.strip():
        return None

    # Try direct parse first (clean JSON).
    try:
        data = json.loads(text.strip())
        if _validate(data):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: extract the first {...} block via regex.
    m = _JSON_RE.search(text)
    if m:
        try:
            data = json.loads(m.group())
            if _validate(data):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    logger.debug("entity_extractor: could not parse JSON from LLM response")
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
