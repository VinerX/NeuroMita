from __future__ import annotations

from typing import Any, Dict

from game_connections.handlers.registry import RequestContext


class GetSettingsAction:
    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        try:
            payload = ctx.server.build_loaded_settings_payload()
            await ctx.server.send_json(ctx.writer, payload)
        except Exception as exc:
            await ctx.server.send_error(ctx.writer, f"Failed to load settings: {exc}")
