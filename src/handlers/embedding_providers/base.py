from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class EmbeddingRequest:
    texts: List[str]
    is_query: bool = False
    model: str = ""
    api_key: Optional[str] = None
    api_url: Optional[str] = None          # full endpoint URL or local HF id / path
    reserve_keys: List[str] = field(default_factory=list)
    reserve_keys_distribute: bool = False
    headers: Dict[str, str] = field(default_factory=dict)
    query_prefix: str = ""
    dimensions: int = 0                    # hint only; real dim taken from response
    extra: Dict[str, Any] = field(default_factory=dict)


class BaseEmbeddingProvider(ABC):
    name: str = ""
    supports_batch: bool = True

    @abstractmethod
    def is_applicable(self, req: EmbeddingRequest) -> bool:
        ...

    @abstractmethod
    def embed(self, req: EmbeddingRequest) -> List[Optional[np.ndarray]]:
        """Return L2-normalised float32 vectors, one per input text (None on error)."""
        ...
