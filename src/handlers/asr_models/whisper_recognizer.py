import os
import re
import time
import wave
import gc
from typing import Optional, List

import numpy as np

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from core.installables.helpers import build_runtime_ctx
from core.backends import BackendKind, get_backend_service
from core.install_requirements import InstallRequirement, check_requirements

from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider



def _normalize_hallucination(text: str) -> str:
    """Нормализация для сравнения с чёрным списком галлюцинаций:
    нижний регистр, только буквы/цифры, схлопнутые пробелы."""
    t = (text or "").lower()
    t = re.sub(r"[^0-9a-zа-яё]+", " ", t)
    return " ".join(t.split())


# Известные галлюцинации Whisper на тишине/шуме — артефакты из ютуб-субтитров
# в обучающих данных. Whisper на пустом/шумном фрагменте любит выдавать эти
# фразы целиком. Сравниваем по полному нормализованному совпадению сегмента,
# чтобы не резать легитимную речь ("спасибо" само по себе не пострадает).
_WHISPER_HALLUCINATIONS = frozenset(
    _normalize_hallucination(p) for p in (
        "Субтитры сделал DimaTorzok",
        "Субтитры делал DimaTorzok",
        "Субтитры создавал DimaTorzok",
        "Субтитры сделаны DimaTorzok",
        "Продолжение следует...",
        "Спасибо за просмотр!",
        "Спасибо за внимание!",
        "Подписывайтесь на канал",
        "Ставьте лайки",
        "Редактор субтитров А.Синецкая Корректор А.Егорова",
        "Субтитры А.Синецкая",
        "Субтитры и корректура Оксаны Каменской",
        "続きは次回",
        "Thanks for watching!",
        "Субтитры сделаны сообществом Amara.org",
        "www.amara.org",
    )
)

