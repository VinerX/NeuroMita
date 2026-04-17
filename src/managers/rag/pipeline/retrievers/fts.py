from __future__ import annotations

from typing import Any, List
import numpy as np

from managers.rag.rag_utils import (
    rag_clean_text,
    keyword_score,
    fts_build_match_query,
    normalize_bm25_to_01,
    blob_to_array,
    json_loads_list,
)
from handlers.embedding_presets import resolve_full_config
from ..types import Candidate, QueryState
from ..config import RAGConfig
from ..repositories import HistoryRepository, MemoryRepository


class FTSRetriever:
    name = "fts"

    def __init__(
        self,
        *,
        history_repo: HistoryRepository,
        memory_repo: MemoryRepository,
        rag: Any,  # kept for db/character_id access during transition
        cfg: RAGConfig,
    ):
        self.history_repo = history_repo
        self.memory_repo = memory_repo
        self.rag = rag
        self.cfg = cfg
        cfg_full = resolve_full_config()
        self._model_name = str(
            cfg_full.get("db_model_key") or cfg_full.get("hf_name") or cfg_full.get("model") or ""
        )

    def retrieve(self, qs: QueryState) -> List[Candidate]:
        out: list[Candidate] = []
        with self.rag.db.connection() as conn:
            cur = conn.cursor()
            if not self.rag.db.fts5_ready(cur):
                return out

            _fts_kwargs = dict(
                max_terms=int(self.cfg.fts_max_terms),
                min_len=int(self.cfg.fts_min_len),
                morph_expand=bool(self.cfg.fts_morph_expand),
                prefix_match=bool(self.cfg.fts_prefix_match),
            )
            match_q = fts_build_match_query(str(qs.user_query or ""), **_fts_kwargs)
            if not match_q:
                match_q = fts_build_match_query(str(qs.expanded_query_text or ""), **_fts_kwargs)
            if not match_q:
                return out

            if self.cfg.search_memory:
                out.extend(self._memories(cur, qs, match_q))
            if self.cfg.search_history:
                out.extend(self._histories(cur, qs, match_q))

        return out

    def _memories(self, cur, qs: QueryState, match_q: str) -> list[Candidate]:
        out: list[Candidate] = []

        rows = self.memory_repo.fts_rows(
            cur,
            match_q=match_q,
            top_k=max(1, int(self.cfg.fts_top_k_mem)),
            model_name=self._model_name,
            memory_mode=self.cfg.memory_mode,
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
                    vec = blob_to_array(rd.get("embedding"))
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

            parts = json_loads_list(rd.get("participants"))
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
                    "_bm25": float(rd.get("rank") or 0.0),
                },
                features={"sim": sim, "kw": float(kw), "lex": float(lex), "time": 0.0, "entity": 0.0, "prio": 0.0},
                debug={"bm25": float(rd.get("rank") or 0.0), "lex": float(lex)},
            ))

        return out

    def _histories(self, cur, qs: QueryState, match_q: str) -> list[Candidate]:
        out: list[Candidate] = []

        rows = self.history_repo.fts_rows(
            cur,
            match_q=match_q,
            top_k=max(1, int(self.cfg.fts_top_k_hist)),
            model_name=self._model_name,
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
                    vec = blob_to_array(rd.get("embedding"))
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

            parts = json_loads_list(rd.get("participants"))
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
