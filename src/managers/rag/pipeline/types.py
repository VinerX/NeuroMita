from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import numpy as np


@dataclass
class QueryState:
    character_id: str
    user_query: str
    expanded_query_text: str
    query_vec: Optional[np.ndarray]
    keywords: list[str]
    now_ts: Any  # datetime.datetime, но не тащим import ради мягкости
    ctx_speaker: str = ""
    ctx_target: str = ""
    ctx_participants: list[str] = field(default_factory=list)

    @property
    def ctx_actors(self) -> set[str]:
        return set(x for x in [self.ctx_speaker, self.ctx_target, *self.ctx_participants] if x)


@dataclass
class Candidate:
    source: str          # "memory" | "history" | "graph"
    id: int
    content: Any = None  # keep raw
    meta: dict[str, Any] = field(default_factory=dict)
    features: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    debug: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int]:
        return (str(self.source), int(self.id or 0))

    def merge_from(self, other: "Candidate") -> None:
        """
        Merge another candidate with same key:
        - keep max of feature components
        - fill missing meta/content
        """
        for k, v in (other.features or {}).items():
            try:
                vv = float(v)
            except Exception:
                vv = 0.0
            self.features[k] = max(float(self.features.get(k, 0.0) or 0.0), vv)

        # keep richer meta (fill blanks)
        for k, v in (other.meta or {}).items():
            if self.meta.get(k) in (None, "", [], {}, 0) and v not in (None, "", [], {}):
                self.meta[k] = v

        if self.content in (None, "", [], {}) and other.content not in (None, "", [], {}):
            self.content = other.content

        # debug: keep max-ish numeric values where possible
        if other.debug:
            self.debug = self.debug or {}
            for k, v in other.debug.items():
                if k not in self.debug:
                    self.debug[k] = v
                    continue
                try:
                    self.debug[k] = max(float(self.debug[k]), float(v))
                except Exception:
                    # fallback: keep existing
                    pass

    def to_public_dict(self) -> dict[str, Any]:
        """
        Old API-compatible output:
        - memory: source,id,content,type,priority,date_created,score
        - history: source,id,role,content,date,speaker,target,participants,score
        """
        base = {
            "source": self.source,
            "id": int(self.id or 0),
            "content": self.content,
            "score": float(self.score or 0.0),
            "features": {k: round(float(v), 4) for k, v in (self.features or {}).items()},
        }
        if self.source == "memory":
            base.update({
                "type": self.meta.get("type"),
                "priority": self.meta.get("priority"),
                "date_created": self.meta.get("date_created"),
            })
        elif self.source == "graph":
            base.update({
                "subject": self.meta.get("subject"),
                "predicate": self.meta.get("predicate"),
                "object": self.meta.get("object"),
            })
        else:
            base.update({
                "role": self.meta.get("role"),
                "date": self.meta.get("date"),
                "speaker": self.meta.get("speaker"),
                "target": self.meta.get("target"),
                "participants": self.meta.get("participants") or [],
            })
        return base