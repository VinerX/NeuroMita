import os
import time
import wave
import asyncio
from typing import Optional, List
from collections import deque

import numpy as np

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from handlers.asr_models.requirements import AsrRequirement, check_requirements

from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider
from core.events import get_event_bus, Events


class WhisperRecognizer(SpeechRecognizerInterface):
    
    MODEL_CONFIGS = [
        {
            "id": "whisper",
            "name": "Whisper Large v3 turbo",
            "description": _(
                "Офлайн Whisper через faster-whisper (CTranslate2). Быстро работает на NVIDIA GPU (CUDA), "
                "на CPU тоже поддерживается. Требует скачивания модели в локальный кэш.",
                "Offline Whisper via faster-whisper (CTranslate2). Fast on NVIDIA GPU (CUDA), "
                "CPU is supported as well. Requires downloading the model into local cache."
            ),
            "languages": ["Multilingual"],
            "gpu_vendor": ["NVIDIA", "CPU"],
            "tags": [
                _("Офлайн", "Offline"),
                _("Локально", "Local"),
            ],
            "links": [
                {"label": "faster-whisper (PyPI)", "url": "https://pypi.org/project/faster-whisper/"}
            ]
        }
    ]

    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)

        self._torch = None
        self._sd = None
        self._np = None
        self._fw = None

        self._model = None
        self._current_gpu = None

        self.whisper_device = "auto"   # auto | cuda | cpu | dml (dml пока фолбэк в cpu)
        self.whisper_model = "large-v3-turbo"
        self.compute_type = "auto"     # auto | int8 | float16 | float32 | int8_float16
        self.language = "ru"
        self.beam_size = 5

        self.model_download_root = "SpeechRecognitionModels/WhisperFW"
        self.FAILED_AUDIO_DIR = "FailedAudios"
        self.TEMP_AUDIO_DIR = "TempAudios"

        self._event_bus = get_event_bus()

    # ---------- UI schema ----------
    def settings_spec(self):
        return [
            {"key": "device", "label_ru": "Устройство", "label_en": "Device",
             "type": "combobox", "options": ["auto", "cuda", "cpu", "dml"], "default": "auto"},
            {"key": "model", "label_ru": "Модель", "label_en": "Model",
             "type": "combobox", "options": ["large-v3-turbo", "large-v3"], "default": "large-v3-turbo"},
            {"key": "compute_type", "label_ru": "Точность", "label_en": "Compute type",
             "type": "combobox", "options": ["auto", "int8", "float16", "float32", "int8_float16"], "default": "auto"},
            {"key": "language", "label_ru": "Язык", "label_en": "Language",
             "type": "combobox", "options": ["ru", "en", "auto"], "default": "ru"},
            {"key": "beam_size", "label_ru": "Beam size", "label_en": "Beam size",
             "type": "combobox", "options": [1, 2, 3, 5, 8], "default": 5},
        ]

    def get_default_settings(self):
        return {"device": "auto", "model": "large-v3-turbo", "compute_type": "auto", "language": "ru", "beam_size": 5}

    def apply_settings(self, settings: dict):
        dev = settings.get("device")
        mdl = settings.get("model")
        ct = settings.get("compute_type")
        lang = settings.get("language")
        bs = settings.get("beam_size")

        changed = False

        if dev:
            self.whisper_device = str(dev).strip().lower()
            changed = True
        if mdl:
            self.whisper_model = str(mdl).strip()
            changed = True
        if ct:
            self.compute_type = str(ct).strip().lower()
            changed = True
        if lang:
            self.language = str(lang).strip().lower()
        if bs is not None:
            try:
                self.beam_size = int(bs)
            except Exception:
                pass

        if changed and self._model is not None:
            self.cleanup()

    # ---------- dependency model ----------
    def requirements(self):
        return [
            AsrRequirement(id="torch", kind="python_module", module="torch", required=True),
            AsrRequirement(id="silero_vad", kind="python_module", module="silero_vad", required=True),
            AsrRequirement(id="sounddevice", kind="python_module", module="sounddevice", required=True),
            AsrRequirement(id="numpy", kind="python_module", module="numpy", required=True),
            AsrRequirement(id="faster_whisper", kind="python_module", module="faster_whisper", required=True),
        ]

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        gpu = (ctx.get("gpu_vendor") or "CPU")
        device = str(ctx.get("device") or "auto").strip().lower()

        steps: List[dict] = []

        # torch нужен для silero-vad (даже если whisper сам на CTranslate2)
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

        steps.append({
            "progress": 40,
            "description": _("Установка Silero VAD...", "Installing Silero VAD..."),
            "packages": ["silero-vad"],
            "extra_args": None
        })
        steps.append({
            "progress": 55,
            "description": _("Установка sounddevice...", "Installing sounddevice..."),
            "packages": ["sounddevice"],
            "extra_args": None
        })
        steps.append({
            "progress": 60,
            "description": _("Установка numpy...", "Installing numpy..."),
            "packages": ["numpy"],
            "extra_args": None
        })
        steps.append({
            "progress": 70,
            "description": _("Установка faster-whisper...", "Installing faster-whisper..."),
            "packages": ["faster-whisper"],
            "extra_args": None
        })

        return steps

    def is_installed(self) -> bool:
        if self._current_gpu is None:
            try:
                self._current_gpu = check_gpu_provider() or "CPU"
            except Exception:
                self._current_gpu = "CPU"

        ctx = {"device": self.whisper_device, "gpu_vendor": self._current_gpu}
        st = check_requirements(self.requirements(), ctx=ctx)
        return bool(st.get("ok"))

    # ---------- artifacts install ----------
    async def install(self) -> bool:
        if not self.is_installed():
            return False

        self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
            "model": "whisper",
            "progress": 80,
            "status": _("Загрузка модели Whisper (кэш)...", "Downloading Whisper model (cache)...")
        })

        try:
            from faster_whisper import WhisperModel

            os.makedirs(self.model_download_root, exist_ok=True)

            device = self._resolve_device_for_runtime()
            compute_type = self._resolve_compute_type(device)

            _m = WhisperModel(
                self.whisper_model,
                device=device,
                compute_type=compute_type,
                download_root=self.model_download_root
            )
            del _m

            self._event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                "model": "whisper",
                "progress": 100,
                "status": _("Файлы модели готовы.", "Model files are ready.")
            })
            return True
        except Exception as e:
            self.logger.error(f"Whisper install failed: {e}", exc_info=True)
            return False

    # ---------- runtime ----------
    def _resolve_device_for_runtime(self) -> str:
        dev = (self.whisper_device or "auto").strip().lower()

        if dev == "dml":
            self.logger.warning("Whisper: режим dml пока не реализован, используется CPU.")
            return "cpu"

        if dev == "cpu":
            return "cpu"

        if dev == "cuda":
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda"
                self.logger.warning("Whisper: CUDA запрошен, но недоступен. Используется CPU.")
                return "cpu"
            except Exception:
                return "cpu"

        # auto
        try:
            gpu = check_gpu_provider() or "CPU"
        except Exception:
            gpu = "CPU"

        if gpu == "NVIDIA":
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda"
            except Exception:
                pass

        return "cpu"

    def _resolve_compute_type(self, device: str) -> str:
        ct = (self.compute_type or "auto").strip().lower()
        if ct and ct != "auto":
            return ct
        return "float16" if device == "cuda" else "int8"

    async def init(self, **kwargs) -> bool:
        if self._is_initialized and self._model is not None:
            return True

        if not self.is_installed():
            return False

        try:
            import torch
            import sounddevice as sd
            import numpy as np
            from faster_whisper import WhisperModel

            self._torch = torch
            self._sd = sd
            self._np = np
            self._fw = WhisperModel

            os.makedirs(self.model_download_root, exist_ok=True)

            device = self._resolve_device_for_runtime()
            compute_type = self._resolve_compute_type(device)

            self.logger.info(f"Whisper init: model={self.whisper_model}, device={device}, compute_type={compute_type}")
            self._model = WhisperModel(
                self.whisper_model,
                device=device,
                compute_type=compute_type,
                download_root=self.model_download_root
            )

            self._is_initialized = True
            return True

        except Exception as e:
            self.logger.error(f"Whisper init failed: {e}", exc_info=True)
            self._is_initialized = False
            return False

    def _write_temp_wav(self, audio_data: np.ndarray, sample_rate: int) -> str:
        os.makedirs(self.TEMP_AUDIO_DIR, exist_ok=True)
        path = os.path.join(self.TEMP_AUDIO_DIR, f"temp_whisper_{time.time_ns()}.wav")

        audio = audio_data
        if audio is None:
            raise ValueError("audio_data is None")
        audio = np.asarray(audio).astype(np.float32)
        audio = audio.reshape(-1)

        audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate))
            wf.writeframes(audio_int16.tobytes())

        return path

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized or self._model is None:
            return None

        lang = (self.language or "ru").strip().lower()
        if lang == "auto":
            lang = None

        audio = np.asarray(audio_data).astype(np.float32).reshape(-1)

        tmp_path = None
        try:
            # faster-whisper умеет принимать и np.ndarray, но на всякий случай держим файловый фолбэк
            try:
                segments, _info = self._model.transcribe(
                    audio,
                    language=lang,
                    beam_size=int(self.beam_size or 5),
                    vad_filter=False,
                    condition_on_previous_text=False,
                )
            except Exception:
                tmp_path = self._write_temp_wav(audio, sample_rate)
                segments, _info = self._model.transcribe(
                    tmp_path,
                    language=lang,
                    beam_size=int(self.beam_size or 5),
                    vad_filter=False,
                    condition_on_previous_text=False,
                )

            parts = []
            for seg in segments:
                t = (getattr(seg, "text", "") or "").strip()
                if t:
                    parts.append(t)

            text = " ".join(parts).strip()
            return text or None

        except Exception as e:
            self.logger.error(f"Whisper transcribe error: {e}", exc_info=True)
            return None

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    async def live_recognition(self, microphone_index: int, handle_voice_callback,
                              vad_model, active_flag, **kwargs) -> None:
        if not self._is_initialized or self._model is None:
            self.logger.error("Whisper не инициализирован")
            return

        if vad_model is None:
            self.logger.error("Whisper: vad_model не передан")
            return

        sample_rate = int(kwargs.get('sample_rate', 16000))
        chunk_size = int(kwargs.get('chunk_size', 512))
        vad_threshold = float(kwargs.get('vad_threshold', 0.5))
        silence_timeout = float(kwargs.get('silence_timeout', 1.0))
        pre_buffer_duration = float(kwargs.get('pre_buffer_duration', 0.3))

        silence_chunks_needed = int(silence_timeout * sample_rate / chunk_size)
        pre_buffer_size = int(pre_buffer_duration * sample_rate / chunk_size)

        pre_speech_buffer = deque(maxlen=max(1, pre_buffer_size))
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

            audio_data_int16 = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(self._np.int16)

            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data_int16.tobytes())

            self.logger.info(f"Фрагмент сохранен в: {filename}")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить аудиофрагмент: {e}")

    def cleanup(self) -> None:
        self._model = None
        self._fw = None
        self._torch = None
        self._sd = None
        self._np = None
        self._is_initialized = False