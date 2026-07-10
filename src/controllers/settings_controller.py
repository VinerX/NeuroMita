import os
import base64
import json
import re
from typing import Dict, Any

from managers.settings_manager import SettingsManager
from main_logger import logger
from core.events import get_event_bus, Events, Event
from core.services import services
from services.contracts import SettingsService
from services.settings_service import SettingsManagerService


class SettingsController:
    """Владелец SettingsManager. Регистрирует SettingsService."""

    def __init__(self, config_path):
        self.config_path = config_path
        self.event_bus = get_event_bus()
        self.settings = SettingsManager(self.config_path)

        self.settings_service = services().register(
            SettingsService, SettingsManagerService(self.settings), replace=True
        )

        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Settings.SAVE_SETTING, self._on_save_setting, weak=False)

    def load_api_settings(self, update_model: bool = True):
        """Compatibility bridge for the model preset only.

        Local settings consumers read SettingsService directly. Telegram,
        capture and speech controllers initialize from a registry snapshot and
        therefore must not depend on a broadcast emitted during startup.
        """
        if not update_model:
            return None

        logger.info("Applying API preset to model runtime")
        preset_id = self.settings.get("LAST_API_PRESET_ID", 0)

        try:
            from managers.api_preset_resolver import ApiPresetResolver

            resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)
            preset = resolver.resolve(int(preset_id) if preset_id else None)
        except Exception as exc:
            logger.error(f"Failed to resolve API preset: {exc}", exc_info=True)
            return None

        if preset is None:
            return None

        model_settings = {
            "api_key": preset.api_key,
            "api_key_res": "\n".join(
                str(key).strip()
                for key in (preset.reserve_keys or [])
                if str(key).strip()
            ),
            "api_url": preset.api_url,
            "api_model": preset.api_model,
            "protocol_id": preset.protocol_id,
            "dialect_id": preset.dialect_id,
            "provider_name": preset.provider_name,
        }
        self.event_bus.emit("model_settings_loaded", model_settings)
        return model_settings

    def _on_save_setting(self, event: Event):
        key = event.data.get('key')
        value = event.data.get('value')

        if key:
            self.update_setting(key, value)

    def update_setting(self, key, value):
        self.settings_service.update(key, value)
        logger.debug(f"Setting '{key}' applied with value: {value}")

    def close(self) -> None:
        return None




