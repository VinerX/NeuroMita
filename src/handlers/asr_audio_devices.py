from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any


ASR_CAPTURE_SAMPLE_RATE = 16000
_PORTAUDIO_CATALOG_LOCK = RLock()

_WINDOWS_DEFAULT_INPUT_ALIASES = frozenset(
    {
        "microsoft sound mapper - input",
        "primary sound capture driver",
        "первичный драйвер записи звука",
        "первичный драйвер захвата звука",
    }
)


@dataclass(frozen=True)
class ASRInputDevice:
    index: int
    name: str
    host_api: str
    default_sample_rate: float | None = None

    @property
    def option_text(self) -> str:
        return f"{self.name} ({self.index})"


def normalize_device_name(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _host_api_priority(host_api: str) -> int:
    normalized = str(host_api or "").casefold()
    if "wasapi" in normalized:
        return 0
    if "directsound" in normalized:
        return 1
    if normalized == "mme" or " mme" in normalized:
        return 2
    return 3


def _host_api_name(sounddevice, device: Any) -> str:
    try:
        host_api = sounddevice.query_hostapis(int(device.get("hostapi")))
        return str(host_api.get("name") or "").strip()
    except Exception:
        return ""


def _supports_asr_capture(
    sounddevice,
    index: int,
    sample_rate: int,
    default_sample_rate: float | None = None,
) -> bool:
    checker = getattr(sounddevice, "check_input_settings", None)
    if not callable(checker):
        return True

    # WASAPI endpoints commonly accept only their Windows mix format (usually
    # 48 kHz).  AudioCaptureService resamples that stream to the 16 kHz ASR
    # format, so such an endpoint is compatible even when PortAudio rejects a
    # direct 16 kHz open.
    candidate_rates = [int(sample_rate)]
    try:
        native_rate = int(round(float(default_sample_rate)))
    except (TypeError, ValueError):
        native_rate = 0
    if native_rate > 0 and native_rate not in candidate_rates:
        candidate_rates.append(native_rate)

    for candidate_rate in candidate_rates:
        try:
            checker(
                device=int(index),
                channels=1,
                dtype="float32",
                samplerate=candidate_rate,
            )
            return True
        except Exception:
            continue
    return False


def refresh_portaudio_catalog(sounddevice) -> None:
    """Force PortAudio to rescan hot-plugged devices when supported.

    python-sounddevice has no public refresh call.  Its device catalog belongs
    to the PortAudio lifetime, so a new ``query_devices()`` alone can keep the
    snapshot taken when the process started.  The private lifecycle functions
    are stable in the pinned sounddevice 0.5.1 used by the application.
    """

    with _PORTAUDIO_CATALOG_LOCK:
        terminate = getattr(sounddevice, "_terminate", None)
        initialize = getattr(sounddevice, "_initialize", None)
        if not callable(terminate) or not callable(initialize):
            return

        initialized_count = max(1, int(getattr(sounddevice, "_initialized", 1) or 1))
        terminated_count = 0
        try:
            for _ in range(initialized_count):
                terminate()
                terminated_count += 1
        finally:
            # Restore the previous initialization reference count even when one
            # of the PortAudio termination calls reports an error.
            for _ in range(terminated_count):
                initialize()


def list_asr_input_devices(
    sounddevice,
    *,
    sample_rate: int = ASR_CAPTURE_SAMPLE_RATE,
    refresh: bool = False,
) -> list[ASRInputDevice]:
    """Return one compatible PortAudio endpoint for each input-device name.

    PortAudio exposes the same Windows endpoint through several host APIs.  The
    ASR capture loop uses blocking ``InputStream.read()``, so WDM-KS endpoints
    must not be offered: that host API rejects blocking streams.  Of the other
    representations, keep the best one that can actually open the ASR format.
    """

    with _PORTAUDIO_CATALOG_LOCK:
        if refresh:
            refresh_portaudio_catalog(sounddevice)
        return _list_asr_input_devices(sounddevice, sample_rate=sample_rate)


def _list_asr_input_devices(
    sounddevice,
    *,
    sample_rate: int,
) -> list[ASRInputDevice]:
    raw_devices = list(sounddevice.query_devices())

    selected: dict[tuple[str, int], ASRInputDevice] = {}
    order: list[tuple[str, int]] = []
    occurrences: dict[tuple[str, str], int] = {}

    for index, device in enumerate(raw_devices):
        try:
            if int(device.get("max_input_channels", 0) or 0) <= 0:
                continue
        except Exception:
            continue

        name = " ".join(str(device.get("name") or f"Device {index}").split())
        key = normalize_device_name(name)
        if not key:
            continue

        host_api = _host_api_name(sounddevice, device)
        occurrence_key = (host_api.casefold(), key)
        occurrence = occurrences.get(occurrence_key, 0)
        occurrences[occurrence_key] = occurrence + 1
        physical_key = (key, occurrence)

        # These are PortAudio aliases for the Windows default input, not
        # additional microphones.  Keeping them would reintroduce a duplicate
        # for whichever physical endpoint is currently the system default.
        if key in _WINDOWS_DEFAULT_INPUT_ALIASES:
            continue

        try:
            default_rate = float(device.get("default_samplerate"))
        except (TypeError, ValueError):
            default_rate = None

        if "wdm-ks" in host_api.casefold():
            continue
        if not _supports_asr_capture(
            sounddevice,
            index,
            sample_rate,
            default_rate,
        ):
            continue

        candidate = ASRInputDevice(
            index=int(index),
            name=name,
            host_api=host_api,
            default_sample_rate=default_rate,
        )
        current = selected.get(physical_key)
        if current is None:
            selected[physical_key] = candidate
            order.append(physical_key)
        elif _host_api_priority(candidate.host_api) < _host_api_priority(current.host_api):
            selected[physical_key] = candidate

    return [selected[key] for key in order]


def resolve_asr_input_device(
    sounddevice,
    *,
    requested_index: int | None,
    requested_name: str | None,
    sample_rate: int = ASR_CAPTURE_SAMPLE_RATE,
    refresh: bool = False,
) -> ASRInputDevice | None:
    """Resolve persisted selection to a currently compatible PortAudio index."""

    devices = list_asr_input_devices(
        sounddevice,
        sample_rate=sample_rate,
        refresh=refresh,
    )
    if not devices:
        return None

    try:
        requested_index_value = int(requested_index) if requested_index is not None else None
    except (TypeError, ValueError):
        requested_index_value = None

    requested_key = normalize_device_name(requested_name)
    if requested_key:
        same_name = [
            device
            for device in devices
            if normalize_device_name(device.name) == requested_key
        ]
        for device in same_name:
            if device.index == requested_index_value:
                return device
        if same_name:
            return same_name[0]

    if requested_index_value is not None:
        for device in devices:
            if device.index == requested_index_value:
                return device

    try:
        default_device = sounddevice.default.device
        try:
            default_input = int(default_device[0])
        except (TypeError, IndexError, KeyError):
            default_input = int(default_device)
    except Exception:
        default_input = -1
    for device in devices:
        if device.index == default_input:
            return device

    return devices[0]
