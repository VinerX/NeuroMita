# File: src/controllers/server_controller.py
from typing import Dict, Any, Optional, Tuple
from collections import deque
from main_logger import logger
from core.events import get_event_bus, Events, Event

from managers.task_manager import TaskStatus


class ServerEchoSuppressor:
    def __init__(self, max_out_ids_per_speaker: int = 200, max_seen_in_ids: int = 500):
        self._out_ids: dict[Tuple[str, str], deque[str]] = {}
        self._out_text: dict[Tuple[str, str], str] = {}
        self._seen_in_ids: dict[str, deque[str]] = {}
        self._max_out_ids = int(max_out_ids_per_speaker)
        self._max_seen_in = int(max_seen_in_ids)

    def register_outgoing(self, client_id: str, speaker: str, message_id: str, text: str):
        client_id = str(client_id or "")
        speaker = str(speaker or "")
        message_id = str(message_id or "")
        text = str(text or "")

        if not client_id or not speaker or not message_id:
            return

        key = (client_id, speaker)
        dq = self._out_ids.get(key)
        if dq is None:
            dq = deque(maxlen=self._max_out_ids)
            self._out_ids[key] = dq

        dq.append(message_id)
        if text.strip():
            self._out_text[key] = text.strip()

    def _seen_in(self, client_id: str) -> deque[str]:
        client_id = str(client_id or "")
        dq = self._seen_in_ids.get(client_id)
        if dq is None:
            dq = deque(maxlen=self._max_seen_in)
            self._seen_in_ids[client_id] = dq
        return dq

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


