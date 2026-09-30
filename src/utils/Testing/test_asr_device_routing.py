from types import SimpleNamespace
from unittest.mock import Mock, patch

from handlers.asr_models.gigaam_onnx_process import onnx_providers_for_device
from handlers.asr_models.whisper_onnx_process import WhisperOnnxProcessWorker


def test_gigaam_onnx_routes_selected_directml_adapter():
    providers = onnx_providers_for_device(
        "dml:2", {"DmlExecutionProvider", "CPUExecutionProvider"}
    )

    assert providers == [
        ("DmlExecutionProvider", {"device_id": 2}),
        "CPUExecutionProvider",
    ]


def test_whisper_onnx_routes_selected_directml_adapter():
    worker = WhisperOnnxProcessWorker(Mock(), Mock(), Mock())
    worker.device = "dml:1"
    worker._rt = SimpleNamespace(
        get_available_providers=lambda: ["DmlExecutionProvider", "CPUExecutionProvider"]
    )

    assert worker._select_provider() == (
        "DmlExecutionProvider",
        {"device_id": 1},
    )


def test_onnx_asr_stable_selection_reaches_provider_with_current_adapter_index():
    from core.voice_device_selection import expand_voice_device_schema
    from handlers.asr_models.gigaam_onnx_recognizer import GigaAMOnnxRecognizer
    from handlers.asr_models.whisper_onnx_recognizer import WhisperOnnxRecognizer

    hardware = {"adapters": [
        {"index": 0, "name": "AMD Radeon", "luid": "0000000000000001"},
        {"index": 1, "name": "NVIDIA RTX", "luid": "0000000000000002"},
    ]}
    selected = "dml@0000000000000002"
    whisper = WhisperOnnxRecognizer.__new__(WhisperOnnxRecognizer)
    whisper.device = selected
    gigaam = GigaAMOnnxRecognizer.__new__(GigaAMOnnxRecognizer)
    gigaam.gigaam_device = selected
    for recognizer in (whisper, gigaam):
        schema = expand_voice_device_schema(recognizer.settings_spec(), hardware)
        device = next(item for item in schema if item.get("key") == "device")
        assert "dml" not in device["options"]["values"]
        assert device["options"]["display_labels"][selected] == "dml:1 (NVIDIA RTX)"

    with patch("utils.gpu_utils.get_hardware_snapshot", return_value=hardware):
        assert whisper._runtime_device() == "dml:1"
        assert gigaam._runtime_device() == "dml:1"
        providers = onnx_providers_for_device(gigaam._runtime_device(), {"DmlExecutionProvider"})
        assert providers[0] == ("DmlExecutionProvider", {"device_id": 1})
        worker = WhisperOnnxProcessWorker(Mock(), Mock(), Mock())
        worker.device = whisper._runtime_device()
        worker._rt = SimpleNamespace(get_available_providers=lambda: ["DmlExecutionProvider"])
        assert worker._select_provider() == ("DmlExecutionProvider", {"device_id": 1})
