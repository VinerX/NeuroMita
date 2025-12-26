import os
import time
import wave
import asyncio
import multiprocessing as mp
from multiprocessing import Queue, Process
from threading import Thread, Event
import queue
from typing import Optional, List, Callable
from collections import deque
import numpy as np
import urllib.request
from tqdm import tqdm
from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider
from core.events import get_event_bus, Events


class GigaAMRecognizer(SpeechRecognizerInterface):
    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)
        self._torch = None
        self._sd = None
        self._np = None
        self._current_gpu = None
        self.gigaam_model = "v2_rnnt"
        self.gigaam_device = "auto"
        self.gigaam_onnx_export_path = "SpeechRecognitionModels/GigaAM_ONNX"
        self.gigaam_model_path = "SpeechRecognitionModels/GigaAM"
        self.FAILED_AUDIO_DIR = "FailedAudios"
        
        self._process: Optional[Process] = None
        self._command_queue: Optional[Queue] = None
        self._result_queue: Optional[Queue] = None
        self._log_queue: Optional[Queue] = None
        self._monitor_thread: Optional[Thread] = None
        self._process_initialized = False
        self._stop_monitor = Event()
        
        self._transcribe_result = None
        self._transcribe_event = Event()
        
        self._event_bus = get_event_bus()
        
        self._url_dir = "https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM"
        self._model_names = [
            "ctc", "rnnt", "ssl", "emo",
            "v1_ctc", "v1_rnnt", "v1_ssl",
            "v2_ctc", "v2_rnnt", "v2_ssl",
        ]
        
    def settings_spec(self):
        return [{"key": "device", "label_ru": "Устройство", "label_en": "Device",
                 "type": "combobox", "options": ["auto", "cuda", "cpu", "dml"], "default": "auto"}]

    def get_default_settings(self):
        return {"device": "auto"}

    def apply_settings(self, settings: dict):
        dev = settings.get("device")
        if dev:
            self.set_options(device=dev)
    
    def _show_install_warning(self, packages: list):
        package_str = ", ".join(packages)
        self.logger.warning("="*80)
        self.logger.warning(_(
            f"ВНИМАНИЕ: Для работы выбранного модуля распознавания речи требуются библиотеки: {package_str}.",
            f"WARNING: The selected speech recognition module requires libraries: {package_str}."
        ))
        self.logger.warning(_(
            "Сейчас начнется их автоматическая установка. Это может занять некоторое время.",
            "Automatic installation will now begin. This may take some time."
        ))
        self.logger.warning(_(
            "Также, после установки, будет загружена модель распознавания, которая может занимать до 1 ГБ дискового пространства.",
            "Also, after installation, a recognition model will be downloaded, which can take up to 1 GB of disk space."
        ))
        self.logger.warning("="*80)
        time.sleep(3)
        
    def set_options(self, device: str, model: str = None, onnx_path: str = None):
        old_device = self.gigaam_device
        self.gigaam_device = device
        if model:
            self.gigaam_model = model
        if onnx_path:
            self.gigaam_onnx_export_path = onnx_path
        
        if self._process and self._process.is_alive() and old_device != device:
            self.logger.info(f"Перезапуск GigaAM процесса с новым устройством: {device}")
            self._stop_process()
            self._is_initialized = False
        else:
            self.logger.info(f"Устройство для GigaAM установлено на: {device}")
    
    def is_installed(self) -> bool:
        """Проверка установленности GigaAM:
        - зависимости должны импортироваться
        - веса модели должны быть на диске (.ckpt)
        - для CPU/DML допускаем отсутствие ONNX, т.к. он экспортится при init()
        """
        # обязательные зависимости
        try:
            if self._torch is None:
                import torch
                self._torch = torch
            if self._sd is None:
                import sounddevice as sd
                self._sd = sd
            if self._np is None:
                import numpy as np
                self._np = np
        except ImportError as e:
            self.logger.warning(f"GigaAM deps missing: {e}")
            return False

        # критично: сам пакет gigaam должен импортироваться
        try:
            import gigaam  # noqa: F401
        except Exception as e:
            self.logger.debug(f"GigaAM import failed: {e}")
            return False

        # определение GPU (если не смогли — считаем CPU)
        if self._current_gpu is None:
            try:
                self._current_gpu = check_gpu_provider() or "CPU"
            except Exception:
                self._current_gpu = "CPU"

        device_choice = (self.gigaam_device or "auto").strip().lower()
        is_nvidia = (self._current_gpu == "NVIDIA")

        # имя ckpt такое же, как в _install_model()
        model_name = self.gigaam_model
        if model_name in ["ctc", "rnnt", "ssl"]:
            model_name = f"v2_{model_name}"
        if model_name == "emo":
            model_name = "v1_emo"

        ckpt_path = os.path.join(self.gigaam_model_path, f"{model_name}.ckpt")
        ckpt_exists = os.path.exists(ckpt_path)

        # CUDA/PyTorch ветка (только если реально доступна CUDA)
        if is_nvidia and device_choice in ["auto", "cuda"] and self._torch.cuda.is_available():
            return ckpt_exists

        # CPU/DML ветка: нужен onnxruntime, но сами .onnx могут отсутствовать (экспортятся при init)
        try:
            import onnxruntime  # noqa: F401
        except Exception as e:
            self.logger.debug(f"onnxruntime import failed: {e}")
            return False

        # если ONNX уже есть — ок
        onnx_dir = self.gigaam_onnx_export_path
        name = self.gigaam_model
        if "_" in name:
            version, model_type = name.split("_", 1)
        else:
            version, model_type = "v2", name

        if model_type == "ctc":
            onnx_ok = os.path.exists(os.path.join(onnx_dir, f"{version}_{model_type}.onnx"))
        else:
            base = os.path.join(onnx_dir, f"{version}_{model_type}")
            onnx_ok = all([
                os.path.exists(f"{base}_encoder.onnx"),
                os.path.exists(f"{base}_decoder.onnx"),
                os.path.exists(f"{base}_joint.onnx"),
            ])

        # главное исправление: если ONNX ещё нет, но ckpt уже скачан — считаем установленной
        # (ONNX будет экспортирован при init_recognizer в отдельном процессе)
        return onnx_ok or ckpt_exists

    def _get_libs_abs(self):
        import os
        libs_abs = getattr(self.pip_installer, "libs_path_abs", None)
        if not libs_abs:
            libs_abs = os.path.abspath("Lib")
        return libs_abs

    def _ensure_libs_on_path(self):
        import os, sys
        libs_abs = self._get_libs_abs()
        if libs_abs and libs_abs not in sys.path:
            sys.path.insert(0, libs_abs)
        # Подстрахуем PYTHONPATH для дочерних импортов
        prev = os.environ.get("PYTHONPATH", "")
        if libs_abs and libs_abs not in prev.split(os.pathsep):
            os.environ["PYTHONPATH"] = (libs_abs + (os.pathsep + prev if prev else ""))

    async def install(self) -> bool:
        """Установка зависимостей и модели"""
        try:
            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_STARTED, {"model": "gigaam"})
            
            if self._current_gpu is None:
                self._current_gpu = check_gpu_provider() or "CPU"
            
            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                "model": "gigaam", 
                "progress": 10, 
                "status": _("Установка зависимостей PyTorch...", "Installing PyTorch dependencies...")
            })
            
            if self._torch is None:
                try:
                    import torch
                except ImportError:
                    if self._current_gpu == "NVIDIA":
                        success = self.pip_installer.install_package(
                            ["torch==2.7.1", "torchaudio==2.7.1"],
                            description=_("Установка PyTorch с поддержкой CUDA...", "Installing PyTorch with CUDA support..."),
                            extra_args=["--index-url", "https://download.pytorch.org/whl/cu128"]
                        )
                    else:
                        success = self.pip_installer.install_package(
                            ["torch==2.7.1", "torchaudio==2.7.1"],
                            description=_("Установка PyTorch CPU...", "Installing PyTorch CPU..."),
                        )
                    if not success:
                        raise ImportError("Не удалось установить torch, необходимый для GigaAM.")
                    import torch
                
                try:
                    import omegaconf
                except ImportError:
                    success = self.pip_installer.install_package(
                        "omegaconf",
                        description=_("Установка omegaconf...", "Installing omegaconf...")
                    )
                    if not success:
                        raise ImportError("Не удалось установить omegaconf, необходимый для GigaAM.")
                
                import omegaconf, typing, collections
                torch.serialization.add_safe_globals([
                    omegaconf.dictconfig.DictConfig, 
                    omegaconf.base.ContainerMetadata, 
                    typing.Any, 
                    dict, 
                    collections.defaultdict, 
                    omegaconf.nodes.AnyNode, 
                    omegaconf.nodes.Metadata, 
                    omegaconf.listconfig.ListConfig, 
                    list, 
                    int
                ])
                self.logger.warning("TORCH ADDED SAFE GLOBALS!")
                self._torch = torch

            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                "model": "gigaam", 
                "progress": 30, 
                "status": _("Установка GigaAM и дополнительных библиотек...", "Installing GigaAM and additional libraries...")
            })

            try:
                import gigaam
            except ImportError:
                self._show_install_warning(["gigaam"])
                success = self.pip_installer.install_package(
                    ["gigaam", "hydra-core", "sentencepiece"],
                    description=_("Установка GigaAM...", "Installing GigaAM..."),
                    extra_args=["--no-deps"]
                )
                if not success:
                    raise ImportError("Не удалось установить GigaAM.")
            
            try:
                import silero_vad
            except ImportError:
                self._show_install_warning(["silero-vad"])
                self.pip_installer.install_package(
                    ["silero-vad"], 
                    description=_("Установка Silero VAD...", "Installing Silero VAD...")
                )
            
            if self._sd is None:
                try:
                    import sounddevice as sd
                    self._sd = sd
                except ImportError:
                    self.pip_installer.install_package(
                        ["sounddevice"],
                        description=_("Установка sounddevice...", "Installing sounddevice...")
                    )
                    import sounddevice as sd
                    self._sd = sd
            
            if self._np is None:
                import numpy as np
                self._np = np

            try:
                self._ensure_libs_on_path()
                import gigaam  # noqa: F401
            except Exception as e:
                self.logger.error(f"После установки модуль 'gigaam' не импортируется: {e}")
            
            if self._current_gpu != "NVIDIA" and self.gigaam_device != "cuda":
                try:
                    import onnxruntime
                except ImportError:
                    deps_to_install = ["onnx", "onnxruntime"]
                    desc = _("Установка ONNX Runtime...", "Installing ONNX Runtime...")
                    
                    if self.gigaam_device in ["auto", "dml"] and self._current_gpu != "NVIDIA":
                        deps_to_install.append("onnxruntime-directml")
                        desc = _("Установка ONNX Runtime с поддержкой DirectML...", 
                                "Installing ONNX Runtime with DirectML support...")
                    
                    self._show_install_warning(deps_to_install)
                    self.pip_installer.install_package(deps_to_install, description=desc)
            
            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                "model": "gigaam", 
                "progress": 60, 
                "status": _("Загрузка модели GigaAM...", "Downloading GigaAM model...")
            })
            
            success = await self._install_model()
            
            if success:
                self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FINISHED, {"model": "gigaam"})
                return True
            else:
                self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {
                    "model": "gigaam",
                    "error": _("Не удалось загрузить модель", "Failed to download model")
                })
                return False
            
        except ImportError as e:
            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {
                "model": "gigaam",
                "error": str(e)
            })
            self.logger.critical(f"Критическая ошибка: не удалось импортировать или установить библиотеку для GigaAM: {e}")
            return False
        except Exception as e:
            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {
                "model": "gigaam",
                "error": str(e)
            })
            self.logger.error(f"Ошибка при установке зависимостей GigaAM: {e}", exc_info=True)
            return False
    
    async def _install_model(self) -> bool:
        """Загрузка модели GigaAM"""
        try:
            if self.is_installed():
                self.logger.info("Модель GigaAM уже установлена")
                return True
                
            model_name = self.gigaam_model
            if model_name not in self._model_names:
                self.logger.error(f"Неизвестная модель: {model_name}")
                return False
                
            if model_name in ["ctc", "rnnt", "ssl"]:
                model_name = f"v2_{model_name}"
            if model_name == "emo":
                model_name = f"v1_{model_name}"
                
            model_url = f"{self._url_dir}/{model_name}.ckpt"
            os.makedirs(self.gigaam_model_path, exist_ok=True)
            model_file = os.path.join(self.gigaam_model_path, f"{model_name}.ckpt")
            
            if os.path.exists(model_file):
                self.logger.info(f"Модель {model_name} уже скачана")
                return True
                
            self.logger.info(f"Загрузка модели {model_name} из {model_url}")
            
            def download_hook(block_num, block_size, total_size):
                downloaded = block_num * block_size
                percent = min(downloaded * 100 / total_size, 100)
                progress = 60 + int(percent * 0.35)
                
                self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                    "model": "gigaam",
                    "progress": progress,
                    "status": _(
                        f"Загрузка модели: {percent:.1f}% ({downloaded/1024/1024:.1f}MB / {total_size/1024/1024:.1f}MB)",
                        f"Downloading model: {percent:.1f}% ({downloaded/1024/1024:.1f}MB / {total_size/1024/1024:.1f}MB)"
                    )
                })
            
            urllib.request.urlretrieve(model_url, model_file, reporthook=download_hook)
            
            if self.gigaam_model == "rnnt" or self.gigaam_model == "v1_rnnt":
                tokenizer_url = f"{self._url_dir}/{model_name}_tokenizer.model"
                tokenizer_file = os.path.join(self.gigaam_model_path, f"{model_name}_tokenizer.model")
                
                if not os.path.exists(tokenizer_file):
                    self.logger.info(f"Загрузка токенизатора для {model_name}")
                    
                    def tokenizer_hook(block_num, block_size, total_size):
                        downloaded = block_num * block_size
                        percent = min(downloaded * 100 / total_size, 100)
                        progress = 95 + int(percent * 0.05)
                        
                        self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                            "model": "gigaam",
                            "progress": progress,
                            "status": _(
                                f"Загрузка токенизатора: {percent:.1f}%",
                                f"Downloading tokenizer: {percent:.1f}%"
                            )
                        })
                    
                    urllib.request.urlretrieve(tokenizer_url, tokenizer_file, reporthook=tokenizer_hook)
            
            self.logger.info(f"Модель {model_name} успешно загружена")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка загрузки модели: {e}", exc_info=True)
            return False
    
    async def init(self, **kwargs) -> bool:
        """Инициализация - запуск отдельного процесса для работы модели"""
        if self._is_initialized and self._process and self._process.is_alive():
            return True
        
        if self._start_process():
            self._is_initialized = True
            self._event_bus.emit(Events.Speech.ASR_MODEL_INITIALIZED, {"model": "gigaam"})
            return True
        return False
    
    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        """Отправка команды на транскрибацию в процесс"""
        if not self._is_initialized or not self._process or not self._process.is_alive():
            self.logger.error("GigaAM процесс не инициализирован")
            return None
        
        self._transcribe_event.clear()
        self._transcribe_result = None
        
        self._command_queue.put(('transcribe', audio_data, sample_rate))
        
        if self._transcribe_event.wait(timeout=30):
            return self._transcribe_result
        else:
            self.logger.error("Таймаут при ожидании транскрибации")
            return None

    async def live_recognition(self, microphone_index: int, handle_voice_callback, 
                          vad_model, active_flag, **kwargs) -> None:
        """Live recognition с VAD в основном процессе, транскрибация в отдельном"""
        if not self._is_initialized or not self._process or not self._process.is_alive():
            self.logger.error("GigaAM процесс не инициализирован")
            return
        
        sample_rate = kwargs.get('sample_rate', 16000)
        chunk_size = kwargs.get('chunk_size', 512)
        vad_threshold = kwargs.get('vad_threshold', 0.5)
        silence_timeout = kwargs.get('silence_timeout', 1.0)
        pre_buffer_duration = kwargs.get('pre_buffer_duration', 0.3)
        
        silence_chunks_needed = int(silence_timeout * sample_rate / chunk_size)
        pre_buffer_size = int(pre_buffer_duration * sample_rate / chunk_size)
        
        try:
            devices = self._sd.query_devices()
            input_devices = [dev['name'] for dev in devices if dev['max_input_channels'] > 0]
            mic_name = input_devices[microphone_index] if microphone_index < len(input_devices) else "Unknown"
            self.logger.info(f"Используется микрофон: {mic_name}")
        except Exception as e:
            self.logger.error(f"Ошибка при получении информации о микрофоне: {e}")
            return

        self.logger.info("Ожидание речи (GigaAM + Silero VAD)...")

        pre_speech_buffer = deque(maxlen=pre_buffer_size)
        speech_buffer = []
        is_speaking = False
        silence_counter = 0

        stream = self._sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype='float32',
            blocksize=chunk_size,
            device=microphone_index
        )
        stream.start()

        try:
            while active_flag():
                if not active_flag():
                    break
                try:
                    audio_chunk, overflowed = stream.read(chunk_size)
                except Exception as e:
                    if not active_flag():
                        break
                    self.logger.warning(f"Input stream read aborted: {e}")
                    break

                if overflowed:
                    self.logger.warning("Переполнение буфера аудиопотока!")

                if not is_speaking:
                    pre_speech_buffer.append(audio_chunk)

                audio_tensor = self._torch.from_numpy(audio_chunk.flatten())
                speech_prob = vad_model(audio_tensor, sample_rate).item()

                if speech_prob > vad_threshold:
                    if not is_speaking:
                        self.logger.debug("🟢 Начало речи. Захват из пред-буфера.")
                        is_speaking = True
                        speech_buffer.clear()
                        speech_buffer.extend(list(pre_speech_buffer))
                    
                    speech_buffer.append(audio_chunk)
                    silence_counter = 0
                
                elif is_speaking:
                    speech_buffer.append(audio_chunk)
                    silence_counter += 1
                    if silence_counter > silence_chunks_needed:
                        self.logger.debug("🔴 Конец речи. Отправка на распознавание.")
                        audio_to_process = self._np.concatenate(speech_buffer)
                        
                        is_speaking = False
                        speech_buffer.clear()
                        silence_counter = 0
                        
                        text = await self.transcribe(audio_to_process, sample_rate)
                        if text:
                            self.logger.info(f"GigaAM распознал: {text}")
                            await handle_voice_callback(text)
                        else:
                            await self._save_failed_audio(audio_to_process, sample_rate)
                
                await asyncio.sleep(0.01)
        finally:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass


    async def _save_failed_audio(self, audio_data: np.ndarray, sample_rate: int):
        self.logger.info("Сохранение аудиофрагмента в папку Failed...")
        try:
            os.makedirs(self.FAILED_AUDIO_DIR, exist_ok=True)
            timestamp = int(time.time())
            filename = os.path.join(self.FAILED_AUDIO_DIR, f"failed_{timestamp}.wav")
            
            audio_data_int16 = (audio_data * 32767).astype(self._np.int16)

            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data_int16.tobytes())
            self.logger.info(f"Фрагмент сохранен в: {filename}")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить аудиофрагмент: {e}")
    
    def cleanup(self) -> None:
        """Остановка процесса и очистка ресурсов"""
        self._stop_process()
        self._torch = None
        self._sd = None
        self._np = None
        self._is_initialized = False
    
    def _monitor_process(self):
        """Поток для мониторинга результатов от процесса GigaAM"""
        while not self._stop_monitor.is_set() and self._process and self._process.is_alive():
            try:
                while not self._log_queue.empty():
                    try:
                        level, msg = self._log_queue.get_nowait()
                        getattr(self.logger, level)(f"[GigaAM Process] {msg}")
                    except queue.Empty:
                        break
                
                while not self._result_queue.empty():
                    try:
                        result = self._result_queue.get_nowait()
                        result_type = result[0]
                        
                        if result_type == 'init_success':
                            self._process_initialized = True
                            self.logger.info("GigaAM процесс успешно инициализирован")
                            
                        elif result_type == 'init_error':
                            self.logger.error(f"Ошибка инициализации GigaAM: {result[1]}")
                            self._process_initialized = False
                            
                        elif result_type == 'transcription':
                            self._transcribe_result = result[1]
                            self._transcribe_event.set()
                            
                        elif result_type == 'transcription_error':
                            self._transcribe_result = None
                            self._transcribe_event.set()
                            
                    except queue.Empty:
                        break
                        
                time.sleep(0.01)
                
            except Exception as e:
                self.logger.error(f"Ошибка в мониторе GigaAM процесса: {e}")

    def _start_process(self):
        """Запуск процесса GigaAM"""
        if self._process and self._process.is_alive():
            self.logger.warning("GigaAM процесс уже запущен")
            return True
        
        self.logger.info("Запуск отдельного процесса для GigaAM...")
        
        self._command_queue = mp.Queue()
        self._result_queue = mp.Queue()
        self._log_queue = mp.Queue()
        
        from handlers.asr_models.gigaam_process import run_gigaam_process
        
        self._process = mp.Process(
            target=run_gigaam_process,
            args=(
                self._command_queue,
                self._result_queue,
                self._log_queue
            ),
            daemon=True  # важно
        )
        self._process.start()
        
        self._stop_monitor.clear()
        self._monitor_thread = Thread(
            target=self._monitor_process,
            daemon=True
        )
        self._monitor_thread.start()
        
        init_options = {
            'device': self.gigaam_device,
            'model': self.gigaam_model,
            'onnx_path': self.gigaam_onnx_export_path,
            'model_path': self.gigaam_model_path,
            'script_path': r"libs\python\python.exe",
            'libs_path': "Lib"
        }
        self._command_queue.put(('init', init_options))
        
        timeout = 120
        start_time = time.time()
        while not self._process_initialized:
            if time.time() - start_time > timeout:
                self.logger.error("Таймаут инициализации GigaAM процесса")
                self._stop_process()
                return False
            time.sleep(0.1)
        
        self.logger.success("GigaAM процесс успешно запущен и инициализирован")
        return True
    
    def _stop_process(self):
        if not self._process:
            return

        self.logger.info("Остановка GigaAM процесса...")
        self._stop_monitor.set()

        if self._command_queue:
            try:
                self._command_queue.put(('shutdown',))
            except:
                pass

        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)

        if self._process:
            self._process.join(timeout=5)
            if self._process.is_alive():
                self.logger.warning("GigaAM процесс не завершился, принудительное завершение...")
                self._process.terminate()
                self._process.join(timeout=2)

        # корректно закрываем очереди, чтобы завершились фоновые потоки Queue
        for q in (self._command_queue, self._result_queue, self._log_queue):
            try:
                if q is not None:
                    q.close()
                    q.join_thread()
            except Exception:
                pass

        self._process = None
        self._command_queue = None
        self._result_queue = None
        self._log_queue = None
        self._process_initialized = False
        self._monitor_thread = None

        self.logger.info("GigaAM процесс остановлен")