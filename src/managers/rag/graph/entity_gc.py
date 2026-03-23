"""
Entity Garbage Collector / Optimizer for the Knowledge Graph.

Provides rules-based cleanup of noisy, duplicate, and broken entities:
  1. Remove garbage (single chars, predicate-as-entity, stop-words)
  2. Strip punctuation from entity names
  3. Merge duplicate variants (Cyrillic ↔ Latin transliteration, synonyms)
  4. Prune orphaned entities (no relations, low mention count)

Usage:
    gc = EntityGC(db_manager, character_id)
    plan = gc.analyze()      # dry-run: shows what would change
    gc.apply(plan)           # executes the plan
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from main_logger import logger


# ---------------------------------------------------------------------------
# Transliteration table (Cyrillic ↔ Latin)
# ---------------------------------------------------------------------------
_CYR_TO_LAT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

_LAT_TO_CYR = {}
for _c, _l in _CYR_TO_LAT.items():
    if _l and _l not in _LAT_TO_CYR:
        _LAT_TO_CYR[_l] = _c


def transliterate_to_latin(text: str) -> str:
    """Rough Cyrillic → Latin transliteration for fuzzy matching."""
    out = []
    for ch in text.lower():
        out.append(_CYR_TO_LAT.get(ch, ch))
    return "".join(out)


def normalize_for_matching(name: str) -> str:
    """Normalize entity name for duplicate detection.

    Strips punctuation, collapses whitespace, transliterates Cyrillic.
    """
    s = unicodedata.normalize("NFC", name.lower().strip())
    # Remove punctuation except hyphens inside words
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Transliterate Cyrillic → Latin for cross-script comparison
    return transliterate_to_latin(s)


# ---------------------------------------------------------------------------
# Garbage detection rules
# ---------------------------------------------------------------------------

# Entities that look like predicates / verbs
_PREDICATE_PATTERNS = re.compile(
    r"^(is[_ ]|has[_ ]|was[_ ]|are[_ ]|were[_ ]|can[_ ]|will[_ ]|not[_ ]|of[_ ])"
    r"|^(asked|check|action|playing|think|thinking|subject|low|feeling)",
    re.IGNORECASE,
)

# Single common words that are useless as entities
_STOP_ENTITIES: Set[str] = {
    "a", "an", "the", "i", "me", "my", "he", "she", "it", "we", "they",
    "is", "are", "was", "were", "be", "been", "do", "does", "did",
    "yes", "no", "ok", "true", "false",
    "я", "ты", "он", "она", "мы", "вы", "они", "да", "нет",
}


def is_garbage(name: str) -> str | None:
    """Return a reason string if entity name is garbage, else None."""
    s = name.strip()

    # Too short
    if len(s) <= 1:
        return f"too_short (len={len(s)})"

    # Purely numeric
    if s.replace(".", "").replace(",", "").isdigit():
        return "numeric"

    # Stop word
    if s.lower() in _STOP_ENTITIES:
        return f"stop_word ({s})"

    # Looks like a predicate phrase
    if _PREDICATE_PATTERNS.match(s):
        return f"predicate_pattern ({s})"

    # Contains "is" as a word in a phrase (e.g. "player is дима")
    words = s.split()
    if len(words) >= 3 and any(w.lower() in ("is", "are", "was", "has") for w in words):
        return f"sentence_fragment ({s})"

    return None


# ---------------------------------------------------------------------------
# GC Plan
# ---------------------------------------------------------------------------

@dataclass
class GCAction:
    """Single action in a GC plan."""
    action: str           # "delete" | "merge" | "rename" | "retype"
    entity_id: int
    entity_name: str
    reason: str
    # For merge: target entity
    merge_into_id: Optional[int] = None
    merge_into_name: Optional[str] = None
    # For rename
    new_name: Optional[str] = None
    # For retype
    new_type: Optional[str] = None


@dataclass
class GCPlan:
    """Collection of GC actions with summary."""
    character_id: str
    actions: List[GCAction] = field(default_factory=list)
    merge_groups: List[Dict] = field(default_factory=list)  # for display

    def summary(self) -> str:
        by_action = {}
        for a in self.actions:
            by_action.setdefault(a.action, []).append(a)
        lines = [f"=== Entity GC Plan for '{self.character_id}' ==="]
        lines.append(f"Total actions: {len(self.actions)}")
        for act_type, items in sorted(by_action.items()):
            lines.append(f"\n--- {act_type.upper()} ({len(items)}) ---")
            for a in items:
                if a.action == "delete":
                    lines.append(f"  DELETE id={a.entity_id} name={a.entity_name!r}  reason={a.reason}")
                elif a.action == "merge":
                    lines.append(
                        f"  MERGE id={a.entity_id} name={a.entity_name!r} "
                        f"→ id={a.merge_into_id} name={a.merge_into_name!r}  reason={a.reason}"
                    )
                elif a.action == "rename":
                    lines.append(
                        f"  RENAME id={a.entity_id} {a.entity_name!r} → {a.new_name!r}  reason={a.reason}"
                    )
                elif a.action == "retype":
                    lines.append(
                        f"  RETYPE id={a.entity_id} {a.entity_name!r} → type={a.new_type!r}  reason={a.reason}"
                    )

        if self.merge_groups:
            lines.append(f"\n--- MERGE GROUPS ({len(self.merge_groups)}) ---")
            for g in self.merge_groups:
                canonical = g["canonical"]
                variants = g["variants"]
                lines.append(f"  Canonical: {canonical!r}")
                for v in variants:
                    lines.append(f"    ← {v['name']!r} (id={v['id']}, mentions={v['mentions']})")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# EntityGC
# ---------------------------------------------------------------------------

class EntityGC:
    """Analyzes and cleans up graph entities."""

    def __init__(self, db_manager, character_id: str):
        self.db = db_manager
        self.character_id = character_id

    def _load_entities(self, conn: sqlite3.Connection) -> List[dict]:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, entity_type, mention_count FROM graph_entities "
            "WHERE character_id = ? ORDER BY id",
            (self.character_id,),
        )
        return [
            {"id": r[0], "name": r[1], "type": r[2], "mentions": r[3]}
            for r in cur.fetchall()
        ]

    def _load_relations(self, conn: sqlite3.Connection) -> List[dict]:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, subject_id, predicate, object_id FROM graph_relations "
            "WHERE character_id = ?",
            (self.character_id,),
        )
        return [
            {"id": r[0], "subject_id": r[1], "predicate": r[2], "object_id": r[3]}
            for r in cur.fetchall()
        ]

    def _entity_has_relations(self, entity_id: int, relations: List[dict]) -> bool:
        return any(
            r["subject_id"] == entity_id or r["object_id"] == entity_id
            for r in relations
        )

    # ------- Merge duplicate detection -------

    # Known synonym groups (canonical → variants)
    KNOWN_SYNONYMS: Dict[str, List[str]] = {
        # Games
        "chess": ["шахматы"],
        "sea battle": ["морской бой", "battleship"],
        "warcraft 3": ["варкрафт", "warcraft"],
        # Common
        "prompts": ["промты"],
    }

    def _build_merge_groups(self, entities: List[dict]) -> List[Dict]:
        """Find groups of entities that should be merged."""
        # Build normalized name → entities mapping
        norm_map: Dict[str, List[dict]] = {}
        for ent in entities:
            nk = normalize_for_matching(ent["name"])
            norm_map.setdefault(nk, []).append(ent)

        # Also check known synonyms
        name_to_ent: Dict[str, dict] = {e["name"]: e for e in entities}
        synonym_groups: List[Tuple[str, List[dict]]] = []

        for canonical, variants in self.KNOWN_SYNONYMS.items():
            group = []
            if canonical in name_to_ent:
                group.append(name_to_ent[canonical])
            for v in variants:
                if v in name_to_ent:
                    group.append(name_to_ent[v])
            if len(group) >= 2:
                synonym_groups.append((canonical, group))

        # Collect merge groups from normalization
        merge_groups = []
        seen_ids: Set[int] = set()

        for nk, ents in norm_map.items():
            if len(ents) >= 2:
                # Pick canonical: most mentions, prefer person type
                canonical = max(ents, key=lambda e: (e["mentions"], e["type"] == "person"))
                variants = [e for e in ents if e["id"] != canonical["id"]]
                merge_groups.append({
                    "canonical": canonical["name"],
                    "canonical_id": canonical["id"],
                    "reason": "normalized_name_match",
                    "variants": variants,
                })
                for e in ents:
                    seen_ids.add(e["id"])

        # Add synonym groups (if not already covered by normalization)
        for canonical_name, group in synonym_groups:
            group_ids = {e["id"] for e in group}
            if group_ids & seen_ids:
                continue  # already covered
            canon = max(group, key=lambda e: (e["mentions"], e["type"] == "person"))
            variants = [e for e in group if e["id"] != canon["id"]]
            merge_groups.append({
                "canonical": canon["name"],
                "canonical_id": canon["id"],
                "reason": "known_synonym",
                "variants": variants,
            })
            seen_ids.update(group_ids)

        return merge_groups

    # ------- Main analysis -------

    def analyze(self) -> GCPlan:
        """Analyze entities and produce a cleanup plan (dry-run)."""
        conn = self.db.get_connection()
        try:
            entities = self._load_entities(conn)
            relations = self._load_relations(conn)
        finally:
            conn.close()

        plan = GCPlan(character_id=self.character_id)

        # 1. Garbage detection
        for ent in entities:
            reason = is_garbage(ent["name"])
            if reason:
                plan.actions.append(GCAction(
                    action="delete",
                    entity_id=ent["id"],
                    entity_name=ent["name"],
                    reason=f"garbage: {reason}",
                ))

        # 2. Punctuation cleanup (rename)
        for ent in entities:
            cleaned = re.sub(r"[?!.,;:]+$", "", ent["name"]).strip()
            if cleaned != ent["name"] and cleaned:
                plan.actions.append(GCAction(
                    action="rename",
                    entity_id=ent["id"],
                    entity_name=ent["name"],
                    new_name=cleaned,
                    reason="trailing_punctuation",
                ))

        # 3. Merge duplicates
        # Exclude entities already marked for deletion
        delete_ids = {a.entity_id for a in plan.actions if a.action == "delete"}
        alive = [e for e in entities if e["id"] not in delete_ids]

        merge_groups = self._build_merge_groups(alive)
        plan.merge_groups = merge_groups

        for group in merge_groups:
            canon_id = group["canonical_id"]
            for variant in group["variants"]:
                plan.actions.append(GCAction(
                    action="merge",
                    entity_id=variant["id"],
                    entity_name=variant["name"],
                    merge_into_id=canon_id,
                    merge_into_name=group["canonical"],
                    reason=group["reason"],
                ))

        # 4. Orphan detection (no relations, 1 mention, not already handled)
        handled_ids = {a.entity_id for a in plan.actions}
        for ent in entities:
            if ent["id"] in handled_ids:
                continue
            if ent["mentions"] <= 1 and not self._entity_has_relations(ent["id"], relations):
                plan.actions.append(GCAction(
                    action="delete",
                    entity_id=ent["id"],
                    entity_name=ent["name"],
                    reason="orphan (no relations, 1 mention)",
                ))

        return plan

    # ------- Apply plan -------

    def apply(self, plan: GCPlan) -> Dict[str, int]:
        """Execute a GC plan against the database. Returns counts by action."""
        conn = self.db.get_connection()
        counts = {"delete": 0, "merge": 0, "rename": 0, "retype": 0}

        try:
            cur = conn.cursor()

            for action in plan.actions:
                try:
                    if action.action == "delete":
                        self._do_delete(cur, action.entity_id)
                        counts["delete"] += 1

                    elif action.action == "merge":
                        self._do_merge(cur, action.entity_id, action.merge_into_id)
                        counts["merge"] += 1

                    elif action.action == "rename":
                        self._do_rename(cur, action.entity_id, action.new_name)
                        counts["rename"] += 1

                    elif action.action == "retype":
                        cur.execute(
                            "UPDATE graph_entities SET entity_type = ? WHERE id = ?",
                            (action.new_type, action.entity_id),
                        )
                        counts["retype"] += 1

                except Exception as e:
                    logger.warning(f"EntityGC: action failed {action.action} id={action.entity_id}: {e}")

            conn.commit()
            logger.info(f"EntityGC applied: {counts}")
            return counts

        except Exception as e:
            logger.error(f"EntityGC apply failed: {e}", exc_info=True)
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def _do_delete(self, cur: sqlite3.Cursor, entity_id: int) -> None:
        """Delete entity and all its relations."""
        cur.execute(
            "DELETE FROM graph_relations WHERE (subject_id = ? OR object_id = ?) AND character_id = ?",
            (entity_id, entity_id, self.character_id),
        )
        cur.execute(
            "DELETE FROM graph_entities WHERE id = ? AND character_id = ?",
            (entity_id, self.character_id),
        )

    def _do_merge(self, cur: sqlite3.Cursor, source_id: int, target_id: int) -> None:
        """Merge source entity into target: re-point relations, sum mentions, delete source."""
        # Re-point subject relations
        cur.execute(
            "UPDATE graph_relations SET subject_id = ? WHERE subject_id = ? AND character_id = ?",
            (target_id, source_id, self.character_id),
        )
        # Re-point object relations
        cur.execute(
            "UPDATE graph_relations SET object_id = ? WHERE object_id = ? AND character_id = ?",
            (target_id, source_id, self.character_id),
        )
        # Remove duplicate relations (same subject+predicate+object after merge)
        cur.execute(
            """DELETE FROM graph_relations WHERE id NOT IN (
                SELECT MIN(id) FROM graph_relations
                WHERE character_id = ?
                GROUP BY subject_id, predicate, object_id
            ) AND character_id = ?""",
            (self.character_id, self.character_id),
        )
        # Remove self-referential relations
        cur.execute(
            "DELETE FROM graph_relations WHERE subject_id = object_id AND character_id = ?",
            (self.character_id,),
        )
        # Sum mention counts
        cur.execute(
            """UPDATE graph_entities SET
                mention_count = mention_count + COALESCE(
                    (SELECT mention_count FROM graph_entities WHERE id = ?), 0
                )
            WHERE id = ?""",
            (source_id, target_id),
        )
        # Delete source entity
        cur.execute(
            "DELETE FROM graph_entities WHERE id = ? AND character_id = ?",
            (source_id, self.character_id),
        )

    def _do_rename(self, cur: sqlite3.Cursor, entity_id: int, new_name: str) -> None:
        """Rename entity. If new_name already exists, merge into it."""
        cur.execute(
            "SELECT id FROM graph_entities WHERE character_id = ? AND name = ? AND id != ?",
            (self.character_id, new_name.lower().strip(), entity_id),
        )
        existing = cur.fetchone()
        if existing:
            # Name collision → merge
            self._do_merge(cur, entity_id, existing[0])
        else:
            cur.execute(
                "UPDATE graph_entities SET name = ? WHERE id = ? AND character_id = ?",
                (new_name.lower().strip(), entity_id, self.character_id),
            )
