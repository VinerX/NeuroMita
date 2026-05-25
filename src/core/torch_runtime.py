from __future__ import annotations

from pathlib import Path
from typing import Optional

TORCH_VERSION = "2.7.1"
TORCH_PACKAGES = [f"torch=={TORCH_VERSION}", f"torchaudio=={TORCH_VERSION}"]
CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu128"


def has_cuda_libs(torch_target_dir: str | None) -> bool:
    if not torch_target_dir:
        return False

    root = Path(torch_target_dir)
    if not root.is_dir():
        return False

    patterns = (
        "torch/lib/cudart64*",
        "torch/lib/cublas64*",
        "torch/lib/libcudart*",
        "torch/lib/libcublas*",
        "torch/lib/cudnn*",
        "torch/lib/libcudnn*",
        "torch/lib/torch_cuda*",
        "torch/lib/c10_cuda*",
        "nvidia/*/bin/cudart64*",
        "nvidia/*/bin/cublas64*",
        "nvidia/*/bin/cudnn*",
        "nvidia/*/lib/libcudart*",
        "nvidia/*/lib/libcublas*",
        "nvidia/*/lib/libcudnn*",
    )
    for pattern in patterns:
        if any(root.glob(pattern)):
            return True
    return False


def get_installed_torch_variant(target_dir: Optional[str] = None) -> Optional[str]:
    def _variant_from_version(version: str, root: Optional[str] = None) -> str:
        if "+cu" not in str(version or ""):
            return "cpu"
        if root and not has_cuda_libs(root):
            return "cpu"
        return "cuda"

    if target_dir:
        root = Path(target_dir)
        if root.is_dir():
            matches = list(root.glob("torch-*.dist-info"))
            if matches:
                matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
                name = matches[0].name
                version = name[len("torch-"):-len(".dist-info")]
                return _variant_from_version(version, str(root))

    try:
        import importlib.metadata as importlib_metadata

        version = importlib_metadata.version("torch")
    except Exception:
        return None
    if not version:
        return None
    return _variant_from_version(version)


def decide_torch_install(gpu_vendor: str, target_dir: Optional[str] = None) -> dict:
    gpu = str(gpu_vendor or "CPU").upper()
    installed = get_installed_torch_variant(target_dir=target_dir)

    if gpu == "NVIDIA":
        if installed == "cuda":
            return {"action": "skip", "reason": "PyTorch с CUDA уже установлен"}
        if installed == "cpu":
            return {
                "action": "reinstall",
                "extra_args": ["--reinstall", "--index-url", CUDA_INDEX_URL],
                "description": "Переустановка PyTorch: CPU → CUDA (cu128)...",
            }
        return {
            "action": "install",
            "extra_args": ["--index-url", CUDA_INDEX_URL],
            "description": "Установка PyTorch с CUDA (cu128)...",
        }

    if installed is None:
        return {
            "action": "install",
            "extra_args": None,
            "description": "Установка PyTorch CPU...",
        }
    return {"action": "skip", "reason": f"PyTorch уже установлен ({installed})"}


def get_torch_runtime_status(gpu_vendor: str, target_dir: Optional[str] = None) -> dict:
    plan = decide_torch_install(gpu_vendor, target_dir=target_dir)
    variant = get_installed_torch_variant(target_dir=target_dir) or "missing"
    ok = str(plan.get("action") or "skip") == "skip"
    reason = str(plan.get("reason") or plan.get("description") or "")
    return {
        "id": "torch_runtime",
        "kind": "torch_runtime",
        "required": True,
        "ok": ok,
        "extra": {
            "action": plan.get("action"),
            "reason": reason,
            "gpu_vendor": gpu_vendor,
            "variant": variant,
        },
    }


def verify_torch_has_cuda() -> bool:
    try:
        import torch

        return getattr(torch.version, "cuda", None) is not None
    except Exception:
        return False
