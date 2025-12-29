import os
import time
import wave
import asyncio
import multiprocessing as mp
from multiprocessing import Queue, Process
from threading import Thread, Event
import queue
from typing import Optional, List
from collections import deque
import numpy as np
import urllib.request
import urllib.error

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from handlers.asr_models.requirements import AsrRequirement, check_requirements


from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider
from core.events import get_event_bus, Events


class GigaAMRecognizer(SpeechRecognizerInterface):

    MODEL_CONFIGS = [
        {
            "id": "gigaam",
            "name": _("GigaAM", "GigaAM"),
            "description": _(
                "Офлайн-распознавание речи на базе GigaAM (SberDevices). Работает локально, "
                "требует скачивания весов. Поддерживает разные варианты модели (v1/v2/v3, rnnt/ctc/ssl) "
                "и разные устройства (CPU/CUDA/DirectML).",
                "Offline speech recognition based on GigaAM (SberDevices). Runs locally, "
                "requires downloading model weights. Supports multiple variants (v1/v2/v3, rnnt/ctc/ssl) "
                "and multiple devices (CPU/CUDA/DirectML)."
            ),
            "languages": ["Russian"],
            "gpu_vendor": ["NVIDIA", "AMD", "CPU"],
            "tags": [
                _("Офлайн", "Offline"),
                _("Локально", "Local"),
                _("С VAD", "With VAD"),
                _("CPU/CUDA/DML", "CPU/CUDA/DML"),
                _("Несколько вариантов модели", "Multiple model variants"),
            ],
            "links": []
        }
    ]

    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)

        self._torch = None
        self._sd = None
        self._np = None

        self._current_gpu = None

        self.gigaam_model = "v3_rnnt"
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

        # v3 добавлены; семантика имени та же
        self._model_names = [
            "ctc", "rnnt", "ssl", "emo",
            "v1_ctc", "v1_rnnt", "v1_ssl", "v1_emo",
            "v2_ctc", "v2_rnnt", "v2_ssl",
            "v3_ctc", "v3_rnnt", "v3_ssl",
        ]

    # ---------- UI schema ----------
    def settings_spec(self):
        return [
            {"key": "device", "label_ru": "Устройство", "label_en": "Device",
             "type": "combobox", "options": ["auto", "cuda", "cpu", "dml"], "default": "auto"},
            {"key": "model", "label_ru": "Модель", "label_en": "Model",
             "type": "combobox",
             "options": [
                 "v2_rnnt", "v2_ctc", "v2_ssl",
                 "v3_rnnt", "v3_ctc", "v3_ssl",
                 "v1_rnnt", "v1_ctc", "v1_ssl",
                 "emo", "v1_emo"
             ],
             "default": "v2_rnnt"}
        ]

    def get_default_settings(self):
        return {"device": "auto", "model": "v2_rnnt"}

    def apply_settings(self, settings: dict):
        dev = settings.get("device")
        mdl = settings.get("model")
        if dev or mdl:
            self.set_options(device=dev or self.gigaam_device, model=mdl or self.gigaam_model)

    def set_options(self, device: str, model: str = None, onnx_path: str = None, model_path: str = None):
        old_device = self.gigaam_device
        self.gigaam_device = (device or self.gigaam_device).strip().lower()
        if model:
            self.gigaam_model = str(model).strip()
        if onnx_path:
            self.gigaam_onnx_export_path = str(onnx_path)
        if model_path:
            self.gigaam_model_path = str(model_path)

        if self._process and self._process.is_alive() and old_device != self.gigaam_device:
            self.logger.info(f"Перезапуск GigaAM процесса с новым устройством: {self.gigaam_device}")
            self._stop_process()
            self._is_initialized = False

    # ---------- naming / paths ----------
    def _normalized_ckpt_name(self) -> str:
        name = (self.gigaam_model or "v2_rnnt").strip()

        # поддержка коротких алиасов
        if name in ("ctc", "rnnt", "ssl"):
            name = f"v2_{name}"
        if name == "emo":
            name = "v1_emo"

        return name

    def _ckpt_path(self) -> str:
        return os.path.join(self.gigaam_model_path, f"{self._normalized_ckpt_name()}.ckpt")

    def _tokenizer_path(self) -> str:
        name = self._normalized_ckpt_name()
        return os.path.join(self.gigaam_model_path, f"{name}_tokenizer.model")

    # ---------- dependency model ----------
    def requirements(self):
        def need_onnx(ctx: dict) -> bool:
            device_choice = str(ctx.get("device") or "auto").strip().lower()
            gpu = ctx.get("gpu_vendor") or "CPU"
            if device_choice in ("cpu", "dml"):
                return True
            if device_choice == "auto" and gpu != "NVIDIA":
                return True
            return False

        def ckpt_path(_ctx: dict) -> str:
            return self._ckpt_path()

        return [
            AsrRequirement(id="torch", kind="python_module", module="torch", required=True),
            AsrRequirement(id="omegaconf", kind="python_module", module="omegaconf", required=True),
            AsrRequirement(id="hydra", kind="python_module", module="hydra", required=True),
            AsrRequirement(id="sentencepiece", kind="python_module", module="sentencepiece", required=True),

            AsrRequirement(id="silero_vad", kind="python_module", module="silero_vad", required=True),
            AsrRequirement(id="sounddevice", kind="python_module", module="sounddevice", required=True),
            AsrRequirement(id="numpy", kind="python_module", module="numpy", required=True),

            AsrRequirement(id="onnxruntime", kind="python_module", module="onnxruntime", required=True, when=need_onnx),

            AsrRequirement(id="gigaam_ckpt", kind="file", required=True, path_fn=ckpt_path),
        ]

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        """
        Декларативный план pip-установки. Выполняет InstallController.
        ctx: {"gpu_vendor": "...", "device": "..."}
        """
        gpu = (ctx.get("gpu_vendor") or "CPU")
        device = str(ctx.get("device") or "auto").strip().lower()

        steps: List[dict] = []

        # 1) PyTorch
        if gpu == "NVIDIA" and device in ("auto", "cuda"):
            steps.append({
                "progress": 10,
                "description": _("Установка PyTorch с CUDA (cu128)...", "Installing PyTorch with CUDA (cu128)..."),
                "packages": ["torch==2.7.1", "torchaudio==2.7.1"],
                "extra_args": ["--index-url", "https://download.pytorch.org/whl/cu128"]
            })
        else:
            steps.append({
                "progress": 10,
                "description": _("Установка PyTorch CPU...", "Installing PyTorch CPU..."),
                "packages": ["torch==2.7.1", "torchaudio==2.7.1"],
                "extra_args": None
            })

        # 2) GigaAM stack (как раньше: ставили с --no-deps)
        steps.append({
            "progress": 30,
            "description": _("Установка зависимостей...", "Installing GigaAM..."),
            "packages": ["hydra-core", "sentencepiece"],
            "extra_args": ["--no-deps"]
        })

        # 3) omegaconf отдельно (часто нужен для сериализации/конфигов)
        steps.append({
            "progress": 40,
            "description": _("Установка omegaconf...", "Installing omegaconf..."),
            "packages": ["omegaconf"],
            "extra_args": None
        })

        # 4) Silero VAD + runtime deps
        steps.append({
            "progress": 55,
            "description": _("Установка Silero VAD...", "Installing Silero VAD..."),
            "packages": ["silero-vad"],
            "extra_args": None
        })
        steps.append({
            "progress": 60,
            "description": _("Установка sounddevice...", "Installing sounddevice..."),
            "packages": ["sounddevice"],
            "extra_args": None
        })
        steps.append({
            "progress": 65,
            "description": _("Установка numpy...", "Installing numpy..."),
            "packages": ["numpy"],
            "extra_args": None
        })

        # 5) ONNX runtime для cpu/dml ветки
        need_onnx = (device in ("cpu", "dml")) or (device == "auto" and gpu != "NVIDIA")
        if need_onnx:
            pkgs = ["onnx", "onnxruntime"]
            desc = _("Установка ONNX Runtime...", "Installing ONNX Runtime...")

            if (device in ("auto", "dml")) and gpu != "NVIDIA":
                pkgs.append("onnxruntime-directml")
                desc = _("Установка ONNX Runtime + DirectML...", "Installing ONNX Runtime + DirectML...")

            steps.append({
                "progress": 75,
                "description": desc,
                "packages": pkgs,
                "extra_args": None
            })

        return steps

    def is_installed(self) -> bool:
        if self._current_gpu is None:
            try:
                self._current_gpu = check_gpu_provider() or "CPU"
            except Exception:
                self._current_gpu = "CPU"

        ctx = {"device": self.gigaam_device, "gpu_vendor": self._current_gpu}
        st = check_requirements(self.requirements(), ctx=ctx)
        return bool(st.get("ok"))

    # ---------- artifacts install (NO pip) ----------
    async def install(self) -> bool:
        model_name = self._normalized_ckpt_name()

        if model_name not in self._model_names:
            raise RuntimeError(f"Unknown GigaAM model: {model_name}")

        os.makedirs(self.gigaam_model_path, exist_ok=True)

        ckpt_path = self._ckpt_path()
        if not os.path.exists(ckpt_path):
            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                "model": "gigaam",
                "progress": 80,
                "status": _("Загрузка весов модели...", "Downloading model weights...")
            })
            # ИЗМЕНЕНИЕ: Вызываем синхронно, так как мы уже в потоке установки
            ok = self._download_file_with_progress(
                f"{self._url_dir}/{model_name}.ckpt",
                ckpt_path,
                80,
                95
            )
            if not ok:
                raise RuntimeError("Failed to download ckpt")

        if model_name == "v1_rnnt":
            tok_path = self._tokenizer_path()
            if not os.path.exists(tok_path):
                self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                    "model": "gigaam",
                    "progress": 95,
                    "status": _("Загрузка токенизатора...", "Downloading tokenizer...")
                })
                ok = self._download_file_with_progress(
                    f"{self._url_dir}/{model_name}_tokenizer.model",
                    tok_path,
                    95,
                    99
                )
                if not ok:
                    raise RuntimeError("Failed to download tokenizer")

        self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
            "model": "gigaam",
            "progress": 100,
            "status": _("Файлы модели готовы.", "Model files are ready.")
        })
        return True

    def _download_file_with_progress(self, url: str, dest: str, start_prog: int, end_prog: int) -> bool:

        tmp = dest + ".part"
        try:
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python-urllib",
                    "Accept": "*/*",
                },
                method="GET",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                last_emit = 0.0

                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)

                        now = time.time()
                        if now - last_emit < 0.25:
                            continue
                        last_emit = now

                        if total > 0:
                            pct = min(done * 100.0 / total, 100.0)
                        else:
                            pct = 0.0

                        prog = start_prog + int((end_prog - start_prog) * (pct / 100.0))
                        self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                            "model": "gigaam",
                            "progress": int(max(0, min(99, prog))),
                            "status": _(f"Загрузка: {pct:.1f}%", f"Downloading: {pct:.1f}%")
                        })

            # атомарно заменяем
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except Exception:
                    pass
            os.replace(tmp, dest)

            return os.path.exists(dest) and os.path.getsize(dest) > 0

        except urllib.error.HTTPError as e:
            msg = f"HTTP {e.code}: {e.reason}"
            self.logger.error(f"Download failed {url}: {msg}")
            raise RuntimeError(f"Download failed ({msg}) for {url}") from None

        except Exception as e:
            self.logger.error(f"Download failed {url}: {e}", exc_info=True)
            raise

        finally:
            # чистим partial
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    # ---------- runtime ----------
    async def init(self, **kwargs) -> bool:
        if self._is_initialized and self._process and self._process.is_alive():
            return True

        # ленивые импорты (после того, как deps поставлены контроллером)
        try:
            import torch
            import sounddevice as sd
            import numpy as np
            self._torch = torch
            self._sd = sd
            self._np = np
        except Exception as e:
            self.logger.error(f"GigaAM init imports failed: {e}")
            return False

        if self._start_process():
            self._is_initialized = True
            return True
        return False

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized or not self._process or not self._process.is_alive():
            self.logger.error("GigaAM процесс не инициализирован")
            return None

        self._transcribe_event.clear()
        self._transcribe_result = None

        self._command_queue.put(('transcribe', audio_data, sample_rate))

        if self._transcribe_event.wait(timeout=30):
            return self._transcribe_result
        self.logger.error("Таймаут при ожидании транскрибации")
        return None

    async def live_recognition(self, microphone_index: int, handle_voice_callback,
                              vad_model, active_flag, **kwargs) -> None:
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
                        is_speaking = True
                        speech_buffer.clear()
                        speech_buffer.extend(list(pre_speech_buffer))
                    speech_buffer.append(audio_chunk)
                    silence_counter = 0

                elif is_speaking:
                    speech_buffer.append(audio_chunk)
                    silence_counter += 1
                    if silence_counter > silence_chunks_needed:
                        audio_to_process = self._np.concatenate(speech_buffer)

                        is_speaking = False
                        speech_buffer.clear()
                        silence_counter = 0

                        text = await self.transcribe(audio_to_process, sample_rate)
                        if text:
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
        self._stop_process()
        self._torch = None
        self._sd = None
        self._np = None
        self._is_initialized = False

    # ---------- process control ----------
    def _monitor_process(self):
        while not self._stop_monitor.is_set() and self._process and self._process.is_alive():
            try:
                while self._log_queue and not self._log_queue.empty():
                    try:
                        level, msg = self._log_queue.get_nowait()
                        getattr(self.logger, level, self.logger.info)(f"[GigaAM Process] {msg}")
                    except queue.Empty:
                        break

                while self._result_queue and not self._result_queue.empty():
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
            args=(self._command_queue, self._result_queue, self._log_queue),
            daemon=True
        )
        self._process.start()

        self._stop_monitor.clear()
        self._monitor_thread = Thread(target=self._monitor_process, daemon=True)
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
            except Exception:
                pass

        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)

        if self._process:
            self._process.join(timeout=5)
            if self._process.is_alive():
                self.logger.warning("GigaAM процесс не завершился, принудительное завершение...")
                self._process.terminate()
                self._process.join(timeout=2)

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