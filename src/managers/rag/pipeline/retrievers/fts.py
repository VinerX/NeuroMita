from __future__ import annotations

from typing import Any, List
import numpy as np

from managers.rag.rag_utils import (
    rag_clean_text,
    keyword_score,
    fts_build_match_query,
    normalize_bm25_to_01,
)
from handlers.embedding_presets import resolve_model_settings
from ..types import Candidate, QueryState
from ..config import RAGConfig


class FTSRetriever:
    name = "fts"

    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg
        self._model_name = resolve_model_settings()["hf_name"]

    def retrieve(self, qs: QueryState) -> List[Candidate]:
        out: list[Candidate] = []
        with self.rag.db.connection() as conn:
            cur = conn.cursor()
            if not self.rag.db.fts5_ready(cur):
                return out

            # prefer user query; fallback to expanded
            match_q = fts_build_match_query(
                str(qs.user_query or ""),
                max_terms=int(self.cfg.fts_max_terms),
                min_len=int(self.cfg.fts_min_len),
            )
            if not match_q:
                match_q = fts_build_match_query(
                    str(qs.expanded_query_text or ""),
                    max_terms=int(self.cfg.fts_max_terms),
                    min_len=int(self.cfg.fts_min_len),
                )
            if not match_q:
                return out

            if self.cfg.search_memory:
                out.extend(self._memories(cur, qs, match_q))
            if self.cfg.search_history:
                out.extend(self._histories(cur, qs, match_q))

        return out

    def _memories(self, cur, qs: QueryState, match_q: str) -> list[Candidate]:
        out: list[Candidate] = []

        rows = self._fts_memory_rows(
            cur,
            match_q=match_q,
            top_k=max(1, int(self.cfg.fts_top_k_mem)),
        )
        ranks = [float(r.get("rank") or 0.0) for r in rows]
        lex_scores = normalize_bm25_to_01(ranks)

        for rd, lex in zip(rows, lex_scores):
            mid = int(rd.get("eternal_id") or 0)
            if mid <= 0:
                continue

            content_raw = rd.get("content")
            content_clean = rag_clean_text(str(content_raw or ""))
            if not content_clean:
                continue

            sim = 0.0
            if qs.query_vec is not None:
                try:
                    blob = rd.get("embedding")
                    vec = self.rag._blob_to_array(blob) if blob is not None else None
                    if vec is not None:
                        sim = float(np.dot(qs.query_vec, vec))
                except Exception:
                    sim = 0.0

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, content_clean)
                except Exception:
                    kw = 0.0

            parts = self.rag._json_loads_list(rd.get("participants"))
            out.append(Candidate(
                source="memory",
                id=mid,
                content=content_raw,
                meta={
                    "type": rd.get("type"),
                    "priority": rd.get("priority"),
                    "date_created": rd.get("date_created"),
                    "participants": parts,
                    "entities": rd.get("entities"),
                    # optional debug-only:
                    "_bm25": float(rd.get("rank") or 0.0),
                },
                features={"sim": sim, "kw": float(kw), "lex": float(lex), "time": 0.0, "entity": 0.0, "prio": 0.0},
                debug={"bm25": float(rd.get("rank") or 0.0), "lex": float(lex)},
            ))

        return out

    def _histories(self, cur, qs: QueryState, match_q: str) -> list[Candidate]:
        out: list[Candidate] = []

        rows = self._fts_history_rows(
            cur,
            match_q=match_q,
            top_k=max(1, int(self.cfg.fts_top_k_hist)),
        )
        ranks = [float(r.get("rank") or 0.0) for r in rows]
        lex_scores = normalize_bm25_to_01(ranks)

        for rd, lex in zip(rows, lex_scores):
            hid = int(rd.get("id") or 0)
            if hid <= 0:
                continue

            content_raw = rd.get("content")
            content_clean = rag_clean_text(str(content_raw or ""))
            if not content_clean:
                continue

            sim = 0.0
            if qs.query_vec is not None:
                try:
                    blob = rd.get("embedding")
                    vec = self.rag._blob_to_array(blob) if blob is not None else None
                    if vec is not None:
                        sim = float(np.dot(qs.query_vec, vec))
                except Exception:
                    sim = 0.0

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, content_clean)
                except Exception:
                    kw = 0.0

            parts = self.rag._json_loads_list(rd.get("participants"))
            out.append(Candidate(
                source="history",
                id=hid,
                content=content_raw,
                meta={
                    "role": rd.get("role"),
                    "date": rd.get("timestamp"),
                    "message_id": rd.get("message_id"),
                    "speaker": str(rd.get("speaker") or "").strip() or None,
                    "target": str(rd.get("target") or "").strip() or None,
                    "participants": parts,
                    "entities": rd.get("entities"),
                    "_bm25": float(rd.get("rank") or 0.0),
                },
                features={"sim": sim, "kw": float(kw), "lex": float(lex), "time": 0.0, "entity": 0.0, "prio": 0.0},
                debug={"bm25": float(rd.get("rank") or 0.0), "lex": float(lex)},
            ))

        return out

    def _fts_history_rows(
        self,
        cursor,
        *,
        match_q: str,
        top_k: int,
    ) -> List[dict]:
        if not match_q:
            return []
        if not self.rag.db.table_exists(cursor, "history_fts"):
            return []

        cols = ["h.id", "bm25(history_fts) AS rank", "h.role", "h.content", "h.timestamp"]
        cols.append("e.embedding")
        opt = []
        for c in ("message_id", "speaker", "target", "participants", "entities"):
            if c in self.rag._history_cols:
                opt.append(f"h.{c}")
        cols += opt

        where = "h.character_id=? AND h.is_active=0"
        params: list[Any] = [self.rag.character_id]
        if "is_deleted" in self.rag._history_cols:
            where += " AND h.is_deleted=0"

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
                tuple([self._model_name, match_q] + params + [int(top_k)]),
            )
            rows = cursor.fetchall() or []
            keys = [c.split(" AS ")[-1].split(".")[-1] for c in cols]
            out = []
            for r in rows:
                rd = dict(zip(keys, r))
                out.append(rd)
            return out
        except Exception:
            return []

    def _fts_memory_rows(
        self,
        cursor,
        *,
        match_q: str,
        top_k: int,
    ) -> List[dict]:
        if not match_q:
            return []
        if not self.rag.db.table_exists(cursor, "memories_fts"):
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
        if "is_forgotten" in self.rag._mem_cols:
            cols.append("m.is_forgotten")
        if "entities" in self.rag._mem_cols:
            cols.append("m.entities")

        where = "m.character_id=? AND m.is_deleted=0"
        params: list[Any] = [self.rag.character_id]
        if "is_forgotten" in self.rag._mem_cols:
            if self.cfg.memory_mode == "forgotten":
                where += " AND m.is_forgotten=1"
            elif self.cfg.memory_mode == "active":
                where += " AND m.is_forgotten=0"
            elif self.cfg.memory_mode == "all":
                pass

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
                tuple([self._model_name, match_q] + params + [int(top_k)]),
            )
            rows = cursor.fetchall() or []
            keys = [c.split(" AS ")[-1].split(".")[-1] for c in cols]
            out = []
            for r in rows:
                rd = dict(zip(keys, r))
                out.append(rd)
            return out
        except Exception:
            return []