class ServerController:
    def __init__(self):
        self.event_bus = get_event_bus()
        self.server = None
        self.running = False
        self.ConnectedToGame = False
        self._destroyed = False

        self.settings_to_send = ['ACTION_MENU', 'MITAS_MENU', 'IGNORE_GAME_REQUESTS', 'GAME_BLOCK_LEVEL', 'CHARACTER']

        self.echo_suppressor = ServerEchoSuppressor()

        self._subscribe_to_events()
        self._init_server()

    def _subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Server.STOP_SERVER, self._on_stop_server, weak=False)
        eb.subscribe(Events.Server.GET_CHAT_SERVER, self._on_get_chat_server, weak=False)
        eb.subscribe(Events.Server.SET_GAME_CONNECTION, self._on_update_game_connection, weak=False)
        eb.subscribe(Events.Server.GET_GAME_CONNECTION, self._on_get_connection_status, weak=False)
        eb.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)
        eb.subscribe(Events.Server.LOAD_SERVER_SETTINGS, self._on_load_server_settings, weak=False)

        eb.subscribe(Events.Server.ECHO_CHAT_MESSAGE_REQUESTED, self._on_echo_chat_message_requested, weak=False)

        # --- moved from server.py subscriptions ---
        eb.subscribe(Events.Task.TASK_STATUS_CHANGED, self._on_task_status_changed, weak=False)
        eb.subscribe(Events.Server.SEND_TASK_UPDATE, self._on_send_task_update, weak=False)

        eb.subscribe(Events.Server.BROADCAST_ASR_TEXT, self._on_broadcast_asr_text, weak=False)

    def _unsubscribe_from_events(self):
        if self.event_bus and not self._destroyed:
            eb = self.event_bus
            eb.unsubscribe(Events.Server.STOP_SERVER, self._on_stop_server)
            eb.unsubscribe(Events.Server.GET_CHAT_SERVER, self._on_get_chat_server)
            eb.unsubscribe(Events.Server.SET_GAME_CONNECTION, self._on_update_game_connection)
            eb.unsubscribe(Events.Server.GET_GAME_CONNECTION, self._on_get_connection_status)
            eb.unsubscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed)
            eb.unsubscribe(Events.Server.LOAD_SERVER_SETTINGS, self._on_load_server_settings)

            eb.unsubscribe(Events.Server.ECHO_CHAT_MESSAGE_REQUESTED, self._on_echo_chat_message_requested)

            eb.unsubscribe(Events.Task.TASK_STATUS_CHANGED, self._on_task_status_changed)
            eb.unsubscribe(Events.Server.SEND_TASK_UPDATE, self._on_send_task_update)

            asr_evt = getattr(Events.Server, "BROADCAST_ASR_TEXT", "broadcast_asr_text")
            eb.unsubscribe(asr_evt, self._on_broadcast_asr_text)

    def _init_server(self):
        from game_connections.server import ChatServerNew
        self.server = ChatServerNew()
        logger.info("Используется новый API сервер")

        # controller owns connection state propagation
        def _conn_cb(is_connected: bool, _client_id: str | None):
            try:
                self.event_bus.emit(Events.Server.SET_GAME_CONNECTION, {"is_connected": bool(is_connected)})
            except Exception:
                pass

        try:
            self.server.set_connection_callback(_conn_cb)
        except Exception:
            pass

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
        if not self.running:
            self.running = True
            self.server.start()
            logger.info("Сервер запущен")

    def stop_server(self):
        if not self.running:
            logger.debug("Сервер уже остановлен")
            return

        logger.info("Начинаем остановку сервера...")
        self.running = False

        try:
            if self.server:
                self.server.stop()
        except Exception as e:
            logger.error(f"Ошибка при остановке сервера: {e}", exc_info=True)

        try:
            self.ConnectedToGame = False
            if self.event_bus:
                self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
        except Exception:
            pass

        logger.info("Сервер остановлен")

    def destroy(self):
        if self._destroyed:
            return

        logger.info("Уничтожение ServerController...")
        self._destroyed = True

        self._unsubscribe_from_events()
        self.stop_server()

        try:
            from managers.task_manager import get_task_manager
            task_manager = get_task_manager()
            task_manager.clear_all_tasks()
        except Exception as e:
            logger.error(f"Ошибка при очистке task manager: {e}")

        self.server = None
        self.event_bus = None

    def update_game_connection(self, is_connected):
        if self._destroyed or not self.event_bus:
            return
        self.ConnectedToGame = bool(is_connected)
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    def _on_update_game_connection(self, event: Event):
        if self._destroyed:
            return
        is_connected = (event.data or {}).get('is_connected', False)
        self.update_game_connection(is_connected)

    def _on_get_connection_status(self, event: Event):
        if self._destroyed:
            return None
        try:
            srv = self.server
            conns = getattr(srv, "active_connections", None) if srv else None
            if isinstance(conns, dict):
                return bool(conns)
        except Exception:
            pass
        return bool(self.ConnectedToGame)

    def _on_stop_server(self, event: Event):
        if self._destroyed:
            return
        self.stop_server()

    def _on_get_chat_server(self, event: Event):
        if self._destroyed:
            return None
        return self.server

    def _on_setting_changed(self, event: Event):
        if self._destroyed or not self.server:
            return

        key = (event.data or {}).get('key')
        value = (event.data or {}).get('value')

        if key == 'IGNORE_GAME_REQUESTS':
            self.server.set_ignore_game_requests(bool(value))
        elif key == 'GAME_BLOCK_LEVEL':
            self.server.set_game_block_level(str(value))
        elif key == 'GM_VOICE':
            self.server.set_game_master_voice(bool(value))

        if key in self.settings_to_send:
            try:
                body = self._prepare_loaded_settings_body()
                # server transport method, thread-safe
                self.server.schedule_broadcast_loaded_settings(body)
            except Exception as e:
                logger.warning(f"Не удалось отправить обновлённые настройки клиентам ({key}): {e}")

    def _on_load_server_settings(self, event: Event):
        if self._destroyed or not self.server:
            return
        try:
            body = self._prepare_loaded_settings_body()
            self.server.schedule_broadcast_loaded_settings(body)
        except Exception as e:
            logger.warning(f"LOAD_SERVER_SETTINGS broadcast failed: {e}")

    def _prepare_loaded_settings_body(self) -> Dict[str, Any]:
        settings = {}
        for setting in self.settings_to_send:
            settings[str(setting)] = self._get_setting(setting)
        return {"settings": settings}

    def _get_setting(self, key: str, default=None):
        try:
            result = self.event_bus.emit_and_wait(
                Events.Settings.GET_SETTING,
                {'key': key, 'default': default},
                timeout=1.0
            )
            return result[0] if result else default
        except Exception:
            return default

    # ---------------- moved subscriptions logic ----------------
    def _on_task_status_changed(self, event: Event):
        data = event.data or {}
        task = data.get("task")
        if not task or not getattr(task, "data", None):
            return

        # 1) internal server bookkeeping (idle tracking, last text)
        try:
            if self.server:
                self.server.on_task_status_changed(task)
        except Exception:
            pass

        # 2) echo suppression bookkeeping
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

        # 3) send update to Unity client
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

    # ---------------- GUI echo (unchanged) ----------------
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