"""
SQLite-backed graph storage for entity-relation triples.

Tables:
    graph_entities  — distinct entities (person, place, thing, concept)
    graph_relations — subject → predicate → object triples

All writes use the shared DatabaseManager singleton (WAL, busy_timeout).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from main_logger import logger


class GraphStore:
    """Lightweight graph persistence layer on top of SQLite."""

    def __init__(self, db_manager, character_id: str):
        self.db = db_manager
        self.character_id = character_id
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _ensure_schema(self) -> None:
        with self.db.connection() as conn:
            cur = conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS graph_entities (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    character_id  TEXT    NOT NULL,
                    name          TEXT    NOT NULL,
                    entity_type   TEXT    DEFAULT 'thing',
                    mention_count INTEGER DEFAULT 1,
                    first_seen    TEXT,
                    last_seen     TEXT,
                    UNIQUE(character_id, name)
                );

                CREATE TABLE IF NOT EXISTS graph_relations (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    character_id      TEXT    NOT NULL,
                    subject_id        INTEGER NOT NULL REFERENCES graph_entities(id),
                    predicate         TEXT    NOT NULL,
                    object_id         INTEGER NOT NULL REFERENCES graph_entities(id),
                    confidence        REAL    DEFAULT 1.0,
                    source_message_id INTEGER,
                    created_at        TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_ge_char_name
                    ON graph_entities(character_id, name);
                CREATE INDEX IF NOT EXISTS idx_gr_char
                    ON graph_relations(character_id);
                CREATE INDEX IF NOT EXISTS idx_gr_subject
                    ON graph_relations(subject_id);
                CREATE INDEX IF NOT EXISTS idx_gr_object
                    ON graph_relations(object_id);
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------
    def upsert_entity(
        self,
        name: str,
        entity_type: str = "thing",
        *,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert or update an entity.  Returns the entity id."""
        now = datetime.now().isoformat(timespec="seconds")
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Entity name must not be empty")

        own_conn = conn is None
        if own_conn:
            conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO graph_entities (character_id, name, entity_type, mention_count, first_seen, last_seen)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(character_id, name) DO UPDATE SET
                    mention_count = mention_count + 1,
                    last_seen     = excluded.last_seen,
                    entity_type   = CASE
                        WHEN excluded.entity_type != 'thing' THEN excluded.entity_type
                        ELSE graph_entities.entity_type
                    END
                """,
                (self.character_id, normalized, entity_type, now, now),
            )
            # Fetch the id (works for both INSERT and UPDATE paths).
            cur.execute(
                "SELECT id FROM graph_entities WHERE character_id = ? AND name = ?",
                (self.character_id, normalized),
            )
            row = cur.fetchone()
            if own_conn:
                conn.commit()
            return int(row[0])
        finally:
            if own_conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------
    def upsert_relation(
        self,
        subject_id: int,
        predicate: str,
        object_id: int,
        *,
        confidence: float = 1.0,
        source_message_id: Optional[int] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert a relation triple. Returns the relation id."""
        now = datetime.now().isoformat(timespec="seconds")
        pred = predicate.strip().lower()

        own_conn = conn is None
        if own_conn:
            conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            # Avoid exact duplicates (same subject, predicate, object for this character).
            cur.execute(
                """
                SELECT id FROM graph_relations
                WHERE character_id = ? AND subject_id = ? AND predicate = ? AND object_id = ?
                """,
                (self.character_id, subject_id, pred, object_id),
            )
            existing = cur.fetchone()
            if existing:
                # Update confidence / source if newer.
                cur.execute(
                    "UPDATE graph_relations SET confidence = ?, source_message_id = ? WHERE id = ?",
                    (confidence, source_message_id, existing[0]),
                )
                if own_conn:
                    conn.commit()
                return int(existing[0])

            cur.execute(
                """
                INSERT INTO graph_relations
                    (character_id, subject_id, predicate, object_id, confidence, source_message_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (self.character_id, subject_id, pred, object_id, confidence, source_message_id, now),
            )
            rid = cur.lastrowid
            if own_conn:
                conn.commit()
            return int(rid)
        finally:
            if own_conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def query_by_entities(self, names: List[str]) -> List[Dict]:
        """Return relations where subject OR object name is in *names*."""
        if not names:
            return []
        normalized = [n.strip().lower() for n in names if n.strip()]
        if not normalized:
            return []

        placeholders = ",".join("?" * len(normalized))
        sql = f"""
            SELECT
                e1.name  AS subject,
                r.predicate,
                e2.name  AS object,
                r.confidence,
                e1.entity_type AS subject_type,
                e2.entity_type AS object_type,
                r.created_at
            FROM graph_relations r
            JOIN graph_entities e1 ON r.subject_id = e1.id
            JOIN graph_entities e2 ON r.object_id  = e2.id
            WHERE r.character_id = ?
              AND (e1.name IN ({placeholders}) OR e2.name IN ({placeholders}))
            ORDER BY r.confidence DESC, r.created_at DESC
        """
        params = [self.character_id] + normalized + normalized

        with self.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_neighborhood(self, name: str, depth: int = 1) -> List[Dict]:
        """Get 1-hop (or multi-hop) neighborhood around an entity."""
        normalized = name.strip().lower()
        if not normalized:
            return []

        visited_names: set = {normalized}
        results: List[Dict] = []

        for _ in range(depth):
            new_results = self.query_by_entities(list(visited_names))
            for r in new_results:
                if r not in results:
                    results.append(r)
                visited_names.add(r["subject"])
                visited_names.add(r["object"])

        return results

    def get_all_entities(self, limit: int = 500) -> List[Dict]:
        """Return top entities by mention_count."""
        with self.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT name, entity_type, mention_count, first_seen, last_seen
                FROM graph_entities
                WHERE character_id = ?
                ORDER BY mention_count DESC
                LIMIT ?
                """,
                (self.character_id, limit),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_all_relations(self, limit: int = 10000) -> List[Dict]:
        """Export all relations as dicts with resolved entity names."""
        with self.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    e1.name          AS subject,
                    r.predicate,
                    e2.name          AS object,
                    r.confidence,
                    e1.entity_type   AS subject_type,
                    e2.entity_type   AS object_type,
                    r.source_message_id,
                    r.created_at
                FROM graph_relations r
                JOIN graph_entities e1 ON r.subject_id = e1.id
                JOIN graph_entities e2 ON r.object_id  = e2.id
                WHERE r.character_id = ?
                ORDER BY r.confidence DESC
                LIMIT ?
                """,
                (self.character_id, limit),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_stats(self) -> Dict[str, int]:
        """Quick statistics for debugging."""
        with self.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM graph_entities WHERE character_id = ?",
                (self.character_id,),
            )
            n_ent = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM graph_relations WHERE character_id = ?",
                (self.character_id,),
            )
            n_rel = cur.fetchone()[0]
        return {"entities": n_ent, "relations": n_rel}
