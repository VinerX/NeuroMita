"""Общая логика установки PyTorch с учётом наличия CUDA.

Используется из трёх мест:
 - `src/handlers/voice_models/install_plan_helpers.py` (план установки голосов/ASR)
 - `src/handlers/embedding_handler.py` (runtime-бутстрап эмбеддера)
 - `src/managers/rag/pipeline/cross_encoder.py` (страховка для standalone)

Модуль НЕ импортирует `torch` — только `importlib.metadata`, чтобы можно было
проверить уже установленный вариант без загрузки расширений в процесс.
Это важно: если torch уже импортирован, переустановка не заменит нативные
расширения в текущем процессе.
"""
from __future__ import annotations

from typing import Optional

TORCH_VERSION = "2.7.1"
TORCH_PACKAGES = [f"torch=={TORCH_VERSION}", f"torchaudio=={TORCH_VERSION}"]
CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu128"


def get_installed_torch_variant() -> Optional[str]:
    """Возвращает 'cuda', 'cpu' или None.

    Читает версию через `importlib.metadata.version('torch')` — без импорта
    самого torch. Для колёс с pytorch.org это обычно '2.7.1+cpu' или
    '2.7.1+cu128'. Подстрока '+cu' однозначно указывает на CUDA-билд.
    При отсутствии локального идентификатора (т.е. версия вида '2.7.1')
    считаем, что это CPU-билд (стандартный PyPI torch на Windows — CPU).
    """
    try:
        import importlib.metadata as _im
    except Exception:
        return None
    try:
        ver = _im.version("torch")
    except Exception:
        return None
    if not ver:
        return None
    if "+cu" in ver:
        return "cuda"
    return "cpu"


def decide_torch_install(gpu_vendor: str) -> dict:
    """Решает, что делать с torch для данного вендора GPU.

    Возвращает словарь одного из трёх видов:
      {'action': 'skip',      'reason': '...'}
      {'action': 'install',   'extra_args': [...] | None, 'description': '...'}
      {'action': 'reinstall', 'extra_args': [...] | None, 'description': '...'}

    Логика:
      gpu == 'NVIDIA':
          installed == 'cuda' -> skip (ничего не делаем)
          installed == 'cpu'  -> reinstall в cu128 (снести + поставить)
          installed is None   -> install cu128 (чистая установка)
      gpu != 'NVIDIA':
          installed is None   -> install cpu
          installed == 'cuda' -> skip (не даунгрейдим — CUDA-билд работает и без GPU)
          installed == 'cpu'  -> skip
    """
    gpu = str(gpu_vendor or "CPU").upper()
    installed = get_installed_torch_variant()

    if gpu == "NVIDIA":
        if installed == "cuda":
            return {"action": "skip", "reason": "PyTorch с CUDA уже установлен"}
        if installed == "cpu":
            return {
                "action": "reinstall",
                "extra_args": ["--index-url", CUDA_INDEX_URL],
                "description": "Переустановка PyTorch: CPU → CUDA (cu128)...",
            }
        # installed is None
        return {
            "action": "install",
            "extra_args": ["--index-url", CUDA_INDEX_URL],
            "description": "Установка PyTorch с CUDA (cu128)...",
        }

    # non-NVIDIA
    if installed is None:
        return {
            "action": "install",
            "extra_args": None,
            "description": "Установка PyTorch CPU...",
        }
    return {"action": "skip", "reason": f"PyTorch уже установлен ({installed})"}
