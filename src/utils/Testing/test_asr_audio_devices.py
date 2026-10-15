from __future__ import annotations
from infrastructure.audio.windows_endpoint_identity import EndpointIdentityRead
from domain.audio_input import EndpointIdentityStatus, MicrophoneSelection
from infrastructure.audio.portaudio_catalog import read_portaudio_catalog
from services.microphone_selection import resolve_microphone

from types import SimpleNamespace
import pytest

from handlers.asr_audio_devices import (
    list_asr_input_devices,
    resolve_asr_input_device,
    portaudio_stream_scope,
)


def test_refresh_does_not_reinitialize_portaudio_while_a_stream_is_open():
    sounddevice = _HotPlugSoundDevice([], [], [], supported=set())
    with portaudio_stream_scope():
        list_asr_input_devices(sounddevice, refresh=True)
    assert sounddevice.terminate_calls == 0


def test_missing_saved_name_does_not_fall_back_to_reused_index_or_default():
    sounddevice = _FakeSoundDevice(
        [_device("Another microphone", 0)], [{"name": "WASAPI"}], supported={(0, 16000)}
    )
    assert (
        resolve_asr_input_device(
            sounddevice, requested_index=0, requested_name="Missing microphone"
        )
        is None
    )


class _FakeSoundDevice:
    def __init__(self, devices, host_apis, *, supported, default_input=0):
        self._devices = devices
        self._host_apis = host_apis
        self._supported = set(supported)
        self.default = SimpleNamespace(device=(default_input, -1))

    def query_devices(self):
        return self._devices

    def query_hostapis(self, index):
        return self._host_apis[index]

    def check_input_settings(self, *, device, channels, dtype, samplerate):
        assert channels == 1
        assert dtype == "float32"
        if (device, samplerate) not in self._supported:
            raise RuntimeError("Invalid sample rate")


class _HotPlugSoundDevice(_FakeSoundDevice):
    def __init__(self, old_devices, new_devices, host_apis, *, supported):
        super().__init__(old_devices, host_apis, supported=supported)
        self._old_devices = old_devices
        self._new_devices = new_devices
        self._refreshed = False
        self._initialized = 1
        self.terminate_calls = 0
        self.initialize_calls = 0

    def query_devices(self):
        return self._new_devices if self._refreshed else self._old_devices

    def _terminate(self):
        self.terminate_calls += 1
        self._initialized -= 1

    def _initialize(self):
        self.initialize_calls += 1
        self._initialized += 1
        self._refreshed = True


def _device(name, hostapi, *, inputs=1, sample_rate=48000):
    return {
        "name": name,
        "hostapi": hostapi,
        "max_input_channels": inputs,
        "default_samplerate": sample_rate,
    }


def test_duplicate_windows_endpoints_collapse_to_one_compatible_device():
    sounddevice = _FakeSoundDevice(
        [
            _device("FIFINE Microphone", 0),
            _device("FIFINE Microphone", 1),
            _device("FIFINE Microphone", 2),
            _device("FIFINE Microphone", 3),
        ],
        [
            {"name": "MME"},
            {"name": "Windows DirectSound"},
            {"name": "Windows WASAPI"},
            {"name": "Windows WDM-KS"},
        ],
        supported={(0, 16000), (1, 16000), (3, 16000)},
    )

    devices = list_asr_input_devices(sounddevice)

    assert [(device.name, device.index, device.host_api) for device in devices] == [
        ("FIFINE Microphone", 1, "Windows DirectSound")
    ]


def test_native_rate_wasapi_is_preferred_for_capture():
    sounddevice = _FakeSoundDevice(
        [
            _device("USB Microphone", 0, sample_rate=44100),
            _device("USB Microphone", 1, sample_rate=48000),
        ],
        [
            {"name": "Windows DirectSound"},
            {"name": "Windows WASAPI"},
        ],
        supported={(0, 16000), (1, 48000)},
    )

    devices = list_asr_input_devices(sounddevice)

    assert [
        (device.index, device.host_api, device.default_sample_rate)
        for device in devices
    ] == [(1, "Windows WASAPI", 48000.0)]


