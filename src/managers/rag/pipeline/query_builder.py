from __future__ import annotations

import datetime
from typing import Any

from managers.rag.rag_utils import rag_clean_text, extract_keywords
from .types import QueryState
from .config import RAGConfig


class QueryBuilder:
    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg

    def build(self, user_query: str) -> QueryState:
        uq = str(user_query or "").strip()
        expanded = self.rag._build_query_from_recent(uq, tail=int(self.cfg.tail_messages or 0))

        keywords: list[str] = []
        if self.cfg.kw_enabled:
            try:
                primary = rag_clean_text(uq)
                kw_primary = extract_keywords(
                    primary,
                    max_terms=self.cfg.kw_max_terms,
                    min_len=self.cfg.kw_min_len,
                    lemmatize=self.cfg.lemmatization,
                )
                kw_ctx = extract_keywords(
                    expanded,
                    max_terms=self.cfg.kw_max_terms,
                    min_len=self.cfg.kw_min_len,
                    from_end=True,
                    lemmatize=self.cfg.lemmatization,
                )

                merged: list[str] = []
                seen = set()
                for k in (kw_primary + kw_ctx):
                    ks = str(k or "").strip().lower()
                    if not ks or ks in seen:
                        continue
                    merged.append(ks)
                    seen.add(ks)
                    if len(merged) >= int(self.cfg.kw_max_terms):
                        break
                keywords = merged
            except Exception:
                keywords = []

        # embedding can be None
        qvec = self.rag._build_query_embedding(uq, tail=int(self.cfg.tail_messages or 0))

        # ctx entities from last active message (same logic as old)
        ctx_speaker = ""
        ctx_target = ""
        ctx_participants: list[str] = []
        try:
            with self.rag.db.connection() as conn:
                cur = conn.cursor()

                where = "character_id=? AND is_active=1"
                params = [self.rag.character_id]
                if "is_deleted" in self.rag._history_cols:
                    where += " AND is_deleted=0"

                cols = ["speaker", "target", "participants", "sender"]
                cols = [c for c in cols if c in self.rag._history_cols]
                if cols:
                    cur.execute(
                        f"SELECT {', '.join(cols)} FROM history WHERE {where} ORDER BY id DESC LIMIT 1",
                        tuple(params),
                    )
                    row = cur.fetchone()
                    if row:
                        rd = dict(zip(cols, row))
                        ctx_speaker = str(rd.get("speaker") or rd.get("sender") or "").strip()
                        ctx_target = str(rd.get("target") or "").strip()
                        ctx_participants = self.rag._json_loads_list(rd.get("participants"))
        except Exception:
            pass

        return QueryState(
            character_id=self.rag.character_id,
            user_query=uq,
            expanded_query_text=expanded,
            query_vec=qvec,
            keywords=keywords,
            now_ts=datetime.datetime.now(),
            ctx_speaker=ctx_speaker,
            ctx_target=ctx_target,
            ctx_participants=ctx_participants,
        )
