from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from core.remote_voice import RemoteVoiceConfiguration, RemoteVoiceError, RemoteVoicePreset


class RemoteVoiceRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RemoteVoiceConfiguration:
        if not self.path.exists():
            preset = RemoteVoicePreset(id="fish_audio_default", name="Fish Audio")
            return RemoteVoiceConfiguration(preset.id, (preset,))
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != 1:
                raise ValueError("unsupported version")
            presets = tuple(RemoteVoicePreset(**item) for item in data["presets"])
            for preset in presets:
                if not all(isinstance(getattr(preset, key), str) for key in ("id", "name", "template_id", "api_key", "voice_id", "model")):
                    raise ValueError("invalid preset field types")
            active_id = data["active_id"]
            ids = [preset.id for preset in presets]
            if not ids or any(not value for value in ids) or len(ids) != len(set(ids)) or active_id not in ids:
                raise ValueError("invalid preset ids")
            return RemoteVoiceConfiguration(active_id, presets)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise RemoteVoiceError("Не удалось прочитать настройки API озвучки.", code="settings.read") from None

    def save(self, config: RemoteVoiceConfiguration) -> None:
        name = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".remote-voice-", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump({"version": 1, "active_id": config.active_id, "presets": [asdict(p) for p in config.presets]}, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(name, self.path)
        except OSError:
            raise RemoteVoiceError("Не удалось сохранить настройки API озвучки.", code="settings.write") from None
        finally:
            if name is not None:
                Path(name).unlink(missing_ok=True)
