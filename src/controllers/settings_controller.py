import os
import base64
import json
import re
from typing import Dict, Any

from managers.settings_manager import SettingsManager
from main_logger import logger
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QTimer
from core.events import get_event_bus, Events, Event


class SettingsController:
    def __init__(self, config_path):
        self.config_path = config_path
        self.event_bus = get_event_bus()
        self.settings = SettingsManager(self.config_path)

        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Settings.GET_SETTINGS, self._on_get_settings, weak=False)
        self.event_bus.subscribe(Events.Settings.GET_SETTING, self._on_get_setting, weak=False)
        self.event_bus.subscribe(Events.Settings.SAVE_SETTING, self._on_save_setting, weak=False)
        self.event_bus.subscribe(Events.Settings.GET_APP_VARS, self._on_get_app_vars, weak=False)

    def load_api_settings(self, update_model):
        logger.info("Начинаю загрузку настроек API")

        preset_id = self.settings.get("LAST_API_PRESET_ID", 0)

        try:
            from managers.api_preset_resolver import ApiPresetResolver
            resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)
            ps = resolver.resolve(int(preset_id) if preset_id else None)
        except Exception as e:
            logger.error(f"Не удалось резолвнуть пресет API: {e}", exc_info=True)
            ps = None

        if ps and update_model:
            model_settings = {
                "api_key": ps.api_key,
                "api_key_res": "\n".join([str(k).strip() for k in (ps.reserve_keys or []) if str(k).strip()]),
                "api_url": ps.api_url,
                "api_model": ps.api_model,
                "protocol_id": ps.protocol_id,
                "dialect_id": ps.dialect_id,
                "provider_name": ps.provider_name,
            }
            self.event_bus.emit("model_settings_loaded", model_settings)

        telegram_settings = {
            "api_id": self.settings.get("NM_TELEGRAM_API_ID", ""),
            "api_hash": self.settings.get("NM_TELEGRAM_API_HASH", ""),
            "phone": self.settings.get("NM_TELEGRAM_PHONE", ""),
            "settings": self.settings
        }
        self.event_bus.emit("telegram_settings_loaded", telegram_settings)

        capture_settings = {"settings": self.settings}
        self.event_bus.emit("capture_settings_loaded", capture_settings)

        speech_settings = {"settings": self.settings}
        self.event_bus.emit("speech_settings_loaded", speech_settings)

        logger.info("Настройки API применены")

    def _on_get_settings(self, event: Event):
        return self.settings

    def _on_save_setting(self, event: Event):
        key = event.data.get('key')
        value = event.data.get('value')

        if key:
            self.settings.set(key, value)
            self.settings.save_settings()
            self.update_setting(key, value)

    def _on_get_setting(self, event: Event):
        key = event.data.get('key')
        default = event.data.get('default', None)
        return self.settings.get(key, default)

    def update_setting(self, key, value):
        self.settings.set(key, value)
        self.settings.save_settings()
        self.event_bus.emit(Events.Core.SETTING_CHANGED, {"key": key, "value": value})
        logger.debug(f"Настройка '{key}' успешно применена со значением: {value}")

    def _on_get_app_vars(self, event: Event):
        bool_keys = [
            "ENABLE_CAMERA_CAPTURE",
            "ENABLE_SCREEN_ANALYSIS",
            "MIC_ACTIVE",

            "ENABLE_GAMES",
            "ALLOW_GAMES_WHEN_CONNECTED",
            "ENABLE_GAME_CHESS",
            "ENABLE_GAME_SEABATTLE",

            "REMINDERS_ENABLED",
        ]

        custom_vars: Dict[str, Any] = {
            "app_version": "1.0.0",
        }

        game_connected = False
        try:
            res = self.event_bus.emit_and_wait(Events.Server.GET_GAME_CONNECTION, timeout=0.5)
            if res:
                game_connected = bool(res[0])
        except Exception:
            game_connected = False

        flag_vars: Dict[str, Any] = {
            key: bool(self.settings.get(key, False))
            for key in bool_keys
        }

        flag_vars["GAME_CONNECTED"] = bool(game_connected)

        return {**flag_vars, **custom_vars}