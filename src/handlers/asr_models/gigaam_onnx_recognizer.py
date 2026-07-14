import os
import time
import gc
import multiprocessing as mp
from multiprocessing import Queue, Process
from threading import Thread, Event
import queue
from typing import Optional, List
import numpy as np
import urllib.request
import urllib.error

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from core.installables.helpers import build_runtime_ctx
from core.events import Events, get_event_bus
from core.backends import BackendKind
from core.install_requirements import InstallRequirement, check_requirements
from core.task_supervisor import task_supervisor

from utils import getTranslationVariant as _


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
                "Офлайн-распознавание речи на базе GigaAM через ONNXRuntime DirectML на Windows "
                "с CPU fallback. Запускается в отдельном процессе.",
                "Offline speech recognition based on GigaAM via ONNXRuntime. "
                "Uses DirectML on Windows with CPU fallback and runs in a separate process."
            ),
            "languages": ["Russian"],
            "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
            "tags": [
                _("ONNX", "ONNX"),
                _("Отдельный процесс", "Separate process"),
                _("CPU/DirectML", "CPU/DirectML"),
            ],
            "links": []
        }
    ]

    # Единственный источник истины по допустимым моделям и дефолту
    # (SSL/Emo-чекпоинты распознавать речь не умеют и сюда не входят).
    VALID_MODELS = ("v2_rnnt", "v2_ctc", "v3_rnnt", "v3_ctc", "v3_e2e_ctc", "v3_e2e_rnnt")
    DEFAULT_MODEL = "v2_rnnt"

    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)

        self._torch = None
        self._np = None

        self._current_gpu = None

        self.gigaam_model = self.DEFAULT_MODEL
        self.gigaam_device = "auto"  # auto/cpu/dml
        self.gigaam_onnx_export_path = "SpeechRecognitionModels/GigaAM_ONNX"
        self.gigaam_model_path = "SpeechRecognitionModels/GigaAM"

        self._process: Optional[Process] = None
        self._command_queue: Optional[Queue] = None
        self._result_queue: Optional[Queue] = None
        self._log_queue: Optional[Queue] = None
        self._monitor_thread: Optional[Thread] = None

        self._process_initialized = False
        self._stop_monitor = Event()

        self._transcribe_result = None
        self._transcribe_event = Event()

        self._url_dir = "https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM"

        self._model_names = list(self.VALID_MODELS)

    # ---------- UI schema ----------
    def settings_spec(self):
        return [
            {"key": "device", "label_ru": "Устройство", "label_en": "Device",
             "type": "combobox", "options": ["auto", "cpu", "dml"], "default": "auto"},
            {"key": "model", "label_ru": "Модель", "label_en": "Model",
             "type": "combobox",
             "options": list(self.VALID_MODELS),
             "default": self.DEFAULT_MODEL}
        ]

    def get_default_settings(self):
        return {"device": "auto", "model": self.DEFAULT_MODEL}

    def apply_settings(self, settings: dict):
        dev = settings.get("device")
        mdl = settings.get("model")
        if dev or mdl:
            self.set_options(device=dev or self.gigaam_device, model=mdl or self.gigaam_model)

    def set_options(self, device: str, model: str = None, onnx_path: str = None, model_path: str = None):
        old_device = self.gigaam_device
        self.gigaam_device = (device or self.gigaam_device).strip().lower()
        if model:
            new_model = str(model).strip()
            if new_model not in self.VALID_MODELS:
                self.logger.warning(
                    f"GigaAM ONNX: model '{new_model}' is not a valid ASR checkpoint — "
                    f"falling back to '{self.DEFAULT_MODEL}'."
                )
                new_model = self.DEFAULT_MODEL
            self.gigaam_model = new_model
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
        name = (self.gigaam_model or self.DEFAULT_MODEL).strip()
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
            InstallRequirement(id="onnx", kind="python_module", module="onnx", required=True),
        ]

    def pip_install_steps(self, ctx: dict) -> List[dict]:
        steps: List[dict] = []

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
            "progress": 75,
            "description": _("Установка ONNX export tooling...", "Installing ONNX export tooling..."),
            "packages": ["onnx"],
            "extra_args": None
        })

        return steps

    def required_backend(self, ctx: dict) -> BackendKind:
        return BackendKind.ONNX

    def is_installed(self, ctx: dict | None = None) -> bool:
        run_ctx = build_runtime_ctx(ctx)
        run_ctx.setdefault("device", self.gigaam_device)
        if self._current_gpu is None:
            self._current_gpu = str(run_ctx.get("gpu_vendor") or "CPU")
        run_ctx.setdefault("gpu_vendor", self._current_gpu)
        st = check_requirements(self.requirements(), ctx=run_ctx)
        return bool(st.get("ok"))
    
    def install_manifest(self) -> list[dict]:
        model_name = self._normalized_ckpt_name()
        if model_name not in self._model_names:
            return []

        ckpt_dest = self._ckpt_path()

        items: list[dict] = [
            {"url": f"{self._url_dir}/{model_name}.ckpt", "dest": ckpt_dest},
        ]

        if model_name == "v1_rnnt":
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
            self.logger.error(f"GigaAM ONNX download failed: HTTP {e.code} {e.reason}", exc_info=True)
            return False
        except Exception as e:
            self.logger.error(f"GigaAM ONNX install failed: {e}", exc_info=True)
            return False

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
                        get_event_bus().emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
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
            import numpy as np
            self._torch = torch
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

    def cleanup(self) -> None:
        self._stop_process()
        gc.collect()
        try:
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()
        except Exception:
            pass
        self._torch = None
        self._np = None
        self._is_initialized = False

    # ---------- process control ----------
    def _handle_process_result(self, result):
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

    def _monitor_process(self):
        while not self._stop_monitor.is_set() and self._process and self._process.is_alive():
            try:
                if self._result_queue:
                    try:
                        result = self._result_queue.get(timeout=0.1)
                        self._handle_process_result(result)
                    except queue.Empty:
                        pass

                while self._result_queue:
                    try:
                        self._handle_process_result(self._result_queue.get_nowait())
                    except queue.Empty:
                        break

                while self._log_queue:
                    try:
                        level, msg = self._log_queue.get_nowait()
                        getattr(self.logger, level, self.logger.info)(f"[GigaAM ONNX Process] {msg}")
                    except queue.Empty:
                        break
            except Exception as e:
                self.logger.error(f"Ошибка в мониторе GigaAM ONNX процесса: {e}")

    def _start_process(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._stop_process()
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
        self._monitor_thread = task_supervisor().start_thread(
            self, "gigaam-onnx-monitor", self._monitor_process, replace=True
        )

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

        process = self._process
        monitor_thread = self._monitor_thread
        command_queue = self._command_queue
        result_queue = self._result_queue
        log_queue = self._log_queue

        self.logger.info("Остановка GigaAM ONNX процесса...")
        self._stop_monitor.set()

        if command_queue:
            try:
                command_queue.put(("shutdown",))
                command_queue.cancel_join_thread()
                command_queue.close()
            except Exception:
                pass

        if monitor_thread:
            monitor_thread.join(timeout=2)

        if process:
            process.join(timeout=5)
            if process.is_alive():
                self.logger.warning("GigaAM ONNX процесс не завершился, принудительное завершение...")
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    self.logger.warning("GigaAM ONNX процесс не завершился после terminate(), kill()")
                    process.kill()
                    process.join(timeout=2)
            if process.exitcode is None:
                self.logger.warning("GigaAM ONNX процесс не завершился корректно.")

        for q in (command_queue, result_queue, log_queue):
            try:
                if q is not None:
                    q.cancel_join_thread()
                    q.close()
            except Exception:
                pass

        self._process = None
        self._command_queue = None
        self._result_queue = None
        self._log_queue = None
        self._process_initialized = False
        self._monitor_thread = None

        self.logger.info("GigaAM ONNX процесс остановлен")
