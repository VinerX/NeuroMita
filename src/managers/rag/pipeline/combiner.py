from __future__ import annotations

from typing import Dict, List
from .types import Candidate


class UnionCombiner:
    """
    Default behavior: union + dedup by (source,id), merging features by max.
    """
    name = "union"

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