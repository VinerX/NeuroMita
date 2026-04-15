from __future__ import annotations

from typing import Any, List
import numpy as np

from managers.rag.rag_utils import (
    rag_clean_text,
    keyword_score,
    blob_to_array,
    l2_normalize,
    json_loads_list,
)
from handlers.embedding_presets import resolve_model_settings
from ..types import Candidate, QueryState
from ..config import RAGConfig
from ..repositories import HistoryRepository, MemoryRepository
from .faiss_index import HAS_FAISS, faiss_retrieve


class VectorRetriever:
    name = "vector"

    def __init__(
        self,
        *,
        history_repo: HistoryRepository,
        memory_repo: MemoryRepository,
        rag: Any,  # kept for db access during transition
        cfg: RAGConfig,
    ):
        self.history_repo = history_repo
        self.memory_repo = memory_repo
        self.rag = rag
        self.cfg = cfg
        self._model_name = resolve_model_settings()["hf_name"]

    def retrieve(self, qs: QueryState) -> List[Candidate]:
        if qs.query_vec is None:
            from main_logger import logger as _log
            _log.warning(
                "[VectorRetriever] query_vec is None — embedding model failed to load or "
                "RAG_ENABLED=False. Vector search disabled; results will use FTS/keyword only."
            )
            return []

        out: list[Candidate] = []

        with self.rag.db.connection() as conn:
            cur = conn.cursor()

            # --- Memories ---
            if self.cfg.search_memory:
                if self.cfg.sentence_level:
                    out.extend(self._memories_sentence(cur, qs))
                else:
                    out.extend(self._memories(cur, qs))

            # --- History ---
            if self.cfg.search_history:
                if self.cfg.sentence_level:
                    out.extend(self._histories_sentence(cur, qs))
                else:
                    out.extend(self._histories(cur, qs))
                # --- Actor pre-filter (extra pass at threshold=0) ---
                if self.cfg.prefilter_actors and qs.ctx_actors:
                    out.extend(self._histories_actor_boost(cur, qs))

        return out

    # ------------------------------------------------------------------
    # Memories
    # ------------------------------------------------------------------

    def _memories(self, cur, qs: QueryState) -> list[Candidate]:
        out: list[Candidate] = []
        thr = float(self.cfg.threshold or 0.0)

        # ── FAISS fast-path ────────────────────────────────────────────────
        if HAS_FAISS:
            hits = faiss_retrieve(
                cur.connection, self.rag.character_id,
                self._model_name, "memories",
                qs.query_vec, k=500,
            )
            if hits:
                return self._memories_from_faiss(cur, qs, hits, thr)
        # ── fallback: full blob scan ───────────────────────────────────────

        rows = self.memory_repo.vector_blob_rows(
            cur,
            model_name=self._model_name,
            memory_mode=self.cfg.memory_mode,
        )
        for rd in rows:
            eternal_id = int(rd.get("eternal_id") or 0)
            if eternal_id <= 0:
                continue

            vec = blob_to_array(rd.get("embedding"))
            if vec is None:
                continue
            if np.isnan(vec).any() or np.isinf(vec).any():
                continue
            vec = l2_normalize(vec)
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

            parts = json_loads_list(rd.get("participants"))
            out.append(Candidate(
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
            ))

        return out

    def _memories_from_faiss(
        self, cur, qs: QueryState,
        hits: list[tuple[int, float]],
        thr: float,
    ) -> list[Candidate]:
        """Build Candidates from FAISS hits: fetch only metadata (no blobs)."""
        out: list[Candidate] = []

        candidates = [(eid, sim) for eid, sim in hits if sim >= thr or self.cfg.kw_enabled]
        if not candidates:
            return out

        sim_map = {eid: sim for eid, sim in candidates}
        rows = self.memory_repo.vector_meta_rows(
            cur,
            model_name=self._model_name,
            ids=list(sim_map.keys()),
            memory_mode=self.cfg.memory_mode,
        )
        for rd in rows:
            eternal_id = int(rd.get("eternal_id") or 0)
            if eternal_id <= 0:
                continue

            sim = sim_map.get(eternal_id, 0.0)

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, rag_clean_text(str(rd.get("content") or "")))
                except Exception:
                    kw = 0.0

            if sim < thr and (not self.cfg.kw_enabled or kw < float(self.cfg.kw_min_score or 0.0)):
                continue

            parts = json_loads_list(rd.get("participants"))
            out.append(Candidate(
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
            ))

        return out

    def _memories_sentence(self, cur, qs: QueryState) -> list[Candidate]:
        """Retrieve memories using per-sentence embeddings, fall back to whole-doc."""
        rows = self.memory_repo.sentence_rows(
            cur,
            model_name=self._model_name,
            memory_mode=self.cfg.memory_mode,
        )
        if not rows:
            return self._memories(cur, qs)

        thr = float(self.cfg.threshold or 0.0)
        best: dict[int, dict] = {}
        for rd in rows:
            eid = int(rd.get("eternal_id") or 0)
            if eid <= 0:
                continue
            vec = blob_to_array(rd.get("embedding"))
            if vec is None:
                continue
            if np.isnan(vec).any() or np.isinf(vec).any():
                continue
            vec = l2_normalize(vec)
            if vec is None:
                continue
            sim = float(np.dot(qs.query_vec, vec))
            if eid not in best or sim > best[eid]["sim"]:
                best[eid] = {"sim": sim, "rd": rd}

        out: list[Candidate] = []
        for eid, entry in best.items():
            sim = entry["sim"]
            rd = entry["rd"]

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, rag_clean_text(str(rd.get("content") or "")))
                except Exception:
                    kw = 0.0

            if sim < thr and (not self.cfg.kw_enabled or kw < float(self.cfg.kw_min_score or 0.0)):
                continue

            parts = json_loads_list(rd.get("participants"))
            out.append(Candidate(
                source="memory",
                id=eid,
                content=rd.get("content"),
                meta={
                    "type": rd.get("type"),
                    "priority": rd.get("priority"),
                    "date_created": rd.get("date_created"),
                    "participants": parts,
                    "entities": rd.get("entities"),
                },
                features={"sim": sim, "kw": kw, "lex": 0.0, "time": 0.0, "entity": 0.0, "prio": 0.0},
                debug={"matched_sentence": int(rd.get("sentence_idx") or 0)},
            ))

        return out

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _histories(self, cur, qs: QueryState) -> list[Candidate]:
        thr = float(self.cfg.threshold or 0.0)

        # ── FAISS fast-path ────────────────────────────────────────────────
        if HAS_FAISS:
            hits = faiss_retrieve(
                cur.connection, self.rag.character_id,
                self._model_name, "history",
                qs.query_vec, k=500,
            )
            if hits:
                return self._histories_from_faiss(cur, qs, hits, thr)
        # ── fallback: full blob scan ───────────────────────────────────────

        out: list[Candidate] = []
        rows = self.history_repo.vector_blob_rows(cur, model_name=self._model_name)
        for rd in rows:
            hid = int(rd.get("id") or 0)
            if hid <= 0:
                continue

            vec = blob_to_array(rd.get("embedding"))
            if vec is None:
                continue
            if np.isnan(vec).any() or np.isinf(vec).any():
                continue
            vec = l2_normalize(vec)
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

            parts = json_loads_list(rd.get("participants"))
            out.append(Candidate(
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
            ))

        return out

    def _histories_from_faiss(
        self, cur, qs: QueryState,
        hits: list[tuple[int, float]],
        thr: float,
    ) -> list[Candidate]:
        """Build Candidates from FAISS hits: fetch only metadata (no blobs)."""
        out: list[Candidate] = []

        candidates = [(hid, sim) for hid, sim in hits if sim >= thr or self.cfg.kw_enabled]
        if not candidates:
            return out

        sim_map = {hid: sim for hid, sim in candidates}
        rows = self.history_repo.vector_meta_rows(
            cur,
            model_name=self._model_name,
            ids=list(sim_map.keys()),
        )
        for rd in rows:
            hid = int(rd.get("id") or 0)
            if hid <= 0:
                continue

            sim = sim_map.get(hid, 0.0)

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, rag_clean_text(str(rd.get("content") or "")))
                except Exception:
                    kw = 0.0

            if sim < thr and (not self.cfg.kw_enabled or kw < float(self.cfg.kw_min_score or 0.0)):
                continue

            parts = json_loads_list(rd.get("participants"))
            out.append(Candidate(
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
            ))

        return out

    def _histories_sentence(self, cur, qs: QueryState) -> list[Candidate]:
        """Retrieve history using per-sentence embeddings.

        Falls back to whole-message embeddings if no sentence embeddings exist.
        """
        rows = self.history_repo.sentence_rows(cur, model_name=self._model_name)
        if not rows:
            return self._histories(cur, qs)

        thr = float(self.cfg.threshold or 0.0)
        best: dict[int, dict] = {}
        for rd in rows:
            hid = int(rd.get("id") or 0)
            if hid <= 0:
                continue
            vec = blob_to_array(rd.get("embedding"))
            if vec is None:
                continue
            if np.isnan(vec).any() or np.isinf(vec).any():
                continue
            vec = l2_normalize(vec)
            if vec is None:
                continue
            sim = float(np.dot(qs.query_vec, vec))
            if hid not in best or sim > best[hid]["sim"]:
                best[hid] = {"sim": sim, "rd": rd}

        out: list[Candidate] = []
        for hid, entry in best.items():
            sim = entry["sim"]
            rd = entry["rd"]

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, rag_clean_text(str(rd.get("content") or "")))
                except Exception:
                    kw = 0.0

            if sim < thr and (not self.cfg.kw_enabled or kw < float(self.cfg.kw_min_score or 0.0)):
                continue

            parts = json_loads_list(rd.get("participants"))
            out.append(Candidate(
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
                debug={"matched_sentence": int(rd.get("sentence_idx") or 0)},
            ))

        return out

    def _histories_actor_boost(self, cur, qs: QueryState) -> list[Candidate]:
        """Extra pass: fetch history rows where speaker or target matches ctx_actors."""
        actors = [a for a in qs.ctx_actors if a]
        if not actors:
            return []

        out: list[Candidate] = []
        rows = self.history_repo.actor_boost_rows(
            cur,
            model_name=self._model_name,
            actors=actors,
        )
        for rd in rows:
            hid = int(rd.get("id") or 0)
            if hid <= 0:
                continue

            vec = blob_to_array(rd.get("embedding"))
            if vec is None:
                continue
            if np.isnan(vec).any() or np.isinf(vec).any():
                continue
            vec = l2_normalize(vec)
            if vec is None:
                continue

            sim = float(np.dot(qs.query_vec, vec))

            kw = 0.0
            if self.cfg.kw_enabled and qs.keywords:
                try:
                    kw, _ = keyword_score(qs.keywords, rag_clean_text(str(rd.get("content") or "")))
                except Exception:
                    kw = 0.0

            parts = json_loads_list(rd.get("participants"))
            out.append(Candidate(
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
            ))

        return out
