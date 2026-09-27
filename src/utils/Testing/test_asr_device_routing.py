from types import SimpleNamespace
from unittest.mock import Mock

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
