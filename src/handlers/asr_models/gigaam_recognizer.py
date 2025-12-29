import os
import time
import wave
import asyncio
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
    """
    Обычная PyTorch-версия:
    - без отдельного процесса
    - работает на CPU/CUDA (если доступно)
    """

    MODEL_CONFIGS = [
        {
            "id": "gigaam",
            "name": "GigaAM",
            "description": _(
                "Офлайн-распознавание речи на базе GigaAM (PyTorch). Работает в текущем процессе.",
                "Offline speech recognition based on GigaAM (PyTorch). Runs in current process."
            ),
            "languages": ["Russian"],
            "gpu_vendor": ["NVIDIA", "CPU"],
            "tags": [
                _("Локально", "Local"),
                _("Без отдельного процесса", "No separate process"),
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
        self.gigaam_device = "auto"  # auto/cuda/cpu
        self.gigaam_model_path = "SpeechRecognitionModels/GigaAM"

        self.FAILED_AUDIO_DIR = "FailedAudios"
        self._event_bus = get_event_bus()
        self._url_dir = "https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM"

        self._model = None  # PyTorch модель

        self._model_names = [
            "v2_rnnt", "v2_ctc",
            "v3_rnnt", "v3_ctc",
            "v3_e2e_ctc", "v3_e2e_rnnt"
        ]

    # ---------- UI schema ----------
    def settings_spec(self):
        return [
            {"key": "device", "label_ru": "Устройство", "label_en": "Device",
             "type": "combobox", "options": ["auto", "cuda", "cpu"], "default": "auto"},
            {"key": "model", "label_ru": "Модель", "label_en": "Model",
             "type": "combobox",
             "options": [
                 "v2_rnnt", "v2_ctc",
                 "v3_rnnt", "v3_ctc",
                 "v3_e2e_ctc", "v3_e2e_rnnt"
             ],
             "default": "v3_e2e_rnnt"}
        ]

    def get_default_settings(self):
        return {"device": "auto", "model": "v3_e2e_rnnt"}

    def apply_settings(self, settings: dict):
        dev = settings.get("device")
        mdl = settings.get("model")
        if dev or mdl:
            self.set_options(device=dev or self.gigaam_device, model=mdl or self.gigaam_model)

    def set_options(self, device: str, model: str = None, model_path: str = None):
        self.gigaam_device = (device or self.gigaam_device).strip().lower()
        if model:
            self.gigaam_model = str(model).strip()
        if model_path:
            self.gigaam_model_path = str(model_path)

        # если модель уже загружена — сбрасываем, чтобы переинициализировать на другом устройстве
        if self._model is not None:
            self.logger.info("Настройки изменены — модель будет перезагружена при следующем init()")
            self._model = None
            self._is_initialized = False

    # ---------- naming / paths ----------
    def _normalized_ckpt_name(self) -> str:
        name = (self.gigaam_model or "v2_rnnt").strip()
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
        def ckpt_path(_ctx: dict) -> str:
            return self._ckpt_path()

        return [
            AsrRequirement(id="torch", kind="python_module", module="torch", required=True),
            AsrRequirement(id="torchaudio", kind="python_module", module="torchaudio", required=True),
            AsrRequirement(id="omegaconf", kind="python_module", module="omegaconf", required=True),
            AsrRequirement(id="hydra", kind="python_module", module="hydra", required=True),
            AsrRequirement(id="sentencepiece", kind="python_module", module="sentencepiece", required=True),

            AsrRequirement(id="silero_vad", kind="python_module", module="silero_vad", required=True),
            AsrRequirement(id="sounddevice", kind="python_module", module="sounddevice", required=True),
            AsrRequirement(id="numpy", kind="python_module", module="numpy", required=True),
        ]

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        gpu = (ctx.get("gpu_vendor") or "CPU")
        device = str(ctx.get("device") or "auto").strip().lower()

        steps: List[dict] = []

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
            "progress": 30,
            "description": _("Установка зависимостей...", "Installing deps..."),
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
                            "model": "gigaam",
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
        if self._is_initialized and self._model is not None:
            return True

        try:
            import sys
            import torch
            import torchaudio
            import sounddevice as sd
            import numpy as np

            self._torch = torch
            self._sd = sd
            self._np = np
        except Exception as e:
            self.logger.error(f"GigaAM init imports failed: {e}")
            return False

        # alias для hydra targets ("gigaam.*")
        import handlers.asr_models.gigaam as gigaam
        import sys
        sys.modules["gigaam"] = gigaam

        # safe_globals для torch.load(ckpt)
        import omegaconf, typing, collections
        self._torch.serialization.add_safe_globals([
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

        # выбор девайса
        device_choice = (self.gigaam_device or "auto").strip().lower()
        if device_choice == "cuda" and not (self._torch.cuda.is_available()):
            self.logger.warning("Запрошен CUDA, но CUDA недоступен. Переходим на CPU.")
            device_choice = "cpu"

        if device_choice == "auto":
            device_choice = "cuda" if self._torch.cuda.is_available() else "cpu"

        try:
            self.logger.info(f"Загрузка GigaAM (PyTorch) на {device_choice}...")
            self._model = gigaam.load_model(
                self.gigaam_model,
                device=device_choice,
                download_root=self.gigaam_model_path,
                use_flash=False,
            )
            self._is_initialized = True
            self.logger.success("GigaAM (PyTorch) успешно инициализирован")
            return True
        except Exception as e:
            self.logger.error(f"Не удалось загрузить GigaAM: {e}", exc_info=True)
            self._model = None
            self._is_initialized = False
            return False

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized or self._model is None:
            self.logger.error("GigaAM не инициализирован")
            return None

        try:
            import torchaudio

            wav = self._torch.from_numpy(np.asarray(audio_data, dtype=np.float32).reshape(-1))
            # ресемпл до 16k (чтобы соответствовать модели, как делал ffmpeg)
            if int(sample_rate) != 16000:
                wav = torchaudio.functional.resample(wav, int(sample_rate), 16000)

            wav = wav.to(next(self._model.parameters()).device).to(next(self._model.parameters()).dtype)
            length = self._torch.tensor([wav.numel()], device=wav.device, dtype=self._torch.long)

            # напрямую используем forward+decoding (без временного файла)
            encoded, encoded_len = self._model.forward(wav.unsqueeze(0), length)
            text = self._model.decoding.decode(self._model.head, encoded, encoded_len)[0]

            if text and text.strip():
                return text
            return None

        except Exception as e:
            self.logger.error(f"Ошибка транскрибации: {e}", exc_info=True)
            return None

    async def live_recognition(self, microphone_index: int, handle_voice_callback,
                              vad_model, active_flag, **kwargs) -> None:
        if not self._is_initialized or self._model is None:
            self.logger.error("GigaAM не инициализирован")
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
        try:
            if self._model is not None:
                del self._model
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()
        except Exception:
            pass

        self._model = None
        self._torch = None
        self._sd = None
        self._np = None
        self._is_initialized = False