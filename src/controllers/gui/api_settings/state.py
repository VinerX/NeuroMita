from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class PresetSnapshot:
    url: str
    model: str
    key: str
    base: Optional[int]
    reserve_keys_text: str
    reserve_keys_distribute: bool
    protocol_id: str
    generation_overrides: Dict[str, Any] = field(default_factory=dict)
    openrouter_routing: Dict[str, Any] = field(default_factory=dict)
    fallbacks: tuple = ()  # tuple of (preset_id, model) for hashable comparison
