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


def _has_cuda_libs(torch_pkg_dir: str) -> bool:
    """Проверяет наличие CUDA-библиотек в директории пакета torch.

    Это быстрая проверка БЕЗ импорта torch. Ищем характерные CUDA DLL/so файлы
    (cudart, cublas и т.д.) внутри torch/lib/. Если dist-info говорит cu128,
    а этих файлов нет — значит метаданные врут.
    """
    import glob as _glob
    import os as _os

    lib_dir = _os.path.join(torch_pkg_dir, "torch", "lib")
    if not _os.path.isdir(lib_dir):
        return False
    # На Windows — cudart64_*.dll, на Linux — libcudart.so*
    cuda_patterns = [
        _os.path.join(lib_dir, "cudart64*"),
        _os.path.join(lib_dir, "cublas64*"),
        _os.path.join(lib_dir, "libcudart*"),
        _os.path.join(lib_dir, "cudnn*"),
    ]
    for pat in cuda_patterns:
        if _glob.glob(pat):
            return True
    return False


def get_installed_torch_variant(target_dir: Optional[str] = None) -> Optional[str]:
    """Возвращает 'cuda', 'cpu' или None.

    Сначала ищет torch-*.dist-info в target_dir (если указан) — это папка
    куда pip/uv устанавливает через --target. Это позволяет получить точную
    версию, которая реально будет импортирована, игнорируя другие Python-окружения.

    Если dist-info говорит CUDA, дополнительно проверяет наличие реальных CUDA
    DLL в torch/lib/. Если DLL нет — возвращает 'cpu' (метаданные врут).

    Если target_dir не указан или dist-info там не найден — fallback на
    importlib.metadata (ищет по sys.path).

    Подстрока '+cu' в версии → CUDA-билд. Иначе → CPU.
    """
    import glob as _glob
    import os as _os

    def _variant_from_ver(ver: str, pkg_dir: Optional[str] = None) -> str:
        if "+cu" in ver:
            # Доверяй, но проверяй: есть ли реальные CUDA DLL?
            if pkg_dir and not _has_cuda_libs(pkg_dir):
                return "cpu"  # dist-info врёт
            return "cuda"
        return "cpu"

    if target_dir and _os.path.isdir(target_dir):
        matches = _glob.glob(_os.path.join(target_dir, "torch-*.dist-info"))
        if matches:
            # Берём самую свежую по времени изменения, если вдруг несколько
            matches.sort(key=_os.path.getmtime, reverse=True)
            di_name = _os.path.basename(matches[0])  # "torch-2.7.1+cu128.dist-info"
            ver = di_name[len("torch-"):-len(".dist-info")]
            return _variant_from_ver(ver, pkg_dir=target_dir)

    try:
        import importlib.metadata as _im
        ver = _im.version("torch")
    except Exception:
        return None
    if not ver:
        return None
    # Для fallback пути пытаемся найти torch пакет через importlib
    _pkg_dir = None
    try:
        import importlib.util as _iu
        _spec = _iu.find_spec("torch")
        if _spec and _spec.origin:
            _pkg_dir = _os.path.dirname(_os.path.dirname(_spec.origin))
    except Exception:
        pass
    return _variant_from_ver(ver, pkg_dir=_pkg_dir)


def decide_torch_install(gpu_vendor: str, target_dir: Optional[str] = None) -> dict:
    """Решает, что делать с torch для данного вендора GPU.

    target_dir — папка установки (--target), проверяется в первую очередь.
    Если None — используется только importlib.metadata.

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
    installed = get_installed_torch_variant(target_dir=target_dir)

    if gpu == "NVIDIA":
        if installed == "cuda":
            return {"action": "skip", "reason": "PyTorch с CUDA уже установлен"}
        if installed == "cpu":
            return {
                "action": "reinstall",
                "extra_args": [
                    "--reinstall",
                    "--index-url", CUDA_INDEX_URL,
                ],
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


def verify_torch_has_cuda() -> bool:
    """Проверяет РЕАЛЬНЫЙ загруженный torch на наличие CUDA.

    Вызывать ТОЛЬКО после `import torch`.
    Возвращает True если torch.version.cuda не None (т.е. бинарники собраны с CUDA).
    Это авторитетнее, чем dist-info метаданные, которые могут врать после
    неполной переустановки.
    """
    try:
        import torch
        return getattr(torch.version, "cuda", None) is not None
    except Exception:
        return False
