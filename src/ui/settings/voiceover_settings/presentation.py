from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiIntent


@dataclass(frozen=True, slots=True)
class StartTelegramVoice(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class OpenVoiceAIHub(UiIntent):
    model_id: str | None = None


@dataclass(frozen=True, slots=True)
class OpenAIEngineSettings(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class RestartVoiceService(UiIntent):
    pass
