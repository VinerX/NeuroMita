from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
from threading import RLock
from typing import Any
from domain.audio_input import ASRInputDevice, AudioInputCatalog, EndpointIdentityStatus
from infrastructure.audio.windows_endpoint_identity import (
    read_windows_endpoint_ids,
    EndpointIdentityRead,
)
from services.audio_input_contracts import AudioInputCatalogUnavailable

ASR_CAPTURE_SAMPLE_RATE = 16000
_MME_PRODUCT_NAME_MAX_UTF16_UNITS = 31
_PORTAUDIO_CATALOG_LOCK = RLock()
_ACTIVE_STREAMS = 0


@contextmanager
def portaudio_stream_scope():
    """Prevent catalog reinitialization while a capture or monitor owns streams."""
    global _ACTIVE_STREAMS
    with _PORTAUDIO_CATALOG_LOCK:
        _ACTIVE_STREAMS += 1
    try:
        yield
    finally:
        with _PORTAUDIO_CATALOG_LOCK:
            _ACTIVE_STREAMS -= 1


_WINDOWS_DEFAULT_INPUT_ALIASES = frozenset(
    {
        "microsoft sound mapper - input",
        "primary sound capture driver",
        "первичный драйвер записи звука",
        "первичный драйвер захвата звука",
    }
)


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
        if _ACTIVE_STREAMS:
            return
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


def read_portaudio_catalog(
    sounddevice,
    *,
    sample_rate: int = ASR_CAPTURE_SAMPLE_RATE,
    refresh: bool = False,
) -> AudioInputCatalog:
    """Return one compatible PortAudio representation per physical endpoint.

    PortAudio exposes the same Windows endpoint through several host APIs.  The
    ASR capture loop uses blocking ``InputStream.read()``, so WDM-KS endpoints
    must not be offered: that host API rejects blocking streams.  Of the other
    representations, keep the best one that can actually open the ASR format.
    """

    with _PORTAUDIO_CATALOG_LOCK:
        if refresh:
            refresh_portaudio_catalog(sounddevice)
        return _read_portaudio_catalog(sounddevice, sample_rate=sample_rate)


def _read_portaudio_catalog(
    sounddevice,
    *,
    sample_rate: int,
) -> AudioInputCatalog:
    raw_devices = list(sounddevice.query_devices())
    input_indices = set()
    for index, device in enumerate(raw_devices):
        try:
            if int(device.get("max_input_channels", 0) or 0) > 0:
                input_indices.add(index)
        except (TypeError, ValueError):
            continue
    host_names = [_host_api_name(sounddevice, device) for device in raw_devices]
    backend_name_counts = Counter(
        (host_names[index].casefold(), normalize_device_name(raw_devices[index].get("name")))
        for index in input_indices
    )
    wasapi_indices = [
        index
        for index in sorted(input_indices)
        if "wasapi" in host_names[index].casefold()
    ]
    identity = _endpoint_ids(sounddevice, wasapi_indices)
    if (
        input_indices
        and not wasapi_indices
        and identity.status == EndpointIdentityStatus.AVAILABLE
    ):
        identity = EndpointIdentityRead(
            status=EndpointIdentityStatus.UNSUPPORTED,
            detail="No WASAPI input endpoints are exposed by this backend",
        )
    endpoint_ids = dict(identity.values)
    endpoints = [
        (
            " ".join(str(raw_devices[index].get("name") or "").split()),
            endpoint_ids.get(index),
        )
        for index in wasapi_indices
    ]
    full_names = set()
    for index in sorted(input_indices):
        device = raw_devices[index]
        host_api = host_names[index].casefold()
        if "wasapi" in host_api or "directsound" in host_api:
            full_names.add(" ".join(str(device.get("name") or "").split()))

    selected: dict[tuple[str, int], ASRInputDevice] = {}
    order: list[tuple[str, int]] = []
    occurrences: dict[tuple[str, str], int] = {}
    representations = []
    compatible = []
    groups = {}

    for index in sorted(input_indices):
        device = raw_devices[index]
        name = " ".join(str(device.get("name") or f"Device {index}").split())
        key = normalize_device_name(name)
        if not key:
            continue

        host_api = host_names[index]
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

        display_name = None
        if (
            host_api.casefold() == "mme"
            and len(name.encode("utf-16-le")) // 2 == _MME_PRODUCT_NAME_MAX_UTF16_UNITS
        ):
            matches = {
                full_name
                for full_name in full_names
                if normalize_device_name(full_name).startswith(key)
            }
            if len(matches) == 1:
                full_name = matches.pop()
                if len(full_name) > len(name):
                    display_name = full_name

        uid = endpoint_ids.get(index)
        if (
            uid is None
            and backend_name_counts[occurrence_key] == 1
            and identity.status in (
                EndpointIdentityStatus.AVAILABLE,
                EndpointIdentityStatus.PARTIAL,
            )
        ):
            matches = {
                endpoint_uid
                for endpoint_name, endpoint_uid in endpoints
                if normalize_device_name(endpoint_name) == key
                or (
                    host_api.casefold() == "mme"
                    and len(name.encode("utf-16-le")) // 2
                    == _MME_PRODUCT_NAME_MAX_UTF16_UNITS
                    and normalize_device_name(endpoint_name).startswith(key)
                )
            }
            if len(matches) == 1:
                uid = matches.pop()
        if uid is not None:
            physical_key = (uid, 0)

        candidate = ASRInputDevice(
            index=int(index),
            name=name,
            host_api=host_api,
            default_sample_rate=default_rate,
            display_name=display_name,
            uid=uid,
        )
        representations.append(candidate)
        groups[index] = physical_key
        if "wdm-ks" in host_api.casefold():
            continue
        if not _supports_asr_capture(
            sounddevice,
            index,
            sample_rate,
            default_rate,
        ):
            continue

        compatible.append(candidate)
        current = selected.get(physical_key)
        if current is None:
            selected[physical_key] = candidate
            order.append(physical_key)
        elif _host_api_priority(candidate.host_api) < _host_api_priority(
            current.host_api
        ):
            selected[physical_key] = candidate

    try:
        default_index = int(sounddevice.default.device[0])
    except (AttributeError, TypeError, IndexError, KeyError, ValueError):
        default_index = None
    return AudioInputCatalog(
        devices=tuple(selected[key] for key in order),
        representations=tuple(representations),
        preferred_indices=tuple(
            (index, selected[key].index)
            for index, key in groups.items()
            if key in selected
        ),
        default_index=default_index,
        identity_status=identity.status,
        identity_detail=identity.detail,
        compatible_representations=tuple(compatible),
    )


def _endpoint_ids(sounddevice, indices):
    """The pinned sounddevice bridge exposes its loaded PortAudio library path here."""
    return read_windows_endpoint_ids(getattr(sounddevice, "_libname", None), indices)


class PortAudioCatalogProvider:
    def __init__(self, sounddevice, *, sample_rate=ASR_CAPTURE_SAMPLE_RATE):
        self._sounddevice = sounddevice
        self._sample_rate = sample_rate

    def read(self, *, refresh=False):
        try:
            return read_portaudio_catalog(
                self._sounddevice, sample_rate=self._sample_rate, refresh=refresh
            )
        except Exception as error:
            raise AudioInputCatalogUnavailable(str(error)) from error
