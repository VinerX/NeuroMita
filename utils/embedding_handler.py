# Файл с моделью для эмбеддингов

from utils.GpuUtils import check_gpu_provider
from utils.PipInstaller import PipInstaller
import sys, os

current_gpu = check_gpu_provider()

from SettingsManager import SettingsManager

script_dir = os.path.dirname(sys.executable)  
checkpoints_dir = os.path.join(script_dir, "checkpoints")
os.makedirs(checkpoints_dir, exist_ok=True)

def getTranslationVariant(ru_str, en_str=""):
    lang = SettingsManager.get("LANGUAGE", "RU")
    if en_str and lang == "EN":
        return en_str
    return ru_str

_ = getTranslationVariant

from Logger import logger

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


try:
    import torch
except ImportError:
    if pip_installer == None:
        raise Exception("PipInstaller не инициализирован - установку нельзя осуществить")
    if current_gpu in ["NVIDIA"]:
        success = pip_installer.install_package(
                ["torch==2.6.0", "torchaudio==2.6.0"],
                description=_("Установка PyTorch с поддержкой CUDA 12.4...", "Installing PyTorch with CUDA 12.4 support..."),
                extra_args=["--index-url", "https://download.pytorch.org/whl/cu124"]
            )
    else:
        success = pip_installer.install_package(
                ["torch==2.6.0", "torchaudio==2.6.0"],
                description=_("Установка PyTorch CPU", "Installing PyTorch CPU"),
            )
    if not success:
        raise Exception("Не удалось установить torch+cuda12.4")
    
    try:
        import torch
    except ImportError:
        raise ImportError("Даже после установки TORCH - не получилось импортировать.")
        

    

        
    
try:
    from transformers import AutoModel, AutoTokenizer
except ImportError:
    if pip_installer == None:
        raise Exception("PipInstaller не инициализирован - установку нельзя осуществить")
    success = pip_installer.install_package("transformers>=4.45.2", "Установка transformers>=4.45.2")
    if not success:
        raise Exception("Не удалось установить transformers>=4.45.2")
    try:
        from transformers import AutoModel, AutoTokenizer
    except ImportError:
        raise ImportError("Даже после установки TRANSFORMERS - не получилось импортировать.")
    
from Logger import logger
import numpy as np
import time
import os
from typing import Tuple, Optional

# --- Константы модели ---
MODEL_NAME = 'Snowflake/snowflake-arctic-embed-m-v2.0'
QUERY_PREFIX = 'query: '

class EmbeddingModelHandler:
    """Управляет загрузкой модели Snowflake и получением эмбеддингов."""
    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self.device = self._get_device()
        self.tokenizer, self.model = self._load_model()
        self.hidden_size = self.model.config.hidden_size # Сохраняем размерность

    def _get_device(self) -> torch.device:
        """Определяет устройство для вычислений (CPU/GPU)."""
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

    def _load_model(self) -> Tuple[AutoTokenizer, AutoModel]:
        """Загружает модель и токенизатор с указанными параметрами."""
        logger.info(f"Загрузка токенизатора и модели '{self.model_name}' на {self.device.type.upper()}...")
        logger.info(f"Модель будет сохранена в {checkpoints_dir}")
        start_time = time.time()
        
        # Используем папку checkpoints для кэширования
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_name, 
            cache_dir=checkpoints_dir
        )
        
        try:
            model = AutoModel.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                add_pooling_layer=False,
                attn_implementation="sdpa",
                use_memory_efficient_attention=False,
                cache_dir=checkpoints_dir  # Добавлено для локального кэширования
            )
            logger.info("Модель успешно загружена с attn_implementation='sdpa'.")
        except ValueError as ve:
            # Тот же обработчик ошибок, но с добавленным cache_dir
            sdpa_errors = ["SDPA implementation requires", "Cannot use SDPA on CPU", "Torch SDPA backend requires torch>=2.0", "flash attention is not available", "requires a GPU", "No available kernel"]
            if any(error_msg in str(ve) for error_msg in sdpa_errors):
                logger.error(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось использовать 'sdpa'. Переключаемся на 'eager'. (Ошибка: {ve})")
                model = AutoModel.from_pretrained(
                    self.model_name,
                    trust_remote_code=True,
                    add_pooling_layer=False,
                    attn_implementation="eager",
                    use_memory_efficient_attention=False,
                    cache_dir=checkpoints_dir  # Добавлено для локального кэширования
                )
                logger.info("Модель успешно загружена с attn_implementation='eager'.")
            else:
                logger.error(f"Непредвиденная ошибка ValueError при загрузке модели: {ve}")
                raise ve
        except Exception as e:
            logger.error(f"Критическая ошибка при загрузке модели: {e}")
            raise e

        model.eval()
        model.to(self.device)
        end_time = time.time()
        logger.info(f"Токенизатор и модель загружены за {end_time - start_time:.2f} секунд.")
        actual_attn_impl = getattr(model.config, '_attn_implementation', 'Не удалось определить')
        logger.info(f"Фактическая реализация внимания: {actual_attn_impl}")
        return tokenizer, model

    def get_embedding(self, text: str, prefix: str = QUERY_PREFIX) -> Optional[np.ndarray]:
        """Получает нормализованный эмбеддинг для одного текста."""
        if not text:
            return None
        try:
            inputs = [prefix + text]
            # Используем self.tokenizer и self.model
            tokens = self.tokenizer(inputs, padding=True, truncation=True, return_tensors='pt', max_length=512).to(self.device)
            with torch.no_grad():
                outputs = self.model(**tokens)
                embedding = outputs.last_hidden_state[:, 0]
            normalized_embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)
            return normalized_embedding.cpu().numpy()[0]
        except Exception as e:
            logger.error(f"Ошибка при вычислении эмбеддинга для текста '{text}': {e}")
            return None

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