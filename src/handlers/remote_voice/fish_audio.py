from __future__ import annotations

import math
import os
import re
import tempfile
import time
import wave
from dataclasses import replace
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

import httpx

from core.networking import ManagedHttpClient, NetworkRequestError
from core.remote_voice import RemoteVoiceError, RemoteVoicePreset, RemoteVoiceTemplate
from handlers.remote_voice.base import RemoteVoiceProvider


class FishAudioProvider(RemoteVoiceProvider):
    """Fish Audio PCM transport, adapted from pull-request111 by Codekeeper45."""

    MAX_AUDIO_BYTES = 100 * 1024 * 1024
    MAX_DURATION = 180.0
    SAMPLE_RATE = 44100

    def __init__(self, client: ManagedHttpClient) -> None:
        self._client = client

    def normalize(
        self, preset: RemoteVoicePreset, *, require_ready: bool
    ) -> RemoteVoicePreset:
        voice = str(preset.voice_id or "").strip()
        if "://" in voice:
            try:
                parsed = urlsplit(voice)
            except ValueError:
                raise RemoteVoiceError(
                    "Укажите корректную ссылку на голос Fish Audio.",
                    code="voice.invalid",
                ) from None
            if parsed.scheme != "https" or parsed.hostname not in {
                "fish.audio",
                "www.fish.audio",
            }:
                raise RemoteVoiceError(
                    "Укажите ID голоса или HTTPS-ссылку на fish.audio.",
                    code="voice.invalid",
                )
            voice = next(
                (
                    part
                    for part in parsed.path.split("/")
                    if re.fullmatch(r"[a-fA-F0-9]{32}", part)
                ),
                "",
            )
            if not voice:
                raise RemoteVoiceError(
                    "В ссылке не найден ID голоса.", code="voice.invalid"
                )
        if voice and not re.fullmatch(r"[a-fA-F0-9]{32}", voice):
            raise RemoteVoiceError(
                "ID голоса должен содержать 32 шестнадцатеричных символа.",
                code="voice.invalid",
            )
        try:
            speed = float(preset.speed)
        except (TypeError, ValueError):
            raise RemoteVoiceError(
                "Укажите корректную скорость речи.", code="speed.invalid"
            ) from None
        if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
            raise RemoteVoiceError(
                "Скорость речи должна быть от 0.5 до 2.0.", code="speed.invalid"
            )
        key = str(preset.api_key or "").strip()
        if any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise RemoteVoiceError(
                "API-ключ содержит недопустимые символы.", code="key.invalid"
            )
        if require_ready and (not key or not voice):
            raise RemoteVoiceError(
                "Заполните API-ключ и голос в настройках API озвучки.",
                code="configuration.incomplete",
            )
        return replace(preset, api_key=key, voice_id=voice.lower(), speed=speed)

    def synthesize(self, text, preset, template, output_dir, cancelled) -> str:
        if cancelled.is_set():
            raise RemoteVoiceError("Синтез отменён.", code="synthesis.cancelled")
        output_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix="remote_voice_", suffix=".wav", dir=output_dir
        )
        os.close(fd)
        started = time.monotonic()
        payload = {
            "text": text,
            "reference_id": preset.voice_id,
            "format": "pcm",
            "sample_rate": self.SAMPLE_RATE,
            "prosody": {"speed": preset.speed, "normalize_loudness": True},
        }
        try:
            with self._client.stream(
                "POST",
                template.endpoint,
                headers={
                    "Authorization": "Bearer " + preset.api_key,
                    "model": preset.model,
                },
                json=payload,
                timeout=httpx.Timeout(45.0, connect=15.0),
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    reasons = {
                        401: "API-ключ не принят",
                        402: "недостаточно средств или квоты",
                        403: "нет доступа к голосу или API",
                        404: "голос не найден",
                        422: "голос или параметры не поддерживаются выбранной моделью",
                        429: "превышен лимит запросов",
                    }
                    reason = reasons.get(response.status_code, "сервис отклонил запрос")
                    raise RemoteVoiceError(
                        f"Fish Audio: {reason} (HTTP {response.status_code}).",
                        code=f"http.{response.status_code}",
                    )
                content_type = response.headers.get("content-type", "").lower()
                if "json" in content_type or "text/" in content_type:
                    raise RemoteVoiceError(
                        "Fish Audio вернул текст вместо аудио.", code="audio.invalid"
                    )
                size = 0
                pending = bytearray()
                with wave.open(name, "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(self.SAMPLE_RATE)
                    for chunk in response.iter_bytes():
                        if cancelled.is_set():
                            raise RemoteVoiceError(
                                "Синтез отменён.", code="synthesis.cancelled"
                            )
                        if time.monotonic() - started > self.MAX_DURATION:
                            raise RemoteVoiceError(
                                "Превышено время ожидания озвучки.",
                                code="synthesis.timeout",
                            )
                        size += len(chunk)
                        if size > self.MAX_AUDIO_BYTES:
                            raise RemoteVoiceError(
                                "Ответ Fish Audio превышает 100 МБ.",
                                code="audio.too_large",
                            )
                        pending.extend(chunk)
                        even_length = len(pending) - len(pending) % 2
                        if even_length:
                            audio.writeframesraw(pending[:even_length])
                            del pending[:even_length]
                    if not size or pending:
                        raise RemoteVoiceError(
                            "Fish Audio вернул пустое или повреждённое PCM аудио.",
                            code="audio.invalid",
                        )
            if cancelled.is_set():
                raise RemoteVoiceError("Синтез отменён.", code="synthesis.cancelled")
            return str(Path(name).resolve())
        except BaseException as exc:
            Path(name).unlink(missing_ok=True)
            if isinstance(exc, NetworkRequestError):
                raise RemoteVoiceError(exc.message, code=exc.code) from None
            if isinstance(exc, RemoteVoiceError):
                raise
            if isinstance(exc, (httpx.HTTPError, OSError, ValueError)):
                raise RemoteVoiceError(
                    "Не удалось получить или сохранить аудио Fish Audio.",
                    code="synthesis.failed",
                ) from None
            raise
