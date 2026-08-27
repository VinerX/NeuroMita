from __future__ import annotations

from typing import Any, Dict

from core.events import Events
from game_connections.handlers.registry import RequestContext
from main_logger import logger


def _as_bool(value: Any) -> bool:
    """Строковое «false» из JSON мода — это False, а не непустая строка.

    Поле приходит из C#-сериализации, где bool легко превращается в "false"/"False"/"0";
    `bool("false")` дал бы True и заглушил микрофон до конца аренды.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


class SpeechStateAction:
    """Мод сообщает, что реплика Миты реально зазвучала (или отзвучала).

    До этого окно «Мита говорит» при подключённой игре считалось по длительности
    синтезированного wav и только тогда, когда синтез делал Python. Игра могла
    начать воспроизведение позже, оборвать его или озвучить своими средствами —
    и микрофон ловил голос Миты из колонок.
    """

    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        active = _as_bool(request.get("active", False))
        character = str(request.get("character") or "")
        # Один клиент может вести несколько реплик сразу (две Миты, добивка
        # предыдущей фразы). Мод присылает id реплики — тогда «конец» закрывает
        # именно её; старый мод его не шлёт, и различаем по персонажу.
        speech_id = str(request.get("speech_id") or request.get("id") or "")
        try:
            duration_sec = float(request.get("duration_sec", 0.0) or 0.0)
        except (TypeError, ValueError):
            duration_sec = 0.0

        logger.debug(
            f"speech_state от {ctx.client_id}: active={active} character={character!r} "
            f"speech_id={speech_id!r} duration={duration_sec}"
        )
        ctx.event_bus.emit(Events.Audio.MITA_SPEAKING_WINDOW, {
            "active": active,
            "character": character,
            "speech_id": speech_id,
            "duration_sec": duration_sec,
            "source": str(ctx.client_id or ""),
        })
