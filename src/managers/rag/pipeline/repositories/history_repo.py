"""HistoryRepository — все SQL-запросы к таблице history.

Принимает cursor (соединение открывает вызывающий код),
возвращает list[dict] с сырыми строками.
"""
from __future__ import annotations

from typing import Any, List, Optional

from managers.rag.pipeline.types import SchemaInfo


class HistoryRepository:
    """Инкапсулирует SQL к таблице history; не знает о Candidate / RAGConfig."""

    def __init__(self, db: Any, character_id: str, schema: SchemaInfo) -> None:
        self.db = db
        self.character_id = character_id
        self.schema = schema

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _opt_cols(self, names: tuple[str, ...], prefix: str = "h") -> list[str]:
        """Return 'prefix.col' for each column that exists in history_cols."""
        return [f"{prefix}.{c}" for c in names if c in self.schema.history_cols]

    def _where_not_deleted(self) -> str:
        return " AND h.is_deleted=0" if "is_deleted" in self.schema.history_cols else ""

    def _rows_to_dicts(self, cursor, cols: list[str]) -> list[dict]:
        keys = [c.split(" AS ")[-1].split(".")[-1] for c in cols]
        return [dict(zip(keys, row)) for row in (cursor.fetchall() or [])]

    # ------------------------------------------------------------------
    # FTS search
    # ------------------------------------------------------------------

    def fts_rows(
        self,
        cursor,
        *,
        match_q: str,
        top_k: int,
        model_name: str,
    ) -> list[dict]:
        """BM25 FTS5 search against history_fts."""
        if not match_q:
            return []
        if not self.db.table_exists(cursor, "history_fts"):
            return []

        cols = ["h.id", "bm25(history_fts) AS rank", "h.role", "h.content", "h.timestamp"]
        cols.append("e.embedding")
        cols += self._opt_cols(("message_id", "speaker", "target", "participants", "entities"))

        where = f"h.character_id=? AND h.is_active=0{self._where_not_deleted()}"
        try:
            cursor.execute(
                f"""
                SELECT {", ".join(cols)}
                FROM history_fts
                JOIN history h ON h.id = history_fts.rowid
                LEFT JOIN embeddings e
                  ON e.source_table='history' AND e.source_id=h.id
                  AND e.character_id=h.character_id AND e.model_name=?
                WHERE history_fts MATCH ? AND {where}
                ORDER BY rank
                LIMIT ?
                """,
                (model_name, match_q, self.character_id, int(top_k)),
            )
            return self._rows_to_dicts(cursor, cols)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Vector search — full blob scan (no FAISS)
    # ------------------------------------------------------------------

    def vector_blob_rows(self, cursor, *, model_name: str) -> list[dict]:
        """Full blob scan: returns all history rows with embeddings."""
        cols = ["h.id", "h.role", "h.content", "e.embedding", "h.timestamp"]
        keys = ["id", "role", "content", "embedding", "timestamp"]
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.schema.history_cols:
                cols.append(f"h.{opt}")
                keys.append(opt)

        where = f"h.character_id=? AND h.is_active=0{self._where_not_deleted()}"
        try:
            cursor.execute(
                f"""SELECT {', '.join(cols)} FROM history h
                    INNER JOIN embeddings e
                      ON e.source_table='history' AND e.source_id=h.id
                      AND e.character_id=h.character_id AND e.model_name=?
                    WHERE {where}""",
                (model_name, self.character_id),
            )
            return [dict(zip(keys, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Vector search — metadata-only fetch for FAISS hits
    # ------------------------------------------------------------------

    def vector_meta_rows(self, cursor, *, model_name: str, ids: list[int]) -> list[dict]:
        """Fetch metadata (no embeddings) for a list of history IDs (FAISS hits)."""
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        opt_cols: list[str] = []
        opt_keys: list[str] = []
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.schema.history_cols:
                opt_cols.append(f"h.{opt}")
                opt_keys.append(opt)

        base_cols = ["h.id", "h.role", "h.content", "h.timestamp"]
        base_keys = ["id", "role", "content", "timestamp"]
        all_cols = base_cols + opt_cols
        all_keys = base_keys + opt_keys

        where = f"h.character_id=? AND h.is_active=0 AND h.id IN ({placeholders}){self._where_not_deleted()}"
        try:
            cursor.execute(
                f"SELECT {', '.join(all_cols)} FROM history h WHERE {where}",
                tuple([self.character_id] + ids),
            )
            return [dict(zip(all_keys, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Sentence-level retrieval
    # ------------------------------------------------------------------

    def sentence_rows(self, cursor, *, model_name: str) -> list[dict]:
        """Retrieve history joined with per-sentence embeddings."""
        cols_h = ["h.id", "h.role", "h.content", "h.timestamp"]
        keys_h = ["id", "role", "content", "timestamp"]
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.schema.history_cols:
                cols_h.append(f"h.{opt}")
                keys_h.append(opt)

        where = f"h.character_id=? AND h.is_active=0{self._where_not_deleted()}"
        try:
            cursor.execute(
                f"""SELECT {', '.join(cols_h)}, se.sentence_idx, se.embedding
                    FROM history h
                    INNER JOIN sentence_embeddings se
                      ON se.source_table='history' AND se.source_id=h.id
                      AND se.character_id=h.character_id AND se.model_name=?
                    WHERE {where}""",
                (model_name, self.character_id),
            )
            keys_full = keys_h + ["sentence_idx", "embedding"]
            return [dict(zip(keys_full, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Actor pre-filter (extra pass for speaker/target boost)
    # ------------------------------------------------------------------

    def actor_boost_rows(self, cursor, *, model_name: str, actors: list[str]) -> list[dict]:
        """Fetch history rows where speaker or target is in *actors*."""
        if not actors:
            return []
        cols = ["h.id", "h.role", "h.content", "e.embedding", "h.timestamp"]
        keys = ["id", "role", "content", "embedding", "timestamp"]
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.schema.history_cols:
                cols.append(f"h.{opt}")
                keys.append(opt)

        placeholders = ",".join("?" * len(actors))
        actor_where = f"(h.speaker IN ({placeholders}) OR h.target IN ({placeholders}))"
        where = (
            f"h.character_id=? AND h.is_active=0 AND {actor_where}"
            f"{self._where_not_deleted()}"
        )
        try:
            cursor.execute(
                f"""SELECT {', '.join(cols)} FROM history h
                    INNER JOIN embeddings e
                      ON e.source_table='history' AND e.source_id=h.id
                      AND e.character_id=h.character_id AND e.model_name=?
                    WHERE {where}""",
                tuple([model_name, self.character_id] + actors + actors),
            )
            return [dict(zip(keys, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Keyword search (embedding IS NULL rows)
    # ------------------------------------------------------------------

    def keyword_rows(self, cursor, *, keywords: list[str], limit: int) -> list[dict]:
        """LIKE-based search for rows that have no embeddings yet."""
        kw_clauses: list[str] = []
        kw_params: list[str] = []
        for k in keywords:
            if isinstance(k, str) and k.strip():
                kw_clauses.append("content LIKE ?")
                kw_params.append(f"%{k}%")
        if not kw_clauses:
            return []

        where = (
            "character_id=? AND is_active=0 AND (embedding IS NULL) "
            "AND content IS NOT NULL AND TRIM(content) != ''"
        )
        if "is_deleted" in self.schema.history_cols:
            where += " AND is_deleted=0"
        where += " AND (" + " OR ".join(kw_clauses) + ")"

        cols = ["id", "role", "content", "timestamp"]
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.schema.history_cols:
                cols.append(opt)

        try:
            cursor.execute(
                f"SELECT {', '.join(cols)} FROM history WHERE {where} ORDER BY id DESC LIMIT ?",
                tuple([self.character_id] + kw_params + [int(limit)]),
            )
            return [dict(zip(cols, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Context helpers used by QueryBuilder
    # ------------------------------------------------------------------

    def last_active_row(self, cursor) -> Optional[dict]:
        """Return the most recent active history row (for ctx speaker/target)."""
        possible = ["speaker", "target", "participants", "sender"]
        cols = [c for c in possible if c in self.schema.history_cols]
        if not cols:
            return None
        where = "character_id=? AND is_active=1"
        if "is_deleted" in self.schema.history_cols:
            where += " AND is_deleted=0"
        try:
            cursor.execute(
                f"SELECT {', '.join(cols)} FROM history WHERE {where} ORDER BY id DESC LIMIT 1",
                (self.character_id,),
            )
            row = cursor.fetchone()
            return dict(zip(cols, row)) if row else None
        except Exception:
            return None

    def recent_active_contents(
        self,
        cursor,
        *,
        tail: int,
        role_filter: str = "user_only",
    ) -> list[str]:
        """Return text content of recent active history messages."""
        if tail <= 0:
            return []
        rf = str(role_filter or "user_only").strip().lower()
        if rf not in ("user_only", "user_and_assistant", "assistant_only"):
            rf = "user_only"

        where = "character_id=? AND is_active=1"
        if "is_deleted" in self.schema.history_cols:
            where += " AND is_deleted=0"

        role_map = {
            "user_only": " AND role='user'",
            "assistant_only": " AND role='assistant'",
            "user_and_assistant": " AND role IN ('user','assistant')",
        }
        where += role_map[rf]
        try:
            cursor.execute(
                f"SELECT role, content FROM history WHERE {where} ORDER BY id DESC LIMIT ?",
                (self.character_id, int(tail)),
            )
            return [str(r[1] or "") for r in (cursor.fetchall() or []) if r[1]]
        except Exception:
            return []
