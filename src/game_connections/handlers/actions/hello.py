from __future__ import annotations

from typing import Any, Dict

from game_connections.handlers.registry import RequestContext


class HelloAction:
    """Рукопожатие: клиент представляется до того, как участвовать в диалоге.

    Роль решает, кому достаётся голос игрока, а «самое свежее подключение» для
    этого не годится: тестовый клиент или внешняя утилита подключаются последними
    и уводили ход у игры. Роль фиксируется один раз и живёт до разрыва связи.
    """

    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        server = ctx.server
        role = server.declare_client_role(ctx.client_id, request.get("client_role"))
        await server.send_json(ctx.writer, {
            "type": "hello_ack",
            "protocol_version": server.PROTOCOL_VERSION,
            "session_id": str(ctx.client_id or ""),
            "client_role": role,
            "owns_player_input": server.owns_player_input(ctx.client_id),
        })
