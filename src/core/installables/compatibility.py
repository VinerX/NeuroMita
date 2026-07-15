from __future__ import annotations

import re
from typing import Any

from core.installables.types import CompatibilityRule, coerce_compatibility_spec


_SUPPORTED_BACKENDS: dict[str, frozenset[str]] = {
    "NVIDIA": frozenset({"cuda", "onnx", "cpu", "none", ""}),
    "AMD": frozenset({"onnx", "cpu", "none", ""}),
    "INTEL": frozenset({"onnx", "cpu", "none", ""}),
    "CPU": frozenset({"onnx", "cpu", "none", ""}),
}


def normalize_hardware_vendor(value: Any) -> str:
    normalized = str(value or "CPU").strip().upper()
    return normalized if normalized in _SUPPORTED_BACKENDS else "CPU"


def normalize_compute_capability(value: Any) -> int | None:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        try:
            return int(value[0]) * 10 + int(value[1])
        except (TypeError, ValueError):
            return None
    if isinstance(value, int):
        return value if value >= 10 else value * 10
    if isinstance(value, float):
        return int(value * 10)
    match = re.search(r"(\d+)\D*(\d+)?", str(value or ""))
    if match is None:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    if str(value or "").strip().lower().startswith("sm_"):
        return int(f"{major}{minor}") if match.group(2) else major
    return major * 10 + minor if major < 10 else major


def hardware_compute_capability(hardware: dict[str, Any] | None) -> int | None:
    snapshot = hardware if isinstance(hardware, dict) else {}
    primary = snapshot.get("primary") if isinstance(snapshot.get("primary"), dict) else {}
    primary_cuda = primary.get("cuda") if isinstance(primary.get("cuda"), dict) else {}
    primary_value = normalize_compute_capability(
        (primary_cuda.get("compute_major"), primary_cuda.get("compute_minor"))
        if primary_cuda.get("compute_major") is not None
        and primary_cuda.get("compute_minor") is not None
        else primary_cuda.get("compute_capability")
    )
    if primary_value is not None:
        return primary_value
    cuda = snapshot.get("cuda") if isinstance(snapshot.get("cuda"), dict) else {}
    capabilities: list[int] = []
    for device in cuda.get("devices") or ():
        if not isinstance(device, dict):
            continue
        major = device.get("compute_major")
        minor = device.get("compute_minor")
        value = normalize_compute_capability(
            (major, minor)
            if major is not None and minor is not None
            else device.get("compute_capability")
        )
        if value is not None:
            capabilities.append(value)
    return max(capabilities) if capabilities else None


def format_compute_capability(value: int | None) -> str:
    if value is None:
        return "unknown"
    return f"sm_{int(value):02d}"


def _rule_warning(rule: CompatibilityRule, language: str) -> str:
    return rule.warning_en if str(language or "RU").upper() == "EN" else rule.warning_ru


def evaluate_installable_compatibility(
    *,
    backend: str,
    hardware: dict[str, Any] | None,
    compatibility: dict[str, Any] | None = None,
    language: str = "RU",
) -> dict[str, Any]:
    snapshot = hardware if isinstance(hardware, dict) else {}
    normalized_backend = str(backend or "none").strip().lower()
    vendor = normalize_hardware_vendor(snapshot.get("vendor"))
    compute_capability = hardware_compute_capability(snapshot)
    spec = coerce_compatibility_spec(compatibility)

    backend_supported = normalized_backend in _SUPPORTED_BACKENDS[vendor]
    vendor_supported = not spec.supported_vendors or vendor in spec.supported_vendors
    supported = backend_supported and vendor_supported
    recommended = supported
    reason_code = "supported"
    warnings: list[str] = []

    if not backend_supported:
        reason_code = "backend_incompatible"
        if str(language or "RU").upper() == "EN":
            warnings.append(
                f"The {normalized_backend.upper()} backend is incompatible with the current device ({vendor})."
            )
        else:
            warnings.append(
                f"Backend {normalized_backend.upper()} несовместим с текущим устройством ({vendor})."
            )
    elif not vendor_supported:
        reason_code = "vendor_incompatible"
        supported_vendors = ", ".join(spec.supported_vendors)
        if str(language or "RU").upper() == "EN":
            warnings.append(
                f"This component supports only: {supported_vendors}. Detected device: {vendor}."
            )
        else:
            warnings.append(
                f"Компонент поддерживает только: {supported_vendors}. Обнаружено устройство: {vendor}."
            )
    elif normalized_backend == "onnx" and vendor == "NVIDIA":
        recommended = False
        reason_code = "cuda_preferred"
        if str(language or "RU").upper() == "EN":
            warnings.append(
                "DirectML is supported, but the CUDA model variant is usually faster and better optimized on NVIDIA."
            )
        else:
            warnings.append(
                "DirectML поддерживается, но на NVIDIA обычно быстрее и стабильнее CUDA-версия модели."
            )

    hardware_tags: list[dict[str, str]] = []
    for rule in spec.rules:
        warning = _rule_warning(rule, language)
        if rule.tag:
            hardware_tags.append(
                {
                    "label": rule.tag,
                    "variant": rule.tag_variant or "danger",
                    "tooltip": warning,
                }
            )
        if not supported or (rule.vendors and vendor not in rule.vendors):
            continue
        if (
            rule.minimum_compute_capability is not None
            and compute_capability is not None
            and compute_capability >= rule.minimum_compute_capability
        ):
            continue
        effect = rule.effect if rule.effect in {"unsupported", "not_recommended", "warning"} else "warning"
        if effect == "unsupported":
            supported = False
            recommended = False
        elif effect == "not_recommended":
            recommended = False
        reason_code = rule.code or reason_code
        if warning:
            warnings.append(warning)

    return {
        "supported": supported,
        "recommended": recommended,
        "reason_code": reason_code,
        "warning": "\n\n".join(dict.fromkeys(warnings)),
        "backend": normalized_backend,
        "gpu_vendor": vendor,
        "compute_capability": format_compute_capability(compute_capability),
        "hardware_tags": hardware_tags,
    }
