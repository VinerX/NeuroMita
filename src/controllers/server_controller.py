# File: src/controllers/server_controller.py
from typing import Dict, Any
from main_logger import logger
from core.events import get_event_bus, Events, Event


class ServerController:
    def __init__(self):
        self.event_bus = get_event_bus()
        self.server = None
        self.running = False
        self.ConnectedToGame = False
        self._destroyed = False

        self.settings_to_send = ['ACTION_MENU', 'MITAS_MENU', 'IGNORE_GAME_REQUESTS', 'GAME_BLOCK_LEVEL','CHARACTER']

        self._subscribe_to_events()
        self._init_server()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Server.STOP_SERVER, self._on_stop_server, weak=False)
        self.event_bus.subscribe(Events.Server.GET_CHAT_SERVER, self._on_get_chat_server, weak=False)
        self.event_bus.subscribe(Events.Server.SET_GAME_CONNECTION, self._on_update_game_connection, weak=False)
        self.event_bus.subscribe(Events.Server.GET_GAME_CONNECTION, self._on_get_connection_status, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)
        self.event_bus.subscribe(Events.Server.LOAD_SERVER_SETTINGS, self._on_load_server_settings, weak=False)

    def _unsubscribe_from_events(self):
        if self.event_bus and not self._destroyed:
            self.event_bus.unsubscribe(Events.Server.STOP_SERVER, self._on_stop_server)
            self.event_bus.unsubscribe(Events.Server.GET_CHAT_SERVER, self._on_get_chat_server)
            self.event_bus.unsubscribe(Events.Server.SET_GAME_CONNECTION, self._on_update_game_connection)
            self.event_bus.unsubscribe(Events.Server.GET_GAME_CONNECTION, self._on_get_connection_status)
            self.event_bus.unsubscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed)
            self.event_bus.unsubscribe(Events.Server.LOAD_SERVER_SETTINGS, self._on_load_server_settings)

    def _init_server(self):
        from game_connections.server import ChatServerNew
        self.server = ChatServerNew()
        logger.info("Используется новый API сервер")
        self._apply_initial_settings()
        self.start_server()

    def _apply_initial_settings(self):
        # Применяем рантайм-флаги на сервер для блокировок
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
        self.ConnectedToGame = is_connected
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
        
        self.event_bus.emit(Events.Settings.SAVE_SETTING, {
            'key': 'GAME_CONNECTED', 
            'value': is_connected
        })

    def _on_update_game_connection(self, event: Event):
        if self._destroyed:
            return
        is_connected = event.data.get('is_connected', False)
        self.update_game_connection(is_connected)

    def _on_get_connection_status(self, event: Event):
        if self._destroyed:
            return None
        return self.ConnectedToGame

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

        key = event.data.get('key')
        value = event.data.get('value')

        # Рантайм-флаги для логики блокировок
        if key == 'IGNORE_GAME_REQUESTS':
            self.server.set_ignore_game_requests(bool(value))
        elif key == 'GAME_BLOCK_LEVEL':
            self.server.set_game_block_level(str(value))
        elif key == 'GM_VOICE':
            self.server.set_game_master_voice(bool(value))

        if key in self.settings_to_send:
            try:
                body = self._prepare_loaded_settings_body()
                self.server.broadcast_loaded_settings(body)
            except Exception as e:
                logger.warning(f"Не удалось отправить обновлённые настройки клиентам ({key}): {e}")

    def _on_load_server_settings(self, event: Event):
        if self._destroyed or not self.server:
            return
        try:
            body = self._prepare_loaded_settings_body()
            self.server.broadcast_loaded_settings(body)
        except Exception as e:
            logger.warning(f"LOAD_SERVER_SETTINGS broadcast failed: {e}")

    def _prepare_loaded_settings_body(self) -> Dict[str, Any]:
        settings = {}
        for setting in self.settings_to_send:
            settings[str(setting)] = self._get_setting(setting)

        return {
            "settings": settings
        }

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