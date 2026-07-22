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


def _normalise_reaction_events(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_events = data.get("reaction_events")
    if not isinstance(raw_events, (list, tuple)):
        return []

    events: List[Dict[str, Any]] = []
    for raw in raw_events[:24]:
        if not isinstance(raw, dict):
            continue

        reason = str(raw.get("reason_content") or raw.get("reason") or "").strip()
        if not reason:
            continue

        reason_type = str(raw.get("reason_type") or "Generic").strip() or "Generic"
        try:
            duration = max(0.0, float(raw.get("duration") or 0.0))
        except (TypeError, ValueError):
            duration = 0.0
        try:
            count = max(1, min(1000, int(raw.get("count") or 1)))
        except (TypeError, ValueError):
            count = 1

        events.append({
            "reason_type": reason_type,
            "reason_content": reason,
            "duration": duration,
            "count": count,
        })

    return events


def _build_react_prompt(
    data: Dict[str, Any],
    *,
    react_level: int,
) -> tuple[List[str], str, float, List[Dict[str, Any]]]:
    reaction_events = _normalise_reaction_events(data)
    if reaction_events:
        lines = [
            "This is a collected batch of react events from the game. React to the batch as one current turn.",
            f"React level: {react_level}",
            "The current Unity world state is authoritative if an older event conflicts with it.",
            "Events accumulated while the previous turn was active (oldest to newest):",
        ]
        for index, item in enumerate(reaction_events, start=1):
            count_suffix = f"; occurrences: {item['count']}" if item["count"] > 1 else ""
            duration_suffix = (
                f"; duration: {item['duration']:.1f}s"
                if item["duration"] > 0
                else ""
            )
            lines.append(
                f"{index}. [{item['reason_type']}] {item['reason_content']}"
                f"{count_suffix}{duration_suffix}"
            )

        latest = reaction_events[-1]
        reason_text = latest["reason_content"]
        duration = max(item["duration"] for item in reaction_events)
        return lines, reason_text, duration, reaction_events

    reason_type = str(data.get("reason_type") or "").strip()
    reason_content = str(data.get("reason_content") or "").strip()
    reason_text = reason_content or str(data.get("reason") or "").strip() or "player_react"
    try:
        duration = max(0.0, float(data.get("duration") or 0.0))
    except (TypeError, ValueError):
        duration = 0.0

    lines = [
        "This is a react event from the game. React to it!",
        f"React level: {react_level}",
    ]
    if reason_type:
        lines.append(f"Reason type: {reason_type}")
    lines.append(f"Reason: {reason_text}")
    lines.append(f"Duration (seconds): {duration:.1f}")
    return lines, reason_text, duration, []


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
    game_state: Optional[dict] = None,
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
            "game_state": dict(game_state or {}),
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

        game_state_payload = {
            "distance": float(str(context.get("distance", "0")).replace(",", ".")),
            "roomPlayer": int(context.get("roomPlayer", 0)),
            "roomMita": int(context.get("roomMita", 0)),
            "nearObjects": context.get("hierarchy", ""),
            "world_state": context.get("world_state", ""),
            "runtime_rules": context.get("runtime_rules", ""),
            "runtime_static_catalog": context.get("runtime_static_catalog", ""),
            "runtime_capabilities": context.get("runtime_capabilities", ""),
            "intent_rules": context.get("intent_rules", ""),
            "runtime_events": context.get("runtime_events", []),
        }
        # Runtime events are consumable by this exact turn and must never leak
        # into the persistent fallback state used by non-Unity requests.
        persistent_game_state = dict(game_state_payload)
        persistent_game_state.pop("runtime_events", None)
        event_bus.emit(Events.Server.SET_GAME_DATA, persistent_game_state)

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
            game_state=game_state_payload,
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

            system_input = ""

            # Label continuous in-game camera frames when Unity flags them
            effective_image_source = str(context.get("image_source") or "")
            if _should_label_as_mita_camera(event_type, context):
                camera_label = "[Your eyes (in-game camera)] The attached image shows what you currently see through your own eyes in-game. It is not a player photo, selfie, or drawing."
                system_input = camera_label
                effective_image_source = "mita_camera"

            await _dispatch_task(
                **_shared,
                task_type="chat",
                model_event_type=model_event_type,
                policy_dict=policy.to_dict(),
                user_input=str(user_input or ""),
                system_input=system_input,
                images=collect_context_images(context, client_id=ctx.client_id),
                image_source=effective_image_source,
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

            idle_prompt = data.get("message")
            if not isinstance(idle_prompt, str) or not idle_prompt.strip():
                idle_prompt = "The player has been silent for 180 seconds. React naturally to this silence."

            task = use(TaskService).create_task("idle", {
                "character": character_id,
                "character_stats": character_stats,
                "message": idle_prompt,
                "system_input": "",
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
                    "game_state": dict(game_state_payload),
                })
            else:
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="Failed to create idle task", req_id=req_id)
            return

        # ── system_info_flush ─────────────────────────────────────────────────
        if event_type == "system_info_flush":
            policy = resolve_policy(model_event_type="chat")
            runtime_events = context.get("runtime_events", [])
            if not isinstance(runtime_events, (list, tuple)):
                runtime_events = [runtime_events] if runtime_events else []
            flush_instruction = str(data.get("message") or "").strip()
            if not flush_instruction and not any(str(item).strip() for item in runtime_events):
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason="No runtime events or instruction to flush", req_id=req_id)
                return
            await _dispatch_task(
                **_shared,
                task_type="chat",
                model_event_type="chat",
                policy_dict=policy.to_dict(),
                user_input="",
                system_input=flush_instruction or "React to the accumulated Unity runtime events.",
                images=[],
                image_source="",
                abort_reason="Failed to flush runtime events",
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
            # L1 (тихие реакции) временно выключены и убраны из интерфейса —
            # по умолчанию отключены (совпадает с UI-дефолтом чекбокса).
            # L2 сохраняет прежний backend-дефолт (выкл. при отсутствии ключа).
            level_default = False
            if not bool(use(SettingsService).get(level_key, level_default)):
                await server._send_aborted_update(ctx.client_id, event_type, character_id, reason=f"React level {policy.react_level or 1} disabled by settings", req_id=req_id)
                return

            react_lines, reason_text, duration, reaction_events = _build_react_prompt(
                data,
                react_level=policy.react_level or 1,
            )

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
                extra_task_data={
                    "reason": reason_text,
                    "duration": duration,
                    "reaction_events": reaction_events,
                },
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
                abort_reason="Failed to create easel drawing task",
            )
            return

        await server._send_aborted_update(ctx.client_id, event_type, character_id, reason=f"Unknown event type: {event_type}", req_id=req_id)
