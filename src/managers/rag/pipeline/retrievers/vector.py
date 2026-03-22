from __future__ import annotations

from typing import Any, List
import numpy as np

from managers.rag.rag_utils import rag_clean_text, keyword_score
from handlers.embedding_presets import resolve_model_settings
from ..types import Candidate, QueryState
from ..config import RAGConfig


class VectorRetriever:
    name = "vector"

    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg
        self._model_name = resolve_model_settings()["hf_name"]

    def retrieve(self, qs: QueryState) -> List[Candidate]:
        if qs.query_vec is None:
            return []

        out: list[Candidate] = []

        with self.rag.db.connection() as conn:
            cur = conn.cursor()

            # --- Memories ---
            if self.cfg.search_memory:
                out.extend(self._memories(cur, qs))

            # --- History ---
            if self.cfg.search_history:
                out.extend(self._histories(cur, qs))

        return out

    def _memories(self, cur, qs: QueryState) -> list[Candidate]:
        out: list[Candidate] = []

        mem_where = "m.character_id=? AND m.is_deleted=0"
        params: list = [self.rag.character_id]

        has_forgotten_col = ("is_forgotten" in self.rag._mem_cols)
        if has_forgotten_col:
            if self.cfg.memory_mode == "forgotten":
                mem_where += " AND m.is_forgotten=1"
            elif self.cfg.memory_mode == "active":
                mem_where += " AND m.is_forgotten=0"
        else:
            if self.cfg.memory_mode == "forgotten":
                return out

        cols = ["m.eternal_id", "m.content", "e.embedding", "m.type", "m.priority", "m.date_created", "m.participants"]
        keys = ["eternal_id", "content", "embedding", "type", "priority", "date_created", "participants"]
        if has_forgotten_col:
            cols.append("m.is_forgotten")
            keys.append("is_forgotten")
        if "entities" in self.rag._mem_cols:
            cols.append("m.entities")
            keys.append("entities")

        try:
            cur.execute(
                f"""SELECT {', '.join(cols)} FROM memories m
                    INNER JOIN embeddings e
                      ON e.source_table='memories' AND e.source_id=m.eternal_id
                      AND e.character_id=m.character_id AND e.model_name=?
                    WHERE {mem_where}""",
                tuple([self._model_name] + params),
            )
            rows = cur.fetchall() or []
        except Exception:
            return out

        thr = float(self.cfg.threshold or 0.0)

        for row in rows:
            rd = dict(zip(keys, row))
            eternal_id = int(rd.get("eternal_id") or 0)
            if eternal_id <= 0:
                continue

            blob = rd.get("embedding")
            vec = self.rag._blob_to_array(blob)
            if vec is None:
                continue
            if np.isnan(vec).any() or np.isinf(vec).any():
                continue
            vec = self.rag._l2_normalize(vec)
            if vec is None:
                continue

            sim = float(np.dot(qs.query_vec, vec))

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, rag_clean_text(str(rd.get("content") or "")))
                except Exception:
                    kw = 0.0

            if sim < thr and (not self.cfg.kw_enabled or kw < float(self.cfg.kw_min_score or 0.0)):
                continue

            parts = self.rag._json_loads_list(rd.get("participants"))
            c = Candidate(
                source="memory",
                id=eternal_id,
                content=rd.get("content"),
                meta={
                    "type": rd.get("type"),
                    "priority": rd.get("priority"),
                    "date_created": rd.get("date_created"),
                    "participants": parts,
                    "entities": rd.get("entities"),
                },
                features={"sim": sim, "kw": kw, "lex": 0.0, "time": 0.0, "entity": 0.0, "prio": 0.0},
            )
            out.append(c)

        return out

    def _histories(self, cur, qs: QueryState) -> list[Candidate]:
        out: list[Candidate] = []

        cols = ["h.id", "h.role", "h.content", "e.embedding", "h.timestamp"]
        keys = ["id", "role", "content", "embedding", "timestamp"]
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.rag._history_cols:
                cols.append(f"h.{opt}")
                keys.append(opt)

        where = "h.character_id=? AND h.is_active=0"
        params: list = [self.rag.character_id]
        if "is_deleted" in self.rag._history_cols:
            where += " AND h.is_deleted=0"

        try:
            cur.execute(
                f"""SELECT {', '.join(cols)} FROM history h
                    INNER JOIN embeddings e
                      ON e.source_table='history' AND e.source_id=h.id
                      AND e.character_id=h.character_id AND e.model_name=?
                    WHERE {where}""",
                tuple([self._model_name] + params),
            )
            rows = cur.fetchall() or []
        except Exception:
            return out

        thr = float(self.cfg.threshold or 0.0)

        for row in rows:
            rd = dict(zip(keys, row))
            hid = int(rd.get("id") or 0)
            if hid <= 0:
                continue

            blob = rd.get("embedding")
            vec = self.rag._blob_to_array(blob)
            if vec is None:
                continue
            if np.isnan(vec).any() or np.isinf(vec).any():
                continue
            vec = self.rag._l2_normalize(vec)
            if vec is None:
                continue

            sim = float(np.dot(qs.query_vec, vec))

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, rag_clean_text(str(rd.get("content") or "")))
                except Exception:
                    kw = 0.0

            if sim < thr and (not self.cfg.kw_enabled or kw < float(self.cfg.kw_min_score or 0.0)):
                continue

            parts = self.rag._json_loads_list(rd.get("participants"))
            c = Candidate(
                source="history",
                id=hid,
                content=rd.get("content"),
                meta={
                    "role": rd.get("role"),
                    "date": rd.get("timestamp"),
                    "message_id": rd.get("message_id"),
                    "speaker": str(rd.get("speaker") or "").strip() or None,
                    "target": str(rd.get("target") or "").strip() or None,
                    "participants": parts,
                    "entities": rd.get("entities"),
                },
                features={"sim": sim, "kw": kw, "lex": 0.0, "time": 0.0, "entity": 0.0, "prio": 0.0},
            )
            out.append(c)

        return out
