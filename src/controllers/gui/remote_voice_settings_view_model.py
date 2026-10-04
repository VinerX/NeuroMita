from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from controllers.gui.intent_view_model import IntentViewModel
from core.remote_voice import RemoteVoiceConfiguration, RemoteVoiceError
from main_logger import logger
from ui.settings.voiceover_settings.remote_presentation import (
    LoadRemoteVoice, SaveRemoteVoice, SelectRemoteVoice, AddRemoteVoice,
    DeleteRemoteVoice, PreviewRemoteVoice,
)


@dataclass(frozen=True, slots=True)
class RemoteVoiceSettingsState:
    configuration: RemoteVoiceConfiguration | None = None
    busy: bool = False
    message: str = ""
    error: bool = False


class RemoteVoiceSettingsViewModel(IntentViewModel[RemoteVoiceSettingsState]):
    def __init__(self, service, parent=None, *, playback_state=None, playback_volume=None):
        super().__init__(RemoteVoiceSettingsState(), parent)
        self._service = service
        self.templates = service.templates()
        self._playback_state = playback_state or (lambda _active: None)
        self._playback_volume = playback_volume or (lambda: 100)

    def dispatch(self, intent):
        if not isinstance(intent, (LoadRemoteVoice, SaveRemoteVoice, SelectRemoteVoice, AddRemoteVoice, DeleteRemoteVoice, PreviewRemoteVoice)):
            return
        operation = type(intent).__name__
        if self.state.busy or self.is_closed:
            return
        self.update_state(busy=True, message="", error=False)

        def work():
            try:
                if isinstance(intent, SaveRemoteVoice):
                    self._service.save_preset(intent.preset)
                elif isinstance(intent, SelectRemoteVoice):
                    self._service.save_preset(intent.draft)
                    self._service.select_preset(intent.preset_id)
                elif isinstance(intent, AddRemoteVoice):
                    self._service.save_preset(intent.draft)
                    self._service.add_preset(intent.template_id)
                elif isinstance(intent, DeleteRemoteVoice):
                    self._service.delete_preset(intent.preset_id)
                elif isinstance(intent, PreviewRemoteVoice):
                    self._service.save_preset(intent.preset)
                    asyncio.run(self._preview(intent.text))
                config = self._service.configuration()
                message = "Профиль сохранён." if isinstance(intent, SaveRemoteVoice) else ""
                if isinstance(intent, PreviewRemoteVoice):
                    message = "Проверка пройдена. Озвучка воспроизведена."
                return config, message, False
            except RemoteVoiceError as exc:
                logger.warning("[RemoteVoice/UI] Operation failed; operation=%s; code=%s", operation, exc.code)
                return None, str(exc), True
            except Exception:
                logger.error("[RemoteVoice/UI] Operation failed; operation=%s", operation)
                return None, "Не удалось выполнить действие. Проверьте настройки API озвучки.", True

        def apply(result):
            config, message, error = result
            self.update_state(configuration=config or self.state.configuration, busy=False, message=message, error=error)

        self.run_exclusive("remote_voice_settings", work, apply,
                           lambda _exc: self.update_state(busy=False, message="Не удалось запустить действие.", error=True))

    async def _preview(self, text):
        from handlers.audio_handler import AudioHandler
        path = await self._service.synthesize(text)
        try:
            if not self.is_closed:
                try:
                    volume = max(0, min(200, int(self._playback_volume())))
                except (ValueError, TypeError):
                    volume = 100
                self._playback_state(True)
                try:
                    await AudioHandler.handle_voice_file(path, delete=False, volume=volume, raise_errors=True)
                finally:
                    self._playback_state(False)
        finally:
            Path(path).unlink(missing_ok=True)
