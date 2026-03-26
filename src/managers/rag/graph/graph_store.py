"""
SQLite-backed graph storage for entity-relation triples.

Tables:
    graph_entities          — distinct entities (person, place, thing, concept)
    graph_relations         — subject → predicate → object triples
    graph_entity_aliases    — surface forms / synonyms for deduplication
    graph_entity_embeddings — float32 embeddings for vector entity search

All writes use the shared DatabaseManager singleton (WAL, busy_timeout).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

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

                CREATE TABLE IF NOT EXISTS graph_entity_aliases (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id   INTEGER NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
                    surface     TEXT    NOT NULL,
                    language    TEXT    DEFAULT 'auto',
                    UNIQUE(entity_id, surface)
                );

                CREATE TABLE IF NOT EXISTS graph_entity_embeddings (
                    entity_id   INTEGER PRIMARY KEY REFERENCES graph_entities(id) ON DELETE CASCADE,
                    model_name  TEXT    NOT NULL DEFAULT '',
                    embedding   BLOB    NOT NULL,
                    updated_at  TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_ge_char_name
                    ON graph_entities(character_id, name);
                CREATE INDEX IF NOT EXISTS idx_gr_char
                    ON graph_relations(character_id);
                CREATE INDEX IF NOT EXISTS idx_gr_subject
                    ON graph_relations(subject_id);
                CREATE INDEX IF NOT EXISTS idx_gr_object
                    ON graph_relations(object_id);
                CREATE INDEX IF NOT EXISTS idx_gea_surface
                    ON graph_entity_aliases(surface);

                CREATE TABLE IF NOT EXISTS graph_processed_messages (
                    character_id TEXT    NOT NULL,
                    message_id   INTEGER NOT NULL,
                    processed_at TEXT,
                    PRIMARY KEY (character_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_gpm_char
                    ON graph_processed_messages(character_id);
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Processed-message tracking
    # ------------------------------------------------------------------
    def mark_messages_processed(self, message_ids: List[int]) -> None:
        """Mark history message IDs as processed (regardless of whether entities were found)."""
        if not message_ids:
            return
        now = datetime.utcnow().isoformat()
        with self.db.connection() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO graph_processed_messages (character_id, message_id, processed_at) VALUES (?, ?, ?)",
                [(self.character_id, mid, now) for mid in message_ids],
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_name(name: str) -> str:
        """Lowercase, strip whitespace and punctuation (keep hyphens/apostrophes)."""
        name = name.strip().lower()
        name = re.sub(r"[^\w\s\-']", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

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
        normalized = self.normalize_name(name)
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

    def add_alias(self, entity_id: int, surface: str, language: str = "auto") -> None:
        """Register a surface form as alias for an existing entity."""
        surface = self.normalize_name(surface)
        if not surface:
            return
        with self.db.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO graph_entity_aliases (entity_id, surface, language) VALUES (?,?,?)",
                (entity_id, surface, language),
            )
            conn.commit()

    def find_by_alias(self, surface: str) -> Optional[int]:
        """Return entity_id if surface form is a known alias, else None."""
        surface = self.normalize_name(surface)
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT e.id FROM graph_entity_aliases a
                   JOIN graph_entities e ON a.entity_id = e.id
                   WHERE a.surface = ? AND e.character_id = ?""",
                (surface, self.character_id),
            ).fetchone()
        return int(row[0]) if row else None

    def store_entity_embedding(
        self, entity_id: int, embedding: bytes, model_name: str = ""
    ) -> None:
        """Store or replace embedding for an entity."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO graph_entity_embeddings (entity_id, model_name, embedding, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(entity_id) DO UPDATE SET
                       embedding=excluded.embedding,
                       model_name=excluded.model_name,
                       updated_at=excluded.updated_at""",
                (entity_id, model_name, embedding, now),
            )
            conn.commit()

    def get_entities_without_embeddings(self) -> List[Dict]:
        """Return entities that have no embedding yet."""
        with self.db.connection() as conn:
            cur = conn.execute(
                """SELECT ge.id, ge.name FROM graph_entities ge
                   LEFT JOIN graph_entity_embeddings gee ON gee.entity_id = ge.id
                   WHERE ge.character_id = ? AND gee.entity_id IS NULL""",
                (self.character_id,),
            )
            return [{"id": r[0], "name": r[1]} for r in cur.fetchall()]

    def find_by_embedding(
        self, query_vec, threshold: float = 0.6, top_k: int = 10
    ) -> List[str]:
        """Vector search: return entity names with cosine similarity >= threshold."""
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT ge.name, gee.embedding
                   FROM graph_entity_embeddings gee
                   JOIN graph_entities ge ON gee.entity_id = ge.id
                   WHERE ge.character_id = ?""",
                (self.character_id,),
            ).fetchall()
        if not rows:
            return []

        results: List[Tuple[str, float]] = []
        for name, emb_bytes in rows:
            try:
                emb = np.frombuffer(emb_bytes, dtype=np.float32)
                sim = float(np.dot(query_vec, emb))
                if sim >= threshold:
                    results.append((name, sim))
            except Exception:
                continue

        results.sort(key=lambda x: -x[1])
        return [n for n, _ in results[:top_k]]

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
