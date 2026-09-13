from core.error_utils import format_exception
import io
import json
import os
import wave
import asyncio
from typing import Optional, List
import numpy as np
import requests

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from core.backends import BackendKind
from core.installables.helpers import build_runtime_ctx
from core.install_requirements import InstallRequirement, check_requirements
from utils import getTranslationVariant as _


class NanoGPTRecognizer(SpeechRecognizerInterface):
    """
    Онлайн-распознавание речи через NanoGPT API (Whisper Large V3 и др.).
    Совместимо с OpenAI Audio Transcriptions API.
    Не требует загрузки весов локально.
    """

    MODEL_CONFIGS = [
        {
            "id": "nanogpt",
            "name": "NanoGPT (Whisper Large V3)",
            "languages": ["Multilingual", "Russian", "English"],
            "gpu_vendor": ["CPU"],
            "tags": [
                _("Онлайн", "Online"),
                _("NanoGPT", "NanoGPT"),
                _("Whisper", "Whisper"),
            ],
            "description": _(
                "Онлайн-распознавание речи через NanoGPT API (Whisper Large V3). "
                "Высокая точность и скорость, без скачивания весов модели.",
                "Online speech recognition via NanoGPT API (Whisper Large V3). "
                "High accuracy and speed, no model weights download required.",
            ),
            "links": [
                {"label": "NanoGPT Audio Models", "url": "https://nano-gpt.com/models/audio"},
                {"label": "NanoGPT API", "url": "https://nano-gpt.com/api"},
            ],
        }
    ]

    _DEFAULT_KEY = ""

    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)
        self.api_key = ""
        self.model = "Whisper-Large-V3"
        self.language = "ru"

    def settings_spec(self) -> List[dict]:
        return [
            {
                "key": "api_key",
                "label_ru": "API Ключ (NanoGPT)",
                "label_en": "API Key (NanoGPT)",
                "type": "entry",
                "default": "",
            },
            {
                "key": "model",
                "label_ru": "Модель",
                "label_en": "Model",
                "type": "combobox",
                "options": [
                    "Whisper-Large-V3",
                    "gpt-4o-mini-transcribe",
                    "xai/speech-to-text/v1",
                    "Wizper",
                    "whisper-1",
                    "fun-asr-flash-2026-06-15",
                ],
                "default": "Whisper-Large-V3",
            },
            {
                "key": "language",
                "label_ru": "Язык",
                "label_en": "Language",
                "type": "combobox",
                "options": ["ru", "en", "auto"],
                "default": "ru",
            },
        ]

    def get_default_settings(self) -> dict:
        return {
            "api_key": "",
            "model": "Whisper-Large-V3",
            "language": "ru",
        }

    def apply_settings(self, settings: dict) -> None:
        if not isinstance(settings, dict):
            return
        if "api_key" in settings:
            self.api_key = str(settings.get("api_key") or "").strip()
        if "model" in settings:
            self.model = str(settings.get("model") or "Whisper-Large-V3").strip()
        if "language" in settings:
            self.language = str(settings.get("language") or "ru").strip()

    def _resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key

        try:
            from services.asr_settings_service import ensure_asr_settings_service
            k = str(ensure_asr_settings_service().model_settings("nanogpt").get("api_key") or "").strip()
            if k:
                return k
        except Exception:
            pass

        return find_nanogpt_key_in_api_presets()

    def requirements(self) -> List[InstallRequirement]:
        return []

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        return []

    def required_backend(self, ctx: dict) -> BackendKind:
        return BackendKind.NONE

    def install_manifest(self) -> list[dict]:
        return []

    def is_installed(self, ctx: dict | None = None) -> bool:
        return True

    async def install(self) -> bool:
        return True

    async def init(self, **kwargs) -> bool:
        self._is_initialized = True
        return True

    def cleanup(self) -> None:
        self._is_initialized = False

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized:
            return None
        if audio_data is None or len(audio_data) == 0:
            return None

        return await asyncio.to_thread(self._sync_transcribe, audio_data, sample_rate)

    def _sync_transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        api_key = self._resolve_api_key()
        if not api_key:
            if self.logger:
                self.logger.error("NanoGPT ASR: API-ключ не настроен.")
            return None

        try:
            if audio_data.dtype in (np.float32, np.float64):
                pcm_data = (np.clip(audio_data, -1.0, 1.0) * 32767.0).astype(np.int16)
            else:
                pcm_data = audio_data.astype(np.int16)

            duration_sec = len(pcm_data) / max(1, sample_rate)
            if duration_sec < 0.25:
                return None

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_data.tobytes())
            buf.seek(0)
            wav_bytes = buf.read()
        except Exception as exc:
            if self.logger:
                self.logger.error(f"NanoGPT ASR: ошибка кодирования WAV: {format_exception(exc)}")
            return None

        try:
            resp = request_nanogpt_transcription(
                wav_bytes, api_key=api_key, model=self.model,
                language=self.language, timeout=25.0,
            )
            if resp.status_code != 200:
                if self.logger:
                    self.logger.error(f"NanoGPT ASR HTTP error {resp.status_code}")
                return None

            result = resp.json()
            text = str(result.get("text") or "").strip()

            lowered = text.lower().strip(" .!?,")
            if lowered in (
                "",
                "you",
                "thank you",
                "thanks for watching",
                "продолжение следует",
                "субтитры сделал",
                "субтитры добавил",
                "редактор субтитров",
                "подпишись",
                "подписывайтесь на канал",
            ):
                return None

            return text if text else None
        except Exception as exc:
            if self.logger:
                self.logger.error(f"NanoGPT ASR ошибка запроса: {format_exception(exc)}")
            return None


