# Файл с моделью для эмбеддингов
from __future__ import annotations

from threading import Lock
from utils.gpu_utils import check_gpu_provider
from utils.pip_installer import PipInstaller
import sys, os
import importlib.util

current_gpu = check_gpu_provider()

from managers.settings_manager import SettingsManager

script_dir = os.path.dirname(sys.executable)
checkpoints_dir = os.path.join(script_dir, "checkpoints")
os.makedirs(checkpoints_dir, exist_ok=True)


def getTranslationVariant(ru_str, en_str=""):
    lang = SettingsManager.get("LANGUAGE", "RU")
    if en_str and lang == "EN":
        return en_str
    return ru_str


_ = getTranslationVariant

from main_logger import logger

def _module_available(name: str) -> bool:
    """Проверка наличия модуля без тяжёлого импорта."""
    return importlib.util.find_spec(name) is not None

try:
    pip_installer = PipInstaller(
        script_path=r"libs\python\python.exe",
        libs_path="Lib",
        update_log=logger.info
    )
    logger.info("PipInstaller успешно инициализирован.")
except Exception as e:
    logger.error(f"Не удалось инициализировать PipInstaller: {e}", exc_info=True)
    pip_installer = None

if not _module_available("torch"):
    if pip_installer == None:
        raise Exception("PipInstaller не инициализирован - установку нельзя осуществить")
    if current_gpu in ["NVIDIA"]:
        success = pip_installer.install_package(
            ["torch==2.7.1", "torchaudio==2.7.1"],
            description=_("Установка PyTorch с поддержкой CUDA 12.8...",
                          "Installing PyTorch with CUDA 12.8 support..."),
            extra_args=["--index-url", "https://download.pytorch.org/whl/cu128"]
        )
    else:
        success = pip_installer.install_package(
            ["torch==2.7.1", "torchaudio==2.7.1"],
            description=_("Установка PyTorch CPU", "Installing PyTorch CPU"),
        )
    if not success:
        raise Exception("Не удалось установить torch+cuda12.8")

if not _module_available("transformers"):
    if pip_installer == None:
        raise Exception("PipInstaller не инициализирован - установку нельзя осуществить")
    success = pip_installer.install_package("transformers>=4.45.2", "Установка transformers>=4.45.2")
    if not success:
        raise Exception("Не удалось установить transformers>=4.45.2")

from main_logger import logger
import numpy as np
import time
import os
from typing import Tuple, Optional, List
from typing import ClassVar

# --- Константы модели ---
MODEL_NAME = 'Snowflake/snowflake-arctic-embed-m-v2.0'
QUERY_PREFIX = 'query: '