def test_windows_default_aliases_are_not_shown_as_extra_microphones():
    sounddevice = _FakeSoundDevice(
        [
            _device("Microsoft Sound Mapper - Input", 0),
            _device("Primary Sound Capture Driver", 1),
            _device("Первичный драйвер записи звука", 1),
            _device("FIFINE Microphone", 0),
        ],
        [{"name": "MME"}, {"name": "Windows DirectSound"}],
        supported={(0, 16000), (1, 16000), (2, 16000), (3, 16000)},
    )

    devices = list_asr_input_devices(sounddevice)

    assert [f"{device.name} ({device.index})" for device in devices] == [
        "FIFINE Microphone (3)"
    ]


def test_refresh_rescans_portaudio_after_microphone_hot_plug():
    sounddevice = _HotPlugSoundDevice(
        [_device("Desk microphone", 0)],
        [_device("Desk microphone", 0), _device("Webcam microphone", 0)],
        [{"name": "MME"}],
        supported={(0, 16000), (1, 16000)},
    )

    before = list_asr_input_devices(sounddevice)
    after = list_asr_input_devices(sounddevice, refresh=True)

    assert [device.name for device in before] == ["Desk microphone"]
    assert [device.name for device in after] == [
        "Desk microphone",
        "Webcam microphone",
    ]
    assert sounddevice.terminate_calls == 1
    assert sounddevice.initialize_calls == 1


def test_wdm_ks_is_never_offered_even_when_format_probe_succeeds():
    sounddevice = _FakeSoundDevice(
        [_device("Kernel microphone", 0)],
        [{"name": "Windows WDM-KS"}],
        supported={(0, 16000)},
    )

    assert list_asr_input_devices(sounddevice) == []


def test_distinct_microphones_remain_distinct():
    sounddevice = _FakeSoundDevice(
        [_device("Desk microphone", 0), _device("Headset microphone", 0)],
        [{"name": "MME"}],
        supported={(0, 16000), (1, 16000)},
    )

    devices = list_asr_input_devices(sounddevice)

    assert [f"{device.name} ({device.index})" for device in devices] == [
        "Desk microphone (0)",
        "Headset microphone (1)",
    ]


def test_two_physical_microphones_with_the_same_name_remain_selectable():
    sounddevice = _FakeSoundDevice(
        [
            _device("USB Microphone", 0),
            _device("USB Microphone", 0),
            _device("USB Microphone", 1),
            _device("USB Microphone", 1),
        ],
        [{"name": "MME"}, {"name": "Windows DirectSound"}],
        supported={(0, 16000), (1, 16000), (2, 16000), (3, 16000)},
    )

    devices = list_asr_input_devices(sounddevice)

    assert [f"{device.name} ({device.index})" for device in devices] == [
        "USB Microphone (2)",
        "USB Microphone (3)",
    ]


def test_saved_wdm_ks_index_is_migrated_by_physical_device_name():
    sounddevice = _FakeSoundDevice(
        [
            _device("FIFINE Microphone", 0),
            _device("Other microphone", 1),
            _device("FIFINE Microphone", 2),
        ],
        [
            {"name": "Windows DirectSound"},
            {"name": "Windows WDM-KS"},
            {"name": "Windows WDM-KS"},
        ],
        supported={(0, 16000), (1, 16000), (2, 16000)},
    )

    resolved = resolve_asr_input_device(
        sounddevice,
        requested_index=2,
        requested_name="FIFINE Microphone",
    )

    assert resolved is not None
    assert resolved.index == 0
    assert resolved.host_api == "Windows DirectSound"


def test_saved_name_wins_over_an_index_reused_by_another_device():
    sounddevice = _FakeSoundDevice(
        [_device("Other microphone", 0), _device("FIFINE Microphone", 0)],
        [{"name": "MME"}],
        supported={(0, 16000), (1, 16000)},
    )

    resolved = resolve_asr_input_device(
        sounddevice,
        requested_index=0,
        requested_name="FIFINE Microphone",
    )

    assert resolved is not None
    assert resolved.index == 1


