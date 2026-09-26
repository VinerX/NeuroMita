import pytest

from core.setting_behaviors import evaluate_setting_behaviors, normalize_setting_behaviors
from core.voice_device_selection import (
    VoiceDeviceCatalog,
    device_half_precision_behavior,
    expand_voice_device_schema,
    migrate_voice_device_values,
    validate_voice_devices,
)


HARDWARE = {
    "cuda": {
        "devices": [
            {"ordinal": 0, "name": "NVIDIA GeForce RTX 5060 Ti"},
            {"ordinal": 1, "name": "NVIDIA RTX A400"},
        ]
    },
    "accelerators": [
        {"dxgi_index": 0, "name": "AMD Radeon RX 7900 GRE"},
        {"dxgi_index": 1, "name": "NVIDIA RTX A400"},
        {"dxgi_index": 2, "name": "NVIDIA GeForce RTX 5060 Ti"},
    ],
}


def test_cuda_schema_lists_both_nvidia_cards_without_amd():
    source = [
        {"key": "fsprvc_fsp_device", "type": "combobox", "options": {"values": ["cuda"], "default": "cuda"}},
        {"key": "fsprvc_rvc_device", "type": "combobox", "options": {"values": ["cuda:0", "cpu"], "default": "cuda:0"}},
    ]

    result = expand_voice_device_schema(source, HARDWARE)

    assert result[0]["options"]["values"] == ["cuda:0", "cuda:1"]
    assert result[0]["options"]["default"] == "cuda:0"
    assert result[1]["options"]["values"] == ["cuda:0", "cuda:1", "cpu"]
    assert result[1]["options"]["display_labels"]["cuda:1"] == "cuda:1 (NVIDIA RTX A400)"
    assert source[0]["options"]["values"] == ["cuda"]


def test_legacy_asr_schema_is_normalized_and_lists_every_cuda_device():
    source = [{
        "key": "device",
        "type": "combobox",
        "options": ["auto", "cuda", "cpu"],
        "default": "auto",
    }]

    result = expand_voice_device_schema(source, HARDWARE)

    assert result[0]["options"]["values"] == ["auto", "cuda:0", "cuda:1", "cpu"]
    assert result[0]["options"]["default"] == "auto"
    assert result[0]["options"]["display_labels"]["cuda:0"].endswith("RTX 5060 Ti)")


def test_legacy_cuda_value_migrates_to_first_available_cuda_device():
    schema = expand_voice_device_schema(
        [{
            "key": "device",
            "type": "combobox",
            "options": {"values": ["cuda", "cpu"], "default": "cuda"},
        }],
        HARDWARE,
    )

    assert migrate_voice_device_values(schema, {"device": "cuda"}) == {
        "device": "cuda:0"
    }
    assert migrate_voice_device_values(schema, {"device": "cuda:1"}) == {
        "device": "cuda:1"
    }


def test_directml_schema_lists_amd_and_both_nvidia_adapters():
    source = [{"key": "device", "type": "combobox", "options": {"values": ["dml", "cpu"], "default": "dml"}}]

    result = expand_voice_device_schema(source, HARDWARE)
    options = result[0]["options"]

    assert options["values"] == ["dml", "dml:0", "dml:1", "dml:2", "cpu"]
    assert options["display_labels"]["dml:0"] == "dml:0 (AMD Radeon RX 7900 GRE)"
    assert validate_voice_devices(result, {"device": "dml:0"}) == {}
    assert "device" in validate_voice_devices(result, {"device": "dml:9"})


def test_amd_variant_replaces_cuda_default_with_directml():
    source = [{"key": "f5rvc_rvc_device", "type": "combobox", "options": {
        "values": ["cuda:0", "cpu"], "default": "cuda:0",
        "values_amd": ["dml", "cpu"], "default_amd": "dml",
    }}]
    hardware = {
        "vendor": "AMD",
        "cuda": {"devices": []},
        "accelerators": [{"dxgi_index": 0, "name": "AMD Radeon", "vendor": "AMD"}],
    }

    options = expand_voice_device_schema(source, hardware)[0]["options"]

    assert options["values"] == ["dml", "dml:0", "cpu"]
    assert options["default"] == "dml"


def test_directml_identity_resolves_current_dxgi_index_after_reordering():
    luid = "1234567890abcdef"
    before = VoiceDeviceCatalog({"adapters": [
        {"index": 0, "name": "AMD Radeon", "luid": luid},
    ]})
    after = VoiceDeviceCatalog({"adapters": [
        {"index": 0, "name": "NVIDIA RTX", "luid": "0000000000000001"},
        {"index": 1, "name": "AMD Radeon", "luid": luid},
    ]})

    assert before.dml[0].value == f"dml@{luid}"
    assert after.resolve_runtime_device(f"dml@{luid}") == "dml:1"
    with pytest.raises(ValueError, match="no longer available"):
        after.resolve_runtime_device("dml:1")
    with pytest.raises(ValueError, match="no longer available"):
        VoiceDeviceCatalog({"adapters": []}).resolve_runtime_device(f"dml@{luid}")


def test_half_precision_reacts_to_the_selected_cuda_device():
    hardware = {
        "vendor": "NVIDIA",
        "cuda": {"devices": [
            {"ordinal": 0, "name": "NVIDIA GeForce RTX 5060 Ti", "compute_capability": "sm_120"},
            {"ordinal": 1, "name": "NVIDIA GeForce GTX 1060", "compute_capability": "sm_61"},
        ]},
    }
    source = [
        {"key": "device", "type": "combobox", "options": {"values": ["cuda", "cpu"], "default": "cuda"}},
        {
            "key": "is_half",
            "type": "combobox",
            "options": {"values": ["True", "False"], "default": "True"},
            "behavior": device_half_precision_behavior("device"),
        },
    ]
    schema = expand_voice_device_schema(source, hardware)

    fast = evaluate_setting_behaviors(schema, {"device": "cuda:0", "is_half": "True"})
    old = evaluate_setting_behaviors(schema, {"device": "cuda:1", "is_half": "True"})

    assert fast["is_half"] == {"enabled": True, "value": None}
    assert old["is_half"] == {"enabled": False, "value": "False"}
    assert normalize_setting_behaviors(
        schema, {"device": "cuda:1", "is_half": "True"}
    )["is_half"] == "False"
