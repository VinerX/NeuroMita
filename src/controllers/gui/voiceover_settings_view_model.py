from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from controllers.gui.intent_view_model import IntentViewModel
from controllers.gui.presentation_contracts import UiTopic
from ui.settings.voiceover_settings.presentation import (
    OpenAIEngineSettings,
    OpenVoiceAIHub,
    RestartVoiceService,
    StartTelegramVoice,
)


@dataclass(frozen=True, slots=True)
class _VoiceoverActionsState:
    revision: int = 0


class VoiceoverSettingsViewModel(IntentViewModel[_VoiceoverActionsState]):
    def __init__(
        self,
        *,
        events,
        open_settings: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(_VoiceoverActionsState(), parent)
        self._events = events
        self._open_settings = open_settings

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, StartTelegramVoice):
            self._events.publish(
                UiTopic.TELEGRAM_START_SILERO,
                {"source": "ui", "force": True},
            )
            return
        if isinstance(intent, RestartVoiceService):
            self._events.publish(
                UiTopic.AI_RESTART_SERVICE,
                {"service": "tts"},
            )
            return
        if isinstance(intent, OpenVoiceAIHub):
            payload = {"category": "tts"}
            model_id = str(intent.model_id or "").strip()
            if model_id:
                payload["component_id"] = f"tts:{model_id}"
            self._events.publish(
                UiTopic.GUI_SHOW_WINDOW,
                {"window_id": "ai_hub", "payload": payload},
            )
            return
        if isinstance(intent, OpenAIEngineSettings):
            if self._open_settings is not None:
                self._open_settings("ai_engine")
