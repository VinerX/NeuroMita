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


class GigaAMOnnxRecognizer(SpeechRecognizerInterface):
    """
    ONNX-only версия:
    - всегда работает через отдельный процесс
    - device: auto/cpu/dml
    """

    MODEL_CONFIGS = [
        {
            "id": "gigaam_onnx",
            "name": "GigaAM ONNX",
            "description": _(
                "Офлайн-распознавание речи на базе GigaAM через ONNXRuntime. "
                "Запускается в отдельном процессе. Подходит для CPU/DirectML.",
                "Offline speech recognition based on GigaAM via ONNXRuntime. "
                "Runs in a separate process. Suitable for CPU/DirectML."
            ),
            "languages": ["Russian"],
            "gpu_vendor": ["AMD", "CPU"],
            "tags": [
                _("ONNX", "ONNX"),
                _("Отдельный процесс", "Separate process"),
                _("CPU/DirectML", "CPU/DirectML"),
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

        self.gigaam_model = "v2_rnnt"
        self.gigaam_device = "auto"  # auto/cpu/dml
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
            "v1_ctc", "v1_rnnt",
            "v2_ctc", "v2_rnnt",
            "v3_ctc", "v3_rnnt",
        ]

    # ---------- UI schema ----------
    def settings_spec(self):
        return [
            {"key": "device", "label_ru": "Устройство", "label_en": "Device",
             "type": "combobox", "options": ["auto", "cpu", "dml"], "default": "auto"},
            {"key": "model", "label_ru": "Модель", "label_en": "Model",
             "type": "combobox",
             "options": ["v2_rnnt", "v2_ctc", "v3_rnnt", "v3_ctc", "v1_rnnt", "v1_ctc"],
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
            self.logger.info(f"Перезапуск GigaAM ONNX процесса с новым устройством: {self.gigaam_device}")
            self._stop_process()
            self._is_initialized = False

    # ---------- naming / paths ----------
    def _normalized_ckpt_name(self) -> str:
        name = (self.gigaam_model or "v2_rnnt").strip()
        if name in ("ctc", "rnnt"):
            name = f"v2_{name}"
        return name

    def _ckpt_path(self) -> str:
        return os.path.join(self.gigaam_model_path, f"{self._normalized_ckpt_name()}.ckpt")

    def _tokenizer_path(self) -> str:
        name = self._normalized_ckpt_name()
        return os.path.join(self.gigaam_model_path, f"{name}_tokenizer.model")

    # ---------- dependency model ----------
    def requirements(self):
        def ckpt_path(_ctx: dict) -> str:
            return self._ckpt_path()

        # ONNX-версия: onnxruntime нужен всегда
        return [
            AsrRequirement(id="torch", kind="python_module", module="torch", required=True),
            AsrRequirement(id="torchaudio", kind="python_module", module="torchaudio", required=True),
            AsrRequirement(id="omegaconf", kind="python_module", module="omegaconf", required=True),
            AsrRequirement(id="hydra", kind="python_module", module="hydra", required=True),
            AsrRequirement(id="sentencepiece", kind="python_module", module="sentencepiece", required=True),

            AsrRequirement(id="silero_vad", kind="python_module", module="silero_vad", required=True),
            AsrRequirement(id="sounddevice", kind="python_module", module="sounddevice", required=True),
            AsrRequirement(id="numpy", kind="python_module", module="numpy", required=True),

            AsrRequirement(id="onnxruntime", kind="python_module", module="onnxruntime", required=True),

            AsrRequirement(id="gigaam_ckpt", kind="file", required=True, path_fn=ckpt_path),
        ]

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        gpu = (ctx.get("gpu_vendor") or "CPU")
        device = str(ctx.get("device") or "auto").strip().lower()

        steps: List[dict] = []

        # torch CPU достаточно (onnx inference всё равно в ORT; torch нужен для preprocessor/экспорта)
        steps.append({
            "progress": 10,
            "description": _("Установка PyTorch CPU...", "Installing PyTorch CPU..."),
            "packages": ["torch==2.7.1", "torchaudio==2.7.1"],
            "extra_args": None
        })

        steps.append({
            "progress": 30,
            "description": _("Установка зависимостей GigaAM...", "Installing GigaAM deps..."),
            "packages": ["hydra-core", "sentencepiece", "omegaconf"],
            "extra_args": None
        })

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

        # ONNX runtime (+ directml при необходимости)
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
                "model": "gigaam_onnx",
                "progress": 80,
                "status": _("Загрузка весов модели...", "Downloading model weights...")
            })
            ok = self._download_file_with_progress(
                f"{self._url_dir}/{model_name}.ckpt",
                ckpt_path,
                80,
                95
            )
            if not ok:
                raise RuntimeError("Failed to download ckpt")

        # токенизатор нужен для v1_rnnt
        if model_name == "v1_rnnt":
            tok_path = self._tokenizer_path()
            if not os.path.exists(tok_path):
                self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                    "model": "gigaam_onnx",
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
            "model": "gigaam_onnx",
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
                headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
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

                        pct = (min(done * 100.0 / total, 100.0) if total > 0 else 0.0)
                        prog = start_prog + int((end_prog - start_prog) * (pct / 100.0))
                        self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                            "model": "gigaam_onnx",
                            "progress": int(max(0, min(99, prog))),
                            "status": _(f"Загрузка: {pct:.1f}%", f"Downloading: {pct:.1f}%")
                        })

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
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    # ---------- runtime ----------
    async def init(self, **kwargs) -> bool:
        if self._is_initialized and self._process and self._process.is_alive():
            return True

        try:
            import torch
            import sounddevice as sd
            import numpy as np
            self._torch = torch
            self._sd = sd
            self._np = np
        except Exception as e:
            self.logger.error(f"GigaAMOnnx init imports failed: {e}")
            return False

        if self._start_process():
            self._is_initialized = True
            return True
        return False

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized or not self._process or not self._process.is_alive():
            self.logger.error("GigaAM ONNX процесс не инициализирован")
            return None

        self._transcribe_event.clear()
        self._transcribe_result = None

        self._command_queue.put(("transcribe", audio_data, sample_rate))

        if self._transcribe_event.wait(timeout=30):
            return self._transcribe_result

        self.logger.error("Таймаут при ожидании транскрибации (ONNX)")
        return None

    async def live_recognition(self, microphone_index: int, handle_voice_callback,
                              vad_model, active_flag, **kwargs) -> None:
        if not self._is_initialized or not self._process or not self._process.is_alive():
            self.logger.error("GigaAM ONNX процесс не инициализирован")
            return

        sample_rate = kwargs.get("sample_rate", 16000)
        chunk_size = kwargs.get("chunk_size", 512)
        vad_threshold = kwargs.get("vad_threshold", 0.5)
        silence_timeout = kwargs.get("silence_timeout", 1.0)
        pre_buffer_duration = kwargs.get("pre_buffer_duration", 0.3)

        silence_chunks_needed = int(silence_timeout * sample_rate / chunk_size)
        pre_buffer_size = int(pre_buffer_duration * sample_rate / chunk_size)

        pre_speech_buffer = deque(maxlen=pre_buffer_size)
        speech_buffer = []
        is_speaking = False
        silence_counter = 0

        stream = self._sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
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

            audio_data_int16 = (audio_data.reshape(-1) * 32767).astype(self._np.int16)

            with wave.open(filename, "wb") as wf:
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
                        getattr(self.logger, level, self.logger.info)(f"[GigaAM ONNX Process] {msg}")
                    except queue.Empty:
                        break

                while self._result_queue and not self._result_queue.empty():
                    try:
                        result = self._result_queue.get_nowait()
                        t = result[0]

                        if t == "init_success":
                            self._process_initialized = True
                            self.logger.info("GigaAM ONNX процесс успешно инициализирован")
                        elif t == "init_error":
                            self.logger.error(f"Ошибка инициализации GigaAM ONNX: {result[1]}")
                            self._process_initialized = False
                        elif t == "transcription":
                            self._transcribe_result = result[1]
                            self._transcribe_event.set()
                        elif t == "transcription_error":
                            self._transcribe_result = None
                            self._transcribe_event.set()
                    except queue.Empty:
                        break

                time.sleep(0.01)
            except Exception as e:
                self.logger.error(f"Ошибка в мониторе GigaAM ONNX процесса: {e}")

    def _start_process(self):
        if self._process and self._process.is_alive():
            self.logger.warning("GigaAM ONNX процесс уже запущен")
            return True

        self.logger.info("Запуск отдельного процесса для GigaAM ONNX...")

        self._command_queue = mp.Queue()
        self._result_queue = mp.Queue()
        self._log_queue = mp.Queue()

        from handlers.asr_models.gigaam_onnx_process import run_gigaam_onnx_process

        self._process = mp.Process(
            target=run_gigaam_onnx_process,
            args=(self._command_queue, self._result_queue, self._log_queue),
            daemon=True
        )
        self._process.start()

        self._stop_monitor.clear()
        self._monitor_thread = Thread(target=self._monitor_process, daemon=True)
        self._monitor_thread.start()

        init_options = {
            "device": self.gigaam_device,
            "model": self.gigaam_model,
            "onnx_path": self.gigaam_onnx_export_path,
            "model_path": self.gigaam_model_path,
        }
        self._command_queue.put(("init", init_options))

        timeout = 120
        start_time = time.time()
        while not self._process_initialized:
            if time.time() - start_time > timeout:
                self.logger.error("Таймаут инициализации GigaAM ONNX процесса")
                self._stop_process()
                return False
            time.sleep(0.1)

        self.logger.success("GigaAM ONNX процесс успешно запущен и инициализирован")
        return True

    def _stop_process(self):
        if not self._process:
            return

        self.logger.info("Остановка GigaAM ONNX процесса...")
        self._stop_monitor.set()

        if self._command_queue:
            try:
                self._command_queue.put(("shutdown",))
            except Exception:
                pass

        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)

        if self._process:
            self._process.join(timeout=5)
            if self._process.is_alive():
                self.logger.warning("GigaAM ONNX процесс не завершился, принудительное завершение...")
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

        self.logger.info("GigaAM ONNX процесс остановлен")