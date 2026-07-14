from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.events import Events
from core.services import use
from services.contracts import CharacterRegistry, SettingsService, TaskService
from core.request_policy import resolve_policy
from managers.task_manager import TaskStatus
from game_connections.handlers.registry import RequestContext
from game_connections.shared_image_transfer import collect_context_images

logger = logging.getLogger(__name__)


def _collect_context_images(context: dict) -> List:
    """Backward-compatible shim kept for existing call sites."""
    return list(collect_context_images(context))


def _has_context_images(context: dict) -> bool:
    return bool((context.get("image_base64_list") or []) or (context.get("image_paths") or []))


def _should_label_as_mita_camera(event_type: str, context: dict) -> bool:
    """
    Unity6 continuous FrameRecorder currently attaches frames without an explicit
    `mita_camera` flag in the payload. For ordinary answer/react turns, attached
    images therefore come from Mita's POV unless a dedicated image event is used.
    """
    if not _has_context_images(context):
        return False
    if str(context.get("image_source") or "").strip().lower() == "mita_camera":
        return True
    if context.get("mita_camera", False):
        return True
    if event_type in ("camera_snapshot_result", "easel_drawing", "tv_reaction"):
        return False
    return event_type in ("answer", "react")


async def _dispatch_task(
    *,
    server,
    event_bus,
    ctx: RequestContext,
    task_type: str,
    model_event_type: str,
    policy_dict: dict,
    user_input: str,
    system_input: str,
    images: List,
    character_id: str,
    character_stats: dict,
    sender: str,
    participants: list,
    req_id,
    origin_message_id,
    event_type: str,
    image_source: str = "",
    extra_task_data: Optional[dict] = None,
    abort_reason: str = "Failed to create task",
) -> Any:
    """
    Emit CREATE_TASK then SEND_MESSAGE — the shared boilerplate for most event types.
    Returns the created task, or None if creation failed (abort update already sent).
    """
    task_data: dict = {
        "character": character_id,
        "character_stats": character_stats,
        "user_input": user_input,
        "system_input": system_input,
        "client_id": ctx.client_id,
        "event_type": event_type,
        "req_id": req_id,
        "sender": sender,
        "participants": participants,
        "origin_message_id": origin_message_id,
        "policy": policy_dict,
    }
    if extra_task_data:
        task_data.update(extra_task_data)

    task = use(TaskService).create_task(task_type, task_data)

    if task:
        server.client_tasks[ctx.client_id].add(task.uid)
        await server.send_task_update(ctx.client_id, task)
        event_bus.emit(Events.Chat.SEND_MESSAGE, {
            "user_input": user_input,
            "system_input": system_input,
            "image_data": images,
            "image_source": image_source,
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
        await server._send_aborted_update(
            ctx.client_id, event_type, character_id,
            reason=abort_reason, req_id=req_id,
        )
    return task


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

        def _get_character_stats(cid: str) -> Dict[str, float]:
            cid = str(cid or "").strip()
            if not cid:
                return {"attitude": 60.0, "boredom": 10.0, "stress": 5.0}
            try:
                ch = use(CharacterRegistry).get(cid)
                if ch is not None and hasattr(ch, "get_stats_dict"):
                    v = ch.get_stats_dict()
                    if isinstance(v, dict):
                        return {
                            "attitude": float(v.get("attitude", 60.0)),
                            "boredom": float(v.get("boredom", 10.0)),
                            "stress": float(v.get("stress", 5.0)),
                        }
            except Exception:
                pass
            return {"attitude": 60.0, "boredom": 10.0, "stress": 5.0}

        character_stats = _get_character_stats(character_id)

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

        # Shared kwargs forwarded to every _dispatch_task call
        _shared = dict(
            server=server,
            event_bus=event_bus,
            ctx=ctx,
            character_id=character_id,
            character_stats=character_stats,
            sender=sender,
            participants=participants,
            req_id=req_id,
            origin_message_id=origin_message_id,
            event_type=event_type,
        )

        # ── answer ────────────────────────────────────────────────────────────
        if event_type == "answer":
            model_event_type = "chat"
            policy = resolve_policy(model_event_type=model_event_type)
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

            # Label continuous in-game camera frames when Unity flags them
            effective_image_source = str(context.get("image_source") or "")
            if _should_label_as_mita_camera(event_type, context):
                camera_label = "[Your eyes (in-game camera)] The attached image shows what you currently see through your own eyes in-game. It is not a player photo, selfie, or drawing."
                collected_sys = (camera_label + "\n" + collected_sys).strip() if collected_sys else camera_label
                effective_image_source = "mita_camera"

            await _dispatch_task(
                **_shared,
                task_type="chat",
                model_event_type=model_event_type,
                policy_dict=policy.to_dict(),
                user_input=str(user_input or ""),
                system_input=collected_sys,
                images=collect_context_images(context, client_id=ctx.client_id),
                image_source=effective_image_source,
                extra_task_data={"system_info": context.get("currentInfo", "")},
                abort_reason="Failed to create task",
            )
            return

        # ── idle_timeout ──────────────────────────────────────────────────────
        # Kept separate: uses task type "idle", different SEND_MESSAGE system_input,
        # and must track server.last_idle_tasks.
        if event_type == "idle_timeout":
            model_event_type = "idle_timeout"
            policy = resolve_policy(model_event_type=model_event_type)
            policy_dict = policy.to_dict()

            last_idle_uid = server.last_idle_tasks.get(character_id)
            if last_idle_uid:
                last_task = use(TaskService).get_task(last_idle_uid)
                if last_task and last_task.status == TaskStatus.PENDING:
                    await server.send_task_update(ctx.client_id, last_task)
                    return

            collected_sys = ""
            if policy.use_pending_sysinfo:
                collected_sys = "\n".join(server.pending_sysinfo.pop(character_id, []))

            task = use(TaskService).create_task("idle", {
                "character": character_id,
                "character_stats": character_stats,
                "message": data.get("message", "Player idle for 90 seconds"),
                "system_input": collected_sys,
                "client_id": ctx.client_id,
                "event_type": event_type,
                "req_id": req_id,
                "sender": sender,
                "participants": participants,
                "origin_message_id": origin_message_id,
                "policy": policy_dict,
            })
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

        # ── system_info ───────────────────────────────────────────────────────
        if event_type == "system_info":
            msg = data.get("message", "")
            if msg:
                server.pending_sysinfo.setdefault(character_id, []).append(msg)
            await server.send_json(ctx.writer, {"type": "info", "stored": len(server.pending_sysinfo.get(character_id, []))})
            return

        # ── system_info_flush ─────────────────────────────────────────────────
        if event_type == "system_info_flush":
            policy = resolve_policy(model_event_type="chat")
            collected_sys = "\n".join(server.pending_sysinfo.pop(character_id, []))
            if not collected_sys:
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="No pending system_info to flush", req_id=req_id)
                return
            await _dispatch_task(
                **_shared,
                task_type="chat",
                model_event_type="chat",
                policy_dict=policy.to_dict(),
                user_input="",
                system_input=collected_sys,
                images=[],
                image_source="",
                extra_task_data={"system_info": context.get("currentInfo", "")},
                abort_reason="Failed to flush system info",
            )
            return

        # ── react ─────────────────────────────────────────────────────────────
        if event_type == "react":
            model_event_type = "react"

            if not bool(use(SettingsService).get("REACT_ENABLED", False)):
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="React disabled by settings", req_id=req_id)
                return

            incoming_level = data.get("react_level", None)
            policy = resolve_policy(model_event_type=model_event_type, react_level=incoming_level)
            level_key = "REACT_L2_ENABLED" if policy.react_level == 2 else "REACT_L1_ENABLED"
            level_default = False if policy.react_level == 2 else True
            if not bool(use(SettingsService).get(level_key, level_default)):
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason=f"React level {policy.react_level or 1} disabled by settings", req_id=req_id)
                return

            reason_type = str(data.get("reason_type") or "").strip()
            reason_content = str(data.get("reason_content") or "").strip()
            reason_text = reason_content or str(data.get("reason") or "").strip() or "player_react"
            duration = data.get("duration", 0.0)

            react_lines = [
                "This is a react event from the game. React to it!",
                f"React level: {policy.react_level or 1}",
            ]
            if reason_type:
                react_lines.append(f"Reason type: {reason_type}")
            react_lines.append(f"Reason: {reason_text}")
            react_lines.append(f"Duration (seconds): {float(duration or 0.0):.1f}")

            current_info = context.get("currentInfo", "")
            if current_info and not policy.use_pending_sysinfo:
                react_lines += ["", "Current game info:", str(current_info)]

            if policy.use_pending_sysinfo:
                collected_sys = "\n".join(server.pending_sysinfo.pop(character_id, []))
                if collected_sys.strip():
                    react_lines += ["", "Pending system info:", collected_sys]

            # Label continuous in-game camera frames when Unity flags them
            effective_image_source = str(context.get("image_source") or "")
            if _should_label_as_mita_camera(event_type, context):
                react_lines.insert(0, "[Your eyes (in-game camera)] The attached image shows what you currently see through your own eyes in-game. It is not a player photo, selfie, or drawing.")
                effective_image_source = "mita_camera"

            await _dispatch_task(
                **_shared,
                task_type="react",
                model_event_type=model_event_type,
                policy_dict=policy.to_dict(),
                user_input="",
                system_input="\n".join(react_lines),
                images=collect_context_images(context, client_id=ctx.client_id),
                image_source=effective_image_source,
                extra_task_data={"reason": reason_text, "duration": duration},
                abort_reason="Failed to create react task",
            )
            return

        # ── camera_snapshot_result ────────────────────────────────────────────
        if event_type == "camera_snapshot_result":
            policy = resolve_policy(model_event_type="chat")
            snapshot_msg = str(data.get("message", "Camera snapshot taken"))
            system_input = f"[Your eyes (in-game camera)] {snapshot_msg}"
            await _dispatch_task(
                **_shared,
                task_type="chat",
                model_event_type="chat",
                policy_dict=policy.to_dict(),
                user_input="",
                system_input=system_input,
                images=collect_context_images(context, client_id=ctx.client_id),
                image_source="mita_camera",
                extra_task_data={"system_info": context.get("currentInfo", "")},
                abort_reason="Failed to create snapshot task",
            )
            return

        # ── tv_reaction ───────────────────────────────────────────────────────
        if event_type == "tv_reaction":
            policy = resolve_policy(model_event_type="react")
            raw_msg = str(data.get("message", "")).strip()
            tv_content = raw_msg or "The player is watching TV. React to what is shown."
            system_input = f"[TV] {tv_content}"
            await _dispatch_task(
                **_shared,
                task_type="react",
                model_event_type="react",
                policy_dict=policy.to_dict(),
                user_input="",
                system_input=system_input,
                images=collect_context_images(context, client_id=ctx.client_id),
                image_source=str(context.get("image_source") or ""),
                extra_task_data={"system_info": context.get("currentInfo", "")},
                abort_reason="Failed to create TV reaction task",
            )
            return

        # ── easel_drawing ─────────────────────────────────────────────────────
        if event_type == "easel_drawing":
            policy = resolve_policy(model_event_type="chat")
            raw_msg = str(data.get("message", "")).strip()
            easel_label = "[Easel drawing] The attached image is the player's drawing shown on the in-game easel/canvas."
            system_input = raw_msg or easel_label
            if system_input != easel_label:
                system_input = f"{easel_label}\n{system_input}"
            await _dispatch_task(
                **_shared,
                task_type="chat",
                model_event_type="chat",
                policy_dict=policy.to_dict(),
                user_input="",
                system_input=system_input,
                images=collect_context_images(context, client_id=ctx.client_id),
                image_source="easel",
                extra_task_data={"system_info": context.get("currentInfo", "")},
                abort_reason="Failed to create easel drawing task",
            )
            return

        await server._send_aborted_update(ctx.client_id, event_type, character_id, reason=f"Unknown event type: {event_type}", req_id=req_id)
