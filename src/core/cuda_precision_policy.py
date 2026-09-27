from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CudaHalfPrecisionDecision:
    allowed: bool
    reason: str
    compute_capability: int | None
    gpu_name: str


def _normalize_compute_capability(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        try:
            return int(value[0]) * 10 + int(value[1])
        except (TypeError, ValueError):
            return None
    if isinstance(value, int):
        return value if value >= 10 else value * 10
    if isinstance(value, float):
        return int(value * 10)

    text = str(value or "").strip().lower()
    match = re.search(r"(\d+)\D*(\d+)?", text)
    if match is None:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    if text.startswith("sm_"):
        return int(f"{major}{minor}") if match.group(2) else major
    return major * 10 + minor if major < 10 else major


def _sm75_tensor_core_sku(gpu_name: str) -> bool:
    """Distinguish the mixed Turing SM 7.5 family.

    Compute capability 7.5 alone is insufficient: RTX/T4 parts expose Tensor
    Cores, while GTX 16xx/T-series workstation parts based on TU116/TU117 do
    not. CUDA has no stable device attribute that directly reports Tensor Core
    presence, so name classification is intentionally limited to this one
    ambiguous SM generation.
    """

    name = str(gpu_name or "").upper()
    if "RTX" in name:
        return True
    return re.search(r"(?:^|\s)T4(?:\s|$)", name) is not None


def evaluate_rvc_half_precision(
    *,
    vendor: str,
    compute_capability: Any,
    gpu_name: str = "",
) -> CudaHalfPrecisionDecision:
    """Return whether RVC may use FP16 by default/runtime policy.

    This is deliberately stricter than "does CUDA implement FP16". RVC half
    mode is enabled only where Tensor-Core-class FP16 execution is known to be
    suitable. Unknown hardware fails closed to FP32.
    """

    normalized_vendor = str(vendor or "CPU").strip().upper()
    cc = _normalize_compute_capability(compute_capability)
    name = str(gpu_name or "").strip()

    if normalized_vendor != "NVIDIA":
        return CudaHalfPrecisionDecision(False, "non_nvidia", cc, name)
    if cc is None:
        return CudaHalfPrecisionDecision(False, "unknown_compute_capability", None, name)

    # Volta / Xavier have Tensor Cores; Pascal and older do not qualify for
    # this RVC policy even where scalar/native FP16 instructions exist.
    if cc in {70, 72}:
        return CudaHalfPrecisionDecision(True, "tensor_core_sm", cc, name)

    # Turing is the only relevant generation where one SM value spans both
    # Tensor-Core and non-Tensor-Core consumer/workstation SKUs.
    if cc == 75:
        if _sm75_tensor_core_sku(name):
            return CudaHalfPrecisionDecision(True, "sm75_tensor_core_sku", cc, name)
        return CudaHalfPrecisionDecision(False, "sm75_without_tensor_core_evidence", cc, name)

    if cc >= 80:
        return CudaHalfPrecisionDecision(True, "tensor_core_sm", cc, name)

    return CudaHalfPrecisionDecision(False, "compute_capability_below_tensor_core_policy", cc, name)
