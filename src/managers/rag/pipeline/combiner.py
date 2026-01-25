from __future__ import annotations

from typing import Dict, List, Tuple
from .types import Candidate
from .config import RAGConfig


def _sim(c: Candidate) -> float:
    try:
        return float((c.features or {}).get("sim", 0.0) or 0.0)
    except Exception:
        return 0.0


class UnionCombiner:
    """
    Default behavior: union + dedup by (source,id), merging features by max.
    """
    name = "union"

    def __init__(self, *, cfg: RAGConfig):
        self.cfg = cfg

    def combine(self, buckets: Dict[str, List[Candidate]]) -> List[Candidate]:
        merged: dict[tuple[str, int], Candidate] = {}

        for _name, cands in (buckets or {}).items():
            for c in (cands or []):
                k = c.key
                if k[1] <= 0:
                    continue
                if k not in merged:
                    merged[k] = c
                else:
                    merged[k].merge_from(c)

        return list(merged.values())


class VectorOnlyCombiner:
    """
    Return only vector candidates.
    Optional cap: RAG_VECTOR_TOP_K by sim (descending).
    """
    name = "vector_only"

    def __init__(self, *, cfg: RAGConfig):
        self.cfg = cfg

    def combine(self, buckets: Dict[str, List[Candidate]]) -> List[Candidate]:
        vec = list((buckets or {}).get("vector") or [])
        if not vec:
            return []

        # dedup inside vector bucket
        merged: dict[tuple[str, int], Candidate] = {}
        for c in vec:
            k = c.key
            if k[1] <= 0:
                continue
            if k not in merged:
                merged[k] = c
            else:
                merged[k].merge_from(c)

        out = list(merged.values())
        out.sort(key=_sim, reverse=True)

        top_k = int(self.cfg.vector_top_k or 0)
        if top_k > 0:
            out = out[:top_k]
        return out


class IntersectCombiner:
    """
    Keep only candidates that appear in >= min_methods buckets.
    Optionally require that candidate exists in vector bucket (require_vector=True).
    If intersection becomes empty and fallback_union=True -> return union result.
    """
    name = "intersect"

    def __init__(
        self,
        *,
        cfg: RAGConfig,
        min_methods: int = 2,
        require_vector: bool = True,
        fallback_union: bool = True,
    ):
        self.cfg = cfg
        self.min_methods = max(1, int(min_methods))
        self.require_vector = bool(require_vector)
        self.fallback_union = bool(fallback_union)

    def combine(self, buckets: Dict[str, List[Candidate]]) -> List[Candidate]:
        # count presence per method
        merged: dict[tuple[str, int], Candidate] = {}
        counts: dict[tuple[str, int], int] = {}
        in_vector: set[tuple[str, int]] = set()

        for bname, cands in (buckets or {}).items():
            seen_in_bucket = set()
            for c in (cands or []):
                k = c.key
                if k[1] <= 0:
                    continue
                if k in seen_in_bucket:
                    continue
                seen_in_bucket.add(k)

                if bname == "vector":
                    in_vector.add(k)

                counts[k] = counts.get(k, 0) + 1

                if k not in merged:
                    merged[k] = c
                else:
                    merged[k].merge_from(c)

        out: list[Candidate] = []
        for k, c in merged.items():
            if counts.get(k, 0) < self.min_methods:
                continue
            if self.require_vector and (k not in in_vector):
                continue
            out.append(c)

        if out:
            return out

        if self.fallback_union:
            return UnionCombiner(cfg=self.cfg).combine(buckets)

        return []


class TwoStageCombiner:
    """
    Stage1: take vector candidates (optionally cap by vector_top_k).
    Stage2: merge ONLY features from other buckets into those vector candidates.
            (does not add new ids)
    If vector stage is empty and fallback_union=True -> return union result.
    """
    name = "two_stage"

    def __init__(self, *, cfg: RAGConfig, fallback_union: bool = True):
        self.cfg = cfg
        self.fallback_union = bool(fallback_union)

    def combine(self, buckets: Dict[str, List[Candidate]]) -> List[Candidate]:
        vec = list((buckets or {}).get("vector") or [])
        if not vec:
            if self.fallback_union:
                return UnionCombiner(cfg=self.cfg).combine(buckets)
            return []

        # dedup vector
        vmap: dict[Tuple[str, int], Candidate] = {}
        for c in vec:
            k = c.key
            if k[1] <= 0:
                continue
            if k not in vmap:
                vmap[k] = c
            else:
                vmap[k].merge_from(c)

        # cap by sim if configured
        out = list(vmap.values())
        out.sort(key=_sim, reverse=True)
        top_k = int(self.cfg.vector_top_k or 0)
        if top_k > 0:
            out = out[:top_k]
            vmap = {c.key: c for c in out}

        # stage2: merge features from non-vector buckets only if key exists in vector set
        for bname, cands in (buckets or {}).items():
            if bname == "vector":
                continue
            for c in (cands or []):
                k = c.key
                base = vmap.get(k)
                if base is None:
                    continue
                base.merge_from(c)

        return list(vmap.values())