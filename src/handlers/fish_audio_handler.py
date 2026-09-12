"""Fish Audio cloud TTS. Credentials stay outside shared/exported settings."""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import wave
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from core.app_paths import base_dir, settings_path

MODELS = ("s2.1-pro", "s2-pro", "s1", "s2.1-pro-free", "drama-3-preview")
ENDPOINT = "https://api.fish.audio/v1/tts"


def voice_id(value: str) -> str:
    value = str(value or "").strip()
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.hostname not in {"fish.audio", "www.fish.audio"}:
            raise ValueError("Нужна ссылка на голос fish.audio или его ID.")
        value = next((p for p in parsed.path.split("/") if re.fullmatch(r"[a-fA-F0-9]{32}", p)), "")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", value):
        raise ValueError("Укажите ID голоса Fish Audio (32 символа) или ссылку на его страницу.")
    return value.lower()


def load_config() -> dict:
    try:
        data = json.loads(settings_path("fish_audio.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as exc:
        raise ValueError("Не удалось прочитать Settings/fish_audio.json.") from exc
    if not isinstance(data, dict):
        raise ValueError("Неверный формат Settings/fish_audio.json.")
    return {"api_key": "", "voice_id": "", "model": "s2.1-pro", "speed": 1.0, **data}


def save_config(config: dict) -> None:
    path = settings_path("fish_audio.json", create_parent=True)
    fd, name = tempfile.mkstemp(prefix=".fish-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(config, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def validate_config(config: dict) -> dict:
    result = dict(config)
    result["api_key"] = str(result.get("api_key") or "").strip()
    if not result["api_key"]:
        raise ValueError("Введите API-ключ Fish Audio в настройках озвучки.")
    result["voice_id"] = voice_id(result.get("voice_id", ""))
    if result.get("model") not in MODELS:
        raise ValueError("Выберите поддерживаемую модель Fish Audio.")
    result["speed"] = float(result.get("speed", 1.0))
    if not 0.5 <= result["speed"] <= 2.0:
        raise ValueError("Скорость должна быть от 0.5 до 2.0.")
    return result


def is_configured() -> bool:
    try:
        validate_config(load_config())
        return True
    except (ValueError, TypeError):
        return False


async def synthesize(text: str, *, config: dict | None = None, output_dir=None, transport=None) -> str:
    config = validate_config(load_config() if config is None else config)
    if not text or not text.strip():
        raise ValueError("Нет текста для озвучки.")
    headers = {"Authorization": "Bearer " + config["api_key"], "model": config["model"]}
    payload = {"text": text, "reference_id": config["voice_id"], "format": "pcm",
               "sample_rate": 44100, "prosody": {"speed": config["speed"]}}
    directory = Path(output_dir) if output_dir is not None else base_dir()
    fd, name = tempfile.mkstemp(prefix="fish_", suffix=".wav", dir=directory)
    os.close(fd)
    try:
        # PCM avoids streaming WAV headers with unknown/incorrect data lengths.
        async with asyncio.timeout(180):
            async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=15), transport=transport,
                                         follow_redirects=False) as client:
                async with client.stream("POST", ENDPOINT, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        messages = {401: "API-ключ не принят", 402: "недостаточно средств или квоты",
                                    403: "нет доступа к голосу или API", 404: "голос не найден",
                                    422: "голос или параметры не поддерживаются выбранной моделью",
                                    429: "лимит запросов, попробуйте позже"}
                        reason = messages.get(response.status_code, "сервис отклонил запрос")
                        raise ValueError(f"Fish Audio: {reason} (HTTP {response.status_code}).")
                    content_type = response.headers.get("content-type", "").lower()
                    if "json" in content_type or "text/" in content_type:
                        raise ValueError("Fish Audio вернул текст вместо аудио.")
                    size = 0
                    with wave.open(name, "wb") as audio:
                        audio.setnchannels(1)
                        audio.setsampwidth(2)
                        audio.setframerate(44100)
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 100 * 1024 * 1024:
                                raise ValueError("Ответ Fish Audio превышает 100 МБ.")
                            audio.writeframesraw(chunk)
                    if size < 2 or size % 2:
                        raise ValueError("Fish Audio вернул пустое или повреждённое аудио.")
        return str(Path(name).resolve())
    except BaseException as exc:
        Path(name).unlink(missing_ok=True)
        if isinstance(exc, (httpx.HTTPError, TimeoutError)):
            raise ValueError("Fish Audio: ошибка сети или превышено время ожидания.") from None
        raise
