from __future__ import annotations

from typing import Any, Dict

from core.events import Events
from managers.task_manager import TaskStatus
from game_connections.handlers.registry import RequestContext


class GetTaskStatusAction:
    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        task_uid = request.get("task_uid")
        if not task_uid:
            await ctx.server.send_error(ctx.writer, "Missing task_uid")
            return

        task_result = ctx.event_bus.emit_and_wait(Events.Task.GET_TASK, {"uid": task_uid}, timeout=1.0)
        task = task_result[0] if task_result else None
        if not task:
            await ctx.server.send_error(ctx.writer, f"Task {task_uid} not found")
            return

        response = task.to_dict()

        if task.status == TaskStatus.SUCCESS and task.result:
            audio_path = task.result.get("voiceover_path", "") if isinstance(task.result, dict) else ""
            if audio_path:
                response.setdefault("result", {})["audio_path"] = audio_path

            silero_result = ctx.event_bus.emit_and_wait(Events.Telegram.GET_SILERO_STATUS, timeout=1.0)
            response["silero_connected"] = silero_result[0] if silero_result else False

            current_profile_res = ctx.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
            current_profile = current_profile_res[0] if current_profile_res else {}
            current_character_id = current_profile.get("character_id", "") if isinstance(current_profile, dict) else ""
            is_gm = (current_character_id == "GameMaster")

            response["GM_ON"] = is_gm
            response["GM_READ"] = is_gm

            gm_voice_res = ctx.event_bus.emit_and_wait(
                Events.Settings.GET_SETTING,
                {"key": "GM_VOICE", "default": False},
                timeout=1.0
            )
            gm_voice = bool(gm_voice_res[0]) if gm_voice_res else False
            response["GM_VOICE"] = bool(is_gm and gm_voice)

        await ctx.server.send_json(ctx.writer, response)