# src/managers/protocol_registry.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from main_logger import logger


@dataclass(frozen=True)
class ApiProtocol:
    id: str
    name: str
    dialect: str
    provider: str
    auth: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    transforms: List[Dict[str, Any]] = field(default_factory=list)


class ProtocolRegistry:
    def __init__(self, protocols: List[Dict[str, Any]]):
        items: Dict[str, ApiProtocol] = {}
        for raw in protocols or []:
            try:
                p = ApiProtocol(
                    id=str(raw["id"]),
                    name=str(raw.get("name", raw["id"])),
                    dialect=str(raw.get("dialect", "")),
                    provider=str(raw.get("provider", "")),
                    auth=dict(raw.get("auth", {}) or {}),
                    headers=dict(raw.get("headers", {}) or {}),
                    capabilities=dict(raw.get("capabilities", {}) or {}),
                    transforms=list(raw.get("transforms", []) or []),
                )
                items[p.id] = p
            except Exception as e:
                logger.error(f"Bad protocol definition: {raw} ({e})", exc_info=True)
        self._items = items

    def get(self, protocol_id: str) -> Optional[ApiProtocol]:
        if not protocol_id:
            return None
        return self._items.get(str(protocol_id))

    def pick_default(self) -> Optional[ApiProtocol]:
        return self.get("openai_compatible_default") or next(iter(self._items.values()), None)


_global_registry: Optional[ProtocolRegistry] = None


def get_protocol_registry() -> ProtocolRegistry:
    global _global_registry
    if _global_registry is None:
        from presets.api_protocols import API_PROTOCOLS_DATA
        _global_registry = ProtocolRegistry(API_PROTOCOLS_DATA)
    return _global_registry