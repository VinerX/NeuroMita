from __future__ import annotations

from core.app_paths import settings_dir

from services.contracts import ExternalVoiceService
from services.external_tts_service import ExternalTTSClient, ExternalTTSConfig


def external_config_from_settings(settings) -> ExternalTTSConfig:
    try:
        total_timeout = float(settings.get("EXTERNAL_TTS_TIMEOUT", 180) or 180)
    except (TypeError, ValueError):
        total_timeout = 180.0
    return ExternalTTSConfig(
        base_url=str(settings.get("EXTERNAL_TTS_BASE_URL", "") or "").strip(),
        api_key=str(settings.get("EXTERNAL_TTS_API_KEY", "") or ""),
        voice_id=str(settings.get("EXTERNAL_TTS_VOICE_ID", "") or "").strip(),
        connect_timeout=min(5.0, total_timeout),
        total_timeout=total_timeout,
        output_dir=str(settings.get("EXTERNAL_TTS_OUTPUT_DIR", "") or settings_dir() / "ExternalTTS"),
    )


class ExternalVoiceController(ExternalVoiceService):
    def __init__(self, settings):
        self._settings = settings
        self._client = ExternalTTSClient()

    def configuration_snapshot(self) -> ExternalTTSConfig:
        return external_config_from_settings(self._settings)

    async def health(self, config_snapshot: ExternalTTSConfig | None = None) -> dict:
        config = config_snapshot or self.configuration_snapshot()
        return await self._client.health(config)

    async def synthesize(
        self,
        text: str,
        *,
        character_id: str | None = None,
        voice_id: str | None = None,
        config_snapshot: ExternalTTSConfig | None = None,
    ) -> str:
        config = config_snapshot or self.configuration_snapshot()
        return await self._client.synthesize(
            config,
            text,
            character_id=character_id,
            voice_id=voice_id,
        )
