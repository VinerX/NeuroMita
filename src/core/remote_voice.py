from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RemoteVoiceTemplate:
    id: str
    name: str
    endpoint: str
    models: tuple[str, ...]
    default_model: str
    voices_url: str
    keys_url: str


@dataclass(frozen=True, slots=True)
class RemoteVoicePreset:
    id: str
    name: str
    template_id: str = "fish_audio"
    api_key: str = field(default="", repr=False)
    voice_id: str = ""
    model: str = "s1"
    speed: float = 1.0


@dataclass(frozen=True, slots=True)
class RemoteVoiceConfiguration:
    active_id: str
    presets: tuple[RemoteVoicePreset, ...]

    @property
    def active(self) -> RemoteVoicePreset:
        return next(preset for preset in self.presets if preset.id == self.active_id)


@dataclass(frozen=True, slots=True)
class RemoteVoiceStatus:
    configured: bool
    verified: bool
    provider_name: str
    model: str


class RemoteVoiceError(RuntimeError):
    def __init__(self, message: str, *, code: str = "remote_voice.error") -> None:
        super().__init__(message)
        self.code = code
