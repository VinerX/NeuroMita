from __future__ import annotations

from typing import Any, List
import numpy as np

from managers.rag.rag_utils import rag_clean_text, keyword_score
from handlers.embedding_presets import resolve_model_settings
from ..types import Candidate, QueryState
from ..config import RAGConfig
from .faiss_index import HAS_FAISS, faiss_retrieve


class VectorRetriever:
    name = "vector"

    def __init__(self, *, rag: Any, cfg: RAGConfig):
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

    def _memories(self, cur, qs: QueryState) -> list[Candidate]:
        out: list[Candidate] = []

        has_forgotten_col = ("is_forgotten" in self.rag._mem_cols)
        thr = float(self.cfg.threshold or 0.0)

        # ── FAISS fast-path ────────────────────────────────────────────────
        if HAS_FAISS:
            hits = faiss_retrieve(
                cur.connection, self.rag.character_id,
                self._model_name, "memories",
                qs.query_vec, k=500,
            )
            if hits:
                return self._memories_from_faiss(cur, qs, hits, has_forgotten_col, thr)
        # ── fallback: full blob scan ───────────────────────────────────────

        mem_where = "m.character_id=? AND m.is_deleted=0"
        params: list = [self.rag.character_id]

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

    def _memories_from_faiss(
        self, cur, qs: QueryState,
        hits: list[tuple[int, float]],
        has_forgotten_col: bool,
        thr: float,
    ) -> list[Candidate]:
        """Build Candidates from FAISS hits: fetch only metadata (no blobs)."""
        out: list[Candidate] = []

        # Pre-filter by threshold (keep if sim>=thr; also keep if kw may rescue)
        candidates = [(eid, sim) for eid, sim in hits if sim >= thr or self.cfg.kw_enabled]
        if not candidates:
            return out

        sim_map = {eid: sim for eid, sim in candidates}
        ids = list(sim_map.keys())
        placeholders = ",".join("?" * len(ids))

        mem_where = f"m.character_id=? AND m.is_deleted=0 AND m.eternal_id IN ({placeholders})"
        params: list = [self.rag.character_id] + ids

        if has_forgotten_col:
            if self.cfg.memory_mode == "forgotten":
                mem_where += " AND m.is_forgotten=1"
            elif self.cfg.memory_mode == "active":
                mem_where += " AND m.is_forgotten=0"
        else:
            if self.cfg.memory_mode == "forgotten":
                return out

        cols = ["m.eternal_id", "m.content", "m.type", "m.priority", "m.date_created", "m.participants"]
        keys = ["eternal_id", "content", "type", "priority", "date_created", "participants"]
        if has_forgotten_col:
            cols.append("m.is_forgotten"); keys.append("is_forgotten")
        if "entities" in self.rag._mem_cols:
            cols.append("m.entities"); keys.append("entities")

        try:
            cur.execute(f"SELECT {', '.join(cols)} FROM memories m WHERE {mem_where}", tuple(params))
            rows = cur.fetchall() or []
        except Exception:
            return out

        for row in rows:
            rd = dict(zip(keys, row))
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

            parts = self.rag._json_loads_list(rd.get("participants"))
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

    # ------------------------------------------------------------------ #
    #  Actor pre-filter: extra retrieval pass limited to speaker/target   #
    # ------------------------------------------------------------------ #

    def _histories_actor_boost(self, cur, qs: QueryState) -> list[Candidate]:
        """Extra pass: fetch history rows where speaker or target matches ctx_actors.

        Uses threshold=0 so actor-relevant docs are always in the candidate pool
        regardless of vector similarity.  The combiner deduplicates by key.
        """
        actors = [a for a in qs.ctx_actors if a]
        if not actors:
            return []

        out: list[Candidate] = []

        cols = ["h.id", "h.role", "h.content", "e.embedding", "h.timestamp"]
        keys = ["id", "role", "content", "embedding", "timestamp"]
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.rag._history_cols:
                cols.append(f"h.{opt}")
                keys.append(opt)

        placeholders = ",".join("?" * len(actors))
        actor_where = f"(h.speaker IN ({placeholders}) OR h.target IN ({placeholders}))"
        where = f"h.character_id=? AND h.is_active=0 AND {actor_where}"
        where_params: list = [self.rag.character_id] + actors + actors
        if "is_deleted" in self.rag._history_cols:
            where += " AND h.is_deleted=0"

        try:
            cur.execute(
                f"""SELECT {', '.join(cols)} FROM history h
                    INNER JOIN embeddings e
                      ON e.source_table='history' AND e.source_id=h.id
                      AND e.character_id=h.character_id AND e.model_name=?
                    WHERE {where}""",
                tuple([self._model_name] + where_params),
            )
            rows = cur.fetchall() or []
        except Exception:
            return []

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

    # ------------------------------------------------------------------ #
    #  Sentence-level retrieval                                           #
    # ------------------------------------------------------------------ #

    def _histories_sentence(self, cur, qs: QueryState) -> list[Candidate]:
        """Retrieve history using per-sentence embeddings from sentence_embeddings table.

        For each message, the sentence with the highest cosine similarity is used.
        Falls back to whole-message embeddings if no sentence embeddings exist.
        """
        cols_h = ["h.id", "h.role", "h.content", "h.timestamp"]
        keys_h = ["id", "role", "content", "timestamp"]
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.rag._history_cols:
                cols_h.append(f"h.{opt}")
                keys_h.append(opt)

        where = "h.character_id=? AND h.is_active=0"
        params: list = [self.rag.character_id]
        if "is_deleted" in self.rag._history_cols:
            where += " AND h.is_deleted=0"

        try:
            cur.execute(
                f"""SELECT {', '.join(cols_h)}, se.sentence_idx, se.embedding
                    FROM history h
                    INNER JOIN sentence_embeddings se
                      ON se.source_table='history' AND se.source_id=h.id
                      AND se.character_id=h.character_id AND se.model_name=?
                    WHERE {where}""",
                tuple([self._model_name] + params),
            )
            rows = cur.fetchall() or []
        except Exception:
            # Table may not exist yet → fall back to whole-doc retrieval
            return self._histories(cur, qs)

        if not rows:
            return self._histories(cur, qs)

        keys_full = keys_h + ["sentence_idx", "embedding"]
        thr = float(self.cfg.threshold or 0.0)

        # Group by message id: keep best (max sim) sentence per message
        best: dict[int, dict] = {}
        for row in rows:
            rd = dict(zip(keys_full, row))
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
                debug={"matched_sentence": int(rd.get("sentence_idx") or 0)},
            )
            out.append(c)

        return out

    def _memories_sentence(self, cur, qs: QueryState) -> list[Candidate]:
        """Retrieve memories using per-sentence embeddings, fall back to whole-doc."""
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
                return []

        mem_cols = ["m.eternal_id", "m.content", "m.type", "m.priority", "m.date_created", "m.participants"]
        mem_keys = ["eternal_id", "content", "type", "priority", "date_created", "participants"]
        if has_forgotten_col:
            mem_cols.append("m.is_forgotten")
            mem_keys.append("is_forgotten")
        if "entities" in self.rag._mem_cols:
            mem_cols.append("m.entities")
            mem_keys.append("entities")

        try:
            cur.execute(
                f"""SELECT {', '.join(mem_cols)}, se.sentence_idx, se.embedding
                    FROM memories m
                    INNER JOIN sentence_embeddings se
                      ON se.source_table='memories' AND se.source_id=m.eternal_id
                      AND se.character_id=m.character_id AND se.model_name=?
                    WHERE {mem_where}""",
                tuple([self._model_name] + params),
            )
            rows = cur.fetchall() or []
        except Exception:
            return self._memories(cur, qs)

        if not rows:
            return self._memories(cur, qs)

        keys_full = mem_keys + ["sentence_idx", "embedding"]
        thr = float(self.cfg.threshold or 0.0)

        best: dict[int, dict] = {}
        for row in rows:
            rd = dict(zip(keys_full, row))
            eid = int(rd.get("eternal_id") or 0)
            if eid <= 0:
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

            parts = self.rag._json_loads_list(rd.get("participants"))
            c = Candidate(
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
            )
            out.append(c)

        return out
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
        ids = list(sim_map.keys())
        placeholders = ",".join("?" * len(ids))

        opt_cols = []
        opt_keys = []
        for opt in ("message_id", "speaker", "target", "participants", "entities"):
            if opt in self.rag._history_cols:
                opt_cols.append(f"h.{opt}")
                opt_keys.append(opt)

        base_cols = ["h.id", "h.role", "h.content", "h.timestamp"]
        base_keys = ["id", "role", "content", "timestamp"]
        all_cols = base_cols + opt_cols
        all_keys = base_keys + opt_keys

        where = f"h.character_id=? AND h.is_active=0 AND h.id IN ({placeholders})"
        params: list = [self.rag.character_id] + ids
        if "is_deleted" in self.rag._history_cols:
            where += " AND h.is_deleted=0"

        try:
            cur.execute(f"SELECT {', '.join(all_cols)} FROM history h WHERE {where}", tuple(params))
            rows = cur.fetchall() or []
        except Exception:
            return out

        for row in rows:
            rd = dict(zip(all_keys, row))
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

            parts = self.rag._json_loads_list(rd.get("participants"))
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
