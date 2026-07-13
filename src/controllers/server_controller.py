# File: src/controllers/server_controller.py
import ipaddress
import os
import threading
from typing import Dict, Any, Optional, Tuple
from collections import deque
from main_logger import logger
from core.events import get_event_bus, Events, Event
from core.services import use
from services.contracts import CharacterRegistry, SettingsService

from managers.task_manager import TaskStatus
from game_connections.shared_image_transfer import ensure_shared_transfer_dirs


class ServerEchoSuppressor:
    def __init__(self, max_out_ids_per_speaker: int = 200, max_seen_in_ids: int = 500):
        self._out_ids: dict[Tuple[str, str], deque[str]] = {}
        self._out_text: dict[Tuple[str, str], str] = {}
        self._seen_in_ids: dict[str, deque[str]] = {}
        self._max_out_ids = int(max_out_ids_per_speaker)
        self._max_seen_in = int(max_seen_in_ids)
        self._lock = threading.RLock()

    def register_outgoing(self, client_id: str, speaker: str, message_id: str, text: str):
        client_id = str(client_id or "")
        speaker = str(speaker or "")
        message_id = str(message_id or "")
        text = str(text or "")

        if not client_id or not speaker or not message_id:
            return

        key = (client_id, speaker)
        with self._lock:
            dq = self._out_ids.get(key)
            if dq is None:
                dq = deque(maxlen=self._max_out_ids)
                self._out_ids[key] = dq

            dq.append(message_id)
            if text.strip():
                self._out_text[key] = text.strip()

    def _seen_in(self, client_id: str) -> deque[str]:
        client_id = str(client_id or "")
        with self._lock:
            dq = self._seen_in_ids.get(client_id)
            if dq is None:
                dq = deque(maxlen=self._max_seen_in)
                self._seen_in_ids[client_id] = dq
            return dq

    def forget_client(self, client_id: str) -> None:
        client_id = str(client_id or "")
        if not client_id:
            return
        with self._lock:
            self._seen_in_ids.pop(client_id, None)
            for mapping in (self._out_ids, self._out_text):
                stale = [key for key in mapping if key[0] == client_id]
                for key in stale:
                    mapping.pop(key, None)

    def should_echo_incoming(
        self,
        *,
        client_id: str,
        sender: str,
        text: str,
        incoming_message_id: Optional[str] = None,
        origin_message_id: Optional[str] = None,
    ) -> bool:
        client_id = str(client_id or "")
        sender = str(sender or "")
        text = str(text or "")

        if not client_id:
            return True

        with self._lock:
            if incoming_message_id:
                seen = self._seen_in(client_id)
                if incoming_message_id in seen:
                    return False
                seen.append(incoming_message_id)

            if sender == "Player":
                return True

            if origin_message_id:
                key = (client_id, sender)
                dq = self._out_ids.get(key)
                if dq and origin_message_id in dq:
                    return False

            key = (client_id, sender)
            last = self._out_text.get(key, "")
            if last and last == text.strip():
                return False

            return True


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().strip("[]")
    if normalized.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class ServerController:
    def __init__(self, game_link):
        self.event_bus = get_event_bus()
        self.game_link = game_link
        self.game_link.attach_probe(self._probe_connection)
        self.server = None
        self.running = False
        self.ConnectedToGame = False
        self._destroyed = False

        self.settings_to_send = [
            'ACTION_MENU', 'MITAS_MENU', 'IGNORE_GAME_REQUESTS', 'GAME_BLOCK_LEVEL',
            'CHARACTER', 'WORLD_HIERARCHY_TREE',
            'BEAT_SYNC_ENABLED', 'BEAT_SYNC_STREAMING', 'BEAT_SYNC_CHUNK_SECONDS',
            'BEAT_SYNC_MIN_CONFIDENCE', 'BEAT_SYNC_AUTO_INSTALL',
            'BEAT_SYNC_USE_FILE_TRANSFER',
            # Mita head-camera (FrameRecorder)
            'MITA_CAMERA_ENABLED', 'MITA_CAMERA_CONTINUOUS', 'MITA_CAMERA_ON_DEMAND',
            'MITA_CAMERA_INTERVAL', 'MITA_CAMERA_MAX_FRAMES', 'MITA_CAMERA_FRAMES_TO_SEND',
            'MITA_CAMERA_JPEG_QUALITY', 'MITA_CAMERA_USE_FILE_TRANSFER',
            # Image transport: "shared_files" | "socket" | "auto"
            'IMAGE_TRANSPORT_MODE',
        ]

        self.echo_suppressor = ServerEchoSuppressor()
        self.settings = use(SettingsService)
        self._settings_subscription = self.settings.subscribe(
            self._on_setting_changed,
            keys=set(self.settings_to_send) | {"GM_VOICE"},
        )

        self._subscribe_to_events()
        self._init_server()

    def _subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Server.STOP_SERVER, self._on_stop_server, weak=False)
        eb.subscribe(Events.Server.LOAD_SERVER_SETTINGS, self._on_load_server_settings, weak=False)

        eb.subscribe(Events.Server.ECHO_CHAT_MESSAGE_REQUESTED, self._on_echo_chat_message_requested, weak=False)

        eb.subscribe(Events.Task.TASK_STATUS_CHANGED, self._on_task_status_changed, weak=False)
        eb.subscribe(Events.Server.SEND_TASK_UPDATE, self._on_send_task_update, weak=False)

        eb.subscribe(Events.Server.BROADCAST_ASR_TEXT, self._on_broadcast_asr_text, weak=False)

    def _unsubscribe_from_events(self):
        if self.event_bus and not self._destroyed:
            eb = self.event_bus
            eb.unsubscribe(Events.Server.STOP_SERVER, self._on_stop_server)
            eb.unsubscribe(Events.Server.LOAD_SERVER_SETTINGS, self._on_load_server_settings)

            eb.unsubscribe(Events.Server.ECHO_CHAT_MESSAGE_REQUESTED, self._on_echo_chat_message_requested)

            eb.unsubscribe(Events.Task.TASK_STATUS_CHANGED, self._on_task_status_changed)
            eb.unsubscribe(Events.Server.SEND_TASK_UPDATE, self._on_send_task_update)

            asr_evt = getattr(Events.Server, "BROADCAST_ASR_TEXT", "broadcast_asr_text")
            eb.unsubscribe(asr_evt, self._on_broadcast_asr_text)

    def _init_server(self):
        from game_connections.server import ChatServerNew

        host = str(
            os.environ.get("NEUROMITA_SERVER_HOST")
            or self._get_setting("SERVER_HOST", "127.0.0.1")
            or "127.0.0.1"
        ).strip()
        raw_port = os.environ.get("NEUROMITA_SERVER_PORT")
        if raw_port in (None, ""):
            raw_port = self._get_setting("SERVER_PORT", 12345)
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            logger.warning(f"Invalid SERVER_PORT={raw_port!r}; using 12345")
            port = 12345
        if not 1 <= port <= 65535:
            logger.warning(f"SERVER_PORT out of range: {port}; using 12345")
            port = 12345

        if not _is_loopback_host(host):
            logger.warning(
                f"Server is binding to non-loopback address {host}:{port}. "
                "The game protocol has no network authentication; expose it only "
                "on a trusted network or behind an authenticated tunnel."
            )

        self.server = ChatServerNew(host=host, port=port)
        try:
            transfer_dirs = ensure_shared_transfer_dirs()
            logger.info(f"Shared image transfer root: {transfer_dirs['root']}")
        except Exception as e:
            logger.warning(f"Failed to prepare shared image transfer directories: {e}")
        logger.info("Using new API server")

        def _conn_cb(client_connected: bool, client_id: str | None):
            self.update_game_connection(client_connected, client_id)

        self.server.set_connection_callback(_conn_cb)
        self.server.set_settings_provider(self._prepare_loaded_settings_body)

        self._apply_initial_settings()
        self.start_server()

    def _apply_initial_settings(self):
        try:
            ignore_game_requests_value = self._get_setting('IGNORE_GAME_REQUESTS', False)
            self.server.set_ignore_game_requests(bool(ignore_game_requests_value))
        except Exception:
            self.server.set_ignore_game_requests(False)

        try:
            game_block_level_value = self._get_setting('GAME_BLOCK_LEVEL', 'Idle events')
            self.server.set_game_block_level(str(game_block_level_value))
        except Exception:
            self.server.set_game_block_level('Idle events')

        try:
            game_master_voice_value = self._get_setting('GM_VOICE', False)
            self.server.set_game_master_voice(bool(game_master_voice_value))
        except Exception:
            self.server.set_game_master_voice(False)

    def start_server(self):
        if self.running:
            return True
        if not self.server:
            return False

        started = bool(self.server.start(timeout=5.0))
        self.running = started
        if started:
            logger.info("Server started")
            return True

        error = getattr(self.server, "startup_error", None)
        logger.error(f"Server failed to start: {error or 'startup timeout'}")
        return False

    def stop_server(self):
        if not self.server:
            self.running = False
            return

        logger.info("Stopping server...")
        self.running = False

        try:
            self.server.stop()
        except Exception as e:
            logger.error(f"Error while stopping server: {e}", exc_info=True)

        try:
            self.ConnectedToGame = False
            if self.event_bus:
                self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
        except Exception:
            pass

        logger.info("Server stopped")

    def destroy(self):
        if self._destroyed:
            return

        logger.info("Destroying ServerController...")
        subscription = self._settings_subscription
        self._settings_subscription = None
        if subscription is not None:
            subscription.close()
        self._unsubscribe_from_events()
        self.stop_server()
        self._destroyed = True

        try:
            from managers.task_manager import get_task_manager
            task_manager = get_task_manager()
            task_manager.clear_all_tasks()
        except Exception as e:
            logger.error(f"Error while cleaning up task manager: {e}")

        self.server = None
        self.event_bus = None

    def update_game_connection(self, client_connected, client_id: str | None = None):
        if self._destroyed or not self.event_bus:
            return

        connections = getattr(self.server, "active_connections", None) if self.server else None
        if isinstance(connections, dict):
            self.ConnectedToGame = bool(connections)
        else:
            self.ConnectedToGame = bool(client_connected)
        self.game_link.set_connected(self.ConnectedToGame)

        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

        if bool(client_connected) and client_id and self.server:
            try:
                body = self._prepare_loaded_settings_body()
                self.server.schedule_send_loaded_settings(client_id, body)
            except Exception as exc:
                logger.warning(f"Failed to send initial settings to {client_id}: {exc}")
        elif not bool(client_connected) and client_id:
            self.echo_suppressor.forget_client(client_id)

    def _probe_connection(self) -> Optional[bool]:
        """Живое состояние соединений сервера; None — если сказать нечего."""
        if self._destroyed:
            return None
        srv = self.server
        conns = getattr(srv, "active_connections", None) if srv else None
        if isinstance(conns, dict):
            return bool(conns)
        return None

    def _on_stop_server(self, event: Event):
        if self._destroyed:
            return
        self.stop_server()

    def _on_get_chat_server(self, event: Event):
        if self._destroyed:
            return None
        return self.server

    def _on_setting_changed(self, change):
        if self._destroyed or not self.server:
            return

        key = change.key
        value = change.value

        if key == 'IGNORE_GAME_REQUESTS':
            self.server.set_ignore_game_requests(bool(value))
        elif key == 'GAME_BLOCK_LEVEL':
            self.server.set_game_block_level(str(value))
        elif key == 'GM_VOICE':
            self.server.set_game_master_voice(bool(value))
        elif key == 'BEAT_SYNC_ENABLED' and bool(value):
            try:
                import asyncio
                from game_connections.services.beat_service import get_beat_service

                if self.server and self.server.can_schedule():
                    asyncio.run_coroutine_threadsafe(
                        get_beat_service().warmup(auto_install=False),
                        self.server._loop,
                    )
            except Exception as e:
                logger.warning(f"Beat sync warmup failed: {e}")

        if key in self.settings_to_send:
            try:
                body = self._prepare_loaded_settings_body()
                self.server.schedule_broadcast_loaded_settings(body)
            except Exception as e:
                logger.warning(f"Failed to push updated settings to clients ({key}): {e}")

    def _on_load_server_settings(self, event: Event):
        if self._destroyed or not self.server:
            return
        try:
            body = self._prepare_loaded_settings_body()
            self.server.schedule_broadcast_loaded_settings(body)
        except Exception as e:
            logger.warning(f"LOAD_SERVER_SETTINGS broadcast failed: {e}")

    def _get_character_stats(self, character_id: str) -> Dict[str, float]:
        cid = str(character_id or "").strip()
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

    def _collect_characters_stats(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}

        all_ids = use(CharacterRegistry).all_ids()

        for cid in all_ids:
            s = str(cid or "").strip()
            if not s:
                continue
            out[s] = self._get_character_stats(s)

        return out

    def _prepare_loaded_settings_body(self) -> Dict[str, Any]:
        settings = {}
        for setting in self.settings_to_send:
            if setting == 'BEAT_SYNC_USE_FILE_TRANSFER':
                settings[str(setting)] = True
                continue
            if setting == 'BEAT_SYNC_AUTO_INSTALL':
                settings[str(setting)] = False
                continue
            settings[str(setting)] = self._get_setting(setting)

        characters_stats = self._collect_characters_stats()

        transport_raw = str(settings.get("IMAGE_TRANSPORT_MODE") or "auto").strip().lower()
        if transport_raw not in ("shared_files", "socket", "auto"):
            transport_raw = "auto"
        settings["IMAGE_TRANSPORT_MODE"] = transport_raw

        shared_transfer: Dict[str, Any] = {}
        try:
            dirs = ensure_shared_transfer_dirs()
            shared_transfer = {
                "protocol": "shared_files_v1",
                "root": str(dirs["root"]),
                "images_dir": str(dirs["images"]),
                "manifests_dir": str(dirs["manifests"]),
                "mode": transport_raw,
            }
        except Exception as e:
            logger.warning(f"Failed to describe shared image transfer settings: {e}")

        body = {"settings": settings, "characters_stats": characters_stats}
        if shared_transfer:
            body["shared_image_transfer"] = shared_transfer
        return body

    def _get_setting(self, key: str, default=None):
        return use(SettingsService).get(key, default)

    def _on_task_status_changed(self, event: Event):
        data = event.data or {}
        task = data.get("task")
        if not task or not getattr(task, "data", None):
            return

        try:
            if self.server:
                self.server.on_task_status_changed(task)
        except Exception:
            pass

        try:
            character_id = str(task.data.get("character") or "")
            if character_id:
                stats = self._get_character_stats(character_id)

                try:
                    task.data["character_stats"] = stats
                except Exception:
                    pass

                if task.status == TaskStatus.SUCCESS:
                    try:
                        if task.result is None or not isinstance(task.result, dict):
                            task.result = {}
                        task.result["character_stats"] = stats
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            client_id = str(task.data.get("client_id") or "")
            speaker = str(task.data.get("character") or "")
            if client_id and speaker and task.status == TaskStatus.SUCCESS:
                result = getattr(task, "result", None) or {}
                text = result.get("response") if isinstance(result, dict) else ""
                message_id = str(getattr(task, "uid", "") or "")
                if message_id:
                    self.echo_suppressor.register_outgoing(client_id, speaker, message_id, str(text or ""))
        except Exception:
            pass

        try:
            client_id = str(task.data.get("client_id") or "")
            if client_id and self.server:
                self.server.schedule_send_task_update(client_id, task)
        except Exception:
            pass

    def _on_send_task_update(self, event: Event):
        task = (event.data or {}).get('task')
        if not task or not getattr(task, "data", None):
            return
        client_id = str(task.data.get("client_id") or "")
        if client_id and self.server:
            self.server.schedule_send_task_update(client_id, task)

    def _on_broadcast_asr_text(self, event: Event):
        if not self.server:
            return
        data = event.data or {}
        text = str(data.get("text") or "").strip()
        if not text:
            return
        engine = str(data.get("engine") or "")
        ts = data.get("ts", None)
        try:
            self.server.schedule_broadcast_asr_text(text=text, engine=engine, ts=ts)
        except Exception:
            pass

    def _on_echo_chat_message_requested(self, event: Event):
        if self._destroyed:
            return

        p = event.data or {}
        client_id = str(p.get("client_id") or "")
        sender = str(p.get("sender") or "Player")
        text = str(p.get("text") or "")
        incoming_message_id = p.get("message_id")
        origin_message_id = p.get("origin_message_id")

        if not text.strip():
            return

        if not self.echo_suppressor.should_echo_incoming(
            client_id=client_id,
            sender=sender,
            text=text,
            incoming_message_id=str(incoming_message_id) if incoming_message_id else None,
            origin_message_id=str(origin_message_id) if origin_message_id else None,
        ):
            return

        ui_role = "user" if sender == "Player" else "assistant"
        self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
            "role": ui_role,
            "response": text,
            "is_initial": False,
            "emotion": "",
            "speaker_name": ("" if sender == "Player" else sender),
        })



