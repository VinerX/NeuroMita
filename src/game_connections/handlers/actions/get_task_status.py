from __future__ import annotations

from typing import Any, Dict

from core.services import use
from services.contracts import CharacterRegistry, SettingsService, TaskService, TelegramService
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

            is_gm = (use(CharacterRegistry).current_id() == "GameMaster")

            response["GM_ON"] = is_gm
            response["GM_READ"] = is_gm

            response["GM_VOICE"] = bool(is_gm and use(SettingsService).get("GM_VOICE", False))

        await ctx.server.send_json(ctx.writer, response)