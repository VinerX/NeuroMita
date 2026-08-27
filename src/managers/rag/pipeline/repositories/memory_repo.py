"""MemoryRepository — все SQL-запросы к таблице memories.

Принимает cursor (соединение открывает вызывающий код),
возвращает list[dict] с сырыми строками.
"""
from __future__ import annotations

from typing import Any, List, Optional

from managers.rag.pipeline.types import SchemaInfo


class MemoryRepository:
    """Инкапсулирует SQL к таблице memories; не знает о Candidate / RAGConfig."""

    def __init__(self, db: Any, character_id: str, schema: SchemaInfo) -> None:
        self.db = db
        self.character_id = character_id
        self.schema = schema

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _has_forgotten(self) -> bool:
        return "is_forgotten" in self.schema.mem_cols

    @property
    def _has_entities(self) -> bool:
        return "entities" in self.schema.mem_cols

    def _base_where(self, memory_mode: str) -> tuple[str, list]:
        """Build the WHERE clause and params for memory queries."""
        where = "m.character_id=? AND m.is_deleted=0 AND (m.type IS NULL OR m.type NOT LIKE 'island:%')"
        params: list = [self.character_id]
        if self._has_forgotten:
            if memory_mode == "forgotten":
                where += " AND m.is_forgotten=1"
            elif memory_mode == "active":
                where += " AND m.is_forgotten=0"
        elif memory_mode == "forgotten":
            # Column doesn't exist → can't filter, return sentinel
            return "__IMPOSSIBLE__", []
        return where, params

    def _base_cols_keys(self, *, include_forgotten: bool) -> tuple[list[str], list[str]]:
        cols = ["m.eternal_id", "m.content", "m.type", "m.priority", "m.date_created", "m.participants"]
        keys = ["eternal_id", "content", "type", "priority", "date_created", "participants"]
        if include_forgotten and self._has_forgotten:
            cols.append("m.is_forgotten")
            keys.append("is_forgotten")
        if self._has_entities:
            cols.append("m.entities")
            keys.append("entities")
        return cols, keys

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
        memory_mode: str = "active",
    ) -> list[dict]:
        """BM25 FTS5 search against memories_fts."""
        if not match_q:
            return []
        if not self.db.table_exists(cursor, "memories_fts"):
            return []

        cols = [
            "m.eternal_id",
            "bm25(memories_fts) AS rank",
            "m.content",
            "m.type",
            "m.priority",
            "m.date_created",
            "m.participants",
        ]
        cols.append("e.embedding")
        if self._has_forgotten:
            cols.append("m.is_forgotten")
        if self._has_entities:
            cols.append("m.entities")

        where = "m.character_id=? AND m.is_deleted=0 AND (m.type IS NULL OR m.type NOT LIKE 'island:%')"
        params: list = [self.character_id]
        if self._has_forgotten:
            if memory_mode == "forgotten":
                where += " AND m.is_forgotten=1"
            elif memory_mode == "active":
                where += " AND m.is_forgotten=0"
        elif memory_mode == "forgotten":
            return []

        try:
            cursor.execute(
                f"""
                SELECT {", ".join(cols)}
                FROM memories_fts
                JOIN memories m ON m.id = memories_fts.rowid
                LEFT JOIN embeddings e
                  ON e.source_table='memories' AND e.source_id=m.eternal_id
                  AND e.character_id=m.character_id AND e.model_name=?
                WHERE memories_fts MATCH ? AND {where}
                ORDER BY rank
                LIMIT ?
                """,
                tuple([model_name, match_q] + params + [int(top_k)]),
            )
            keys = [c.split(" AS ")[-1].split(".")[-1] for c in cols]
            return [dict(zip(keys, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Vector search — full blob scan (no FAISS)
    # ------------------------------------------------------------------

    def vector_blob_rows(
        self,
        cursor,
        *,
        model_name: str,
        memory_mode: str = "active",
    ) -> list[dict]:
        """Full blob scan: returns all memory rows with embeddings."""
        where, params = self._base_where(memory_mode)
        if where == "__IMPOSSIBLE__":
            return []

        cols, keys = self._base_cols_keys(include_forgotten=True)
        embed_col = "e.embedding"
        all_cols = cols[:1] + ["e.embedding"] + cols[1:]
        all_keys = keys[:1] + ["embedding"] + keys[1:]
        # Actually just append embedding:
        all_cols = cols + [embed_col]
        all_keys = keys + ["embedding"]

        try:
            cursor.execute(
                f"""SELECT {', '.join(all_cols)} FROM memories m
                    INNER JOIN embeddings e
                      ON e.source_table='memories' AND e.source_id=m.eternal_id
                      AND e.character_id=m.character_id AND e.model_name=?
                    WHERE {where}""",
                tuple([model_name] + params),
            )
            return [dict(zip(all_keys, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Vector search — metadata-only fetch for FAISS hits
    # ------------------------------------------------------------------

    def vector_meta_rows(
        self,
        cursor,
        *,
        model_name: str,
        ids: list[int],
        memory_mode: str = "active",
    ) -> list[dict]:
        """Fetch metadata (no embeddings) for a list of eternal_ids (FAISS hits)."""
        if not ids:
            return []
        where, params = self._base_where(memory_mode)
        if where == "__IMPOSSIBLE__":
            return []

        placeholders = ",".join("?" * len(ids))
        where += f" AND m.eternal_id IN ({placeholders})"
        params += ids

        cols, keys = self._base_cols_keys(include_forgotten=True)
        try:
            cursor.execute(
                f"SELECT {', '.join(cols)} FROM memories m WHERE {where}",
                tuple(params),
            )
            return [dict(zip(keys, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Sentence-level retrieval
    # ------------------------------------------------------------------

    def sentence_rows(
        self,
        cursor,
        *,
        model_name: str,
        memory_mode: str = "active",
    ) -> list[dict]:
        """Retrieve memories joined with per-sentence embeddings."""
        where, params = self._base_where(memory_mode)
        if where == "__IMPOSSIBLE__":
            return []

        mem_cols, mem_keys = self._base_cols_keys(include_forgotten=True)
        try:
            cursor.execute(
                f"""SELECT {', '.join(mem_cols)}, se.sentence_idx, se.embedding
                    FROM memories m
                    INNER JOIN sentence_embeddings se
                      ON se.source_table='memories' AND se.source_id=m.eternal_id
                      AND se.character_id=m.character_id AND se.model_name=?
                    WHERE {where}""",
                tuple([model_name] + params),
            )
            keys_full = mem_keys + ["sentence_idx", "embedding"]
            return [dict(zip(keys_full, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Keyword search (embedding IS NULL rows)
    # ------------------------------------------------------------------

    def keyword_rows(
        self,
        cursor,
        *,
        keywords: list[str],
        limit: int,
        memory_mode: str = "active",
    ) -> list[dict]:
        """LIKE-based search for memory rows that have no embeddings yet."""
        kw_clauses: list[str] = []
        kw_params: list[str] = []
        for k in keywords:
            if isinstance(k, str) and k.strip():
                kw_clauses.append("content LIKE ?")
                kw_params.append(f"%{k}%")
        if not kw_clauses:
            return []

        has_forgotten = self._has_forgotten
        if (not has_forgotten) and memory_mode == "forgotten":
            return []

        where = "character_id=? AND is_deleted=0 AND (type IS NULL OR type NOT LIKE 'island:%') AND (embedding IS NULL) AND content IS NOT NULL AND TRIM(content) != ''"
        params: list[Any] = [self.character_id]
        if has_forgotten:
            if memory_mode == "forgotten":
                where += " AND is_forgotten=1"
            elif memory_mode == "active":
                where += " AND is_forgotten=0"
        where += " AND (" + " OR ".join(kw_clauses) + ")"
        params.extend(kw_params)

        cols = ["eternal_id", "content", "type", "priority", "date_created", "participants"]
        if has_forgotten:
            cols.append("is_forgotten")
        if self._has_entities:
            cols.append("entities")

        try:
            cursor.execute(
                f"SELECT {', '.join(cols)} FROM memories WHERE {where} ORDER BY eternal_id DESC LIMIT ?",
                tuple(params + [int(limit)]),
            )
            return [dict(zip(cols, row)) for row in (cursor.fetchall() or [])]
        except Exception:
            return []
