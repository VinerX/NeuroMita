from core.events import Events
from game_connections.handlers.registry import RequestContext


class AsrPttStateAction:
    async def handle(self, request: dict, ctx: RequestContext) -> None:
        active = request.get("active")
        generation = request.get("generation")
        session_id = request.get("session_id")
        cancelled = request.get("cancelled", False)
        if (type(active) is not bool or type(generation) is not int
                or not 0 <= generation <= 2**63 - 1
                or type(cancelled) is not bool
                or not isinstance(session_id, str) or session_id != ctx.client_id
                or not ctx.server.owns_player_input(ctx.client_id)):
            await ctx.server.send_error(ctx.writer, "Invalid asr_ptt_state or session does not own player input")
            return
        payload = {
            "active": active, "session_id": session_id, "generation": generation,
        }
        if "cancelled" in request:
            payload["cancelled"] = cancelled
        ctx.event_bus.emit(Events.Speech.ASR_PTT_STATE, payload)