class EmbeddingModelHandler:
    """Управляет загрузкой модели Snowflake и получением эмбеддингов."""

    # --- Process-wide shared instance (singleton) ---
    _shared_instance: ClassVar[Optional["EmbeddingModelHandler"]] = None
    _shared_lock: ClassVar[Lock] = Lock()

    @classmethod
    def shared(
        cls,
        model_name: str = "",
        query_prefix: str = "",
        reload_if_changed: bool = True,
    ) -> "EmbeddingModelHandler":
        """
        Возвращает общий (процессный) экземпляр EmbeddingModelHandler.
        Если model_name отличается от текущего — выгружает старую и создаёт новую.
        Пустой model_name = MODEL_NAME (default fallback).
        """
        if not model_name:
            model_name = MODEL_NAME
        if not query_prefix and model_name == MODEL_NAME:
            query_prefix = QUERY_PREFIX

        inst = cls._shared_instance
        if inst is not None:
            if reload_if_changed and getattr(inst, "model_name", None) != model_name:
                logger.info(
                    f"EmbeddingModelHandler.shared(): model changed "
                    f"'{getattr(inst, 'model_name', None)}' -> '{model_name}'. Reloading."
                )
                with cls._shared_lock:
                    cls._unload_shared()
                    cls._shared_instance = cls(
                        model_name=model_name,
                        query_prefix=query_prefix,
                    )
                    return cls._shared_instance
            return inst

        with cls._shared_lock:
            inst = cls._shared_instance
            if inst is None:
                cls._shared_instance = cls(
                    model_name=model_name,
                    query_prefix=query_prefix,
                )
            return cls._shared_instance

    @classmethod
    def _unload_shared(cls) -> None:
        """Выгружает текущий shared instance и освобождает память."""
        import torch
        import gc

        inst = cls._shared_instance
        if inst is None:
            return
        cls._shared_instance = None
        try:
            del inst.model
            del inst.tokenizer
        except Exception:
            pass
        del inst
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def __init__(self, model_name: str = MODEL_NAME, query_prefix: str = ""):
        import torch  # локальный импорт (ускоряет import модуля)
        self.model_name = model_name
        self.query_prefix = query_prefix if query_prefix else QUERY_PREFIX
        self.device = self._get_device()
        self.tokenizer, self.model = self._load_model()
        self.hidden_size = self.model.config.hidden_size  # Сохраняем размерность

    def _get_device(self) -> "torch.device":
        """Определяет устройство для вычислений (CPU/GPU)."""
        import torch  # локальный импорт
        logger.info("Проверка доступности CUDA (GPU):")
        if torch.cuda.is_available():
            cuda_visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
            if cuda_visible_devices == "" or cuda_visible_devices == "-1":
                logger.info("CUDA доступна, но скрыта. Используется CPU.")
                return torch.device('cpu')
            else:
                # ОСТАВЛЯЕМ ПРИНУДИТЕЛЬНЫЙ CPU, как и было
                logger.info("CUDA доступна. Используется CPU принудительно.")
                return torch.device('cpu')
        else:
            logger.info("CUDA недоступна. Используется CPU.")
            return torch.device('cpu')

    def _load_model(self) -> Tuple["AutoTokenizer", "AutoModel"]:
        """Загружает модель и токенизатор с указанными параметрами."""
        import torch  # локальный импорт
        from transformers import AutoModel, AutoTokenizer  # локальные импорты

        logger.info(f"Загрузка токенизатора и модели '{self.model_name}' на {self.device.type.upper()}...")
        logger.info(f"Модель будет сохранена в {checkpoints_dir}")
        start_time = time.time()

        # HF_TOKEN для быстрой загрузки / gated-моделей
        hf_token = str(SettingsManager.get("HF_TOKEN", "") or "").strip() or None

        # Используем папку checkpoints для кэширования
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            cache_dir=checkpoints_dir,
            token=hf_token,
        )

        # Цепочка загрузки: sdpa+extras → sdpa → eager → базовая
        # use_memory_efficient_attention и add_pooling_layer — специфичны для Snowflake,
        # другие модели (XLMRoberta и т.д.) их не поддерживают.
        _base = dict(trust_remote_code=True, cache_dir=checkpoints_dir, token=hf_token)
        _load_attempts = [
            {**_base, "add_pooling_layer": False, "attn_implementation": "sdpa", "use_memory_efficient_attention": False},
            {**_base, "add_pooling_layer": False, "attn_implementation": "sdpa"},
            {**_base, "attn_implementation": "sdpa"},
            {**_base, "add_pooling_layer": False, "attn_implementation": "eager"},
            {**_base, "attn_implementation": "eager"},
            {**_base},
        ]

        model = None
        last_err = None
        for i, kwargs in enumerate(_load_attempts):
            try:
                model = AutoModel.from_pretrained(self.model_name, **kwargs)
                attn = kwargs.get("attn_implementation", "default")
                logger.info(f"Модель загружена (attempt {i+1}, attn={attn}).")
                break
            except (TypeError, ValueError) as e:
                last_err = e
                logger.debug(f"Загрузка attempt {i+1} не удалась: {e}")
                continue

        if model is None:
            logger.error(f"Критическая ошибка при загрузке модели: все попытки провалены. Последняя ошибка: {last_err}")
            raise last_err

        model.eval()
        model.to(self.device)
        end_time = time.time()
        logger.info(f"Токенизатор и модель загружены за {end_time - start_time:.2f} секунд.")
        actual_attn_impl = getattr(model.config, '_attn_implementation', 'Не удалось определить')
        logger.info(f"Фактическая реализация внимания: {actual_attn_impl}")
        return tokenizer, model

    def get_embedding(self, text: str, prefix: str = "") -> Optional[np.ndarray]:
        """Получает нормализованный эмбеддинг для одного текста."""
        import torch  # локальный импорт
        if not text:
            return None
        if not prefix:
            prefix = self.query_prefix
        try:
            inputs = [prefix + text]
            # Используем self.tokenizer и self.model
            tokens = self.tokenizer(inputs, padding=True, truncation=True, return_tensors='pt', max_length=512).to(
                self.device)
            with torch.no_grad():
                outputs = self.model(**tokens)
                embedding = outputs.last_hidden_state[:, 0]
            normalized_embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)
            return normalized_embedding.cpu().numpy()[0]
        except Exception as e:
            logger.error(f"Ошибка при вычислении эмбеддинга для текста '{text}': {e}")
            return None

    def get_embeddings(
        self,
        texts: List[str],
        prefix: str = "",
        batch_size: int = 32,
    ) -> List[Optional[np.ndarray]]:
        """
        Batch-версия эмбеддингов:
        - один tokenizer + один forward на батч
        - сохраняет порядок
        - пустые/None -> None
        """
        import torch  # локальный импорт
        if not texts:
            return []
        if not prefix:
            prefix = self.query_prefix

        # Нормализуем вход и сохраняем индексы непустых
        norm_texts: List[str] = []
        valid_idx: List[int] = []
        valid_inputs: List[str] = []

        for i, t in enumerate(texts):
            s = "" if t is None else str(t)
            norm_texts.append(s)
            if s.strip():
                valid_idx.append(i)
                valid_inputs.append(prefix + s)

        # Если все пустые
        if not valid_inputs:
            return [None] * len(texts)

        if batch_size <= 0:
            batch_size = len(valid_inputs)

        results: List[Optional[np.ndarray]] = [None] * len(texts)

        try:
            with torch.no_grad():
                for start in range(0, len(valid_inputs), batch_size):
                    chunk_inputs = valid_inputs[start:start + batch_size]
                    chunk_indices = valid_idx[start:start + batch_size]

                    tokens = self.tokenizer(
                        chunk_inputs,
                        padding=True,
                        truncation=True,
                        return_tensors='pt',
                        max_length=512
                    ).to(self.device)

                    outputs = self.model(**tokens)
                    embedding = outputs.last_hidden_state[:, 0]
                    normalized = torch.nn.functional.normalize(embedding, p=2, dim=1)
                    arr = normalized.cpu().numpy()  # shape: (batch, hidden)

                    for j, orig_i in enumerate(chunk_indices):
                        results[orig_i] = arr[j]

            return results
        except Exception as e:
            logger.error(f"Ошибка при batch-вычислении эмбеддингов: {e}", exc_info=True)
            # В случае ошибки вернём список правильной длины
            return [None] * len(texts)


if __name__ == '__main__':
    print("Тестирование EmbeddingModelHandler...")
    try:
        handler = EmbeddingModelHandler()
        test_text = "проверка связи"
        emb = handler.get_embedding(test_text)
        if emb is not None:
            print(f"Эмбеддинг для '{test_text}' получен успешно, размерность: {emb.shape}")
        else:
            print(f"Не удалось получить эмбеддинг для '{test_text}'.")
    except Exception as e:
        print(f"Ошибка при тестировании EmbeddingModelHandler: {e}")