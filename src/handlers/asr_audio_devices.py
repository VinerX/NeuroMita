"""Compatibility entry points for existing ASR callers."""

from domain.audio_input import ASRInputDevice, MicrophoneSelection
from infrastructure.audio.portaudio_catalog import (
    ASR_CAPTURE_SAMPLE_RATE,
    normalize_device_name,
    portaudio_stream_scope,
    refresh_portaudio_catalog,
    read_portaudio_catalog,
)
from services.microphone_selection import resolve_microphone


def list_asr_input_devices(
    sounddevice, *, sample_rate=ASR_CAPTURE_SAMPLE_RATE, refresh=False
):
    return list(
        read_portaudio_catalog(
            sounddevice, sample_rate=sample_rate, refresh=refresh
        ).devices
    )


def resolve_asr_input_device(
    sounddevice,
    *,
    requested_index=None,
    requested_name=None,
    requested_uid=None,
    requested_backend="",
    sample_rate=ASR_CAPTURE_SAMPLE_RATE,
    refresh=False
):
    catalog = read_portaudio_catalog(
        sounddevice, sample_rate=sample_rate, refresh=refresh
    )
    return resolve_microphone(
        catalog,
        MicrophoneSelection(
            requested_uid, requested_index, requested_name or "", requested_backend
        ),
    )
