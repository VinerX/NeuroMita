"""Compatibility helpers for loading Silero VAD on Windows."""

from __future__ import annotations

from importlib import resources
from typing import Any

from utils.native_paths import NativePathError, path_for_native_loader


def load_silero_vad_compatible() -> Any:
    """Load the bundled JIT VAD model through a native-path-compatible path."""

    try:
        from silero_vad.model import init_jit_model
    except (ImportError, ModuleNotFoundError):
        # Keep lightweight tests and older package layouts compatible.
        from silero_vad import load_silero_vad

        return load_silero_vad()

    model_resource = resources.files("silero_vad.data").joinpath("silero_vad.jit")
    try:
        with resources.as_file(model_resource) as model_path:
            native_path = path_for_native_loader(model_path)
            return init_jit_model(native_path)
    except NativePathError as exc:
        raise RuntimeError(f"Silero VAD model path is not native-loader compatible: {exc}") from exc
