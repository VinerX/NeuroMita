from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from core.events import Events
from core.request_policy import resolve_policy
from managers.task_manager import TaskStatus
from game_connections.handlers.registry import RequestContext


class CreateTaskAction:
    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        server = ctx.server
        event_bus = ctx.event_bus

        event_type = request.get("type", "answer")
        character_id = request.get("character", "Mita")
        data = request.get("data", {}) or {}
        context = request.get("context", {}) or {}
        req_id = request.get("req_id", None)

        sender = str(request.get("sender") or data.get("sender") or "Player")
        origin_message_id = request.get("origin_message_id") or data.get("origin_message_id")

        participants = request.get("participants")
        if participants is None:
            participants = data.get("participants")

        if participants is None or participants == []:
            last_map = getattr(server, "last_participants", None)
            if isinstance(last_map, dict):
                participants = last_map.get(ctx.client_id, [])
            else:
                participants = []
        else:
            if isinstance(participants, str):
                participants = [p.strip() for p in participants.split(",") if p.strip()]
            elif not isinstance(participants, list):
                participants = []
            participants = [str(x) for x in participants if str(x).strip()]

            last_map = getattr(server, "last_participants", None)
            if isinstance(last_map, dict):
                last_map[ctx.client_id] = participants

        event_bus.emit(Events.Server.SET_GAME_DATA, {
            "distance": float(str(context.get("distance", "0")).replace(",", ".")),
            "roomPlayer": int(context.get("roomPlayer", 0)),
            "roomMita": int(context.get("roomMita", 0)),
            "nearObjects": context.get("hierarchy", ""),
            "actualInfo": context.get("currentInfo", "")
        })

        if server._should_block_event(event_type):
            await server._send_aborted_update(ctx.client_id, event_type, character_id, req_id=req_id)
            return

        if event_type == "answer":
            model_event_type = "chat"
            policy = resolve_policy(model_event_type=model_event_type)
            policy_dict = policy.to_dict()

            user_input = data.get("message", "")

            if user_input:
                event_bus.emit(Events.Server.ECHO_CHAT_MESSAGE_REQUESTED, {
                    "client_id": ctx.client_id,
                    "sender": sender,
                    "text": str(user_input),
                    "message_id": req_id,
                    "origin_message_id": origin_message_id,
                })

            collected_sys = ""
            if policy.use_pending_sysinfo:
                collected_sys = "\n".join(server.pending_sysinfo.pop(character_id, []))

            task_result = event_bus.emit_and_wait(Events.Task.CREATE_TASK, {
                "type": "chat",
                "data": {
                    "character": character_id,
                    "user_input": str(user_input or ""),
                    "system_input": collected_sys,
                    "system_info": context.get("currentInfo", ""),
                    "client_id": ctx.client_id,
                    "event_type": event_type,
                    "req_id": req_id,
                    "sender": sender,
                    "participants": participants,
                    "origin_message_id": origin_message_id,
                    "policy": policy_dict,
                }
            }, timeout=5.0)

            task = task_result[0] if task_result else None
            if task:
                server.client_tasks[ctx.client_id].add(task.uid)
                await server.send_task_update(ctx.client_id, task)

                event_bus.emit(Events.Chat.SEND_MESSAGE, {
                    "user_input": str(user_input or ""),
                    "system_input": collected_sys,
                    "image_data": context.get("image_base64_list", []),
                    "task_uid": task.uid,
                    "event_type": model_event_type,
                    "character_id": character_id,
                    "sender": sender,
                    "participants": participants,
                    "req_id": req_id,
                    "origin_message_id": origin_message_id,
                    "policy": policy_dict,
                })
            else:
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="Failed to create task", req_id=req_id)
            return

        if event_type == "idle_timeout":
            model_event_type = "idle_timeout"
            policy = resolve_policy(model_event_type=model_event_type)
            policy_dict = policy.to_dict()

            last_idle_uid = server.last_idle_tasks.get(character_id)
            if last_idle_uid:
                last_task_result = event_bus.emit_and_wait(Events.Task.GET_TASK, {"uid": last_idle_uid}, timeout=1.0)
                last_task = last_task_result[0] if last_task_result else None

                if last_task and last_task.status == TaskStatus.PENDING:
                    await server.send_task_update(ctx.client_id, last_task)
                    return

            collected_sys = ""
            if policy.use_pending_sysinfo:
                collected_sys = "\n".join(server.pending_sysinfo.pop(character_id, []))

            task_result = event_bus.emit_and_wait(Events.Task.CREATE_TASK, {
                "type": "idle",
                "data": {
                    "character": character_id,
                    "message": data.get("message", "Player idle for 90 seconds"),
                    "system_input": collected_sys,
                    "client_id": ctx.client_id,
                    "event_type": event_type,
                    "req_id": req_id,
                    "sender": sender,
                    "participants": participants,
                    "origin_message_id": origin_message_id,
                    "policy": policy_dict,
                }
            }, timeout=5.0)

            task = task_result[0] if task_result else None
            if task:
                server.client_tasks[ctx.client_id].add(task.uid)
                server.last_idle_tasks[character_id] = task.uid
                await server.send_task_update(ctx.client_id, task)

                idle_prompt = "The player has been silent for 90 seconds. React naturally to this silence."
                if collected_sys:
                    idle_prompt += f"\n\nAdditional context:\n{collected_sys}"

                event_bus.emit(Events.Chat.SEND_MESSAGE, {
                    "user_input": "",
                    "system_input": idle_prompt,
                    "image_data": [],
                    "task_uid": task.uid,
                    "event_type": model_event_type,
                    "character_id": character_id,
                    "sender": sender,
                    "participants": participants,
                    "req_id": req_id,
                    "origin_message_id": origin_message_id,
                    "policy": policy_dict,
                })
            else:
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="Failed to create idle task", req_id=req_id)
            return

        if event_type == "system_info":
            msg = data.get("message", "")
            if msg:
                server.pending_sysinfo.setdefault(character_id, []).append(msg)
            await server.send_json(ctx.writer, {"type": "info", "stored": len(server.pending_sysinfo.get(character_id, []))})
            return

        if event_type == "system_info_flush":
            model_event_type = "chat"
            policy = resolve_policy(model_event_type=model_event_type)
            policy_dict = policy.to_dict()

            collected_sys = "\n".join(server.pending_sysinfo.pop(character_id, []))
            if not collected_sys:
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="No pending system_info to flush", req_id=req_id)
                return

            task_result = event_bus.emit_and_wait(Events.Task.CREATE_TASK, {
                "type": "chat",
                "data": {
                    "character": character_id,
                    "user_input": "",
                    "system_input": collected_sys,
                    "system_info": context.get("currentInfo", ""),
                    "client_id": ctx.client_id,
                    "event_type": event_type,
                    "req_id": req_id,
                    "sender": sender,
                    "participants": participants,
                    "origin_message_id": origin_message_id,
                    "policy": policy_dict,
                }
            }, timeout=5.0)

            task = task_result[0] if task_result else None
            if task:
                server.client_tasks[ctx.client_id].add(task.uid)
                await server.send_task_update(ctx.client_id, task)

                event_bus.emit(Events.Chat.SEND_MESSAGE, {
                    "user_input": "",
                    "system_input": collected_sys,
                    "image_data": [],
                    "task_uid": task.uid,
                    "event_type": model_event_type,
                    "character_id": character_id,
                    "sender": sender,
                    "participants": participants,
                    "req_id": req_id,
                    "origin_message_id": origin_message_id,
                    "policy": policy_dict,
                })
            else:
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="Failed to flush system info", req_id=req_id)
            return

        if event_type == "react":
            model_event_type = "react"
            policy = resolve_policy(model_event_type=model_event_type)
            policy_dict = policy.to_dict()

            react_enabled_res = event_bus.emit_and_wait(
                Events.Settings.GET_SETTING,
                {"key": "REACT_ENABLED", "default": False},
                timeout=0.8
            )
            react_enabled = bool(react_enabled_res and react_enabled_res[0])
            if not react_enabled:
                await server._send_aborted_update(
                    ctx.client_id,
                    event_type,
                    character_id,
                    reason="React disabled by settings",
                    req_id=req_id
                )
                return

            reason = data.get("reason", "")
            duration = data.get("duration", 0.0)
            current_info = context.get("currentInfo", "")

            react_system_input_lines = [
                "This is a react event from the game.",
                f"Reason: {reason}" if reason else "Reason: player_look",
                f"Look duration (seconds): {float(duration or 0.0):.1f}",
            ]
            if current_info:
                react_system_input_lines.append("")
                react_system_input_lines.append("Current game info:")
                react_system_input_lines.append(str(current_info))

            react_system_input = "\n".join(react_system_input_lines)

            task_result = event_bus.emit_and_wait(Events.Task.CREATE_TASK, {
                "type": "react",
                "data": {
                    "character": character_id,
                    "user_input": "",
                    "system_input": react_system_input,
                    "client_id": ctx.client_id,
                    "event_type": event_type,
                    "req_id": req_id,
                    "reason": reason,
                    "duration": duration,
                    "sender": sender,
                    "participants": participants,
                    "origin_message_id": origin_message_id,
                    "policy": policy_dict,
                }
            }, timeout=5.0)

            task = task_result[0] if task_result else None
            if task:
                server.client_tasks[ctx.client_id].add(task.uid)
                await server.send_task_update(ctx.client_id, task)

                event_bus.emit(Events.Chat.SEND_MESSAGE, {
                    "user_input": "",
                    "system_input": react_system_input,
                    "image_data": context.get("image_base64_list", []),
                    "task_uid": task.uid,
                    "event_type": model_event_type,
                    "character_id": character_id,
                    "sender": sender,
                    "participants": participants,
                    "req_id": req_id,
                    "origin_message_id": origin_message_id,
                    "policy": policy_dict,
                })
            else:
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="Failed to create react task", req_id=req_id)
            return

        await server._send_aborted_update(ctx.client_id, event_type, character_id, reason=f"Unknown event type: {event_type}", req_id=req_id)