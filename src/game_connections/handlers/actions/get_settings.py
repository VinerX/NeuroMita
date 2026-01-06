from __future__ import annotations

from typing import Any, Dict

from core.events import Events
from game_connections.handlers.registry import RequestContext


class GetSettingsAction:
    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        try:
            ctx.event_bus.emit(Events.Server.LOAD_SERVER_SETTINGS)
        except Exception:
            pass