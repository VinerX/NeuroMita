from dataclasses import dataclass
import re

from core.remote_voice import RemoteVoicePreset
from localization import translate


def remote_voice_message(message: str) -> str:
    match = re.fullmatch(r"Fish Audio: (.+) \(HTTP (\d+)\)\.", message)
    if match:
        reason, status = match.groups()
        return translate("Fish Audio: {reason} (HTTP {status}).").format(reason=translate(reason), status=status)
    match = re.fullmatch(r"Сервер вернул HTTP (\d+|error)\.", message)
    if match:
        return translate("Сервер вернул HTTP {status}.").format(status=match.group(1))
    return translate(message)


@dataclass(frozen=True, slots=True)
class VoiceCharacter:
    character_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class LoadRemoteVoice:
    pass


@dataclass(frozen=True, slots=True)
class SaveRemoteVoice:
    preset: RemoteVoicePreset


@dataclass(frozen=True, slots=True)
class SelectRemoteVoice:
    preset_id: str
    draft: RemoteVoicePreset


@dataclass(frozen=True, slots=True)
class AddRemoteVoice:
    template_id: str
    draft: RemoteVoicePreset


@dataclass(frozen=True, slots=True)
class DeleteRemoteVoice:
    preset_id: str


@dataclass(frozen=True, slots=True)
class PreviewRemoteVoice:
    preset: RemoteVoicePreset
    text: str
    character_id: str | None = None
