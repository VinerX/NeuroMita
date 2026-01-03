from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PresetSnapshot:
    url: str
    model: str
    key: str
    base: Optional[int]
    reserve_keys_text: str
    protocol_id: str