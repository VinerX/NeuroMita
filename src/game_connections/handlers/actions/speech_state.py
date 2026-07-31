from __future__ import annotations

from typing import Any, Dict

from core.events import Events
from game_connections.handlers.registry import RequestContext
from main_logger import logger


class SpeechStateAction:
    """Мод сообщает, что реплика Миты реально зазвучала (или отзвучала).

    До этого окно «Мита говорит» при подключённой игре считалось по длительности
    синтезированного wav и только тогда, когда синтез делал Python. Игра могла
    начать воспроизведение позже, оборвать его или озвучить своими средствами —
    и микрофон ловил голос Миты из колонок.
    """

    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        active = bool(request.get("active", False))
        character = str(request.get("character") or "")

        logger.debug(f"speech_state от {ctx.client_id}: active={active} character={character!r}")
        ctx.event_bus.emit(Events.Audio.MITA_SPEAKING_WINDOW, {
            "active": active,
            "character": character,
        })
