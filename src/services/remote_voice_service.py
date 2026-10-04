from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

import httpx

from core.app_paths import base_dir, settings_path
from core.networking import HttpClientRegistry, shared_http_client_registry
from core.remote_voice import RemoteCharacterVoice, RemoteVoiceConfiguration, RemoteVoiceError, RemoteVoicePreset, RemoteVoiceStatus
from handlers.remote_voice.fish_audio import FishAudioProvider
from main_logger import logger
from presets.remote_voice_templates import REMOTE_VOICE_TEMPLATES, remote_voice_template
from services.contracts import RemoteVoiceService
from services.remote_voice_repository import RemoteVoiceRepository


class DefaultRemoteVoiceService(RemoteVoiceService):
    def __init__(self, *, repository=None, registry: HttpClientRegistry | None = None, output_dir: Path | None = None, client=None) -> None:
        self._repository = repository or RemoteVoiceRepository(settings_path("remote_voice.json"))
        self._output_dir = output_dir or base_dir() / "MitaVoices"
        registry = registry or shared_http_client_registry()
        self._http = registry.acquire("remote_voice.fish_audio", client=client, client_options={"timeout": httpx.Timeout(45, connect=15), "follow_redirects": False})
        self._providers = {"fish_audio": FishAudioProvider(self._http)}
        self._lock = threading.RLock()
        self._config = None
        self._verified: set[RemoteVoicePreset] = set()
        self._requests: set[threading.Event] = set()
        self._closed = False

    def templates(self):
        return REMOTE_VOICE_TEMPLATES

    def configuration(self):
        with self._lock:
            if self._config is None:
                loaded = self._repository.load()
                self._config = replace(loaded, presets=tuple(self._normalize(p) for p in loaded.presets))
            return self._config

    def _normalize(self, preset):
        try:
            template = remote_voice_template(preset.template_id)
        except ValueError:
            raise RemoteVoiceError("Неизвестный провайдер API озвучки.", code="provider.invalid") from None
        name = str(preset.name or "").strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise RemoteVoiceError("Укажите название профиля (до 80 символов).", code="name.invalid")
        if preset.model not in template.models:
            raise RemoteVoiceError("Выберите поддерживаемую модель озвучки.", code="model.invalid")
        provider = self._providers[template.id]
        preset = provider.normalize(replace(preset, name=name, voice_display_name=self._voice_name(preset.voice_display_name)), require_ready=False)
        voices = []
        ids = set()
        for voice in preset.character_voices:
            character_id = voice.character_id
            if not isinstance(character_id, str) or not character_id.strip() or any(ord(c) < 32 for c in character_id) or character_id in ids:
                raise RemoteVoiceError("Некорректное назначение голоса персонажу.", code="character.invalid")
            ids.add(character_id)
            normalized = provider.normalize(replace(preset, voice_id=voice.voice_id), require_ready=False)
            display_name = self._voice_name(voice.display_name)
            if normalized.voice_id or display_name:
                voices.append(RemoteCharacterVoice(character_id, normalized.voice_id, display_name))
        return replace(preset, character_voices=tuple(voices))

    @staticmethod
    def _voice_name(value):
        if not isinstance(value, str) or len(value.strip()) > 80 or any(ord(c) < 32 for c in value):
            raise RemoteVoiceError("Название голоса должно содержать до 80 символов без переносов строк.", code="voice_name.invalid")
        return value.strip()

    def _resolve(self, preset, character_id):
        resolved = replace(preset, voice_id=preset.voice_for(character_id), character_voices=(), voice_display_name="")
        return self._providers[preset.template_id].normalize(resolved, require_ready=True)

    def _ready_voices(self, presets):
        ready = set()
        for preset in presets:
            for character_id in (None, *(v.character_id for v in preset.character_voices)):
                try:
                    ready.add(self._resolve(preset, character_id))
                except RemoteVoiceError:
                    continue
        return ready

    def _store(self, config):
        self._repository.save(config)
        self._config = config
        self._verified.intersection_update(self._ready_voices(config.presets))
        logger.info("[RemoteVoice] Configuration saved; presets=%d; credentials=<redacted>", len(config.presets))
        return config

    def save_preset(self, preset):
        normalized = self._normalize(preset)
        with self._lock:
            config = self.configuration()
            if normalized.id not in {p.id for p in config.presets}:
                raise RemoteVoiceError("Профиль озвучки больше не существует.", code="preset.missing")
            return self._store(replace(config, presets=tuple(normalized if p.id == normalized.id else p for p in config.presets)))

    def select_preset(self, preset_id):
        with self._lock:
            config = self.configuration()
            if preset_id not in {p.id for p in config.presets}:
                raise RemoteVoiceError("Профиль озвучки не найден.", code="preset.missing")
            return self._store(replace(config, active_id=preset_id))

    def add_preset(self, template_id):
        try:
            template = remote_voice_template(template_id)
        except ValueError:
            raise RemoteVoiceError("Неизвестный провайдер API озвучки.", code="provider.invalid") from None
        with self._lock:
            config = self.configuration()
            names = {p.name for p in config.presets}
            name = template.name
            index = 2
            while name in names:
                name = f"{template.name} {index}"
                index += 1
            preset = RemoteVoicePreset(id=uuid.uuid4().hex, name=name, template_id=template.id, model=template.default_model)
            return self._store(RemoteVoiceConfiguration(preset.id, config.presets + (preset,)))

    def delete_preset(self, preset_id):
        with self._lock:
            config = self.configuration()
            remaining = tuple(p for p in config.presets if p.id != preset_id)
            if not remaining:
                raise RemoteVoiceError("Оставьте хотя бы один профиль API озвучки.", code="preset.last")
            active_id = remaining[0].id if config.active_id == preset_id else config.active_id
            return self._store(RemoteVoiceConfiguration(active_id, remaining))

    def status(self, *, character_id=None):
        try:
            if self._closed:
                return RemoteVoiceStatus(False, False, "API", "")
            active = self.configuration().active
            if character_id is not None:
                ready = {self._resolve(active, character_id)}
            else:
                ready = self._ready_voices((active,))
            if not ready:
                return RemoteVoiceStatus(False, False, "API", "")
            preset = next(iter(ready))
            template = remote_voice_template(preset.template_id)
            with self._lock:
                verified = bool(ready.intersection(self._verified))
            return RemoteVoiceStatus(True, verified, template.name, preset.model)
        except RemoteVoiceError:
            return RemoteVoiceStatus(False, False, "API", "")

    def _synthesize(self, text, cancelled, character_id):
        from utils import process_text_to_voice
        if not isinstance(text, str) or not text.strip():
            raise RemoteVoiceError("Введите текст для озвучки.", code="text.empty")
        preset = self._resolve(self.configuration().active, character_id)
        template = remote_voice_template(preset.template_id)
        text = process_text_to_voice(text)
        if not any(char.isalpha() for char in text):
            raise RemoteVoiceError("После подготовки текста не осталось речи для озвучки.", code="text.empty")
        with self._lock:
            if self._closed:
                raise RemoteVoiceError("Сервис API озвучки закрыт.", code="service.closed")
            self._requests.add(cancelled)
        started = time.monotonic()
        logger.info("[RemoteVoice] Synthesis started; provider=%s; model=%s; character=%r; chars=%d; credentials=<redacted>", template.id, preset.model, character_id, len(text))
        try:
            path = self._providers[template.id].synthesize(text, preset, template, self._output_dir, cancelled)
            with self._lock:
                if not cancelled.is_set() and preset in self._ready_voices(self.configuration().presets):
                    self._verified.add(preset)
            logger.info("[RemoteVoice] Synthesis complete; provider=%s; elapsed=%.2fs", template.id, time.monotonic() - started)
            return path
        except RemoteVoiceError as exc:
            with self._lock:
                self._verified.discard(preset)
            logger.warning("[RemoteVoice] Synthesis failed; provider=%s; code=%s; elapsed=%.2fs", template.id, exc.code, time.monotonic() - started)
            raise
        except Exception:
            with self._lock:
                self._verified.discard(preset)
            logger.error("[RemoteVoice] Synthesis failed; provider=%s; code=internal", template.id)
            raise RemoteVoiceError("Не удалось выполнить API озвучку.", code="synthesis.internal") from None
        finally:
            with self._lock:
                self._requests.discard(cancelled)

    async def synthesize(self, text, *, character_id=None):
        cancelled = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(self._synthesize, text, cancelled, character_id))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            def cleanup(done):
                try:
                    Path(done.result()).unlink(missing_ok=True)
                except BaseException:
                    pass
            task.add_done_callback(cleanup)
            raise

    def close(self):
        with self._lock:
            self._closed = True
            for cancelled in self._requests:
                cancelled.set()
        self._http.close()
