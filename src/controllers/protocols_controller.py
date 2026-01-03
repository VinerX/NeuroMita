# src/controllers/protocols_controller.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.events import get_event_bus, Events, Event
from main_logger import logger
from managers.protocol_registry import get_protocol_registry


class ProtocolsController:
    def __init__(self):
        self.event_bus = get_event_bus()
        self._subscribe()

    def _subscribe(self) -> None:
        self.event_bus.subscribe(Events.Protocols.GET_PROTOCOL_LIST, self._on_get_protocol_list, weak=False)
        self.event_bus.subscribe(Events.Protocols.GET_PROTOCOL_FULL, self._on_get_protocol_full, weak=False)
        self.event_bus.subscribe(Events.Protocols.GET_TRANSFORM_LIST, self._on_get_transform_list, weak=False)

    def _on_get_protocol_list(self, _event: Event) -> List[Dict[str, Any]]:
        reg = get_protocol_registry()
        items: List[Dict[str, Any]] = []

        try:
            raw = getattr(reg, "_items", {}) or {}
            for pid, proto in raw.items():
                items.append({
                    "id": str(getattr(proto, "id", pid)),
                    "name": str(getattr(proto, "name", pid)),
                    "dialect": str(getattr(proto, "dialect", "")),
                    "provider": str(getattr(proto, "provider", "")),
                    "headers": dict(getattr(proto, "headers", {}) or {}),
                    "capabilities": dict(getattr(proto, "capabilities", {}) or {}),
                    "transforms": list(getattr(proto, "transforms", []) or []),
                })
        except Exception as e:
            logger.error(f"GET_PROTOCOL_LIST failed: {e}", exc_info=True)

        items.sort(key=lambda x: (0 if x["id"] == "openai_compatible_default" else 1, x.get("name", "").lower()))
        return items

    def _on_get_protocol_full(self, event: Event) -> Optional[Dict[str, Any]]:
        pid = ""
        if isinstance(event.data, dict):
            pid = str(event.data.get("id") or "")
        pid = pid.strip()
        if not pid:
            return None

        reg = get_protocol_registry()
        proto = reg.get(pid)
        if not proto:
            return None

        return {
            "id": str(proto.id),
            "name": str(proto.name),
            "dialect": str(proto.dialect),
            "provider": str(proto.provider),
            "headers": dict(proto.headers or {}),
            "capabilities": dict(proto.capabilities or {}),
            "transforms": list(proto.transforms or []),
        }

    def _on_get_transform_list(self, _event: Event) -> List[Dict[str, Any]]:
        try:
            from handlers.llm_providers.message_transforms import get_transform_catalog
            return list(get_transform_catalog() or [])
        except Exception as e:
            logger.error(f"GET_TRANSFORM_LIST failed: {e}", exc_info=True)
            return []


# auto-register on import (so UI doesn't depend on MainController init order)
_controller_singleton: Optional[ProtocolsController] = None


def ensure_protocols_controller() -> ProtocolsController:
    global _controller_singleton
    if _controller_singleton is None:
        _controller_singleton = ProtocolsController()
    return _controller_singleton


ensure_protocols_controller()