import os
import gc
from typing import Optional, List
import numpy as np
import urllib.request
import urllib.error

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from core.installables.helpers import build_runtime_ctx
from core.backends import BackendKind, get_backend_service
from core.install_requirements import InstallRequirement, check_requirements


def _(ru_str, en_str=""):
    return en_str or ru_str


def check_gpu_provider() -> str:
    try:
        import torch
        return "NVIDIA" if torch.cuda.is_available() else "CPU"
    except Exception:
        return "CPU"


class GigaAMRecognizer(SpeechRecognizerInterface):
    """
    Regular PyTorch version:
    - no separate process
    - runs on CPU/CUDA (if available)
    """

    MODEL_CONFIGS = [
        {
            "id": "gigaam",
            "name": "GigaAM",
            "description": _(
                "Offline speech recognition based on GigaAM (PyTorch). Runs in current process.",
                "Offline speech recognition based on GigaAM (PyTorch). Runs in current process."
            ),
            "languages": ["Russian"],
            "gpu_vendor": ["NVIDIA", "CPU"],
            "tags": [
                _("Local", "Local"),
                _("No separate process", "No separate process"),
            ],
            "links": []
        }
    ]

    # Единственный источник истины по допустимым моделям и дефолту.
    # SSL/Emo-чекпоинты (v3_ssl и т.п.) не умеют распознавать речь и сюда
    # не входят; сохранённые в настройках недопустимые значения приводятся
    # к DEFAULT_MODEL (см. set_options и SpeechController._load_asr_settings).
    VALID_MODELS = ("v2_rnnt", "v2_ctc", "v3_rnnt", "v3_ctc", "v3_e2e_ctc", "v3_e2e_rnnt")
    DEFAULT_MODEL = "v3_e2e_rnnt"

    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)

        self._torch = None
        self._np = None

        self._current_gpu = None

        self.gigaam_model = self.DEFAULT_MODEL
        self.gigaam_device = "auto"  # auto/cuda/cpu
        self.gigaam_model_path = "SpeechRecognitionModels/GigaAM"

        self._url_dir = "https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM"

        self._model = None  # PyTorch model

        self._model_names = list(self.VALID_MODELS)

    # ---------- UI schema ----------
    def settings_spec(self):
        return [
            {"key": "device", "label_ru": "Device", "label_en": "Device",
             "type": "combobox", "options": ["auto", "cuda", "cpu"], "default": "auto"},
            {"key": "model", "label_ru": "Model", "label_en": "Model",
             "type": "combobox",
             "options": list(self.VALID_MODELS),
             "default": self.DEFAULT_MODEL}
        ]

    def get_default_settings(self):
        return {"device": "auto", "model": self.DEFAULT_MODEL}

    def apply_settings(self, settings: dict):
        dev = settings.get("device")
        mdl = settings.get("model")
        if dev is not None or mdl is not None:
            self.set_options(device=dev, model=mdl)

    def set_options(self, device: str, model: str = None, model_path: str = None):
        """
        Idempotent options update.

        Important: do not reset an already loaded model if effective values did not change.
        This protects from repeated apply_settings() calls (for example from UI/indicators)
        that previously reset self._model and self._is_initialized.
        """
        old_device = (self.gigaam_device or "auto").strip().lower()
        old_model = str(self.gigaam_model or "v3_rnnt").strip()
        old_path = str(self.gigaam_model_path or "").strip()

        new_device = old_device
        if device is not None:
            new_device = str(device or old_device).strip().lower()

        new_model = old_model
        if model is not None:
            new_model = str(model or old_model).strip()
        if new_model not in self.VALID_MODELS:
            self.logger.warning(
                f"GigaAM: model '{new_model}' is not a valid ASR checkpoint "
                f"(SSL/Emo checkpoints cannot transcribe speech) — falling back to '{self.DEFAULT_MODEL}'."
            )
            new_model = self.DEFAULT_MODEL

        new_path = old_path
        if model_path is not None:
            new_path = str(model_path or old_path).strip()

        changed = (new_device != old_device) or (new_model != old_model) or (new_path != old_path)

        # Update fields only when values actually changed
        if changed:
            self.gigaam_device = new_device
            self.gigaam_model = new_model
            self.gigaam_model_path = new_path

            # Reset only if the model is already loaded or marked initialized
            if self._model is not None or self._is_initialized:
                self.logger.info("Settings changed - the model will be reloaded on the next init().")
                self._model = None
                self._is_initialized = False

    # ---------- naming / paths ----------
    def _normalized_ckpt_name(self) -> str:
        name = (self.gigaam_model or self.DEFAULT_MODEL).strip()
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

    def _model_root_abs(self) -> str:
        return os.path.abspath(self.gigaam_model_path)

    # ---------- dependency model ----------
    def requirements(self):
        backend_kind = self.required_backend({
            "device": self.gigaam_device,
            "gpu_vendor": self._current_gpu or "CPU",
        })
        return [
            InstallRequirement(id=f"backend_{backend_kind.value}", kind="backend", backend_kind=backend_kind, required=True),
            InstallRequirement(id="omegaconf", kind="python_module", module="omegaconf", required=True),
            InstallRequirement(id="hydra", kind="python_module", module="hydra", required=True),
            InstallRequirement(id="sentencepiece", kind="python_module", module="sentencepiece", required=True),

            InstallRequirement(id="silero_vad", kind="python_module", module="silero_vad", required=True),
            InstallRequirement(id="sounddevice", kind="python_module", module="sounddevice", required=True),
        ]

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        steps: List[dict] = []

        steps.append({
            "progress": 30,
            "description": _("Installing deps...", "Installing deps..."),
            "packages": ["hydra-core", "sentencepiece", "omegaconf"],
            "extra_args": None
        })

        steps.append({
            "progress": 55,
            "description": _("Installing Silero VAD...", "Installing Silero VAD..."),
            "packages": ["silero-vad"],
            "extra_args": None
        })
        steps.append({
            "progress": 60,
            "description": _("Installing sounddevice...", "Installing sounddevice..."),
            "packages": ["sounddevice"],
            "extra_args": None
        })

        return steps

    def required_backend(self, ctx: dict) -> BackendKind:
        return get_backend_service().preferred_torch_kind(ctx)

    def is_installed(self, ctx: dict | None = None) -> bool:
        run_ctx = build_runtime_ctx(ctx)
        run_ctx.setdefault("device", self.gigaam_device)
        if self._current_gpu is None:
            self._current_gpu = str(run_ctx.get("gpu_vendor") or "CPU")
        run_ctx.setdefault("gpu_vendor", self._current_gpu)
        st = check_requirements(self.requirements(), ctx=run_ctx)
        if not bool(st.get("ok")):
            return False

        # Неизвестная модель даёт пустой install_manifest — без этой проверки
        # цикл ниже не выполнился бы ни разу и статус был бы «установлено».
        if self._normalized_ckpt_name() not in self._model_names:
            return False

        for item in self.install_manifest():
            dest = str(item.get("dest") or "").strip()
            if not dest or not os.path.exists(dest) or os.path.getsize(dest) <= 0:
                return False

        return True
    
    def install_manifest(self) -> list[dict]:
        model_name = self._normalized_ckpt_name()
        if model_name not in self._model_names:
            return []

        ckpt_dest = self._ckpt_path()

        items: list[dict] = [
            {"url": f"{self._url_dir}/{model_name}.ckpt", "dest": ckpt_dest},
        ]

        if model_name == "v1_rnnt" or "e2e" in model_name:
            items.append({
                "url": f"{self._url_dir}/{model_name}_tokenizer.model",
                "dest": self._tokenizer_path(),
            })

        return items

    # ---------- artifacts install (NO pip) ----------
    async def install(self) -> bool:
        model_name = self._normalized_ckpt_name()
        if model_name not in self._model_names:
            self.logger.error(f"Unknown GigaAM model: {model_name}")
            return False

        try:
            os.makedirs(self.gigaam_model_path, exist_ok=True)

            items = self.install_manifest()
            for it in items:
                url = str(it.get("url") or "").strip()
                dest = str(it.get("dest") or "").strip()
                if not url or not dest:
                    continue

                if os.path.exists(dest) and os.path.getsize(dest) > 0:
                    continue

                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

                tmp = dest + ".part"
                try:
                    req = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python-urllib",
                            "Accept": "*/*",
                        },
                        method="GET",
                    )

                    with urllib.request.urlopen(req, timeout=60) as resp:
                        with open(tmp, "wb") as f:
                            while True:
                                chunk = resp.read(1024 * 1024 * 4)
                                if not chunk:
                                    break
                                f.write(chunk)

                    if os.path.exists(dest):
                        try:
                            os.remove(dest)
                        except Exception:
                            pass
                    os.replace(tmp, dest)

                finally:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except Exception:
                        pass

            return True

        except urllib.error.HTTPError as e:
            self.logger.error(f"GigaAM download failed: HTTP {e.code} {e.reason}", exc_info=True)
            return False
        except Exception as e:
            self.logger.error(f"GigaAM install failed: {e}", exc_info=True)
            return False

    # ---------- runtime ----------
    async def init(self, **kwargs) -> bool:
        if self._is_initialized and self._model is not None:
            return True

        try:
            import sys
            import torch
            import numpy as np

            self._torch = torch
            self._np = np
        except Exception as e:
            self.logger.error(f"GigaAM init imports failed: {e}")
            return False

        # alias for hydra targets ("gigaam.*")
        import handlers.asr_models.gigaam as gigaam
        import sys
        sys.modules["gigaam"] = gigaam

        # safe_globals for torch.load(ckpt)
        import collections
        import typing

        import omegaconf
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

        # device selection
        device_choice = (self.gigaam_device or "auto").strip().lower()
        if device_choice == "cuda" and not (self._torch.cuda.is_available()):
            self.logger.warning("CUDA was requested but is unavailable. Falling back to CPU.")
            device_choice = "cpu"

        if device_choice == "auto":
            device_choice = "cuda" if self._torch.cuda.is_available() else "cpu"

        try:
            self.logger.info(f"Loading GigaAM (PyTorch) on {device_choice}...")
            self._model = gigaam.load_model(
                self.gigaam_model,
                device=device_choice,
                download_root=self._model_root_abs(),
                use_flash=False,
            )

            from handlers.asr_models.gigaam.model import GigaAMASR
            if not isinstance(self._model, GigaAMASR):
                self.logger.error(
                    f"Loaded model type is {type(self._model).__name__}, but GigaAMASR is required "
                    f"(selected '{self.gigaam_model}' appears to be SSL/Emo, not ASR). "
                    "Choose an ASR model like gigaam_v2_ctc or gigaam_v2_rnnt."
                )
                self._model = None
                self._is_initialized = False
                return False

            self._is_initialized = True
            self.logger.success("GigaAM (PyTorch) initialized successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load GigaAM: {e}", exc_info=True)
            self._model = None
            self._is_initialized = False
            return False

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized or self._model is None:
            self.logger.error("GigaAM is not initialized.")
            return None

        try:
            import torchaudio

            wav = self._torch.from_numpy(np.asarray(audio_data, dtype=np.float32).reshape(-1))
            # resample to 16k (to match model expectations, like ffmpeg did)
            if int(sample_rate) != 16000:
                wav = torchaudio.functional.resample(wav, int(sample_rate), 16000)

            wav = wav.to(next(self._model.parameters()).device).to(next(self._model.parameters()).dtype)
            length = self._torch.tensor([wav.numel()], device=wav.device, dtype=self._torch.long)

            # directly use forward + decoding (without temporary file)
            encoded, encoded_len = self._model.forward(wav.unsqueeze(0), length)
            text = self._model.decoding.decode(self._model.head, encoded, encoded_len)[0]

            if text and text.strip():
                return text
            return None

        except Exception as e:
            self.logger.error(f"Transcription error: {e}", exc_info=True)
            return None

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
        self._torch = None
        self._np = None
        self._is_initialized = False