def test_mme_display_uses_full_wasapi_name_without_changing_device_identity():
    full_name = "Microphone (FIFINE K670 Microphone)"
    short_name = full_name[:31]
    sounddevice = _FakeSoundDevice(
        [_device(short_name, 0), _device(full_name, 1)],
        [{"name": "MME"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000)},
    )
    (device,) = list_asr_input_devices(sounddevice)
    assert device.name == short_name
    assert device.label == full_name
    assert device.index == 0
    assert f"{device.name} ({device.index})" == f"{short_name} (0)"
    assert (
        resolve_asr_input_device(
            sounddevice, requested_index=0, requested_name=short_name
        )
        == device
    )


def test_mme_display_does_not_guess_between_similar_full_names():
    prefix = "Microphone (FIFINE K670 Microph"
    sounddevice = _FakeSoundDevice(
        [
            _device(prefix, 0),
            _device(prefix + "one A)", 1),
            _device(prefix + "one B)", 1),
        ],
        [{"name": "MME"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000)},
    )
    (device,) = list_asr_input_devices(sounddevice)
    assert device.label == prefix
    assert device.display_name is None


def test_endpoint_id_survives_rename_and_portaudio_reordering(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(tuple(sd.identities.items())),
    )
    original = _FakeSoundDevice(
        [_device("Old microphone", 0), _device("Other", 0)],
        [{"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 16000)},
    )
    original.identities = {0: "endpoint-A", 1: "endpoint-B"}
    selected = resolve_asr_input_device(
        original, requested_index=0, requested_name="Old microphone"
    )
    assert selected.uid == "endpoint-A"
    changed = _FakeSoundDevice(
        [_device("Old microphone", 0), _device("Renamed microphone", 0)],
        [{"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 16000)},
    )
    changed.identities = {0: "endpoint-B", 1: "endpoint-A"}
    resolved = resolve_asr_input_device(
        changed,
        requested_index=0,
        requested_name="Old microphone",
        requested_uid=selected.uid,
    )
    assert resolved.index == 1
    assert resolved.name == "Renamed microphone"


def test_missing_endpoint_never_falls_back_to_reused_index_or_name(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(tuple({0: "other-endpoint"}.items())),
    )
    backend = _FakeSoundDevice(
        [_device("Same name", 0)],
        [{"name": "Windows WASAPI"}],
        supported={(0, 16000)},
    )
    assert (
        resolve_asr_input_device(
            backend,
            requested_index=0,
            requested_name="Same name",
            requested_uid="missing-endpoint",
        )
        is None
    )


def test_legacy_truncated_name_migrates_to_same_endpoint_and_duplicates_collapse(
    monkeypatch,
):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(tuple({1: "endpoint-A"}.items())),
    )
    full_name = "Microphone (FIFINE K670 Microphone)"
    backend = _FakeSoundDevice(
        [_device(full_name[:31], 0), _device(full_name, 1)],
        [{"name": "MME"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 48000)},
    )
    devices = list_asr_input_devices(backend)
    assert len(devices) == 1
    assert devices[0].uid == "endpoint-A"
    assert devices[0].index == 1
    assert (
        resolve_asr_input_device(
            backend,
            requested_index=0,
            requested_name=full_name[:31],
        )
        == devices[0]
    )


def test_identical_names_with_different_endpoint_ids_are_not_collapsed(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(tuple({0: "A", 1: "B"}.items())),
    )
    backend = _FakeSoundDevice(
        [_device("Same name", 0), _device("Same name", 0)],
        [{"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 16000)},
    )
    assert [device.uid for device in list_asr_input_devices(backend)] == ["A", "B"]


def test_numeric_legacy_selection_maps_alias_index_to_endpoint(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(tuple({2: "A", 3: "B"}.items())),
    )
    backend = _FakeSoundDevice(
        [
            _device("First", 0),
            _device("Second", 0),
            _device("First", 1),
            _device("Second", 1),
        ],
        [{"name": "MME"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 16000), (2, 48000), (3, 48000)},
    )
    resolved = resolve_asr_input_device(backend, requested_index=1, requested_name=None)
    assert resolved.uid == "B"
    assert resolved.index == 3


def test_input_without_wasapi_identity_remains_selectable(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(((2, "headset-id"),)),
    )
    backend = _FakeSoundDevice(
        [
            _device("Built-in microphone", 0),
            _device("Built-in microphone", 1),
            _device("Headset", 2),
        ],
        [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 16000), (2, 48000)},
    )
    catalog = read_portaudio_catalog(backend)
    selected = resolve_microphone(
        catalog, MicrophoneSelection(index=0, name="Built-in microphone")
    )
    assert selected is not None
    assert selected.index == 1
    assert selected.uid is None
    assert resolve_microphone(
        catalog, MicrophoneSelection(index=0, name="Built-in microphone", backend="MME")
    ).index == 0


def test_partial_identity_failure_preserves_verified_microphone_backends(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(
            ((1, "built-in-id"),), EndpointIdentityStatus.PARTIAL, "Headset ID failed"
        ),
    )
    backend = _FakeSoundDevice(
        [_device("Built-in", 0), _device("Built-in", 1), _device("Headset", 1)],
        [{"name": "MME"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 48000), (2, 48000)},
    )
    catalog = read_portaudio_catalog(backend)
    selected = resolve_microphone(
        catalog, MicrophoneSelection("built-in-id", 0, "Built-in", "MME")
    )
    assert selected.index == 0
    assert selected.uid == "built-in-id"


def test_unmatched_backend_name_remains_available_without_guessed_identity(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(((1, "built-in-id"),)),
    )
    backend = _FakeSoundDevice(
        [_device("Microphone Array (Intel SST)", 0), _device("Microphone Array", 1)],
        [{"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 48000)},
    )
    catalog = read_portaudio_catalog(backend)
    selected = resolve_microphone(
        catalog, MicrophoneSelection(index=0, name="Microphone Array (Intel SST)")
    )
    assert selected is not None
    assert selected.index == 0
    assert selected.uid is None


def test_partial_identity_does_not_guess_alias_between_identical_endpoint_names(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(
            ((1, "verified-id"),), EndpointIdentityStatus.PARTIAL, "Second ID failed"
        ),
    )
    backend = _FakeSoundDevice(
        [_device("Same name", 0), _device("Same name", 1), _device("Same name", 1)],
        [{"name": "MME"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 48000), (2, 48000)},
    )
    catalog = read_portaudio_catalog(backend)
    assert next(d for d in catalog.representations if d.index == 0).uid is None
    assert resolve_microphone(catalog, MicrophoneSelection("verified-id")).index == 1


@pytest.mark.parametrize(
    "status", [EndpointIdentityStatus.AVAILABLE, EndpointIdentityStatus.PARTIAL]
)
def test_duplicate_backend_names_are_not_bound_to_one_endpoint(monkeypatch, status):
    monkeypatch.setattr(
        "infrastructure.audio.portaudio_catalog._endpoint_ids",
        lambda sd, indices: EndpointIdentityRead(((2, "verified-id"),), status),
    )
    backend = _FakeSoundDevice(
        [
            _device("Same name", 0),
            _device("Same name", 0),
            _device("Same name", 1),
            _device("Other", 1),
        ],
        [{"name": "MME"}, {"name": "Windows WASAPI"}],
        supported={(0, 16000), (1, 16000), (2, 48000), (3, 48000)},
    )
    catalog = read_portaudio_catalog(backend)
    selected = resolve_microphone(
        catalog, MicrophoneSelection(index=1, name="Same name", backend="MME")
    )
    assert selected.index == 1
    assert selected.uid is None
    assert all(d.uid is None for d in catalog.representations if d.host_api == "MME")
