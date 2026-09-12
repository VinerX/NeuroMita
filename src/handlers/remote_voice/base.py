from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from threading import Event

from core.remote_voice import RemoteVoicePreset, RemoteVoiceTemplate


class RemoteVoiceProvider(ABC):
    @abstractmethod
    def normalize(self, preset: RemoteVoicePreset, *, require_ready: bool) -> RemoteVoicePreset: ...

    @abstractmethod
    def synthesize(
        self, text: str, preset: RemoteVoicePreset, template: RemoteVoiceTemplate,
        output_dir: Path, cancelled: Event,
    ) -> str: ...
