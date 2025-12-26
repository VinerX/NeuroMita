import os
import sys
import importlib
import traceback
import tempfile
import soundfile as sf
import asyncio
import re
from xml.sax.saxutils import escape

from .base_model import IVoiceModel
from typing import Optional, Any
from main_logger import logger

import re
from PyQt6.QtCore import QTimer
from utils.pip_installer import PipInstaller

from core.events import get_event_bus, Events

from managers.settings_manager import SettingsManager

from utils import getTranslationVariant as _, get_character_voice_paths

from typing import Optional, Any, List, Dict

class EdgeTTS_RVC_Model(IVoiceModel):
    def __init__(self, parent: 'LocalVoice', model_id: str):
        # model_id здесь больше не используется для определения режима,
        # но остается для совместимости с интерфейсом.
        super().__init__(parent, model_id)
        self.tts_rvc_module = None
        self.current_tts_rvc = None
        self.current_silero_model = None
        self.current_silero_sample_rate = 48000
        self.events = get_event_bus()
        self._load_module()
        
    MODEL_CONFIGS = [
        {
            "id": "low",
            "name": "Edge-TTS + RVC",
            "min_vram": 3,
            "rec_vram": 4,
            "gpu_vendor": ["NVIDIA", "AMD"],
            "size_gb": 3,
            "languages": ["Russian", "English"],
            "intents": [_("Быстро", "Fast"), _("Низкие требования", "Low reqs")],
            "description": _(
                "Быстрая модель: Edge-TTS генерирует речь, RVC преобразует тембр. Низкие требования.",
                "Fast pipeline: Edge-TTS generates speech, RVC converts timbre. Low requirements."
            ),
            "settings": [
                {
                    "key": "device", "label": _("Устройство RVC", "RVC Device"), "type": "combobox",
                    "options": {
                        "values_nvidia": ["dml", "cuda:0", "cpu"],
                        "default_nvidia": "cuda:0",
                        "values_amd": ["dml", "cpu"],
                        "default_amd": "dml",
                        "values_other": ["cpu", "mps:0"],
                        "default_other": "cpu"
                    },
                    "help": _(
                        "Устройство для части RVC: 'cuda:0' — первая NVIDIA; 'dml' — DirectML (AMD/Intel); 'cpu' — процессор; 'mps:0' — Apple.",
                        "Compute device for RVC: 'cuda:0' — first NVIDIA; 'dml' — DirectML (AMD/Intel); 'cpu' — CPU; 'mps:0' — Apple."
                    )
                },
                {
                    "key": "is_half", "label": _("Half-precision RVC", "Half-precision RVC"),
                    "type": "combobox",
                    "options": {"values": ["True", "False"], "default_nvidia": "True", "default_amd": "False", "default_other": "False"},
                    "help": _(
                        "Половинная точность (float16) для ускорения и экономии VRAM на совместимых GPU.",
                        "Half precision (float16) for speed and VRAM saving on compatible GPUs."
                    )
                },
                {
                    "key": "f0method", "label": _("Метод F0 (RVC)", "F0 Method (RVC)"),
                    "type": "combobox",
                    "options": {
                        "values_nvidia": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"],
                        "default_nvidia": "rmvpe",
                        "values_amd": ["rmvpe", "harvest", "pm", "dio"],
                        "default_amd": "pm",
                        "values_other": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"],
                        "default_other": "pm"
                    },
                    "help": _(
                        "Алгоритм извлечения F0 (высоты тона): rmvpe/crepe — точнее, pm/harvest — быстрее.",
                        "F0 extraction algorithm: rmvpe/crepe — more accurate, pm/harvest — faster."
                    )
                },
                {"key": "pitch", "label": _("Высота голоса RVC (пт)", "RVC Pitch (semitones)"),
                "type": "entry", "options": {"default": "6"},
                "help": _("Смещение высоты в полутонах. 0 — без изменений.", "Pitch shift in semitones. 0 — no change.")},
                {"key": "use_index_file", "label": _("Исп. .index файл (RVC)", "Use .index file (RVC)"),
                "type": "checkbutton", "options": {"default": True},
                "help": _("Использовать .index для лучшего совпадения тембра.", "Use .index to better match voice timbre.")},
                {"key": "index_rate", "label": _("Соотношение индекса RVC", "RVC Index Rate"),
                "type": "entry", "options": {"default": "0.75"},
                "help": _("Степень влияния .index (0..1).", "How much .index affects result (0..1).")},
                {"key": "protect", "label": _("Защита согласных (RVC)", "Consonant Protection (RVC)"),
                "type": "entry", "options": {"default": "0.33"},
                "help": _("Защищает глухие согласные от искажения тоном (0..0.5).", "Protect voiceless consonants from pitch distortion (0..0.5).")},
                {"key": "tts_rate", "label": _("Скорость TTS (%)", "TTS Speed (%)"),
                "type": "entry", "options": {"default": "0"},
                "help": _("Скорость базового Edge-TTS в процентах.", "Base Edge-TTS speed in percent.")},
                {"key": "filter_radius", "label": _("Радиус фильтра F0 (RVC)", "F0 Filter Radius (RVC)"),
                "type": "entry", "options": {"default": "3"},
                "help": _("Сглаживание кривой F0 (рекоменд. ≥3).", "Smooth F0 curve (recommended ≥3).")},
                {"key": "rms_mix_rate", "label": _("Смешивание RMS (RVC)", "RMS Mixing (RVC)"),
                "type": "entry", "options": {"default": "0.5"},
                "help": _("Смешивание громкости исходника и RVC (0..1).", "Mix source loudness and RVC result (0..1).")},
                {"key": "volume", "label": _("Громкость (volume)", "Volume"),
                "type": "entry", "options": {"default": "1.0"},
                "help": _("Итоговая громкость.", "Final loudness.")}
            ]
        },
        {
            "id": "low+",
            "name": "Silero + RVC",
            "min_vram": 3,
            "rec_vram": 4,
            "gpu_vendor": ["NVIDIA", "AMD"],
            "size_gb": 3,
            "languages": ["Russian", "English"],
            "intents": [_("Быстро", "Fast"), _("Локальный синтез", "Offline synth")],
            "description": _(
                "Silero генерирует речь офлайн, RVC меняет тембр. Требования схожи с Edge-TTS + RVC.",
                "Silero generates speech offline, RVC converts timbre. Requirements similar to Edge-TTS + RVC."
            ),
            "settings": [
                {"key": "silero_rvc_device", "label": _("Устройство RVC", "RVC Device"), "type": "combobox",
                "options": {
                    "values_nvidia": ["dml", "cuda:0", "cpu"],
                    "default_nvidia": "cuda:0",
                    "values_amd": ["dml", "cpu"],
                    "default_amd": "dml",
                    "values_other": ["cpu", "dml"],
                    "default_other": "cpu"
                },
                "help": _("Устройство для RVC (см. выше).", "RVC device (see above).")},
                {"key": "silero_device", "label": _("Устройство Silero", "Silero Device"), "type": "combobox",
                "options": {"values_nvidia": ["cuda", "cpu"], "default_nvidia": "cuda", "values_amd": ["cpu"], "default_amd": "cpu", "values_other": ["cpu"], "default_other": "cpu"},
                "help": _("Устройство для Silero (GPU/CPU).", "Device for Silero (GPU/CPU).")},
                {"key": "silero_rvc_is_half", "label": _("Half-precision RVC", "Half-precision RVC"), "type": "combobox",
                "options": {"values": ["True", "False"], "default_nvidia": "True", "default_amd": "False", "default_other": "False"},
                "help": _("Половинная точность для RVC на совместимых GPU.", "Half precision for RVC on compatible GPUs.")},
                {"key": "silero_rvc_f0method", "label": _("Метод F0 (RVC)", "F0 Method (RVC)"), "type": "combobox",
                "options": { "values_nvidia": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"], "default_nvidia": "rmvpe", "values_amd": ["rmvpe", "harvest", "pm", "dio"], "default_amd": "pm", "values_other": ["pm", "rmvpe", "harvest", "dio"], "default_other": "pm" },
                "help": _("Выбор алгоритма F0 (точность/скорость).", "Choose F0 method (accuracy/speed).")},
                {"key": "silero_rvc_pitch", "label": _("Высота голоса RVC (пт)", "RVC Pitch (semitones)"), "type": "entry", "options": {"default": "6"},
                "help": _("Смещение высоты в полутонах.", "Pitch shift in semitones.")},
                {"key": "silero_rvc_use_index_file", "label": _("Исп. .index файл (RVC)", "Use .index file (RVC)"), "type": "checkbutton", "options": {"default": True},
                "help": _("Улучшает совпадение тембра.", "Improves timbre matching.")},
                {"key": "silero_rvc_index_rate", "label": _("Соотношение индекса RVC", "RVC Index Rate"), "type": "entry", "options": {"default": "0.75"},
                "help": _("Степень влияния .index (0..1).", "How much .index affects result (0..1).")},
                {"key": "silero_rvc_protect", "label": _("Защита согласных (RVC)", "Consonant Protection (RVC)"), "type": "entry", "options": {"default": "0.33"},
                "help": _("Защита глухих согласных (0..0.5).", "Protect voiceless consonants (0..0.5).")},
                {"key": "silero_rvc_filter_radius", "label": _("Радиус фильтра F0 (RVC)", "F0 Filter Radius (RVC)"), "type": "entry", "options": {"default": "3"},
                "help": _("Сглаживание кривой F0 (рекоменд. ≥3).", "Smooth F0 curve (recommended ≥3).")},
                {"key": "silero_rvc_rms_mix_rate", "label": _("Смешивание RMS (RVC)", "RMS Mixing (RVC)"), "type": "entry", "options": {"default": "0.5"},
                "help": _("Смешивание громкости исходника и RVC (0..1).", "Mix source loudness and RVC result (0..1).")},
                {"key": "silero_sample_rate", "label": _("Частота Silero", "Silero Sample Rate"), "type": "combobox",
                "options": {"values": ["48000", "24000", "16000"], "default": "48000"},
                "help": _("Частота дискретизации синтеза Silero.", "Silero synthesis sample rate.")},
                {"key": "silero_put_accent", "label": _("Акценты Silero", "Silero Accents"), "type": "checkbutton", "options": {"default": True},
                "help": _("Авторасстановка ударений.", "Automatic stress placement.")},
                {"key": "silero_put_yo", "label": _("Буква Ё Silero", "Silero Letter Yo"), "type": "checkbutton", "options": {"default": True},
                "help": _("Автозамена 'е' на 'ё' по словарю.", "Auto replace 'e' with 'yo'.")},
                {"key": "volume", "label": _("Громкость (volume)", "Volume"), "type": "entry", "options": {"default": "1.0"},
                "help": _("Итоговая громкость.", "Final loudness.")}
            ]
        }
    ]

    def get_model_configs(self) -> List[Dict[str, Any]]:
        return self.MODEL_CONFIGS

    def _load_module(self):
        if self.tts_rvc_module is not None:
            return

        if getattr(self, "_import_attempted", False):
            return

        self._import_attempted = True

        try:
            libs_path_abs = os.path.abspath("Lib")
            if libs_path_abs not in sys.path:
                sys.path.insert(0, libs_path_abs)

            from tts_with_rvc import TTS_RVC
            self.tts_rvc_module = TTS_RVC
            from silero import silero_tts
        except ImportError:
            self.tts_rvc_module = None
    
    def get_display_name(self) -> str:
        return "EdgeTTS+RVC / Silero+RVC"

    def is_installed(self, model_id) -> bool:
        if self.tts_rvc_module is None:
            self._load_module()
        return self.tts_rvc_module is not None

    def install(self, model_id) -> bool:
        try:
            progress_cb = getattr(self.parent, '_external_progress', lambda *_: None)
            status_cb = getattr(self.parent, '_external_status', lambda *_: None) 
            log_cb = getattr(self.parent, '_external_log', lambda *_: None)
            
            progress_cb(10)
            log_cb(_("Начало установки Edge-TTS + RVC...", "Starting Edge-TTS + RVC installation..."))

            installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_status=status_cb,
                update_log=log_cb,
                progress_window=None
            )

            if self.parent.provider in ["NVIDIA"] and not self.parent.is_cuda_available():
                status_cb(_("Установка PyTorch с поддержкой CUDA 12.8...", "Installing PyTorch with CUDA 12.8 support..."))
                progress_cb(20)
                success = installer.install_package(
                    ["torch==2.7.1", "torchaudio==2.7.1"],
                    description=_("Установка PyTorch с поддержкой CUDA 12.8...", "Installing PyTorch with CUDA 12.8 support..."),
                    extra_args=["--index-url", "https://download.pytorch.org/whl/cu128"],
                )

                if not success:
                    status_cb(_("Ошибка при установке PyTorch", "Error installing PyTorch"))
                    return False
                progress_cb(50)
            else:
                progress_cb(50)

            status_cb(_("Установка зависимостей...", "Installing dependencies..."))
            success = installer.install_package(
                "omegaconf",
                description=_("Установка omegaconf...", "Installing omegaconf...")
            )
            if not success:
                status_cb(_("Ошибка при установке omegaconf", "Error installing omegaconf"))
                return False
            
            success = installer.install_package(
                "silero",
                description=_("Установка библиотеки silero...", "Installing silero library...")
            )
            if not success:
                status_cb(_("Ошибка при установке silero", "Error installing silero"))
                return False

            progress_cb(70)

            package_spec = None
            desc = ""
            if self.parent.provider in ["NVIDIA"]:
                package_spec = "tts_with_rvc"
                desc = _("Установка основной библиотеки tts-with-rvc (NVIDIA)...", "Installing main library tts-with-rvc (NVIDIA)...")
            elif self.parent.provider in ["AMD"]:
                # ONNX + DirectML для AMD
                package_spec = "tts_with_rvc_onnx[dml]"
                desc = _("Установка основной библиотеки tts-with-rvc (AMD)...", "Installing main library tts-with-rvc (AMD)...")
            else:
                log_cb(_(f"Ошибка: не найдена подходящая видеокарта: {self.parent.provider}", f"Error: suitable graphics card not found: {self.parent.provider}"))
                return False

            success = installer.install_package(package_spec, description=desc)
            if not success:
                status_cb(_("Ошибка при установке tts-with-rvc", "Error installing tts-with-rvc"))
                return False

            libs_path_abs = os.path.abspath("Lib")
            progress_cb(95)
            status_cb(_("Применение патчей...", "Applying patches..."))
            config_path = os.path.join(libs_path_abs, "fairseq", "dataclass", "configs.py")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        source = f.read()
                    patched_source = re.sub(r"metadata=\{(.*?)help:", r'metadata={\1"help":', source)
                    with open(config_path, "w", encoding="utf-8") as f:
                        f.write(patched_source)
                    log_cb(_("Патч успешно применен к configs.py", "Patch successfully applied to configs.py"))
                except Exception as e:
                    log_cb(_(f"Ошибка при патче configs.py: {e}", f"Error patching configs.py: {e}"))
            
            progress_cb(100)

            # Сбрасываем флаг одноразового импорта и пробуем загрузить модуль заново
            setattr(self, "_import_attempted", False)
            self._load_module()
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке Edge-TTS + RVC: {e}", exc_info=True)
            return False

    def uninstall(self, model_id) -> bool:
        if self.parent.provider in ["NVIDIA"]:
            return self.parent._uninstall_component("EdgeTTS+RVC", "tts-with-rvc")
        else:
            return self.parent._uninstall_component("EdgeTTS+RVC", "tts-with-rvc-onnx")

    def cleanup_state(self):
        super().cleanup_state()
        self.current_tts_rvc = None
        self.current_silero_model = None
        self.tts_rvc_module = None
        self._import_attempted = True
        logger.info(f"Состояние для обработчика EdgeTTS/Silero+RVC сброшено.")
    
    
    def initialize(self, init: bool = False) -> bool:
        current_mode = self.parent.current_model_id
        logger.info(f"Запрос на инициализацию обработчика в режиме: '{current_mode}'")

        # Шаг 1: Инициализация базового RVC, если его еще нет
        if self.current_tts_rvc is None:
            logger.info("Инициализация базового компонента RVC...")
            if self.tts_rvc_module is None:
                logger.error("Модуль tts_with_rvc не установлен.")
                return False
            
            settings = self.parent.load_model_settings(current_mode)
            
            if current_mode == "low+":
                device = settings.get("silero_rvc_device", "cuda:0" if self.parent.provider == "NVIDIA" else "dml")
                f0_method = settings.get("silero_rvc_f0method", "rmvpe" if self.parent.provider == "NVIDIA" else "pm")
            else:
                device = settings.get("device", "cuda:0" if self.parent.provider == "NVIDIA" else "dml")
                f0_method = settings.get("f0method", "rmvpe" if self.parent.provider == "NVIDIA" else "pm")
            
            is_nvidia = self.parent.provider in ["NVIDIA"]
            model_ext = 'pth' if is_nvidia else 'onnx'
            default_model_path = os.path.join("Models", f"Mila.{model_ext}")
            
            model_path_to_use = self.parent.pth_path if self.parent.pth_path and os.path.exists(self.parent.pth_path) else default_model_path
            if not os.path.exists(model_path_to_use):
                logger.error(f"Не найден файл RVC модели: {model_path_to_use}")
                return False

            self.current_tts_rvc = self.tts_rvc_module(model_path=model_path_to_use, device=device, f0_method=f0_method)
            self._adjust_sampling_rate_for_amd()
            logger.info(f"Базовый компонент RVC инициализирован с device={device}, f0_method={f0_method}")
        
        # Обновляем голос EdgeTTS в RVC
        if self.parent.voice_language == "ru":
            self.current_tts_rvc.set_voice("ru-RU-SvetlanaNeural")
        else:
            self.current_tts_rvc.set_voice("en-US-MichelleNeural")

        # Шаг 2: Silero для режима low+
        if current_mode == "low+":
            if self.current_silero_model is None:
                logger.info("Требуется режим 'low+', инициализация компонента Silero...")
                try:
                    import torch
                    settings = self.parent.load_model_settings(current_mode)
                    silero_device = settings.get("silero_device", "cuda" if self.parent.provider == "NVIDIA" else "cpu")
                    self.current_silero_sample_rate = int(settings.get("silero_sample_rate", 48000))
                    language = 'en' if self.parent.voice_language == 'en' else 'ru'
                    model_id_silero = 'v3_en' if language == 'en' else 'v5_ru'
                    
                    logger.info(f"Загрузка модели Silero ({language}/{model_id_silero}) на устройство {silero_device}...")
                    
                    from silero import silero_tts
                    model, _ = silero_tts(language=language, speaker=model_id_silero)
                    
                    model.to(silero_device)
                    self.current_silero_model = model
                    logger.info("Компонент Silero для 'low+' успешно инициализирован.")
                except Exception as e:
                    logger.error(f"Ошибка инициализации компонента Silero: {e}", exc_info=True)
                    return False
        else:
            if self.current_silero_model is not None:
                logger.info("Переключение в режим без Silero. Выгрузка компонента Silero...")
                self.current_silero_model = None
                import gc
                gc.collect()

        # Готовность компонентов
        is_ready = self.current_tts_rvc is not None
        if current_mode == "low+":
            is_ready = is_ready and self.current_silero_model is not None

        if not is_ready:
            logger.error(f"Не все компоненты для модели '{current_mode}' удалось инициализировать.")
            self.initialized = False
            return False

        self.initialized = True

        # Тестовый прогон
        if init:
            init_text = f"Инициализация модели {current_mode}" if self.parent.voice_language == "ru" else f"{current_mode} Model Initialization"
            logger.info(f"Выполнение тестового прогона для {current_mode}...")
            try:
                results = self.events.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
                main_loop = results[0] if results else None
                if not main_loop or not main_loop.is_running():
                    raise RuntimeError("Главный цикл событий asyncio недоступен.")
                
                future = asyncio.run_coroutine_threadsafe(self.voiceover(init_text), main_loop)
                result_path = future.result(timeout=3600)

                # Успех только если файл создан и непустой
                if not result_path or not os.path.exists(result_path) or os.path.getsize(result_path) == 0:
                    logger.error("Тестовый прогон не создал аудиофайл — инициализация неуспешна.")
                    self.initialized = False
                    return False

                logger.info(f"Тестовый прогон для {current_mode} успешно завершен.")
            except Exception as e:
                logger.error(f"Ошибка во время тестового прогона модели {current_mode}: {e}", exc_info=True)
                self.initialized = False
                return False

        return self.initialized

    def _update_parent_paths(self, character=None):
        """Обновляет пути в parent на основе персонажа"""
        voice_paths = get_character_voice_paths(character, self.parent.provider)
        self.parent.pth_path = voice_paths['pth_path']
        self.parent.index_path = voice_paths['index_path']
        self.parent.clone_voice_filename = voice_paths['clone_voice_filename']
        self.parent.clone_voice_text = voice_paths['clone_voice_text']
        self.parent.current_character_name = voice_paths['character_name']
        logger.info(f"Обновлены пути в parent для персонажа: {voice_paths['character_name']}")

    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        current_mode = self.parent.current_model_id
        if not self.initialized:
            raise Exception(f"Обработчик не инициализирован для режима '{current_mode}'.")
        
        # Обновляем пути в parent перед озвучкой
        self._update_parent_paths(character)
            
        if current_mode == "low":
            return await self._voiceover_edge_tts_rvc(text, character, **kwargs)
        elif current_mode == "low+":
            return await self._voiceover_silero_rvc(text, character)
        else:
            raise ValueError(f"Обработчик вызван с неизвестным режимом: {current_mode}")

    async def apply_rvc_to_file(self, filepath: str, 
                               character: Optional[Any] = None,
                               pitch: float = 0,
                               index_rate: float = 0.75,
                               protect: float = 0.33,
                               filter_radius: int = 3,
                               rms_mix_rate: float = 0.5,
                               is_half: bool = True,
                               f0method: Optional[str] = None,
                               use_index_file: bool = True,
                               volume: str = "1.0",
                               original_model_id: Optional[str] = None) -> Optional[str]:
        """
        Применяет RVC к существующему аудиофайлу.
        
        Параметры:
        - filepath: путь к входному аудиофайлу
        - character: объект персонажа для получения путей к модели
        - pitch: изменение высоты тона (-24 до 24)
        - index_rate: коэффициент использования индексного файла (0.0 до 1.0)
        - protect: защита консонант от изменений (0.0 до 0.5)
        - filter_radius: радиус медианного фильтра (0 до 7)
        - rms_mix_rate: коэффициент смешивания RMS (0.0 до 1.0)
        - is_half: использовать половинную точность (только для NVIDIA)
        - f0method: метод извлечения основного тона (rmvpe, pm, harvest, crepe)
        - use_index_file: использовать индексный файл если доступен
        - original_model_id: ID исходной модели для конфигурации (устарело)
        """
        if not self.initialized:
            logger.info("Инициализация RVC компонента на лету...")
            if not self.initialize(init=False):
                logger.error("Не удалось инициализировать RVC компонент.")
                return None

        logger.info(f"Вызов RVC для файла: {filepath}")
        
        try:
            # Обновляем пути в parent
            self._update_parent_paths(character)
            
            # Получаем пути для персонажа
            voice_paths = get_character_voice_paths(character, self.parent.provider)
            model_path = voice_paths['pth_path']
            index_path = voice_paths['index_path']
            
            # Подготовка параметров инференса
            inference_params = {
                "pitch": pitch,
                "index_rate": index_rate,
                "protect": protect,
                "filter_radius": filter_radius,
                "rms_mix_rate": rms_mix_rate
            }
            
            if self.parent.provider == "NVIDIA":
                inference_params["is_half"] = is_half
                
            if f0method:
                inference_params["f0method"] = f0method
            
            # Установка индексного файла
            if use_index_file and index_path and os.path.exists(index_path):
                self.current_tts_rvc.set_index_path(index_path)
            else:
                self.current_tts_rvc.set_index_path("")
            
            self._adjust_sampling_rate_for_amd()

            # Обновление модели если необходимо
            if os.path.abspath(model_path) != os.path.abspath(self.current_tts_rvc.current_model):
                if self.parent.provider in ["NVIDIA"]:
                    self.current_tts_rvc.current_model = model_path
                elif self.parent.provider in ["AMD"]:
                    if hasattr(self.current_tts_rvc, 'set_model'):
                        self.current_tts_rvc.set_model(model_path)
                        logger.info(f'RVC модель изменена на: {model_path}')
                    else:
                        self.current_tts_rvc.current_model = model_path
                        logger.info(f'RVC модель изменена на: {model_path}')
                        logger.warning("Метод 'set_model' не найден, используется прямое присваивание (может не работать на AMD).")
            else:
                logger.info(f'RVC модель не изменилась: {model_path}')
            
            # Применение RVC
            output_file_rvc = self.current_tts_rvc.voiceover_file(input_path=filepath, **inference_params)
            
            if not output_file_rvc or not os.path.exists(output_file_rvc) or os.path.getsize(output_file_rvc) == 0:
                return None
            
            # Конвертация в стерео
            stereo_output_file = output_file_rvc.replace(".wav", "_stereo.wav")
            converted_file = self.parent.convert_wav_to_stereo(
                output_file_rvc, 
                stereo_output_file, 
                atempo=1.0, 
                volume=volume,
            )

            if converted_file and os.path.exists(converted_file):
                final_output_path = stereo_output_file
                try: os.remove(output_file_rvc)
                except OSError: pass
            else:
                final_output_path = output_file_rvc
            
            return final_output_path
            
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Ошибка при применении RVC к файлу: {error}")
            return None

    async def _voiceover_edge_tts_rvc(self, text, character=None, TEST_WITH_DONE_AUDIO: str = None, settings_model_id: Optional[str] = None):
        if self.current_tts_rvc is None:
            raise Exception("Компонент RVC не инициализирован.")
        try:
            config_id = settings_model_id if settings_model_id else self.parent.current_model_id
            settings = self.parent.load_model_settings(config_id)
            logger.info(f"RVC использует конфигурацию от модели: '{config_id}'")

            # Получаем пути для персонажа
            voice_paths = get_character_voice_paths(character, self.parent.provider)
            model_path = voice_paths['pth_path']
            index_path = voice_paths['index_path'] 
            character_name = voice_paths['character_name']

            # Получаем параметры из настроек
            pitch = float(settings.get("pitch", 0))
            if character_name == "Player" and config_id != "medium+low":
                pitch = -12
            
            index_rate = float(settings.get("index_rate", 0.75))
            protect = float(settings.get("protect", 0.33))
            filter_radius = int(settings.get("filter_radius", 3))
            rms_mix_rate = float(settings.get("rms_mix_rate", 0.5))
            is_half = settings.get("is_half", "True").lower() == "true"
            use_index_file = settings.get("use_index_file", True)
            f0method_override = settings.get("f0method", None)
            tts_rate = int(settings.get("tts_rate", 0)) if config_id != "medium+low" else 0
            vol = str(settings.get("volume", "1.0")) 

            if use_index_file and index_path and os.path.exists(index_path):
                self.current_tts_rvc.set_index_path(index_path)
            else:
                self.current_tts_rvc.set_index_path("")
            
            if self.parent.provider in ["NVIDIA"]:
                inference_params = {"pitch": pitch, "index_rate": index_rate, "protect": protect, "filter_radius": filter_radius, "rms_mix_rate": rms_mix_rate, "is_half": is_half}
            else:
                inference_params = {"pitch": pitch, "index_rate": index_rate, "protect": protect, "filter_radius": filter_radius, "rms_mix_rate": rms_mix_rate}
            if f0method_override:
                inference_params["f0method"] = f0method_override
            
            # Локальная переменная для отслеживания смены модели
            current_model_abs = os.path.abspath(self.current_tts_rvc.current_model)
            model_path_abs = os.path.abspath(model_path)
            
            if current_model_abs != model_path_abs:
                if self.parent.provider in ["NVIDIA"]:
                    self.current_tts_rvc.current_model = model_path
                elif self.parent.provider in ["AMD"]:
                    if hasattr(self.current_tts_rvc, 'set_model'):
                        self.current_tts_rvc.set_model(model_path)
                    else:
                        self.current_tts_rvc.current_model = model_path
                        logger.warning("Метод 'set_model' не найден, используется прямое присваивание (может не работать на AMD).")
                logger.info(f"RVC модель изменена на: {model_path}")

            self._adjust_sampling_rate_for_amd()

            if not TEST_WITH_DONE_AUDIO:
                inference_params["tts_rate"] = tts_rate
                output_file_rvc = self.current_tts_rvc(text=text, **inference_params)
            else:
                output_file_rvc = self.current_tts_rvc.voiceover_file(input_path=TEST_WITH_DONE_AUDIO, **inference_params)

            if not output_file_rvc or not os.path.exists(output_file_rvc) or os.path.getsize(output_file_rvc) == 0:
                return None
            
            stereo_output_file = output_file_rvc.replace(".wav", "_stereo.wav")
            converted_file = self.parent.convert_wav_to_stereo(output_file_rvc, 
                                                               stereo_output_file, 
                                                               atempo=1.0, 
                                                               volume=vol)

            if converted_file and os.path.exists(converted_file):
                final_output_path = stereo_output_file
                try: os.remove(output_file_rvc)
                except OSError: pass
            else:
                final_output_path = output_file_rvc

            connected_to_game = self.events.emit_and_wait(Events.Server.GET_GAME_CONNECTION)[0]
            if connected_to_game and TEST_WITH_DONE_AUDIO is None:
                self.events.emit(Events.Server.SET_PATCH_TO_SOUND_FILE, final_output_path)
            return final_output_path
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Edge-TTS + RVC: {error}")
            return None

    def _preprocess_text_to_ssml(self, text: str, character_name: str):
        lang = self.parent.voice_language
        defaults = {'en': {'pitch': 6, 'speaker': "en_88"}, 'ru': {'pitch': 2, 'speaker': "kseniya"}}
        lang_defaults = defaults.get(lang, defaults['en'])
        char_params = {
            'en': {"CappieMita": (6, "en_26"), "CrazyMita": (6, "en_60"), "GhostMita": (6, "en_33"), "Mila": (6, "en_88"), "MitaKind": (3, "en_33"), "ShorthairMita": (6, "en_60"), "SleepyMita": (6, "en_33"), "TinyMita": (2, "en_60"), "Player": (0, "en_27")},
            'ru': {"CappieMita": (6, "kseniya"), "MitaKind": (1, "kseniya"), "ShorthairMita": (2, "kseniya"), "CrazyMita": (2, "kseniya"), "Mila": (2, "kseniya"), "TinyMita": (-3, "baya"), "SleepyMita": (2, "baya"), "GhostMita": (1, "baya"), "Player": (0, "aidar")}
        }
        character_rvc_pitch, character_speaker = lang_defaults['pitch'], lang_defaults['speaker']
        character_short_name = character_name
        current_lang_params = char_params.get(lang, char_params['en'])
        if specific_params := current_lang_params.get(character_short_name):
            character_rvc_pitch, character_speaker = specific_params
        
        text = escape(re.sub(r'<[^>]*>', '', text))

        pattern = re.compile(
            r'\b'              # начало слова
            r'([MmМм])'        # первая буква M / m / М / м  (группа 1)
            r'([IiИи])'        # вторая буква i / и           (группа 2)
            r'([A-Za-zА-Яа-я]{2,3})'  # ещё 2-3 буквы          (группа 3)
            r'\b',             # конец слова
            re.IGNORECASE
        )

        def put_plus(match: re.Match) -> str:
            return f'{match.group(1)}+{match.group(2)}{match.group(3)}'
    
        text = pattern.sub(put_plus, text)

        parts = re.split(r'([.!?]+[^A-Za-zА-Яа-я0-9_]*)(\s+)', text.strip())
        processed_text = ""
        i = 0
        while i < len(parts):
            if text_part := parts[i]: processed_text += text_part
            if i + 2 < len(parts):
                if punctuation_part := parts[i+1]: processed_text += punctuation_part
                if (whitespace_part := parts[i+2]) and i + 3 < len(parts) and parts[i+3]: processed_text += f' <break time="300ms"/> '
                elif whitespace_part: processed_text += whitespace_part
            i += 3
        ssml_content = processed_text.strip()
        ssml_output = f'<speak><p>{ssml_content}</p></speak>' if ssml_content else '<speak></speak>'
        return ssml_output, character_rvc_pitch, character_speaker
    
    def _adjust_sampling_rate_for_amd(self):
        """
        Для AMD-ветки:
          • ShorthairMita  → 48 000 / 512
          • остальные      → 40 000 / 512
        Требует, чтобы в TTS_RVC был метод set_sampling_params(sr, hop).
        """
        if self.parent.provider != "AMD":
            return  # NVIDIA / CPU обходятся без костыля

        char = getattr(self.parent, "current_character_name", "Mila")
        sr, hop = (48000, 512) if char == "ShorthairMita" else (40000, 512)

        if hasattr(self.current_tts_rvc, "set_sampling_params"):
            self.current_tts_rvc.set_sampling_params(sr, hop)
            self.current_tts_rvc.sampling_rate = sr
            logger.info(f"[AMD] SR patched for '{char}': {sr}/{hop}")
        else:
            logger.warning("set_sampling_params() not found in TTS_RVC – "
                           "SR patch skipped.")

    async def _voiceover_silero_rvc(self, text, character=None):
        if self.current_silero_model is None or self.current_tts_rvc is None:
            raise Exception("Компоненты Silero или RVC не инициализированы для режима low+.")
        
        self.parent.current_character = character if character is not None else getattr(self.parent, 'current_character', None)
        temp_wav = None
        try:
            # Получаем пути для персонажа
            voice_paths = get_character_voice_paths(character, self.parent.provider)
            character_name = voice_paths['character_name']
            
            ssml_text, character_base_rvc_pitch, character_speaker = self._preprocess_text_to_ssml(text, character_name)
            settings = self.parent.load_model_settings('low+')
            
            # Параметры для Silero TTS
            audio_tensor = self.current_silero_model.apply_tts(
                ssml_text=ssml_text, 
                speaker=character_speaker, 
                sample_rate=self.current_silero_sample_rate,
                put_accent=settings.get("silero_put_accent", True), 
                put_yo=settings.get("silero_put_yo", True),
                put_stress_homo=settings.get("silero_put_accent", True),
                put_yo_homo=settings.get("silero_put_yo", True),
            )
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav_file:
                temp_wav = temp_wav_file.name
            sf.write(temp_wav, audio_tensor.cpu().numpy(), self.current_silero_sample_rate)
            
            if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) == 0:
                return None

            # Подготовка параметров RVC для Silero
            base_rvc_pitch_from_settings = float(settings.get("silero_rvc_pitch", 6))
            final_rvc_pitch = base_rvc_pitch_from_settings - (6 - character_base_rvc_pitch)

            vol = str(settings.get("volume", "1.0")) 

            # Применение RVC через общую функцию с правильными параметрами
            final_output_path = await self.apply_rvc_to_file(
                filepath=temp_wav,
                character=character,
                pitch=final_rvc_pitch,
                index_rate=float(settings.get("silero_rvc_index_rate", 0.75)),
                protect=float(settings.get("silero_rvc_protect", 0.33)),
                filter_radius=int(settings.get("silero_rvc_filter_radius", 3)),
                rms_mix_rate=float(settings.get("silero_rvc_rms_mix_rate", 0.5)),
                is_half=settings.get("silero_rvc_is_half", "True").lower() == "true" if self.parent.provider == "NVIDIA" else True,
                f0method=settings.get("silero_rvc_f0method", None),
                use_index_file=settings.get("silero_rvc_use_index_file", True),
                volume=vol
            )
            
            connected_to_game = self.events.emit_and_wait(Events.Server.GET_GAME_CONNECTION)[0]
            if connected_to_game:
                self.events.emit(Events.Server.SET_PATCH_TO_SOUND_FILE, final_output_path)
            
            return final_output_path
            
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Silero + RVC: {error}")
            return None
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try: os.remove(temp_wav)
                except OSError: pass
