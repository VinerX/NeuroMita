from __future__ import annotations

import asyncio
import json
import os
import struct
import tempfile
import uuid
import wave
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp


@dataclass(frozen=True, slots=True)
class ExternalTTSConfig:
    base_url: str
    api_key: str = ""
    voice_id: str = ""
    connect_timeout: float = 5.0
    total_timeout: float = 180.0
    output_dir: str = ""
    max_audio_bytes: int = 32 * 1024 * 1024


class ExternalTTSError(RuntimeError):
    """Safe, user-readable error from the External TTS integration."""


class ExternalTTSConfigError(ExternalTTSError):
    pass


class ExternalTTSConnectionError(ExternalTTSError):
    pass


class ExternalTTSAuthenticationError(ExternalTTSError):
    pass


class ExternalTTSHTTPError(ExternalTTSError):
    pass


class ExternalTTSAudioError(ExternalTTSError):
    pass


class ExternalTTSSizeError(ExternalTTSError):
    pass


class ExternalTTSClient:
    MAX_TEXT_CHARS = 100_000
    MAX_AUDIO_BYTES = 32 * 1024 * 1024
    CHUNK_SIZE = 64 * 1024

    @staticmethod
    def _validate_config(config: ExternalTTSConfig) -> str:
        if not isinstance(config, ExternalTTSConfig):
            raise ExternalTTSConfigError("External TTS configuration is missing.")
        raw_url = str(config.base_url).strip()
        if any(ord(char) <= 0x20 or ord(char) == 0x7F for char in raw_url):
            raise ExternalTTSConfigError("External TTS URL contains invalid whitespace.")
        try:
            parsed = urlsplit(raw_url)
            port = parsed.port
        except ValueError as exc:
            raise ExternalTTSConfigError("External TTS URL or port is invalid.") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in raw_url
            or "#" in raw_url
        ):
            raise ExternalTTSConfigError(
                "External TTS URL must be HTTP/HTTPS without credentials, query, or fragment."
            )
        if port is not None and not 1 <= port <= 65535:
            raise ExternalTTSConfigError("External TTS URL port is invalid.")
        authority = parsed.netloc.rsplit("@", 1)[-1]
        if authority.endswith(":"):
            raise ExternalTTSConfigError("External TTS URL port is invalid.")
        for value in (config.connect_timeout, config.total_timeout):
            if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ExternalTTSConfigError("External TTS timeouts must be positive numbers.")
        if config.connect_timeout > config.total_timeout:
            raise ExternalTTSConfigError("Connect timeout cannot exceed total timeout.")
        if (
            not isinstance(config.max_audio_bytes, int)
            or isinstance(config.max_audio_bytes, bool)
            or not 0 < config.max_audio_bytes <= ExternalTTSClient.MAX_AUDIO_BYTES
        ):
            raise ExternalTTSConfigError("Maximum audio size must be between 1 byte and 32 MiB.")
        if not isinstance(config.api_key, str):
            raise ExternalTTSConfigError("External TTS API key must be text.")
        if "\r" in config.api_key or "\n" in config.api_key:
            raise ExternalTTSConfigError("External TTS API key contains invalid characters.")
        return str(config.base_url).strip().rstrip("/")

    @staticmethod
    def _headers(config: ExternalTTSConfig) -> dict[str, str]:
        key = str(config.api_key or "")
        return {"Authorization": f"Bearer {key}"} if key else {}

    @staticmethod
    def _timeout(config: ExternalTTSConfig) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=float(config.total_timeout),
            connect=float(config.connect_timeout),
        )

    async def health(self, config: ExternalTTSConfig) -> dict:
        base_url = self._validate_config(config)
        try:
            health_timeout = min(15.0, float(config.total_timeout))
            timeout = aiohttp.ClientTimeout(
                total=health_timeout,
                connect=min(float(config.connect_timeout), health_timeout),
            )
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{base_url}/v1/health",
                    headers=self._headers(config),
                    allow_redirects=False,
                ) as response:
                    self._raise_for_status(response.status)
                    content_type = response.content_type.lower()
                    if content_type != "application/json" and not content_type.endswith("+json"):
                        raise ExternalTTSHTTPError("Health endpoint did not return JSON.")
                    if response.content_length is not None and response.content_length > 64 * 1024:
                        raise ExternalTTSHTTPError("Health endpoint response is too large.")
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(8192):
                        if len(body) + len(chunk) > 64 * 1024:
                            raise ExternalTTSHTTPError("Health endpoint response is too large.")
                        body.extend(chunk)
                    try:
                        result = json.loads(body)
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise ExternalTTSHTTPError("Health endpoint returned invalid JSON.") from exc
                    if not isinstance(result, dict) or result.get("status") != "ok":
                        raise ExternalTTSHTTPError("External TTS service is not healthy.")
                    if type(result.get("api_version")) is not int or result["api_version"] != 1:
                        raise ExternalTTSHTTPError("External TTS API version 1 is required.")
                    return result
        except ExternalTTSError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            raise ExternalTTSConnectionError(
                "Could not connect to the External TTS service or the request timed out."
            ) from exc

    async def synthesize(
        self,
        config: ExternalTTSConfig,
        text: str,
        *,
        character_id: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        base_url = self._validate_config(config)
        text = str(text or "")
        if not text.strip():
            raise ExternalTTSConfigError("Text for External TTS cannot be empty.")
        if len(text) > self.MAX_TEXT_CHARS:
            raise ExternalTTSConfigError("Text for External TTS is too long.")

        output_dir = Path(config.output_dir or os.getcwd()).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        request_id = str(uuid.uuid4())
        fd, temporary_path = tempfile.mkstemp(
            prefix=f"external_tts_{request_id}_", suffix=".part", dir=output_dir
        )
        os.close(fd)
        final_path = output_dir / f"external_tts_{request_id}.wav"
        success = False
        try:
            payload = {
                "request_id": request_id,
                "text": text,
                "character_id": str(character_id).strip() if character_id and str(character_id).strip() else None,
                "voice_id": (
                    str(config.voice_id).strip() if voice_id is None else str(voice_id).strip()
                ) or None,
            }
            try:
                async with aiohttp.ClientSession(timeout=self._timeout(config)) as session:
                    async with session.post(
                        f"{base_url}/v1/synthesize",
                        json=payload,
                        headers=self._headers(config),
                        allow_redirects=False,
                    ) as response:
                        self._raise_for_status(response.status)
                        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                        if content_type not in {"audio/wav", "audio/x-wav"}:
                            raise ExternalTTSAudioError("Synthesis endpoint did not return WAV audio.")
                        if response.content_length is not None and response.content_length > config.max_audio_bytes:
                            raise ExternalTTSSizeError("External TTS audio exceeds the configured size limit.")
                        received = 0
                        try:
                            with open(temporary_path, "wb") as audio_file:
                                async for chunk in response.content.iter_chunked(self.CHUNK_SIZE):
                                    received += len(chunk)
                                    if received > config.max_audio_bytes:
                                        raise ExternalTTSSizeError("External TTS audio exceeds the configured size limit.")
                                    audio_file.write(chunk)
                        except ExternalTTSError:
                            raise
                        except OSError as exc:
                            raise ExternalTTSError("Could not save downloaded External TTS audio to disk.") from exc
            except ExternalTTSError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                raise ExternalTTSConnectionError(
                    "Could not connect to the External TTS service or the request timed out."
                ) from exc

            self._validate_wav(temporary_path)
            try:
                os.replace(temporary_path, final_path)
            except OSError as exc:
                raise ExternalTTSError("Could not finalize the downloaded External TTS audio file.") from exc
            success = True
            return str(final_path)
        finally:
            if not success:
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status in {401, 403}:
            raise ExternalTTSAuthenticationError("External TTS authentication was rejected.")
        if status < 200 or status >= 300:
            raise ExternalTTSHTTPError(f"External TTS server returned HTTP {status}.")

    @staticmethod
    def _validate_wav(path: str) -> None:
        try:
            with wave.open(path, "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_rate = wav_file.getframerate()
                sample_width = wav_file.getsampwidth()
                frame_count = wav_file.getnframes()
                if wav_file.getcomptype() != "NONE":
                    raise ExternalTTSAudioError("External TTS must return uncompressed PCM WAV.")
                if channels not in (1, 2):
                    raise ExternalTTSAudioError("External TTS WAV must have one or two channels.")
                if sample_rate < 16_000 or sample_rate > 48_000:
                    raise ExternalTTSAudioError("External TTS WAV sample rate must be 16–48 kHz.")
                if sample_width not in (1, 2, 3, 4):
                    raise ExternalTTSAudioError("External TTS WAV sample format is not supported.")
                if frame_count <= 0:
                    raise ExternalTTSAudioError("External TTS returned an empty WAV.")
                frames = wav_file.readframes(frame_count)
                expected_bytes = frame_count * channels * sample_width
                if len(frames) != expected_bytes:
                    raise ExternalTTSAudioError("External TTS WAV data is incomplete.")
        except ExternalTTSError:
            raise
        except (wave.Error, EOFError, OSError, struct.error) as exc:
            raise ExternalTTSAudioError("External TTS returned an invalid WAV file.") from exc
