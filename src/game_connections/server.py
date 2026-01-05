# File: src/game_connections/server.py
import json
import asyncio
import threading
import time
from typing import Optional, Dict, Any, Set, Callable
from main_logger import logger
from core.events import get_event_bus, Events
from managers.task_manager import TaskStatus
import uuid

from game_connections.handlers import build_action_registry
from game_connections.handlers.registry import RequestContext


class ChatServerNew:
    """
    Transport-only server:
    - TCP accept/read/write
    - JSON framing
    - dispatch action handlers via ActionRegistry
    - NO event bus subscriptions / emits
    - emits connection changes via controller-provided callback
    """

    def __init__(self, host='127.0.0.1', port=12345):
        self.host = host
        self.port = port

        self.active_connections: Dict[str, asyncio.StreamWriter] = {}
        self.event_bus = get_event_bus()

        self.running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server_thread: threading.Thread | None = None

        self.client_tasks: Dict[str, Set[str]] = {}
        self.last_idle_tasks: Dict[str, str] = {}
        self.pending_sysinfo: Dict[str, list[str]] = {}

        self.ignore_game_requests: bool = False
        self.game_block_level: str = 'Idle events'
        self.game_master_voice: bool = False

        self.last_participants: Dict[str, list[str]] = {}
        self._last_sent_dialogue_text: dict[tuple[str, str], str] = {}

        self._actions = build_action_registry()

        # controller hook:
        # called with (is_connected, client_id)
        self.on_connection_changed: Callable[[bool, str | None], None] | None = None

    def set_connection_callback(self, cb: Callable[[bool, str | None], None] | None) -> None:
        self.on_connection_changed = cb

    def _notify_connection_changed(self, is_connected: bool, client_id: str | None):
        cb = self.on_connection_changed
        if not callable(cb):
            return
        try:
            cb(bool(is_connected), client_id)
        except Exception:
            pass

    async def start_async(self):
        self.running = True
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addrs = ', '.join(str(sock.getsockname()) for sock in self.server.sockets)
        logger.info(f'Новый сервер запущен на {addrs}')
        try:
            async with self.server:
                await self.server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("serve_forever cancelled on shutdown (normal)")
        finally:
            self.running = False

    def start(self):
        self._loop = asyncio.new_event_loop()
        self._server_thread = threading.Thread(target=self._run_server_loop, daemon=True)
        self._server_thread.start()

    def _run_server_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self.start_async())

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        client_id = f"{addr[0]}:{addr[1]}"
        logger.info(f"Новое подключение от {client_id}")

        was_empty = (len(self.active_connections) == 0)

        self.active_connections[client_id] = writer
        self.client_tasks[client_id] = set()

        if was_empty:
            self._notify_connection_changed(True, client_id)

        buffer = bytearray()
        decoder = json.JSONDecoder()

        try:
            while self.running:
                chunk = await reader.read(4096)
                if not chunk:
                    break

                buffer.extend(chunk)

                while buffer:
                    try:
                        buf_str = buffer.decode('utf-8')
                        obj, idx = decoder.raw_decode(buf_str)

                        await self.process_request(obj, client_id)

                        del buffer[:len(buf_str[:idx].encode('utf-8'))]
                        while buffer and chr(buffer[0]).isspace():
                            buffer.pop(0)

                    except json.JSONDecodeError:
                        break
                    except UnicodeDecodeError:
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка в handle_client: {e}", exc_info=True)
        finally:
            self.active_connections.pop(client_id, None)
            if client_id in self.client_tasks:
                del self.client_tasks[client_id]

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

            logger.info(f"Клиент {client_id} отключился")

            if not self.active_connections:
                self._notify_connection_changed(False, client_id)

    async def process_request(self, request: Dict[str, Any], client_id: str):
        action = request.get('action')
        writer = self.active_connections.get(client_id)
        if not writer:
            return

        handler = self._actions.get(str(action))
        if not handler:
            await self.send_error(writer, f"Unknown action: {action}")
            return

        ctx = RequestContext(server=self, client_id=client_id, writer=writer, event_bus=self.event_bus)
        await handler.handle(request, ctx)

    def _should_block_event(self, event_type: str) -> bool:
        if not self.ignore_game_requests:
            return False

        if self.game_block_level == 'All events':
            return True
        if event_type == 'idle_timeout' and self.game_block_level == 'Idle events':
            return True
        return False

    async def _send_aborted_update(
        self,
        client_id: str,
        event_type: str,
        character: str,
        reason: str = 'Blocked by settings',
        req_id: Optional[str] = None
    ):
        if client_id not in self.active_connections:
            return

        writer = self.active_connections[client_id]
        uid = f"abrt_{uuid.uuid4().hex}"

        body = {
            "uid": uid,
            "status": TaskStatus.ABORTED.value,
            "type": "idle" if event_type in ("idle_timeout", "idle") else "chat",
            "data": {"character": character, "event_type": event_type},
            "created_at": 0,
            "updated_at": 0,
            "result": {},
            "error": reason
        }
        if req_id:
            body["data"]["req_id"] = req_id

        message = {"type": "task_update", "uid": uid, "status": TaskStatus.ABORTED.value, "body": body}
        await self.send_json(writer, message)

    async def send_task_update(self, client_id: str, task):
        if client_id not in self.active_connections:
            return
        writer = self.active_connections[client_id]
        message = {"type": "task_update", "uid": task.uid, "status": task.status.value, "body": task.to_dict()}
        await self.send_json(writer, message)

    async def send_json(self, writer: asyncio.StreamWriter, data: Dict[str, Any]):
        try:
            json_str = json.dumps(data)
            writer.write(json_str.encode('utf-8'))
            writer.write(b'\n')
            await writer.drain()
        except Exception as e:
            logger.error(f"Ошибка отправки JSON: {e}")

    async def send_error(self, writer: asyncio.StreamWriter, error: str):
        await self.send_json(writer, {"type": "error", "error": error})

    def stop(self):
        self.running = False

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)
            try:
                future.result(timeout=5)
            except Exception as e:
                logger.warning(f"Ошибка при остановке сервера: {e}")

        if self._server_thread:
            self._server_thread.join(timeout=5)
            if self._server_thread.is_alive():
                logger.warning("Server thread did not stop in time")

        # ensure controller sees "disconnected"
        self._notify_connection_changed(False, None)

    async def _async_stop(self):
        if hasattr(self, 'server'):
            self.server.close()
            await self.server.wait_closed()

        for writer in list(self.active_connections.values()):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

        self.active_connections.clear()

    # Runtime setters
    def set_ignore_game_requests(self, value: bool):
        self.ignore_game_requests = bool(value)

    def set_game_block_level(self, value: str):
        self.game_block_level = str(value) if value is not None else 'Idle events'

    def set_game_master_voice(self, value: bool):
        self.game_master_voice = bool(value)

    # ---------------- Controller-facing API (thread-safe scheduling) ----------------
    def can_schedule(self) -> bool:
        return bool(self._loop and self._loop.is_running())

    def schedule_send_task_update(self, client_id: str, task) -> None:
        if not self.can_schedule():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.send_task_update(client_id, task), self._loop)
        except Exception:
            pass

    def schedule_broadcast_json(self, payload: Dict[str, Any]) -> None:
        if not self.can_schedule():
            return

        async def _push():
            if not self.active_connections:
                return
            writers = list(self.active_connections.values())
            await asyncio.gather(*(self.send_json(w, payload) for w in writers), return_exceptions=True)

        try:
            asyncio.run_coroutine_threadsafe(_push(), self._loop)
        except Exception:
            pass

    def schedule_broadcast_loaded_settings(self, body: Dict[str, Any]) -> None:
        self.schedule_broadcast_json({"type": "loaded_settings", "body": body})

    def schedule_broadcast_asr_text(self, text: str, engine: str = "", ts: float | None = None) -> None:
        payload = {
            "type": "asr_text",
            "text": str(text or ""),
            "engine": str(engine or ""),
            "ts": float(ts or time.time()),
        }
        self.schedule_broadcast_json(payload)

    def on_task_status_changed(self, task) -> None:
        try:
            if not task or not getattr(task, "data", None):
                return

            client_id = task.data.get("client_id")
            character = task.data.get("character")
            event_type = task.data.get("event_type")

            try:
                if client_id and character and getattr(task, "status", None) == TaskStatus.SUCCESS and getattr(task, "result", None):
                    resp = task.result.get("response") if isinstance(task.result, dict) else None
                    if isinstance(resp, str) and resp.strip():
                        self._last_sent_dialogue_text[(str(client_id), str(character))] = resp.strip()
            except Exception:
                pass

            if event_type in ('idle', 'idle_timeout') and character:
                if task.status in (
                    TaskStatus.SUCCESS,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.FAILED_ON_GENERATION,
                    TaskStatus.FAILED_ON_VOICEOVER,
                    TaskStatus.ABORTED
                ):
                    if self.last_idle_tasks.get(character) == task.uid:
                        del self.last_idle_tasks[character]
        except Exception:
            return