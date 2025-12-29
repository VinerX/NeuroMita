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


class WhisperOnnxRecognizer(SpeechRecognizerInterface):
    """
    Whisper large-v3-turbo ONNX (onnx-community) через onnxruntime (+ DirectML).
    ONNX runtime и InferenceSession живут в отдельном процессе.
    VAD: внешний (silero-vad), передаётся из asr_handler.
    """

    MODEL_CONFIGS = [
        {
            "id": "whisper_onnx",
            "name": "Whisper Large v3 turbo (ONNX)",
            "description": _(
                "Офлайн Whisper в формате ONNX. Работает через onnxruntime, а на AMD/не‑NVIDIA может "
                "использовать DirectML. Модель и файлы transformers скачиваются локально.",
                "Offline Whisper in ONNX format. Runs via onnxruntime, and on AMD/non‑NVIDIA can "
                "use DirectML. Model and transformers files are downloaded locally."
            ),
            "languages": ["Multilingual"],
            "gpu_vendor": ["NVIDIA", "AMD"],
            "tags": [
                _("Локально", "Local"),
                _("ONNX", "ONNX"),
            ],
            "links": [
                {
                    "label": "onnx-community/whisper-large-v3-turbo-onnx (HF)",
                    "url": "https://huggingface.co/onnx-community/whisper-large-v3-turbo-onnx"
                },
                {"label": "optimum (PyPI)", "url": "https://pypi.org/project/optimum/"}
            ]
        }
    ]

    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)

        self._torch = None
        self._sd = None
        self._np = None

        self._current_gpu = None

        self.device = "auto"
        self.language = "ru"
        self.max_tokens = 192

        self.model_dir = "SpeechRecognitionModels/WhisperONNX/large-v3-turbo"
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

        self._hf_base = "https://huggingface.co/onnx-community/whisper-large-v3-turbo-onnx/resolve/main/onnx"

    def settings_spec(self):
        return [
            {"key": "device", "label_ru": "Устройство", "label_en": "Device",
             "type": "combobox", "options": ["auto", "dml", "cpu", "cuda"], "default": "auto"},
            {"key": "language", "label_ru": "Язык", "label_en": "Language",
             "type": "combobox", "options": ["ru", "en", "auto"], "default": "ru"},
            {"key": "max_tokens", "label_ru": "Макс. токенов", "label_en": "Max tokens",
             "type": "combobox", "options": [96, 128, 160, 192, 224, 256], "default": 192},
        ]

    def get_default_settings(self):
        return {"device": "auto", "language": "ru", "max_tokens": 192}

    def apply_settings(self, settings: dict):
        dev = settings.get("device")
        lang = settings.get("language")
        mt = settings.get("max_tokens")

        old = (self.device, self.language, self.max_tokens)

        if dev:
            self.device = str(dev).strip().lower()
        if lang:
            self.language = str(lang).strip().lower()
        if mt is not None:
            try:
                self.max_tokens = int(mt)
            except Exception:
                pass

        new = (self.device, self.language, self.max_tokens)
        if new != old and self._process and self._process.is_alive():
            self.logger.info("Whisper ONNX: настройки изменились, перезапуск процесса.")
            self._stop_process()
            self._is_initialized = False

    def _onnx_dir(self) -> str:
        return os.path.join(self.model_dir, "onnx")

    def _paths(self):
        d = self._onnx_dir()
        return {
            "encoder": os.path.join(d, "encoder_model.onnx"),
            "encoder_data": os.path.join(d, "encoder_model.onnx_data"),
            "decoder": os.path.join(d, "decoder_model.onnx"),
            "decoder_with_past": os.path.join(d, "decoder_with_past_model.onnx"),
        }

    def requirements(self):
        p = self._paths()
        return [
            AsrRequirement(id="torch", kind="python_module", module="torch", required=True),
            AsrRequirement(id="torchaudio", kind="python_module", module="torchaudio", required=True),
            AsrRequirement(id="sounddevice", kind="python_module", module="sounddevice", required=True),
            AsrRequirement(id="numpy", kind="python_module", module="numpy", required=True),
            AsrRequirement(id="silero_vad", kind="python_module", module="silero_vad", required=True),

            AsrRequirement(id="transformers", kind="python_module", module="transformers", required=True),
            AsrRequirement(id="optimum_ort", kind="python_module", module="optimum.onnxruntime", required=True),
            AsrRequirement(id="onnxruntime", kind="python_module", module="onnxruntime", required=True),

            AsrRequirement(id="whisper_cfg", kind="file", required=True, path=os.path.join(self.model_dir, "config.json")),
            AsrRequirement(id="whisper_tok", kind="file", required=True, path=os.path.join(self.model_dir, "tokenizer.json")),
            AsrRequirement(id="whisper_tok_cfg", kind="file", required=True, path=os.path.join(self.model_dir, "tokenizer_config.json")),
            AsrRequirement(id="whisper_special", kind="file", required=True, path=os.path.join(self.model_dir, "special_tokens_map.json")),
            AsrRequirement(id="whisper_preproc", kind="file", required=True, path=os.path.join(self.model_dir, "preprocessor_config.json")),

            AsrRequirement(id="whisper_onnx_encoder", kind="file", required=True, path=p["encoder"]),
            AsrRequirement(id="whisper_onnx_encoder_data", kind="file", required=True, path=p["encoder_data"]),
            AsrRequirement(id="whisper_onnx_decoder", kind="file", required=True, path=p["decoder"]),
            AsrRequirement(id="whisper_onnx_decoder_with_past", kind="file", required=True, path=p["decoder_with_past"]),
        ]

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        gpu = (ctx.get("gpu_vendor") or "CPU")
        device = str(ctx.get("device") or "auto").strip().lower()

        steps: List[dict] = []

        # 1) torch/torchaudio отдельно (из-за CUDA index-url)
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

        # 2) Остальные зависимости одним шагом
        need_dml = (device in ("auto", "dml")) and gpu != "NVIDIA"
        ort_pkg = "onnxruntime-directml" if need_dml else "onnxruntime"

        steps.append({
            "progress": 65,
            "description": _("Установка зависимостей ASR...", "Installing ASR dependencies..."),
            "packages": [
                "numpy",
                "sounddevice",
                "silero-vad",
                ort_pkg,
                "transformers",
            ],
            "extra_args": None
        })
        steps.append({
            "progress": 80,
            "description": _("Установка optimum (onnxruntime)...", "Installing optimum (onnxruntime)..."),
            "packages": ["optimum[onnxruntime]"],
            "extra_args": None
        })


        return steps

    def is_installed(self) -> bool:
        if self._current_gpu is None:
            try:
                self._current_gpu = check_gpu_provider() or "CPU"
            except Exception:
                self._current_gpu = "CPU"

        ctx = {"device": self.device, "gpu_vendor": self._current_gpu}
        st = check_requirements(self.requirements(), ctx=ctx)
        return bool(st.get("ok"))

    async def install(self) -> bool:
        p = self._paths()
        os.makedirs(self._onnx_dir(), exist_ok=True)
        os.makedirs(self.model_dir, exist_ok=True)

        def _download(url: str, dest: str, start_prog: int, end_prog: int):
            tmp = dest + ".part"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python-urllib", "Accept": "*/*"},
                method="GET",
            )

            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                last_emit = 0.0

                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024 * 4)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)

                        now = time.time()
                        if now - last_emit < 0.4:
                            continue
                        last_emit = now

                        pct = (done * 100.0 / total) if total > 0 else 0.0
                        prog = start_prog + int((end_prog - start_prog) * (pct / 100.0))
                        self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                            "model": "whisper_onnx",
                            "progress": int(max(0, min(99, prog))),
                            "status": _(f"Загрузка: {pct:.1f}%", f"Downloading: {pct:.1f}%")
                        })

            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except Exception:
                    pass
            os.replace(tmp, dest)

        try:
            repo_root = "https://huggingface.co/onnx-community/whisper-large-v3-turbo-onnx/resolve/main"
            repo_onnx = repo_root + "/onnx"

            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                "model": "whisper_onnx",
                "progress": 75,
                "status": _("Загрузка файлов transformers (локально)...", "Downloading transformers files (local)...")
            })

            tf_files = [
                ("config.json", os.path.join(self.model_dir, "config.json")),
                ("tokenizer.json", os.path.join(self.model_dir, "tokenizer.json")),
                ("tokenizer_config.json", os.path.join(self.model_dir, "tokenizer_config.json")),
                ("special_tokens_map.json", os.path.join(self.model_dir, "special_tokens_map.json")),
                ("preprocessor_config.json", os.path.join(self.model_dir, "preprocessor_config.json")),
                ("generation_config.json", os.path.join(self.model_dir, "generation_config.json")),
            ]

            prog_a, prog_b = 75, 80
            span = max(1, len(tf_files))
            for idx, (fname, dest) in enumerate(tf_files):
                if os.path.exists(dest) and os.path.getsize(dest) > 0:
                    continue
                s = prog_a + int((prog_b - prog_a) * (idx / span))
                e = prog_a + int((prog_b - prog_a) * ((idx + 1) / span))
                _download(f"{repo_root}/{fname}", dest, s, e)

            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                "model": "whisper_onnx",
                "progress": 80,
                "status": _("Загрузка ONNX модели Whisper...", "Downloading Whisper ONNX model...")
            })

            if not (os.path.exists(p["encoder"]) and os.path.getsize(p["encoder"]) > 0):
                _download(f"{repo_onnx}/encoder_model.onnx", p["encoder"], 80, 88)

            if not (os.path.exists(p["encoder_data"]) and os.path.getsize(p["encoder_data"]) > 0):
                _download(f"{repo_onnx}/encoder_model.onnx_data", p["encoder_data"], 88, 96)

            if not (os.path.exists(p["decoder"]) and os.path.getsize(p["decoder"]) > 0):
                _download(f"{repo_onnx}/decoder_model.onnx", p["decoder"], 96, 99)

            if not (os.path.exists(p["decoder_with_past"]) and os.path.getsize(p["decoder_with_past"]) > 0):
                _download(f"{repo_onnx}/decoder_with_past_model.onnx", p["decoder"], 96, 99)

            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                "model": "whisper_onnx",
                "progress": 100,
                "status": _("Файлы модели готовы.", "Model files are ready.")
            })
            return True

        except urllib.error.HTTPError as e:
            self.logger.error(f"Whisper ONNX download failed: HTTP {e.code} {e.reason}", exc_info=True)
            return False
        except Exception as e:
            self.logger.error(f"Whisper ONNX install failed: {e}", exc_info=True)
            return False

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
            self.logger.error(f"Whisper ONNX init imports failed: {e}")
            return False

        if self._start_process():
            self._is_initialized = True
            return True

        return False

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized or self._model is None:
            ok = await self.init()
            if not ok or self._model is None:
                self.logger.error("GigaAM не инициализирован (init failed)")
                return None

        if self._torch is None:
            import torch
            self._torch = torch

        torch = self._torch

        self._transcribe_event.clear()
        self._transcribe_result = None

        self._command_queue.put(("transcribe", audio_data, int(sample_rate)))

        if self._transcribe_event.wait(timeout=90):
            return self._transcribe_result
        self.logger.error("Whisper ONNX: таймаут транскрибации")
        return None

    async def live_recognition(self, microphone_index: int, handle_voice_callback,
                            vad_model, active_flag, **kwargs) -> None:
        if not self._is_initialized or self._model is None:
            ok = await self.init()
            if not ok or self._model is None:
                self.logger.error("GigaAM не инициализирован (init failed) — live_recognition остановлен")
                return

        if self._torch is None or self._sd is None or self._np is None:
            try:
                import torch
                import sounddevice as sd
                import numpy as np
                self._torch = self._torch or torch
                self._sd = self._sd or sd
                self._np = self._np or np
            except Exception as e:
                self.logger.error(f"live_recognition imports failed: {e}")
                return

        torch = self._torch
        sd = self._sd
        np = self._np

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

        stream = sd.InputStream(
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

                audio_tensor = torch.from_numpy(audio_chunk.flatten())
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
                        audio_to_process = np.concatenate(speech_buffer)

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

            audio_data_int16 = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(self._np.int16)

            with wave.open(filename, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data_int16.tobytes())

            self.logger.info(f"Фрагмент сохранен в: {filename}")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить аудиофрагмент: {e}")

    def cleanup(self) -> None:
        try:
            if self._model is not None:
                del self._model
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()
        except Exception:
            pass

        self._model = None
        self._is_initialized = False

    def _monitor_process(self):
        while not self._stop_monitor.is_set() and self._process and self._process.is_alive():
            try:
                while self._log_queue:
                    try:
                        level, msg = self._log_queue.get_nowait()
                        getattr(self.logger, level, self.logger.info)(f"[WhisperONNX Process] {msg}")
                    except queue.Empty:
                        break

                while self._result_queue:
                    try:
                        result = self._result_queue.get_nowait()
                        rtype = result[0]

                        if rtype == "init_success":
                            self._process_initialized = True
                        elif rtype == "init_error":
                            self.logger.error(f"Whisper ONNX init error: {result[1]}")
                            self._process_initialized = False
                        elif rtype == "transcription":
                            self._transcribe_result = result[1]
                            self._transcribe_event.set()
                        elif rtype == "transcription_error":
                            self._transcribe_result = None
                            self._transcribe_event.set()
                    except queue.Empty:
                        break

                time.sleep(0.01)

            except Exception as e:
                self.logger.error(f"Ошибка в мониторе Whisper ONNX процесса: {e}")

    def _start_process(self) -> bool:
        if self._process and self._process.is_alive():
            return True

        self._command_queue = mp.Queue()
        self._result_queue = mp.Queue()
        self._log_queue = mp.Queue()

        from handlers.asr_models.whisper_onnx_process import run_whisper_onnx_process

        self._process = mp.Process(
            target=run_whisper_onnx_process,
            args=(self._command_queue, self._result_queue, self._log_queue),
            daemon=True
        )
        self._process.start()

        self._stop_monitor.clear()
        self._process_initialized = False
        self._monitor_thread = Thread(target=self._monitor_process, daemon=True)
        self._monitor_thread.start()

        init_options = {
            "device": self.device,
            "language": self.language,
            "max_tokens": int(self.max_tokens or 192),

            "model_dir": self.model_dir,
            "onnx_subfolder": "onnx",

            "encoder_file_name": "encoder_model.onnx",
            "decoder_file_name": "decoder_model.onnx",
        }
        self._command_queue.put(("init", init_options))

        timeout = 180
        start = time.time()
        while not self._process_initialized:
            if time.time() - start > timeout:
                self.logger.error("Whisper ONNX: таймаут инициализации процесса")
                self._stop_process()
                return False
            time.sleep(0.1)

        self.logger.success("Whisper ONNX процесс успешно запущен и инициализирован")
        return True
    
    def _stop_process(self):
        if not self._process:
            return

        self._stop_monitor.set()

        try:
            if self._command_queue:
                self._command_queue.put(("shutdown",))
        except Exception:
            pass

        try:
            if self._monitor_thread:
                self._monitor_thread.join(timeout=2)
        except Exception:
            pass

        try:
            self._process.join(timeout=5)
            if self._process.is_alive():
                self.logger.warning("Whisper ONNX процесс не завершился, terminate()")
                self._process.terminate()
                self._process.join(timeout=2)
        except Exception:
            pass

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