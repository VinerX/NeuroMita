# src/controllers/protocols_controller.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
import re

from core.events import get_event_bus, Events, Event
from main_logger import logger
from managers.protocol_registry import get_protocol_registry


def _mask_key_in_url(url: str) -> str:
    u = str(url or "")
    if "key=" not in u:
        return u
    return re.sub(r"key=[^&]*", "key=***", u)


def _apply_auth(url: str, headers: Dict[str, str], api_key: str, auth: Dict[str, Any]) -> tuple[str, Dict[str, str]]:
    url = str(url or "")
    headers = dict(headers or {})
    key = str(api_key or "").strip()

    mode = str((auth or {}).get("mode") or "bearer").strip().lower()
    param = str((auth or {}).get("param") or "key").strip()

    # If url contains "{key}" placeholder - replace regardless of mode
    if "{key}" in url:
        url = url.replace("{key}", key)

    if mode == "none" or not key:
        headers.pop("Authorization", None)
        return url, headers

    if mode == "bearer":
        headers["Authorization"] = f"Bearer {key}"
        return url, headers

    if mode == "query":
        headers.pop("Authorization", None)
        # replace existing key=... or append
        if f"{param}=" in url or "key=" in url:
            # replace key=... even if param differs
            url = re.sub(r"(?:key|%s)=[^&]*" % re.escape(param), f"{param}={key}", url)
            return url, headers
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{param}={key}"
        return url, headers

    # fallback: be conservative
    headers.pop("Authorization", None)
    return url, headers


class ProtocolsController:
    def __init__(self):
        self.event_bus = get_event_bus()
        self._subscribe()

    def _subscribe(self) -> None:
        self.event_bus.subscribe(Events.Protocols.GET_PROTOCOL_LIST, self._on_get_protocol_list, weak=False)
        self.event_bus.subscribe(Events.Protocols.GET_PROTOCOL_FULL, self._on_get_protocol_full, weak=False)
        self.event_bus.subscribe(Events.Protocols.GET_TRANSFORM_LIST, self._on_get_transform_list, weak=False)
        self.event_bus.subscribe(Events.Protocols.BUILD_HTTP_REQUEST, self._on_build_http_request, weak=False)

    def _on_get_protocol_list(self, _event: Event) -> List[Dict[str, Any]]:
        reg = get_protocol_registry()
        items: List[Dict[str, Any]] = []
        raw = getattr(reg, "_items", {}) or {}
        for pid, proto in raw.items():
            items.append({
                "id": str(getattr(proto, "id", pid)),
                "name": str(getattr(proto, "name", pid)),
                "dialect": str(getattr(proto, "dialect", "")),
                "provider": str(getattr(proto, "provider", "")),
                "auth": dict(getattr(proto, "auth", {}) or {}),
                "headers": dict(getattr(proto, "headers", {}) or {}),
                "capabilities": dict(getattr(proto, "capabilities", {}) or {}),
                "transforms": list(getattr(proto, "transforms", []) or []),
            })
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
            "auth": dict(proto.auth or {}),
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

    def _on_build_http_request(self, event: Event) -> Dict[str, Any]:
        """
        Input:
          {
            "protocol_id": str,
            "url": str,
            "api_key": str,
            "headers": dict (optional, merged over protocol headers),
          }

        Output:
          {"url": str, "headers": dict, "safe_url": str}
        """
        data = event.data if isinstance(event.data, dict) else {}
        protocol_id = str(data.get("protocol_id") or "").strip()
        url = str(data.get("url") or "")
        api_key = str(data.get("api_key") or "")
        extra_headers = data.get("headers") or {}
        if not isinstance(extra_headers, dict):
            extra_headers = {}

        reg = get_protocol_registry()
        proto = reg.get(protocol_id) if protocol_id else None
        if not proto:
            proto = reg.pick_default()

        proto_headers = dict(getattr(proto, "headers", {}) or {})
        headers = {**proto_headers, **{str(k): str(v) for k, v in extra_headers.items() if k and v is not None}}

        auth = dict(getattr(proto, "auth", {}) or {})
        url2, headers2 = _apply_auth(url, headers, api_key, auth)

        # Never log raw key
        safe_url = _mask_key_in_url(url2)

        return {"url": url2, "headers": headers2, "safe_url": safe_url}


_controller_singleton: Optional[ProtocolsController] = None


def ensure_protocols_controller() -> ProtocolsController:
    global _controller_singleton
    if _controller_singleton is None:
        _controller_singleton = ProtocolsController()
        logger.notify("ProtocolsController успешно инициализирован.")
    return _controller_singleton


ensure_protocols_controller()