from core.error_utils import format_exception
# src/handlers/asr_models/google_recognizer.py
from typing import Optional
import numpy as np

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from handlers.asr_models.asr_languages import asr_language_field, asr_language_names
from core.backends import BackendKind
from core.installables.helpers import build_runtime_ctx
from core.install_requirements import InstallRequirement, check_requirements
from utils import getTranslationVariant as _


class GoogleRecognizer(SpeechRecognizerInterface):
    """
    Pip-установку НЕ делает.
    - pip_install_steps(ctx) отдаёт зависимости адаптера Google и общего ASR-конвейера
    - install() ничего не скачивает (артефактов нет) и возвращает True
    - is_installed() проверяет наличие python-модулей по requirements
    """

    LANGUAGES = dict(zip(asr_language_field("google")["options"], asr_language_names("google")))

    MODEL_CONFIGS = [
        {
            "id": "google",
            "name": "Google",
            "languages": asr_language_names("google"),
            "gpu_vendor": ["CPU"],
            "tags": [
                _("Онлайн", "Online"),
            ],
            "description": _(
                "Онлайн-распознавание через SpeechRecognition (Google Web Speech API). "
                "Без скачивания весов модели, но нужен интернет.",
                "Online recognition via SpeechRecognition (Google Web Speech API). "
                "No model weights download, but internet is required.",
            ),
            "links": [
                {"label": "SpeechRecognition (PyPI)", "url": "https://pypi.org/project/SpeechRecognition/"}
            ],
        }
    ]

    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)
        self._sr = None
        self.language = "ru-RU"

    def settings_spec(self):
        return [
            asr_language_field("google"),
        ]

    def get_default_settings(self):
        return {"language": "ru-RU"}

    def apply_settings(self, settings: dict):
        if "language" in settings:
            result = self.validate_settings({"language": settings["language"]})
            if not result.ok:
                raise ValueError(f"Invalid ASR language: {result.errors}")
        self.language = str(settings.get("language") or "ru-RU").strip() or "ru-RU"

    def requirements(self):
        return [
            InstallRequirement(id="speech_recognition", kind="python_module", module="speech_recognition", required=True),
            InstallRequirement(id="sounddevice", kind="python_module", module="sounddevice", required=True),
            InstallRequirement(id="silero_vad", kind="python_module", module="silero_vad", required=True),
        ]

    def pip_install_steps(self, ctx: dict):
        return [
            {
                "progress": 20,
                "description": _("Установка SpeechRecognition...", "Installing SpeechRecognition..."),
                "packages": ["SpeechRecognition", "sounddevice", "silero-vad"],
                "extra_args": None
            },
        ]

    def required_backend(self, ctx: dict) -> BackendKind:
        return BackendKind.CPU

    def install_manifest(self) -> list[dict]:
        return []

    def is_installed(self, ctx: dict | None = None) -> bool:
        st = check_requirements(self.requirements(), ctx=build_runtime_ctx(ctx))
        return bool(st.get("ok"))

    async def install(self) -> bool:
        return True

    async def init(self, **kwargs) -> bool:
        if not self.is_installed():
            return False
        if self._sr is None:
            try:
                import speech_recognition as sr
                self._sr = sr
            except Exception:
                return False
        self._is_initialized = True
        return True

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized or self._sr is None:
            return None

        recognizer = self._sr.Recognizer()
        audio_data_int16 = (audio_data * 32767).astype(np.int16)

        audio = self._sr.AudioData(
            audio_data_int16.tobytes(),
            sample_rate=sample_rate,
            sample_width=2
        )

        try:
            return recognizer.recognize_google(audio, language=self.language)
        except self._sr.UnknownValueError:
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при распознавании Google: {format_exception(e)}")
            return None

    def cleanup(self) -> None:
        self._sr = None
        self._is_initialized = False
