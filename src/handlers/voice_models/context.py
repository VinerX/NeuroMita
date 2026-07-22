from __future__ import annotations

from typing import Any, Protocol


class VoiceRuntimeContext(Protocol):
    current_model_id: str
    current_character: Any
    current_character_name: str
    provider: Any
    first_compiled: bool
    clone_voice_filename: str
    clone_voice_text: str
    index_path: str
    pth_path: str
    voice_language: str

    def load_model_settings(self, model_id: str) -> dict[str, Any]: ...

    def convert_wav_to_stereo(self, source_path: str, target_path: str | None = None): ...


__all__ = ["VoiceRuntimeContext"]