class WhisperRecognizer(SpeechRecognizerInterface):
    _RUNTIME_PIP_SPECS = (
        "sounddevice",
        "silero-vad",
        "ctranslate2",
        "faster-whisper",
        "transformers",
        "pyyaml>=5.1",
    )

    # Веса CT2-модели качаем прямыми HTTP-ссылками (как ONNX/GigaAM), а НЕ через
    # WhisperModel(...) на этапе установки: скачивание идёт в основном процессе
    # приложения, где faster_whisper/torch недоступны (они в изолированной среде
    # движка). Репозитории — из faster_whisper._MODELS, файлы — из allow_patterns
    # download_model(). vocabulary.* в обоих репах — vocabulary.json.
    _MODEL_REPOS = {
        "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "large-v3": "Systran/faster-whisper-large-v3",
    }
    _MODEL_FILES = (
        "config.json",
        "preprocessor_config.json",
        "tokenizer.json",
        "vocabulary.json",
        "model.bin",
    )


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
            "backend": "cpu",
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
        self._last_requirements_probe_message: Optional[str] = None
        self._last_requirements_probe_status: Optional[dict] = None

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
        backend_kind = self.required_backend({
            "device": self.whisper_device,
            "gpu_vendor": self._current_gpu or "CPU",
        })
        requirements = [
            InstallRequirement(id=f"backend_{backend_kind.value}", kind="backend", backend_kind=backend_kind, required=True),
        ]
        for spec in self._RUNTIME_PIP_SPECS:
            requirements.append(
                InstallRequirement(
                    id=str(spec).split(">=", 1)[0].replace("-", "_"),
                    kind="python_dist",
                    spec=spec,
                    required=True,
                )
            )
        return requirements

    def _describe_requirements_failure(self, status: dict) -> str:
        missing = [str(item) for item in (status.get("missing_required") or []) if str(item).strip()]
        details = status.get("details") if isinstance(status.get("details"), list) else []

        detail_parts: list[str] = []
        for item in details:
            if not isinstance(item, dict) or item.get("ok", True):
                continue
            req_id = str(item.get("id") or "").strip()
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            spec = str(extra.get("spec") or "").strip()
            version = extra.get("version")
            if spec:
                detail_parts.append(f"{req_id}<{spec}> version={version}")
            else:
                detail_parts.append(f"{req_id} version={version}")

        if detail_parts:
            base = f"Whisper requirements are missing or broken: {', '.join(detail_parts)}"
        elif missing:
            base = f"Whisper requirements are missing or broken: {', '.join(missing)}"
        else:
            base = "Whisper requirements are missing or broken."

        if any("pyyaml" in part.lower() and "version=none" in part.lower() for part in detail_parts):
            return (
                base
                + " PyYAML looks corrupted in Lib: the 'yaml' module may exist, but the "
                + "PyYAML dist-info/METADATA is missing or unreadable. Reinstall the Whisper component."
            )
        return base

    def _log_requirements_failure_once(self, status: dict) -> None:
        message = self._describe_requirements_failure(status)
        if message != self._last_requirements_probe_message:
            self.logger.warning(message)
            self._last_requirements_probe_message = message
        self._last_requirements_probe_status = status

    def _diagnose_init_failure(self, exc: Exception) -> str | None:
        text = str(exc or "")
        lower = text.lower()
        if "pyyaml" in lower and "found=none" in lower:
            return (
                "Whisper init diagnostic: transformers found the 'yaml' module but could not read the "
                "installed PyYAML distribution version. Usually this means the PyYAML dist-info in Lib "
                "is missing or corrupted. Reinstall the Whisper ASR component or PyYAML explicitly."
            )
        return None

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        steps: List[dict] = []

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
            "progress": 70,
            "description": _("Установка faster-whisper и зависимостей...", "Installing faster-whisper and dependencies..."),
            "packages": ["pyyaml>=5.1", "transformers", "ctranslate2", "faster-whisper"],
            "extra_args": None
        })

        return steps

    def required_backend(self, ctx: dict) -> BackendKind:
        return get_backend_service().preferred_torch_kind(ctx)

    def is_installed(self, ctx: dict | None = None) -> bool:
        run_ctx = build_runtime_ctx(ctx)
        run_ctx.setdefault("device", self.whisper_device)
        if self._current_gpu is None:
            self._current_gpu = str(run_ctx.get("gpu_vendor") or "CPU")
        run_ctx.setdefault("gpu_vendor", self._current_gpu)
        st = check_requirements(self.requirements(), ctx=run_ctx)
        ok = bool(st.get("ok"))
        if not ok:
            self._last_requirements_probe_message = self._describe_requirements_failure(st)
            self._last_requirements_probe_status = st
            return False
        self._last_requirements_probe_message = None
        self._last_requirements_probe_status = None

        # Пакеты на месте — но модель установлена только когда веса реально
        # скачаны (иначе after-install check «проходил» на пустой папке, а init
        # падал). Проверяем файлы из манифеста, как ONNX/GigaAM.
        manifest = self.install_manifest()
        if not manifest:
            return False
        for item in manifest:
            dest = str(item.get("dest") or "").strip()
            if not dest or not os.path.exists(dest) or os.path.getsize(dest) <= 0:
                return False
        return True

    def _model_local_dir(self) -> str:
        """Каталог с весами текущей модели, напр. SpeechRecognitionModels/WhisperFW/large-v3-turbo."""
        return os.path.join(self.model_download_root, self.whisper_model)

    def install_manifest(self) -> list[dict]:
        repo = self._MODEL_REPOS.get(self.whisper_model)
        if not repo:
            return []
        base = f"https://huggingface.co/{repo}/resolve/main"
        model_dir = self._model_local_dir()
        return [
            {"url": f"{base}/{fname}", "dest": os.path.join(model_dir, fname)}
            for fname in self._MODEL_FILES
        ]

    def uninstall_pip_packages(self) -> list[str]:
        # Только эксклюзивные для Whisper пакеты. sounddevice/silero-vad/transformers/
        # pyyaml — общие с другими движками/RAG, их не трогаем (удаление некаскадное).
        return ["faster-whisper", "ctranslate2"]

    def uninstall_paths(self) -> list[str]:
        # Кэш скачанных весов модели (~1.5 ГБ) — иначе после удаления они остаются
        # на диске, а повторная установка думает, что модель уже скачана.
        return [self.model_download_root]

    # ---------- artifacts install ----------
    async def install(self) -> bool:
        # Веса качает base-план через download_http (install_manifest непустой) —
        # прямыми ссылками, без импорта faster_whisper в основном процессе.
        # Метод оставлен для совместимости контракта и в этот путь не попадает.
        return True

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
            self.logger.error("Whisper init aborted: runtime dependencies are missing or broken.")
            details = self._describe_requirements_failure(self._last_requirements_probe_status or {})
            self.logger.error(details)
            return False

        try:
            import torch
            import numpy as np
            from faster_whisper import WhisperModel

            self._torch = torch
            self._np = np
            self._fw = WhisperModel

            os.makedirs(self.model_download_root, exist_ok=True)

            device = self._resolve_device_for_runtime()
            compute_type = self._resolve_compute_type(device)

            # Грузим из локального каталога с заранее скачанными весами (их кладёт
            # download_http на этапе установки). Так faster_whisper не обращается к
            # своему репо-маппингу и не пытается доскачивать. Фолбэк на имя модели —
            # если каталога нет (напр. старая установка через кэш download_root).
            model_dir = self._model_local_dir()
            if os.path.isfile(os.path.join(model_dir, "model.bin")):
                model_ref = model_dir
            else:
                model_ref = self.whisper_model

            self.logger.info(
                f"Whisper init: model={self.whisper_model}, source={model_ref}, "
                f"device={device}, compute_type={compute_type}"
            )
            self._model = WhisperModel(
                model_ref,
                device=device,
                compute_type=compute_type,
                download_root=self.model_download_root
            )

            self._is_initialized = True
            return True

        except Exception as e:
            diagnostic = self._diagnose_init_failure(e)
            if diagnostic:
                self.logger.error(diagnostic)
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
                if not t:
                    continue
                if _normalize_hallucination(t) in _WHISPER_HALLUCINATIONS:
                    self.logger.debug(f"Whisper: отфильтрована галлюцинация-сегмент: {t!r}")
                    continue
                parts.append(t)

            text = " ".join(parts).strip()
            if not text:
                return None

            # Фолбэк: если весь ответ целиком совпал с известной галлюцинацией
            # (например, единый сегмент без разбивки), тоже отбрасываем.
            if _normalize_hallucination(text) in _WHISPER_HALLUCINATIONS:
                self.logger.debug(f"Whisper: отфильтрована галлюцинация: {text!r}")
                return None

            return text

        except Exception as e:
            self.logger.error(f"Whisper transcribe error: {e}", exc_info=True)
            return None

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
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
        try:
            if self._model is not None:
                try:
                    self._model.cpu()
                except Exception:
                    pass
                model_ref = self._model
                self._model = None
                del model_ref
            gc.collect()
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()
        except Exception:
            pass
        self._model = None
        self._fw = None
        self._torch = None
        self._np = None
        self._is_initialized = False
