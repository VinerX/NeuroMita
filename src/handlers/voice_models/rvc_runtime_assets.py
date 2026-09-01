from __future__ import annotations

from typing import Iterable

from core.app_paths import base_dir
from core.install_requirements import InstallRequirement
from core.install_types import InstallAction


RuntimeAsset = tuple[str, str]

_RVC_ASSET_BASE_URL = "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main"

CUDA_RVC_RUNTIME_ASSETS: tuple[RuntimeAsset, ...] = (
    ("hubert_base.pt", f"{_RVC_ASSET_BASE_URL}/hubert_base.pt"),
    ("rmvpe.pt", f"{_RVC_ASSET_BASE_URL}/rmvpe.pt"),
)

ONNX_RVC_RUNTIME_ASSETS: tuple[RuntimeAsset, ...] = (
    (
        "vec-768-layer-12.onnx",
        "https://huggingface.co/NaruseMioShirakana/MoeSS-SUBModel/resolve/main/vec-768-layer-12.onnx",
    ),
    ("rmvpe.onnx", f"{_RVC_ASSET_BASE_URL}/rmvpe.onnx"),
)


def runtime_asset_path(filename: str) -> str:
    return str(base_dir() / filename)


def runtime_asset_requirements(
    assets: Iterable[RuntimeAsset],
    *,
    id_prefix: str = "rvc_asset",
) -> list[InstallRequirement]:
    return [
        InstallRequirement(
            id=f"{id_prefix}_{filename}",
            kind="file",
            path_fn=lambda _ctx, name=filename: runtime_asset_path(name),
            required=True,
        )
        for filename, _url in assets
    ]


def runtime_asset_download_action(
    assets: Iterable[RuntimeAsset],
    *,
    description: str,
    progress: int,
    progress_to: int,
) -> InstallAction:
    return InstallAction(
        type="download_http",
        description=description,
        progress=progress,
        progress_to=progress_to,
        files=[
            {"url": url, "dest": runtime_asset_path(filename)}
            for filename, url in assets
        ],
    )
