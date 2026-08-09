from __future__ import annotations

from typing import Any, Dict

from core.services import use
from services.contracts import SettingsService, TaskService, TelegramService
from managers.task_manager import TaskStatus
from game_connections.handlers.registry import RequestContext


class GetTaskStatusAction:
    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        task_uid = request.get("task_uid")
        if not task_uid:
            await ctx.server.send_error(ctx.writer, "Missing task_uid")
            return

        task = use(TaskService).get_task(task_uid)
        if not task:
            await ctx.server.send_error(ctx.writer, f"Task {task_uid} not found")
            return

        response = task.to_dict()

        if task.status == TaskStatus.SUCCESS and task.result:
            audio_path = task.result.get("voiceover_path", "") if isinstance(task.result, dict) else ""
            if audio_path:
                response.setdefault("result", {})["audio_path"] = audio_path

            response["silero_connected"] = use(TelegramService).is_silero_connected()
            # GameMaster is an optional moderator, not the selected active Mita.
            # The previous implementation looked at CharacterRegistry.current_id(),
            # making GM_ON/GM_REPEAT UI settings ineffective for normal dialogues.
            settings = use(SettingsService)
            gm_enabled = bool(settings.get("GM_ON", False))
            try:
                gm_repeat = int(settings.get("GM_REPEAT", 2) or 2)
            except (TypeError, ValueError):
                gm_repeat = 2
            # The legacy Unity controller treats this as a number of NPC turns.
            # Keep a bounded positive interval even if settings were edited manually.
            gm_repeat = max(1, min(gm_repeat, 100))

            response["GM_ON"] = gm_enabled
            response["GM_READ"] = gm_enabled
            response["GM_VOICE"] = bool(gm_enabled and settings.get("GM_VOICE", False))
            response["GM_REPEAT"] = gm_repeat
        await ctx.server.send_json(ctx.writer, response)