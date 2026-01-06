from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol

from core.events import EventBus


@dataclass
class RequestContext:
    server: Any
    client_id: str
    writer: Any
    event_bus: EventBus


class IActionHandler(Protocol):
    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None: ...


class ActionRegistry:
    def __init__(self):
        self._handlers: dict[str, IActionHandler] = {}

    def register(self, action: str, handler: IActionHandler) -> None:
        self._handlers[str(action)] = handler

    def get(self, action: str) -> IActionHandler | None:
        return self._handlers.get(str(action))