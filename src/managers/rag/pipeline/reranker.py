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
        for c in cands:
            f = c.features or {}
            sim = float(f.get("sim", 0.0) or 0.0)
            tf = float(f.get("time", 0.0) or 0.0)
            pb = float(f.get("prio", 0.0) or 0.0)
            eb = float(f.get("entity", 0.0) or 0.0)
            kw = float(f.get("kw", 0.0) or 0.0)
            lex = float(f.get("lex", 0.0) or 0.0)

            noise = self._rng.uniform(0.0, max(0.0, float(self.cfg.noise_max or 0.0)))

            score = (
                sim * self.cfg.K1
                + tf * self.cfg.K2
                + pb * self.cfg.K3
                + eb * self.cfg.K4
                + kw * self.cfg.K5
                + lex * self.cfg.K6
                + noise
            )
            c.score = float(score)
            c.debug = c.debug or {}
            c.debug.update({
                "sim": sim, "time": tf, "prio": pb, "entity": eb, "kw": kw, "lex": lex,
                "noise": noise, "final": float(score),
            })
