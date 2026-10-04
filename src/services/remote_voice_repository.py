from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from core.remote_voice import RemoteCharacterVoice, RemoteVoiceConfiguration, RemoteVoiceError, RemoteVoicePreset


class RemoteVoiceRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RemoteVoiceConfiguration:
        if not self.path.exists():
            preset = RemoteVoicePreset(id="fish_audio_default", name="Fish Audio")
            return RemoteVoiceConfiguration(preset.id, (preset,))
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") not in {1, 2, 3}:
                raise ValueError("unsupported version")
            presets = tuple(self._load_preset(item) for item in data["presets"])
            for preset in presets:
                if not all(isinstance(getattr(preset, key), str) for key in ("id", "name", "template_id", "api_key", "voice_id", "model", "voice_display_name")):
                    raise ValueError("invalid preset field types")
            active_id = data["active_id"]
            ids = [preset.id for preset in presets]
            if not ids or any(not value for value in ids) or len(ids) != len(set(ids)) or active_id not in ids:
                raise ValueError("invalid preset ids")
            return RemoteVoiceConfiguration(active_id, presets)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise RemoteVoiceError("Не удалось прочитать настройки API озвучки.", code="settings.read") from None

    @staticmethod
    def _load_preset(item) -> RemoteVoicePreset:
        values = dict(item)
        voices = tuple(RemoteCharacterVoice(**voice) for voice in values.pop("character_voices", []))
        ids = [voice.character_id for voice in voices]
        if any(not isinstance(voice.character_id, str) or not voice.character_id
               or not isinstance(voice.voice_id, str) or not isinstance(voice.display_name, str) for voice in voices):
            raise ValueError("invalid character voice")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate character voice")
        return RemoteVoicePreset(**values, character_voices=voices)

    def save(self, config: RemoteVoiceConfiguration) -> None:
        name = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".remote-voice-", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump({"version": 3, "active_id": config.active_id, "presets": [asdict(p) for p in config.presets]}, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(name, self.path)
        except OSError:
            raise RemoteVoiceError("Не удалось сохранить настройки API озвучки.", code="settings.write") from None
        finally:
            if name is not None:
                Path(name).unlink(missing_ok=True)
