from __future__ import annotations

import os
import sys
import time
from typing import Tuple, Optional

import numpy as np

from main_logger import logger
from utils.gpu_utils import check_gpu_provider
from utils.pip_installer import PipInstaller


# --- Константы модели ---
MODEL_NAME = "Snowflake/snowflake-arctic-embed-m-v2.0"
QUERY_PREFIX = "query: "


def _ensure_checkpoints_dir() -> str:
    script_dir = os.path.dirname(sys.executable)
    checkpoints_dir = os.path.join(script_dir, "checkpoints")
    os.makedirs(checkpoints_dir, exist_ok=True)
    return checkpoints_dir


checkpoints_dir = _ensure_checkpoints_dir()


def _get_default_pip_installer() -> Optional[PipInstaller]:
    try:
        return PipInstaller(
            script_path=r"libs\python\python.exe",
            libs_path="Lib",
            update_log=logger.info
        )
    except Exception:
        return None


def _ensure_lib_on_path():
    lib_path = os.path.abspath("Lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def _ensure_torch_and_transformers(pip_installer: Optional[PipInstaller] = None) -> None:
    """
    Гарантирует, что torch/transformers доступны.
    НЕ вызывается на import-time, только когда реально нужен EmbeddingModelHandler.
    """
    _ensure_lib_on_path()

    try:
        import torch  # noqa: F401
    except Exception:
        pip_installer = pip_installer or _get_default_pip_installer()
        if pip_installer is None:
            raise

        try:
            current_gpu = check_gpu_provider() or "CPU"
        except Exception:
            current_gpu = "CPU"

        if current_gpu == "NVIDIA":
            ok = pip_installer.install_package(
                ["torch==2.7.1", "torchaudio==2.7.1"],
                description="Installing PyTorch with CUDA (cu128)...",
                extra_args=["--index-url", "https://download.pytorch.org/whl/cu128"]
            )
        else:
            ok = pip_installer.install_package(
                ["torch==2.7.1", "torchaudio==2.7.1"],
                description="Installing PyTorch CPU...",
            )
        if not ok:
            raise RuntimeError("Failed to install torch/torchaudio")

    try:
        from transformers import AutoModel, AutoTokenizer  # noqa: F401
    except Exception:
        pip_installer = pip_installer or _get_default_pip_installer()
        if pip_installer is None:
            raise

        ok = pip_installer.install_package("transformers>=4.45.2", "Installing transformers>=4.45.2")
        if not ok:
            raise RuntimeError("Failed to install transformers")


class EmbeddingModelHandler:
    """
    Управляет загрузкой модели Snowflake и получением эмбеддингов.

    Важно:
      - никаких тяжёлых импортов/установок на уровне модуля
      - зависимости подтягиваются (при необходимости) в момент создания инстанса
    """

    def __init__(self, model_name: str = MODEL_NAME, *, pip_installer: Optional[PipInstaller] = None):
        self.model_name = model_name
        self._pip_installer = pip_installer

        _ensure_torch_and_transformers(self._pip_installer)

        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._AutoModel = AutoModel
        self._AutoTokenizer = AutoTokenizer

        self.device = self._get_device()
        self.tokenizer, self.model = self._load_model()
        self.hidden_size = self.model.config.hidden_size

    def _get_device(self):
        # Оставляем принудительный CPU как в оригинале
        try:
            if self._torch.cuda.is_available():
                cuda_visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
                if cuda_visible_devices == "" or cuda_visible_devices == "-1":
                    logger.info("CUDA доступна, но скрыта. Используется CPU.")
                    return self._torch.device("cpu")
                logger.info("CUDA доступна. Используется CPU принудительно.")
                return self._torch.device("cpu")
        except Exception:
            pass

        logger.info("CUDA недоступна. Используется CPU.")
        return self._torch.device("cpu")

    def _load_model(self) -> Tuple[object, object]:
        logger.info(f"Загрузка токенизатора и модели '{self.model_name}' на {self.device.type.upper()}...")
        logger.info(f"Модель будет сохранена в {checkpoints_dir}")
        start_time = time.time()

        tokenizer = self._AutoTokenizer.from_pretrained(self.model_name, cache_dir=checkpoints_dir)

        try:
            model = self._AutoModel.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                add_pooling_layer=False,
                attn_implementation="sdpa",
                use_memory_efficient_attention=False,
                cache_dir=checkpoints_dir
            )
            logger.info("Модель успешно загружена с attn_implementation='sdpa'.")
        except ValueError as ve:
            sdpa_errors = [
                "SDPA implementation requires",
                "Cannot use SDPA on CPU",
                "Torch SDPA backend requires torch>=2.0",
                "flash attention is not available",
                "requires a GPU",
                "No available kernel",
            ]
            if any(msg in str(ve) for msg in sdpa_errors):
                logger.error(f"SDPA недоступна, fallback на eager: {ve}")
                model = self._AutoModel.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    add_pooling_layer=False,
                    attn_implementation="eager",
                    use_memory_efficient_attention=False,
                    cache_dir=checkpoints_dir
                )
                logger.info("Модель успешно загружена с attn_implementation='eager'.")
            else:
                raise
        except Exception:
            raise

        model.eval()
        model.to(self.device)

        end_time = time.time()
        logger.info(f"Токенизатор и модель загружены за {end_time - start_time:.2f} секунд.")
        actual_attn_impl = getattr(model.config, "_attn_implementation", "unknown")
        logger.info(f"Фактическая реализация внимания: {actual_attn_impl}")
        return tokenizer, model

    def get_embedding(self, text: str, prefix: str = QUERY_PREFIX) -> Optional[np.ndarray]:
        if not text:
            return None

        try:
            inputs = [prefix + text]
            tokens = self.tokenizer(
                inputs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512
            ).to(self.device)

            with self._torch.no_grad():
                outputs = self.model(**tokens)
                embedding = outputs.last_hidden_state[:, 0]

            normalized = self._torch.nn.functional.normalize(embedding, p=2, dim=1)
            return normalized.cpu().numpy()[0]

        except Exception as e:
            logger.error(f"Ошибка при вычислении эмбеддинга: {e}", exc_info=True)
            return None