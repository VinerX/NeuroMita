from __future__ import annotations

import threading

from core.app_paths import settings_dir
from main_logger import logger

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
    CLEANUP_INTERVAL_SECONDS = 60 * 60

    def __init__(self, settings):
        self._settings = settings
        self._client = ExternalTTSClient()
        self._cleanup_stop = threading.Event()
        self._output_dirs_lock = threading.Lock()
        self._output_dirs: set[str] = set()
        self._remember_output_dir(external_config_from_settings(settings).output_dir)
        self._cleanup_once()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="external-tts-output-cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def _remember_output_dir(self, path: str) -> None:
        if path:
            with self._output_dirs_lock:
                self._output_dirs.add(str(path))

    def _cleanup_once(self) -> None:
        config = external_config_from_settings(self._settings)
        self._remember_output_dir(config.output_dir)
        with self._output_dirs_lock:
            output_dirs = tuple(self._output_dirs)
        for output_dir in output_dirs:
            self._client.cleanup_outputs(output_dir)

    def _cleanup_loop(self) -> None:
        while not self._cleanup_stop.wait(self.CLEANUP_INTERVAL_SECONDS):
            try:
                self._cleanup_once()
            except Exception as exc:
                logger.warning(f"External TTS output cleanup failed: {type(exc).__name__}")

    def close(self) -> None:
        self._cleanup_stop.set()
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2.0)

    def configuration_snapshot(self) -> ExternalTTSConfig:
        config = external_config_from_settings(self._settings)
        self._remember_output_dir(config.output_dir)
        return config

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
