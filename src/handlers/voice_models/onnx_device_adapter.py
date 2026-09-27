from __future__ import annotations

import re
from typing import Any


def enable_indexed_directml(inference_module: Any) -> bool:
    if getattr(inference_module, "_neuromita_indexed_dml_patch", False):
        return True

    classes = [
        getattr(inference_module, name, None)
        for name in ("OnnxRVC", "ContentVec", "RMVPEONNXPredictor")
    ]
    if any(not callable(getattr(cls, "_get_onnx_providers", None)) for cls in classes):
        return False

    predictor = classes[2]
    original_torch_device = getattr(predictor, "_get_torch_device", None)
    if not callable(original_torch_device):
        return False

    for vendor_class in classes:
        original_providers = vendor_class._get_onnx_providers

        def providers_for_device(instance, device, _original=original_providers):
            match = re.fullmatch(r"dml:(\d+)", str(device or "").lower())
            if match:
                return [
                    ("DmlExecutionProvider", {"device_id": int(match.group(1))}),
                    "CPUExecutionProvider",
                ]
            return _original(instance, device)

        vendor_class._get_onnx_providers = providers_for_device

    def torch_device_for_dml(instance, device, _original=original_torch_device):
        if re.fullmatch(r"dml:\d+", str(device or "").lower()):
            return "cpu"
        return _original(instance, device)

    predictor._get_torch_device = torch_device_for_dml
    inference_module._neuromita_indexed_dml_patch = True
    return True
