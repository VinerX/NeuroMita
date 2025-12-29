# src/handlers/asr_models/speech_recognizer_base.py
from abc import ABC, abstractmethod
from typing import Optional, List
import numpy as np

from handlers.asr_models.requirements import AsrRequirement


class SpeechRecognizerInterface(ABC):
    MODEL_CONFIGS: List[dict] = []

    def get_model_configs(self) -> List[dict]:
        return list(getattr(self, "MODEL_CONFIGS", []) or [])

    def __init__(self, pip_installer, logger):
        self.pip_installer = pip_installer
        self.logger = logger
        self._is_initialized = False

    @abstractmethod
    async def install(self) -> bool:
        """Только артефакты/веса/подготовка. Pip-установка должна быть вынесена наружу."""
        pass

    @abstractmethod
    async def init(self, **kwargs) -> bool:
        pass

    @abstractmethod
    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        pass

    @abstractmethod
    async def live_recognition(self, microphone_index: int, handle_voice_callback,
                               vad_model, active_flag, **kwargs) -> None:
        pass

    @abstractmethod
    def cleanup(self) -> None:
        pass

    @abstractmethod
    def is_installed(self) -> bool:
        pass

    def requirements(self) -> List[AsrRequirement]:
        return []

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        return []

    def settings_spec(self) -> List[dict]:
        return []

    def get_default_settings(self) -> dict:
        return {}

    def apply_settings(self, settings: dict) -> None:
        return

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized