from __future__ import annotations

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

    def enrich(self, qs: QueryState, cands: list[Candidate]) -> None:
        ctx_speaker = qs.ctx_speaker
        ctx_target = qs.ctx_target
        ctx_actors = qs.ctx_actors

        for c in cands:
            if c.source == "memory":
                parts = c.meta.get("participants") or []
                eb = self._overlap_bonus(ctx_actors, parts)
                c.features["entity"] = max(float(c.features.get("entity", 0.0) or 0.0), float(eb))
                continue

            # history
            sp = str(c.meta.get("speaker") or "").strip()
            tg = str(c.meta.get("target") or "").strip()
            parts = c.meta.get("participants") or []

            b = 0.0
            if sp and ctx_speaker and sp == ctx_speaker:
                b += 0.1
            if tg and ctx_target and tg == ctx_target:
                b += 0.1
            b += self._overlap_bonus(ctx_actors, parts)

            b = min(0.2, b)
            c.features["entity"] = max(float(c.features.get("entity", 0.0) or 0.0), float(b))