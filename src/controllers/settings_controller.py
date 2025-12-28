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

        if self.settings.get("GAME_CONNECTED") is None:
            self.settings.set("GAME_CONNECTED", False)
            self.settings.save_settings()
            logger.info("Инициализирован флаг GAME_CONNECTED = False")

        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Settings.GET_SETTINGS, self._on_get_settings, weak=False)
        self.event_bus.subscribe(Events.Settings.GET_SETTING, self._on_get_setting, weak=False)
        self.event_bus.subscribe(Events.Settings.SAVE_SETTING, self._on_save_setting, weak=False)
        self.event_bus.subscribe(Events.Settings.GET_APP_VARS, self._on_get_app_vars, weak=False)

    def load_api_settings(self, update_model):
        logger.info("Начинаю загрузку настроек API")

        preset_id = self.settings.get("LAST_API_PRESET_ID", 0)

        preset = None
        if preset_id:
            preset_res = self.event_bus.emit_and_wait(
                Events.ApiPresets.GET_PRESET_FULL,
                {'id': preset_id},
                timeout=1.0
            )
            preset = preset_res[0] if preset_res and preset_res[0] else None

        state = {}
        if preset_id:
            state_res = self.event_bus.emit_and_wait(
                Events.ApiPresets.LOAD_PRESET_STATE,
                {'id': preset_id},
                timeout=1.0
            )
            state = state_res[0] if state_res and state_res[0] else {}

        def _compute_effective_url(p: dict, model: str, key: str) -> str:
            url_tpl = p.get('url_tpl') or ''
            add_key = bool(p.get('add_key', False))
            url = ""

            if url_tpl:
                if '{model}' in url_tpl:
                    url = url_tpl.format(model=model)
                else:
                    url = url_tpl
            else:
                url = p.get('url', '') or ''

            if add_key and key:
                if "key=" not in url:
                    sep = "&" if "?" in url else "?"
                    url = f"{url}{sep}key={key}"
                else:
                    url = re.sub(r"key=[^&]*", f"key={key}", url)

            return url

        if preset and update_model:
            api_key = str(state.get("key") or preset.get("key") or "")
            api_model = str(state.get("model") or preset.get("default_model") or "")
            reserve_keys = state.get("reserve_keys", preset.get("reserve_keys", []))
            if not isinstance(reserve_keys, list):
                reserve_keys = []

            api_url = _compute_effective_url(preset, api_model, api_key)

            model_settings = {
                'api_key': api_key,
                'api_key_res': "\n".join([str(k).strip() for k in reserve_keys if str(k).strip()]),
                'api_url': api_url,
                'api_model': api_model,
                'makeRequest': bool(preset.get('use_request', False)),
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
            "GAME_CONNECTED",
        ]

        custom_vars: Dict[str, Any] = {
            "app_version": "1.0.0",
        }

        flag_vars: Dict[str, Any] = {
            key: bool(self.settings.get(key, False))
            for key in bool_keys
        }

        return {**flag_vars, **custom_vars}