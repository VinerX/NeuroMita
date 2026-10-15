from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.remote_voice import RemoteVoiceError


class VoiceFailureCode(str, Enum):
    MODEL_NOT_INITIALIZED = "voice.model_not_initialized"
    RUNTIME_UNAVAILABLE = "voice.runtime_unavailable"
    CONFIGURATION = "voice.configuration"
    TIMEOUT = "voice.timeout"
    AUTHENTICATION = "voice.authentication"
    RATE_LIMITED = "voice.rate_limited"
    PROVIDER_UNAVAILABLE = "voice.provider_unavailable"
    SYNTHESIS_FAILED = "voice.synthesis_failed"


_SHORT_MESSAGES = {
    VoiceFailureCode.MODEL_NOT_INITIALIZED: "Initialize the voice model in NeuroMita settings.",
    VoiceFailureCode.RUNTIME_UNAVAILABLE: "The voice runtime is not ready.",
    VoiceFailureCode.CONFIGURATION: "Check the voice settings in NeuroMita.",
    VoiceFailureCode.TIMEOUT: "Voice generation timed out.",
    VoiceFailureCode.AUTHENTICATION: "Check the voice API key.",
    VoiceFailureCode.RATE_LIMITED: "The voice provider limit was reached.",
    VoiceFailureCode.PROVIDER_UNAVAILABLE: "The voice provider is unavailable.",
    VoiceFailureCode.SYNTHESIS_FAILED: "Voice generation failed. See NeuroMita logs.",
}


@dataclass(frozen=True, slots=True)
class VoiceFailure:
    code: VoiceFailureCode
    model_id: str = ""

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "domain": "voice",
            "code": self.code.value,
            "model_id": self.model_id,
            "short_message": _SHORT_MESSAGES[self.code],
        }


class VoiceSynthesisError(RuntimeError):
    def __init__(self, message: str, *, code: VoiceFailureCode, model_id: str = ""):
        super().__init__(message)
        self.failure = VoiceFailure(code, model_id)


def classify_voice_failure(error: BaseException | str | VoiceFailure) -> VoiceFailure:
    if isinstance(error, VoiceFailure):
        return error
    if isinstance(error, VoiceSynthesisError):
        return error.failure
    if isinstance(error, TimeoutError):
        return VoiceFailure(VoiceFailureCode.TIMEOUT)
    if isinstance(error, RemoteVoiceError):
        code = error.code
        if code in {"http.401", "http.403"}:
            return VoiceFailure(VoiceFailureCode.AUTHENTICATION)
        if code == "http.429":
            return VoiceFailure(VoiceFailureCode.RATE_LIMITED)
        if "timeout" in code:
            return VoiceFailure(VoiceFailureCode.TIMEOUT)
        if code.startswith("http.5") or "connection" in code:
            return VoiceFailure(VoiceFailureCode.PROVIDER_UNAVAILABLE)
        if "config" in code:
            return VoiceFailure(VoiceFailureCode.CONFIGURATION)
    return VoiceFailure(VoiceFailureCode.SYNTHESIS_FAILED)