def request_nanogpt_transcription(wav_bytes: bytes, *, api_key: str,
                                  model: str, language: str, timeout: float = 25.0):
    """One request contract for live recognition and the settings connection test."""
    data = {"model": model or "Whisper-Large-V3"}
    if language and language != "auto":
        data["language"] = language
    return requests.post(
        "https://nano-gpt.com/api/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": ("audio.wav", wav_bytes, "audio/wav")},
        data=data, timeout=timeout, allow_redirects=False,
    )


def find_nanogpt_key_in_api_presets() -> str:
    """Ищет ключ NanoGPT в сохранённых API пресетах (Settings/api_presets.json)."""
    from core.app_paths import settings_path
    from urllib.parse import urlsplit

    env_key = os.environ.get("NANOGPT_API_KEY") or os.environ.get("NANO_GPT_API_KEY")
    if env_key:
        return env_key.strip()
    try:
        with open(settings_path("api_presets.json"), "r", encoding="utf-8") as stream:
            data = json.load(stream)
        presets = data.get("presets", {})
        for preset in presets.values():
            if not isinstance(preset, dict):
                continue
            # A renamed/repurposed template or numeric ID does not identify a
            # credential's owner. Only reuse keys for the actual NanoGPT host.
            endpoint = str(preset.get("url") or "")
            if not endpoint and str(preset.get("base")) == "10001":
                endpoint = "https://nano-gpt.com/api/v1"
            if urlsplit(endpoint).hostname != "nano-gpt.com":
                continue
            key = str(preset.get("key") or "").strip()
            if key:
                return key
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return ""


def load_nanogpt_asr_config() -> dict[str, str]:
    api_key = ""
    model = "Whisper-Large-V3"
    language = "ru"

    try:
        from services.asr_settings_service import ensure_asr_settings_service
        cfg = ensure_asr_settings_service().model_settings("nanogpt")
        if isinstance(cfg, dict):
            api_key = str(cfg.get("api_key") or "").strip()
            model = str(cfg.get("model") or "Whisper-Large-V3").strip()
            language = str(cfg.get("language") or "ru").strip()
    except Exception:
        pass

    if not api_key:
        api_key = find_nanogpt_key_in_api_presets()

    return {
        "api_key": api_key,
        "model": model or "Whisper-Large-V3",
        "language": language or "ru",
    }


def save_nanogpt_asr_config(config: dict[str, str]) -> None:
    clean = {
        "api_key": str(config.get("api_key") or "").strip(),
        "model": str(config.get("model") or "Whisper-Large-V3").strip(),
        "language": str(config.get("language") or "ru").strip(),
    }
    from services.asr_settings_service import ensure_asr_settings_service
    ensure_asr_settings_service().set_model_settings("nanogpt", clean)

    try:
        from handlers.asr_handler import SpeechRecognition
        SpeechRecognition.apply_settings("nanogpt", clean)
    except Exception:
        pass


def is_nanogpt_asr_configured() -> bool:
    cfg = load_nanogpt_asr_config()
    return bool(cfg.get("api_key"))
