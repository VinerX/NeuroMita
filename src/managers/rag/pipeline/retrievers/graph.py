"""
GraphRetriever — retrieves entity-relation triples from the graph store.

Matches query keywords against ``graph_entities.name`` (exact + prefix),
fetches 1-hop neighborhood, returns Candidates with formatted triples.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..types import Candidate, QueryState
from ..config import RAGConfig

logger = logging.getLogger(__name__)


class GraphRetriever:
    name = "graph"

    def __init__(self, *, graph_store: Any, cfg: RAGConfig):
        self.gs = graph_store
        self.cfg = cfg

    def retrieve(self, qs: QueryState) -> List[Candidate]:
        if self.gs is None:
            return []

        # Match keywords against entity names.
        matched_names = self._match_entities(qs.keywords)
        # Store matched entities in QueryState for EntityEnricher to use.
        if matched_names:
            qs.matched_entities = qs.matched_entities | set(matched_names)
        if not matched_names:
            return []

        # Fetch 1-hop relations for matched entities.
        triples = self.gs.query_by_entities(matched_names)
        if not triples:
            return []

        out: list[Candidate] = []
        seen: set[str] = set()

        for t in triples:
            subj = t.get("subject", "")
            pred = t.get("predicate", "")
            obj_ = t.get("object", "")
            conf = float(t.get("confidence", 1.0) or 1.0)

            triple_key = f"{subj}|{pred}|{obj_}"
            if triple_key in seen:
                continue
            seen.add(triple_key)

            # Format as readable text for the LLM.
            content = f"{subj} --{pred}--> {obj_}"

            # Score heuristic: confidence × keyword overlap.
            kw_overlap = self._keyword_overlap(qs.keywords, subj, obj_)

            c = Candidate(
                source="graph",
                id=hash(triple_key) & 0x7FFFFFFF,
                content=content,
                meta={
                    "subject": subj,
                    "predicate": pred,
                    "object": obj_,
                    "subject_type": t.get("subject_type", ""),
                    "object_type": t.get("object_type", ""),
                    "created_at": t.get("created_at", ""),
                },
                features={
                    "confidence": conf,
                    "kw_overlap": kw_overlap,
                },
                score=conf * (0.5 + 0.5 * kw_overlap),
            )
            out.append(c)

        logger.debug(f"GraphRetriever: {len(matched_names)} matched entities → {len(out)} triples")
        return out

    def _match_entities(self, keywords: List[str]) -> List[str]:
        """Match keywords against entity names (exact + prefix)."""
        if not keywords:
            return []

        all_entities = self.gs.get_all_entities(limit=1000)
        entity_names = [e["name"] for e in all_entities]

        matched: set[str] = set()
        kw_lower = [k.lower() for k in keywords if k.strip()]

        for ename in entity_names:
            for kw in kw_lower:
                if ename == kw or ename.startswith(kw) or kw.startswith(ename):
                    matched.add(ename)
                    break

        return list(matched)

    @staticmethod
    def _keyword_overlap(keywords: List[str], subj: str, obj_: str) -> float:
        """Fraction of keywords that appear in subject or object names."""
        if not keywords:
            return 0.0
        kw_set = {k.lower() for k in keywords if k.strip()}
        tokens = set(subj.split()) | set(obj_.split())
        hits = sum(1 for k in kw_set if k in tokens or any(k in t for t in tokens))
        return min(hits / max(len(kw_set), 1), 1.0)
