from __future__ import annotations

from types import SimpleNamespace

from handlers.asr_audio_devices import (
    list_asr_input_devices,
    resolve_asr_input_device,
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

    assert [(device.index, device.host_api, device.default_sample_rate) for device in devices] == [
        (1, "Windows WASAPI", 48000.0)
    ]


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

    assert [device.option_text for device in devices] == ["FIFINE Microphone (3)"]


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

    assert [device.option_text for device in devices] == [
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

    assert [device.option_text for device in devices] == [
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
