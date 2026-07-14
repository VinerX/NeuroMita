from __future__ import annotations

from typing import Any


_SUPPORTED_BACKENDS: dict[str, frozenset[str]] = {
    "NVIDIA": frozenset({"cuda", "onnx", "cpu", "none", ""}),
    "AMD": frozenset({"onnx", "cpu", "none", ""}),
    "INTEL": frozenset({"onnx", "cpu", "none", ""}),
    "CPU": frozenset({"onnx", "cpu", "none", ""}),
}


def normalize_hardware_vendor(value: Any) -> str:
    normalized = str(value or "CPU").strip().upper()
    return normalized if normalized in _SUPPORTED_BACKENDS else "CPU"


def evaluate_installable_compatibility(
    *,
    component_id: str,
    backend: str,
    gpu_vendor: str,
    language: str = "RU",
) -> dict[str, Any]:
    component = str(component_id or "").strip()
    normalized_backend = str(backend or "none").strip().lower()
    vendor = normalize_hardware_vendor(gpu_vendor)
    supported = normalized_backend in _SUPPORTED_BACKENDS[vendor]
    recommended = supported
    reason_code = "supported"
    warning_ru = ""
    warning_en = ""

    if not supported:
        recommended = False
        reason_code = "backend_incompatible"
        warning_ru = f"Backend {normalized_backend.upper()} несовместим с текущим устройством ({vendor})."
        warning_en = f"The {normalized_backend.upper()} backend is incompatible with the current device ({vendor})."
    elif normalized_backend == "onnx" and vendor == "NVIDIA":
        recommended = False
        reason_code = "cuda_preferred"
        warning_ru = "DirectML поддерживается, но на NVIDIA обычно быстрее и стабильнее CUDA-версия модели."
        warning_en = "DirectML is supported, but the CUDA model variant is usually faster and better optimized on NVIDIA."
    elif component == "tts:high" and vendor in {"AMD", "INTEL", "CPU"}:
        reason_code = "cpu_fallback"
        warning_ru = "F5-TTS будет работать через CPU fallback и может быть заметно медленнее."
        warning_en = "F5-TTS will use its CPU fallback and may be noticeably slower."
    elif component == "tts:high+low" and vendor in {"AMD", "INTEL", "CPU"}:
        reason_code = "mixed_cpu_onnx_fallback"
        warning_ru = "F5-TTS использует CPU fallback, а RVC — ONNX/DirectML; режим поддерживается, но работает медленнее."
        warning_en = "F5-TTS uses its CPU fallback while RVC uses ONNX/DirectML; this is supported but slower."

    warning = warning_en if str(language or "RU").upper() == "EN" else warning_ru
    return {
        "supported": supported,
        "recommended": recommended,
        "reason_code": reason_code,
        "warning": warning,
        "backend": normalized_backend,
        "gpu_vendor": vendor,
    }
