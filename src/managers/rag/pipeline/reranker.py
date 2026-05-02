from __future__ import annotations

import random
from .types import Candidate
from .config import RAGConfig


class LinearReranker:
    name = "linear"

    def __init__(self, *, cfg: RAGConfig):
        self.cfg = cfg
        self._rng = random.Random(cfg.noise_seed) if cfg.noise_seed is not None else random

    def score_all(self, cands: list[Candidate]) -> None:
        use_rrf = bool(self.cfg.use_rrf)
        for c in cands:
            f = c.features or {}
            tf = float(f.get("time", 0.0) or 0.0)
            pb = float(f.get("prio", 0.0) or 0.0)
            eb = float(f.get("entity", 0.0) or 0.0)
            noise = self._rng.uniform(0.0, max(0.0, float(self.cfg.noise_max or 0.0)))

            if use_rrf:
                # RRF mode: rank-based fusion score + time/prio/entity bonuses.
                # sim/kw/lex weights (K1,K5,K6) are intentionally not used here —
                # their information is already captured in the RRF rank.
                rrf = float(f.get("rrf", 0.0) or 0.0)
                score = rrf + tf * self.cfg.K2 + pb * self.cfg.K3 + eb * self.cfg.K4 + noise
                graph_boost = 1.0
                if c.source == "graph":
                    graph_boost = float(self.cfg.K7)
                    score *= graph_boost
                c.score = float(score)
                c.debug = c.debug or {}
                c.debug.update({
                    "rrf": rrf, "time": tf, "prio": pb, "entity": eb,
                    "noise": noise, "graph_boost": graph_boost, "final": float(score),
                })
            else:
                sim = float(f.get("sim", 0.0) or 0.0)
                kw = float(f.get("kw", 0.0) or 0.0)
                lex = float(f.get("lex", 0.0) or 0.0)
                score = (
                    sim * self.cfg.K1
                    + tf * self.cfg.K2
                    + pb * self.cfg.K3
                    + eb * self.cfg.K4
                    + kw * self.cfg.K5
                    + lex * self.cfg.K6
                    + noise
                )
                # Graph candidates get a global multiplier (K7) so they can
                # realistically compete with vector/memory results despite having
                # sim=0.  K7=1.0 means no boost; K7=1.5 is the default.
                graph_boost = 1.0
                if c.source == "graph":
                    graph_boost = float(self.cfg.K7)
                    score *= graph_boost
                c.score = float(score)
                c.debug = c.debug or {}
                c.debug.update({
                    "sim": sim, "time": tf, "prio": pb, "entity": eb, "kw": kw, "lex": lex,
                    "noise": noise, "graph_boost": graph_boost, "final": float(score),
                })
