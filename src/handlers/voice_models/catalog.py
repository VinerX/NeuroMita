from __future__ import annotations

from typing import Optional, Type, Dict, List


class VoiceModelSpecProtocol:
    @classmethod
    def supported_model_ids(cls) -> List[str]: ...
    @classmethod
    def build_install_plan(cls, model_id: str, ctx: dict): ...
    @classmethod
    def build_uninstall_plan(cls, model_id: str, ctx: dict): ...
    @classmethod
    def is_installed(cls, model_id: str, ctx: dict) -> bool: ...
    @classmethod
    def title(cls, model_id: str) -> str: ...


def _load_specs() -> List[Type[VoiceModelSpecProtocol]]:
    # Единственная точка, где перечисляются спеки (каталог).
    from handlers.voice_models.edge_tts_rvc_model import EdgeTTSRVCInstallSpec
    from handlers.voice_models.fish_speech_model import FishSpeechInstallSpec
    from handlers.voice_models.f5_tts_model import F5TTSInstallSpec

    return [
        EdgeTTSRVCInstallSpec,
        FishSpeechInstallSpec,
        F5TTSInstallSpec,
    ]


_SPECS: List[Type[VoiceModelSpecProtocol]] = _load_specs()

_BY_ID: Dict[str, Type[VoiceModelSpecProtocol]] = {}
for _spec in _SPECS:
    for _mid in (_spec.supported_model_ids() or []):
        _BY_ID[str(_mid)] = _spec


def get_voice_spec(model_id: str) -> Optional[Type[VoiceModelSpecProtocol]]:
    return _BY_ID.get(str(model_id or "").strip())


def get_all_voice_specs() -> List[Type[VoiceModelSpecProtocol]]:
    return list(_SPECS)


def get_supported_model_ids() -> List[str]:
    return list(_BY_ID.keys())