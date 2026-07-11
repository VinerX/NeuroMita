from __future__ import annotations

from core.events import Event, Events, get_event_bus


class GuiFallbackController:
    """Stable fallback answers for GUI-only startup mode."""

    _VOICE_MODEL_FALLBACK_DESCRIPTION = (
        "GUI-only mode is active. Backend voice services are not started."
    )

    def __init__(self, settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        eb = self.event_bus

        # Чтение персонажей идёт через SettingsOnlyCharacterRegistry (MainController).
        eb.subscribe(Events.Character.SET_CURRENT, self._on_set_current_character, weak=False)

        eb.subscribe(Events.ApiPresets.SET_CURRENT_PRESET_ID, self._on_set_current_preset_id, weak=False)

        eb.subscribe(Events.Model.CALCULATE_COST, self._on_get_empty_dict, weak=False)
        eb.subscribe(Events.Model.SCHEDULE_G4F_UPDATE, self._on_schedule_update, weak=False)

        eb.subscribe(Events.Server.STOP_SERVER, self._on_noop_true, weak=False)
        eb.subscribe(Events.Telegram.START_SILERO, self._on_noop_true, weak=False)
        eb.subscribe(Events.Telegram.STOP_SILERO, self._on_noop_true, weak=False)

        eb.subscribe(Events.Capture.CAPTURE_SCREEN, self._on_get_empty_list, weak=False)
        eb.subscribe(Events.Capture.STOP_SCREEN_CAPTURE, self._on_noop_true, weak=False)
        eb.subscribe(Events.Capture.STOP_CAMERA_CAPTURE, self._on_noop_true, weak=False)


        eb.subscribe(Events.Audio.CHECK_MODEL_INITIALIZED, self._on_noop_false, weak=False)
        eb.subscribe(Events.Audio.SELECT_VOICE_MODEL, self._on_noop_false, weak=False)
        eb.subscribe(Events.Audio.INIT_VOICE_MODEL, self._on_noop_false, weak=False)
        eb.subscribe(Events.Audio.DELETE_SOUND_FILES, self._on_noop_true, weak=False)

        eb.subscribe(Events.Chat.SEND_MESSAGE, self._on_chat_send_message, weak=False)
        eb.subscribe(Events.Chat.CLEAR_CHAT, self._on_noop_true, weak=False)
        eb.subscribe(Events.Chat.STAGE_IMAGE, self._on_noop_true, weak=False)
        eb.subscribe(Events.Chat.CLEAR_STAGED_IMAGES, self._on_noop_true, weak=False)

    def _on_get_current_preset_id(self, _event: Event):
        return self.settings.get("LAST_API_PRESET_ID", 0) if self.settings else 0

    def _on_set_current_preset_id(self, event: Event):
        if not self.settings:
            return False
        data = event.data or {}
        preset_id = data.get("id")
        if preset_id is None:
            return False
        self.settings.set("LAST_API_PRESET_ID", int(preset_id))
        self.settings.save_settings()
        return True

    def _on_get_debug_info(self, _event: Event):
        return "GUI-only mode: backend controllers are disabled."

    def _on_get_token_stats(self, _event: Event):
        return {}

    def _on_get_zero(self, _event: Event):
        return 0

    def _on_get_empty_dict(self, _event: Event):
        return {}

    def _on_get_empty_list(self, _event: Event):
        return []

    def _on_get_voice_model_description(self, _event: Event):
        return self._VOICE_MODEL_FALLBACK_DESCRIPTION

    def _on_schedule_update(self, _event: Event):
        self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
            "title": "GUI-only mode",
            "message": "Update scheduling is disabled because backend controllers are not started.",
        })
        return False

    def _on_chat_send_message(self, _event: Event):
        self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
            "title": "GUI-only mode",
            "message": "Message processing is unavailable because backend controllers are disabled.",
        })
        return False

    def _on_set_current_character(self, event: Event):
        if not self.settings:
            return False
        data = event.data or {}
        character_id = str(data.get("character_id") or "").strip()
        if not character_id:
            return False
        self.settings.set("CHARACTER", character_id)
        self.settings.save_settings()
        self.event_bus.emit(Events.Character.CURRENT_CHANGED, {
            "character_id": character_id,
            "character_name": character_id,
        })
        return True

    def _current_character_id(self) -> str:
        if not self.settings:
            return ""
        return str(self.settings.get("CHARACTER", "") or "").strip()

    def _on_noop_true(self, _event: Event):
        return True

    def _on_noop_false(self, _event: Event):
        return False
