# Файл с моделью для эмбеддингов
from __future__ import annotations

import os
import sys
import time
from threading import Lock
from typing import TYPE_CHECKING, ClassVar, List, Optional, Tuple

import numpy as np

from main_logger import logger
from managers.settings_manager import SettingsManager

if TYPE_CHECKING:
    import torch
    from transformers import AutoModel, AutoTokenizer


def getTranslationVariant(ru_str, en_str=""):
    lang = SettingsManager.get("LANGUAGE", "RU")
    if en_str and lang == "EN":
        return en_str
    return ru_str


_ = getTranslationVariant



# --- Константы модели ---
MODEL_NAME = "Snowflake/snowflake-arctic-embed-m-v2.0"
QUERY_PREFIX = "query: "


def _ensure_checkpoints_dir() -> str:
    checkpoints_dir = os.environ.get(
        "NEUROMITA_CHECKPOINTS_DIR",
        os.path.join(os.environ.get("NEUROMITA_BASE_DIR", os.path.dirname(sys.executable)), "checkpoints")
    )
    os.makedirs(checkpoints_dir, exist_ok=True)
    return checkpoints_dir


checkpoints_dir = _ensure_checkpoints_dir()


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
        import gc
        import torch

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

    # Decoder-only model types that need last-token pooling instead of CLS
    _DECODER_TYPES = frozenset({
        "qwen3", "qwen2", "qwen", "llama", "mistral", "falcon", "gpt2",
        "gpt_neox", "bloom", "opt", "gemma", "gemma2", "phi", "phi3",
        "stablelm", "mpt", "rwkv",
    })

    def __init__(self, model_name: str = MODEL_NAME, query_prefix: str = ""):
        self.model_name = model_name
        self.query_prefix = query_prefix if query_prefix else QUERY_PREFIX
        self.device = self._get_device()
        self.tokenizer, self.model = self._load_model()
        self.hidden_size = self.model.config.hidden_size  # Сохраняем размерность
        # Detect pooling strategy: CLS (encoder) vs last-token (decoder)
        model_type = getattr(self.model.config, "model_type", "").lower()
        self._use_last_token_pooling = model_type in self._DECODER_TYPES
        if self._use_last_token_pooling:
            logger.info(f"EmbeddingModelHandler: using last-token pooling for decoder model '{model_type}'")

    def _get_device(self) -> "torch.device":
        """Определяет устройство для вычислений (CPU/GPU)."""
        import torch  # локальный импорт
        if torch.cuda.is_available():
            cuda_visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
            if cuda_visible_devices in ("", "-1"):
                logger.info("CUDA доступна, но скрыта (CUDA_VISIBLE_DEVICES). Используется CPU.")
                return torch.device('cpu')
            logger.info(f"CUDA доступна: {torch.cuda.get_device_name(0)}. Используется GPU.")
            return torch.device('cuda')
        logger.info("CUDA недоступна. Используется CPU.")
        return torch.device('cpu')

    def _model_is_cached(self) -> bool:
        """Модель уже локально: либо это путь к папке, либо есть HF-кэш
        `models--<repo>` в checkpoints (туда же качает AI Hub)."""
        name = str(self.model_name or "")
        if not name:
            return False
        if os.path.isdir(name):
            return True
        marker = os.path.join(checkpoints_dir, "models--" + name.replace("/", "--"))
        return os.path.isdir(marker)

    def _load_model(self) -> Tuple["AutoTokenizer", "AutoModel"]:
        """Загружает модель и токенизатор.

        Если веса уже в кэше — грузим офлайн (`local_files_only=True`), иначе
        `from_pretrained` каждый раз дёргает HF Hub за метаданными ревизии
        (то самое `unauthenticated requests to the HF Hub`), что без токена под
        троттлингом висит и роняет запрос в таймаут даже при скачанной модели.
        На случай неполного кэша — фоллбэк на онлайн-загрузку."""
        cached = self._model_is_cached()
        try:
            return self._load_model_impl(local_files_only=cached)
        except Exception as e:
            if cached:
                logger.warning(
                    f"Офлайн-загрузка модели не удалась ({e}); повтор с обращением к HF Hub."
                )
                return self._load_model_impl(local_files_only=False)
            raise

    def _load_model_impl(self, *, local_files_only: bool) -> Tuple["AutoTokenizer", "AutoModel"]:
        """Загружает модель и токенизатор с указанными параметрами."""
        from transformers import AutoModel, AutoTokenizer  # локальные импорты

        logger.info(
            f"Загрузка токенизатора и модели '{self.model_name}' на {self.device.type.upper()} "
            f"(local_files_only={local_files_only})..."
        )
        logger.info(f"Модель будет сохранена в {checkpoints_dir}")
        start_time = time.time()

        # HF_TOKEN для быстрой загрузки / gated-моделей
        hf_token = str(SettingsManager.get("HF_TOKEN", "") or "").strip() or None

        # Используем папку checkpoints для кэширования
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            cache_dir=checkpoints_dir,
            token=hf_token,
            local_files_only=local_files_only,
        )

        # Цепочка загрузки: sdpa+extras → sdpa → eager → базовая
        # use_memory_efficient_attention и add_pooling_layer — специфичны для Snowflake,
        # другие модели (XLMRoberta и т.д.) их не поддерживают.
        _base = dict(
            trust_remote_code=True,
            cache_dir=checkpoints_dir,
            token=hf_token,
            local_files_only=local_files_only,
        )
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
        actual_attn_impl = getattr(model.config, "_attn_implementation", "unknown")
        logger.info(f"Фактическая реализация внимания: {actual_attn_impl}")
        return tokenizer, model

    @staticmethod
    def _pool(last_hidden_state, attention_mask, use_last_token: bool):
        """Select embedding vector: CLS token or last non-padding token."""
        import torch
        if use_last_token:
            # Last non-padding token index per sequence
            seq_len = attention_mask.sum(dim=1) - 1  # (batch,)
            batch_idx = torch.arange(last_hidden_state.size(0), device=last_hidden_state.device)
            return last_hidden_state[batch_idx, seq_len]
        else:
            return last_hidden_state[:, 0]

    def get_embedding(self, text: str, prefix: str = "") -> Optional[np.ndarray]:
        """Получает нормализованный эмбеддинг для одного текста."""
        import torch  # локальный импорт
        if not text:
            return None
        if not prefix:
            prefix = self.query_prefix
        try:
            inputs = [prefix + text]
            tokens = self.tokenizer(inputs, padding=True, truncation=True, return_tensors='pt', max_length=512).to(
                self.device)
            # Явно задаём position_ids: padding-токены получают позицию последнего реального токена
            # (безопасно, т.к. attention_mask=0 их маскирует). Это обходит баг в custom RoPE
            # Snowflake/snowflake-arctic-embed-m-v2.0 при некоторых версиях torch/transformers.
            tokens["position_ids"] = (tokens["attention_mask"].cumsum(-1) - 1).clamp(min=0)
            with torch.no_grad():
                outputs = self.model(**tokens)
                embedding = self._pool(outputs.last_hidden_state, tokens["attention_mask"], self._use_last_token_pooling)
            normalized_embedding = torch.nn.functional.normalize(embedding.to(torch.float32), p=2, dim=1)
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
                    # Явно задаём position_ids — обход бага в custom RoPE Snowflake
                    # при некоторых версиях torch/transformers (мусорные значения в position_ids).
                    tokens["position_ids"] = (tokens["attention_mask"].cumsum(-1) - 1).clamp(min=0)

                    outputs = self.model(**tokens)
                    embedding = self._pool(outputs.last_hidden_state, tokens["attention_mask"], self._use_last_token_pooling)
                    normalized = torch.nn.functional.normalize(embedding.to(torch.float32), p=2, dim=1)
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
