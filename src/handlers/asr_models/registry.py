from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Any


_ENGINE_LOADERS: tuple[tuple[str, str], ...] = (
    ("google", "handlers.asr_models.google_recognizer:GoogleRecognizer"),
    ("gigaam", "handlers.asr_models.gigaam_recognizer:GigaAMRecognizer"),
    ("gigaam_onnx", "handlers.asr_models.gigaam_onnx_recognizer:GigaAMOnnxRecognizer"),
    ("whisper", "handlers.asr_models.whisper_recognizer:WhisperRecognizer"),
    ("whisper_onnx", "handlers.asr_models.whisper_onnx_recognizer:WhisperOnnxRecognizer"),
)


def engine_ids() -> tuple[str, ...]:
    return tuple(engine_id for engine_id, _loader in _ENGINE_LOADERS)


@lru_cache(maxsize=None)
def engine_class(engine_id: str):
    normalized = str(engine_id or "").strip()
    loader = dict(_ENGINE_LOADERS).get(normalized)
    if loader is None:
        return None
    module_name, _, qualname = loader.partition(":")
    target: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)
    return target


def engine_classes() -> dict[str, type]:
    return {
        engine_id: cls
        for engine_id in engine_ids()
        if (cls := engine_class(engine_id)) is not None
    }


def create_recognizer(engine_id: str, pip_installer, logger):
    cls = engine_class(engine_id)
    return cls(pip_installer, logger) if cls is not None else None


def create_installable_components() -> list[Any]:
    return [
        create_recognizer(engine_id, None, None)
        for engine_id in engine_ids()
    ]


__all__ = [
    "create_installable_components",
    "create_recognizer",
    "engine_class",
    "engine_classes",
    "engine_ids",
]
