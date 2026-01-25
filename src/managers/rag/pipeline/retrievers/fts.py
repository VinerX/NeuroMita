from __future__ import annotations

from typing import Any, List
import numpy as np

from managers.rag.rag_utils import rag_clean_text
from managers.rag.rag_keyword_search import keyword_score
from ..types import Candidate, QueryState
from ..config import RAGConfig


class FTSRetriever:
    name = "fts"

    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg

    def retrieve(self, qs: QueryState) -> List[Candidate]:
        out: list[Candidate] = []
        conn = self.rag.db.get_connection()
        try:
            cur = conn.cursor()
            if not self.rag.db.fts5_ready(cur):
                return out

            # prefer user query; fallback to expanded
            match_q = self.rag._fts_build_match_query(
                str(qs.user_query or ""),
                max_terms=int(self.cfg.fts_max_terms),
                min_len=int(self.cfg.fts_min_len),
            )
            if not match_q:
                match_q = self.rag._fts_build_match_query(
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

        finally:
            try:
                conn.close()
            except Exception:
                pass

        return out

    def _memories(self, cur, qs: QueryState, match_q: str) -> list[Candidate]:
        out: list[Candidate] = []

        rows = self.rag._fts_memory_rows(
            cur,
            match_q=match_q,
            top_k=max(1, int(self.cfg.fts_top_k_mem)),
            memory_mode=self.cfg.memory_mode,
        )
        ranks = [float(r.get("rank") or 0.0) for r in rows]
        lex_scores = self.rag._normalize_bm25_to_01(ranks)

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
                    # optional debug-only:
                    "_bm25": float(rd.get("rank") or 0.0),
                },
                features={"sim": sim, "kw": float(kw), "lex": float(lex), "time": 0.0, "entity": 0.0, "prio": 0.0},
                debug={"bm25": float(rd.get("rank") or 0.0), "lex": float(lex)},
            ))

        return out

    def _histories(self, cur, qs: QueryState, match_q: str) -> list[Candidate]:
        out: list[Candidate] = []

        rows = self.rag._fts_history_rows(
            cur,
            match_q=match_q,
            top_k=max(1, int(self.cfg.fts_top_k_hist)),
        )
        ranks = [float(r.get("rank") or 0.0) for r in rows]
        lex_scores = self.rag._normalize_bm25_to_01(ranks)

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
                    "speaker": str(rd.get("speaker") or "").strip() or None,
                    "target": str(rd.get("target") or "").strip() or None,
                    "participants": parts,
                    "_bm25": float(rd.get("rank") or 0.0),
                },
                features={"sim": sim, "kw": float(kw), "lex": float(lex), "time": 0.0, "entity": 0.0, "prio": 0.0},
                debug={"bm25": float(rd.get("rank") or 0.0), "lex": float(lex)},
            ))

        return out