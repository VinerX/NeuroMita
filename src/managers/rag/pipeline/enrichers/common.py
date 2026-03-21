from __future__ import annotations

import json
from typing import Any
from managers.rag.rag_utils import rag_clean_text
from ..types import Candidate, QueryState
from ..config import RAGConfig


class TimeEnricher:
    name = "time"

    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg

    def enrich(self, qs: QueryState, cands: list[Candidate]) -> None:
        now = qs.now_ts
        dr = float(self.cfg.decay_rate or 0.0)

        for c in cands:
            dt_raw = None
            if c.source == "memory":
                dt_raw = c.meta.get("date_created")
            elif c.source == "graph":
                dt_raw = c.meta.get("created_at")
            else:
                dt_raw = c.meta.get("date")

            dt = self.rag._parse_dt(dt_raw)
            if not dt:
                tf = 0.0
            else:
                days = max(0.0, (now - dt).total_seconds() / 86400.0)
                tf = 1.0 / (1.0 + (dr * days)) if dr > 0.0 else 1.0

            c.features["time"] = max(float(c.features.get("time", 0.0) or 0.0), float(tf))


class PriorityEnricher:
    name = "priority"

    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg

    @staticmethod
    def _prio_bonus(p: Any) -> float:
        pl = str(p or "Normal").strip().lower()
        if pl in ("critical", "high"):
            return 0.25
        if pl == "low":
            return 0.0
        return 0.1

    def enrich(self, qs: QueryState, cands: list[Candidate]) -> None:
        for c in cands:
            if c.source != "memory":
                continue
            pb = self._prio_bonus(c.meta.get("priority"))
            c.features["prio"] = max(float(c.features.get("prio", 0.0) or 0.0), float(pb))


class EntityEnricher:
    name = "entity"

    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg

    @staticmethod
    def _overlap_bonus(ctx_actors: set[str], parts: list[str]) -> float:
        if not ctx_actors or not parts:
            return 0.0
        try:
            return 0.1 if (ctx_actors.intersection(set(parts))) else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _load_entity_tags(raw: Any) -> set[str]:
        """Parse the JSON entity-tag list from meta, return lowercased set."""
        if not raw:
            return set()
        if isinstance(raw, (list, set)):
            return {str(e).lower().strip() for e in raw if e}
        try:
            parsed = json.loads(str(raw))
            if isinstance(parsed, list):
                return {str(e).lower().strip() for e in parsed if e}
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return set()

    def _entity_tag_boost(self, qs: QueryState, tagged: set[str]) -> float:
        """
        Compute entity-tag bonus: how well this candidate's entity tags
        overlap with query keywords and/or graph-matched entities.

        Returns bonus in [0.0, 0.2] — compatible with existing entity scale.
        """
        if not tagged:
            return 0.0

        # Direct keyword match: candidate tagged with "warcraft", user asked about "warcraft"
        kw_lower = {k.lower() for k in qs.keywords if k.strip()} if qs.keywords else set()

        # Graph-expanded match: GraphRetriever found entity "warcraft" → also boosts
        # candidates tagged with "warcraft" even if the query keyword was something else
        graph_ents = {e.lower() for e in qs.matched_entities} if qs.matched_entities else set()

        # Union of both match pools
        match_pool = kw_lower | graph_ents
        if not match_pool:
            return 0.0

        overlap = tagged & match_pool
        if not overlap:
            return 0.0

        # 0.05 per matched entity, capped at 0.2
        return min(0.2, 0.05 * len(overlap))

    def enrich(self, qs: QueryState, cands: list[Candidate]) -> None:
        ctx_speaker = qs.ctx_speaker
        ctx_target = qs.ctx_target
        ctx_actors = qs.ctx_actors

        for c in cands:
            eb = 0.0

            if c.source == "memory":
                parts = c.meta.get("participants") or []
                eb = self._overlap_bonus(ctx_actors, parts)

            elif c.source == "graph":
                # Treat subject/object of the triple as "participants".
                subj = str(c.meta.get("subject") or "").strip()
                obj_ = str(c.meta.get("object") or "").strip()
                graph_parts = [p for p in [subj, obj_] if p]
                eb = self._overlap_bonus(ctx_actors, graph_parts)

            else:
                # history
                sp = str(c.meta.get("speaker") or "").strip()
                tg = str(c.meta.get("target") or "").strip()
                parts = c.meta.get("participants") or []

                if sp and ctx_speaker and sp == ctx_speaker:
                    eb += 0.1
                if tg and ctx_target and tg == ctx_target:
                    eb += 0.1
                eb += self._overlap_bonus(ctx_actors, parts)
                eb = min(0.2, eb)

            # --- Entity-tag boost (NEW): applies to ALL source types ---
            tagged = self._load_entity_tags(c.meta.get("entities"))
            tag_boost = self._entity_tag_boost(qs, tagged)
            eb = max(eb, tag_boost)

            c.features["entity"] = max(float(c.features.get("entity", 0.0) or 0.0), float(eb))