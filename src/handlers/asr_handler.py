import time
import asyncio
from collections import deque
from threading import Lock, RLock
from typing import Optional, List, Dict

from main_logger import logger

from utils.pip_installer import PipInstaller
from utils import getTranslationVariant as _
from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from handlers.asr_models.google_recognizer import GoogleRecognizer
from handlers.asr_models.gigaam_recognizer import GigaAMRecognizer
from handlers.asr_models.gigaam_onnx_recognizer import GigaAMOnnxRecognizer
from handlers.asr_models.whisper_recognizer import WhisperRecognizer
from handlers.asr_models.whisper_onnx_recognizer import WhisperOnnxRecognizer
from core.events import get_event_bus, Events, Event


class AudioState:
    def __init__(self):
        self.is_recording = False
        self.audio_buffer = []
        self.last_sound_time = time.time()
        self.is_playing = False
        self.lock = asyncio.Lock()
        self.vc = None
        self.max_buffer_size = 9999999

    async def add_to_buffer(self, data):
        async with self.lock:
            if len(self.audio_buffer) >= self.max_buffer_size:
                self.audio_buffer = self.audio_buffer[-self.max_buffer_size // 2:]
            self.audio_buffer.append(data.copy())


audio_state = AudioState()


def _asr_install_runner(engine: str, engine_settings: Optional[dict], timeout_sec: float):
    def _runner(*args, **kwargs):
        pip_installer = kwargs.get("pip_installer") if isinstance(kwargs, dict) else None
        callbacks = kwargs.get("callbacks") if isinstance(kwargs, dict) else None
        ctx = kwargs.get("ctx") if isinstance(kwargs, dict) else None

        if pip_installer is None and len(args) >= 1:
            pip_installer = args[0]
        if callbacks is None and len(args) >= 2:
            callbacks = args[1]
        if ctx is None and len(args) >= 3:
            ctx = args[2]

        return SpeechRecognition.build_install_plan(
            engine,
            pip_installer=pip_installer,
            engine_settings=engine_settings or {},
            callbacks=callbacks,
            timeout_sec=float(timeout_sec or 3600.0),
        )

    return _runner


def _on_install_asr_model_event(event: Event):
    data = event.data if isinstance(event.data, dict) else {}

    engine = data.get("model") or data.get("engine") or data.get("item_id")
    if not engine:
        logger.error("INSTALL_ASR_MODEL: missing 'model' in payload")
        return

    engine_settings = data.get("settings") or data.get("engine_settings") or {}
    with_ui = bool(data.get("with_ui", True))
    timeout_sec = float(data.get("timeout_sec", 3600.0) or 3600.0)

    runner = _asr_install_runner(str(engine), engine_settings, timeout_sec)

    payload = {
        "kind": "asr",
        "item_id": str(engine),
        "task_id": f"asr:{engine}",
        "title": _("Установка ASR модели: ", "Installing ASR model: ") + str(engine),
        "initial_status": _("Подготовка...", "Preparing..."),
        "timeout_sec": float(timeout_sec),
        "meta": {
            "kind": "asr",
            "item_id": str(engine),
        },
        "runner": runner,
    }

    eb = get_event_bus()
    eb.emit(Events.Install.RUN_WITH_UI if with_ui else Events.Install.RUN_HEADLESS, payload)


_ASR_INSTALL_EVENTS_REGISTERED = False


def register_asr_install_events() -> None:
    global _ASR_INSTALL_EVENTS_REGISTERED
    if _ASR_INSTALL_EVENTS_REGISTERED:
        return
    eb = get_event_bus()
    eb.subscribe(Events.Speech.INSTALL_ASR_MODEL, _on_install_asr_model_event, weak=False)
    _ASR_INSTALL_EVENTS_REGISTERED = True


class SpeechRecognition:
    microphone_index = 0
    active = True
    _recognizer_type = "google"

    VOSK_SAMPLE_RATE = 16000
    CHUNK_SIZE = 512
    VAD_THRESHOLD = 0.5
    VAD_SILENCE_TIMEOUT_SEC = 0.15
    VAD_PRE_BUFFER_DURATION_SEC = 0.3

    FAILED_AUDIO_DIR = "FailedAudios"

    _text_lock = Lock()
    _text_buffer = deque(maxlen=15)
    _current_text = ""
    _is_running = False
    _recognition_task = None

    _torch = None
    _sd = None
    _np = None
    _silero_vad_loader = None
    _silero_vad_model = None

    _recognizer_instance: Optional[SpeechRecognizerInterface] = None
    _pip_installer = None
    _rec_instance_lock = RLock()

    _registry: Dict[str, type[SpeechRecognizerInterface]] = {
        "google": GoogleRecognizer,
        "gigaam": GigaAMRecognizer,
        "gigaam_onnx": GigaAMOnnxRecognizer,
        "whisper": WhisperRecognizer,
        "whisper_onnx": WhisperOnnxRecognizer,
    }

    @staticmethod
    def _init_pip():
        if SpeechRecognition._pip_installer is None:
            SpeechRecognition._pip_installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_log=logger.info
            )

    @staticmethod
    def _new_instance(engine: str) -> Optional[SpeechRecognizerInterface]:
        cls = SpeechRecognition._registry.get(engine)
        if not cls:
            return None
        SpeechRecognition._init_pip()
        return cls(SpeechRecognition._pip_installer, logger)

    @staticmethod
    def _ensure_instance():
        with SpeechRecognition._rec_instance_lock:
            if SpeechRecognition._recognizer_instance is None:
                inst = SpeechRecognition._new_instance(SpeechRecognition._recognizer_type)
                SpeechRecognition._recognizer_instance = inst
        return True

    @staticmethod
    def _get_recognizer_snapshot():
        with SpeechRecognition._rec_instance_lock:
            return SpeechRecognition._recognizer_instance

    @staticmethod
    def set_recognizer_type(engine: str = None):
        if engine not in SpeechRecognition._registry:
            logger.warning(f"Неизвестный движок ASR: {engine}")
            return
        with SpeechRecognition._rec_instance_lock:
            if engine == SpeechRecognition._recognizer_type:
                return
            if SpeechRecognition._recognizer_instance:
                SpeechRecognition._recognizer_instance.cleanup()
                SpeechRecognition._recognizer_instance = None
            SpeechRecognition._recognizer_type = engine
        logger.info(f"Тип распознавателя установлен на: {engine}")

    @staticmethod
    def build_install_plan(
        engine: str,
        *,
        pip_installer: PipInstaller,
        engine_settings: Optional[dict] = None,
        callbacks: Optional[object] = None,
        timeout_sec: float = 3600.0,
    ) -> "InstallPlan":
        from core.install_types import InstallPlan, InstallAction
        from utils.gpu_utils import check_gpu_provider

        engine_settings = engine_settings or {}

        try:
            gpu_vendor = check_gpu_provider() or "CPU"
        except Exception:
            gpu_vendor = "CPU"

        ctx = {
            "gpu_vendor": gpu_vendor,
            "device": engine_settings.get("device"),
        }

        reg = getattr(SpeechRecognition, "_registry", {}) or {}
        cls = reg.get(engine)
        if not cls:
            return InstallPlan(
                actions=[InstallAction(type="call", description="Failed", progress=1, fn=lambda: False)],
                already_installed=False,
            )

        recognizer = cls(pip_installer, logger)
        try:
            if hasattr(recognizer, "apply_settings"):
                recognizer.apply_settings(engine_settings)
        except Exception:
            pass

        try:
            if recognizer.is_installed():
                return InstallPlan(actions=[], already_installed=True, already_installed_status="Already installed")
        except Exception:
            pass

        try:
            steps = recognizer.pip_install_steps(ctx) if hasattr(recognizer, "pip_install_steps") else []
            steps = steps or []
        except Exception:
            steps = []

        actions: list[InstallAction] = []

        for step in steps:
            try:
                pr = int(step.get("progress", 10) or 10)
            except Exception:
                pr = 10
            desc = str(step.get("description", "Installing...") or "Installing...")
            pkgs = step.get("packages")
            extra = step.get("extra_args")

            if isinstance(pkgs, str):
                pkgs_list = [pkgs]
            elif pkgs:
                pkgs_list = list(pkgs)
            else:
                pkgs_list = []

            actions.append(
                InstallAction(
                    type="pip",
                    description=desc,
                    progress=pr,
                    packages=pkgs_list,
                    extra_args=extra,
                )
            )

        manifest = None
        if hasattr(recognizer, "install_manifest"):
            try:
                manifest = recognizer.install_manifest()
            except Exception:
                manifest = None

        if manifest:
            actions.append(
                InstallAction(
                    type="download_http",
                    description="Downloading model files...",
                    progress=75,
                    progress_to=99,
                    files=list(manifest),
                )
            )
        else:
            async def _install_artifacts_async(**_kwargs) -> bool:
                return bool(await recognizer.install())

            actions.append(
                InstallAction(
                    type="call_async",
                    description="Downloading model files...",
                    progress=75,
                    fn=_install_artifacts_async,
                    timeout_sec=float(timeout_sec or 3600.0),
                )
            )

        def _final_check(**_kwargs) -> bool:
            try:
                return bool(recognizer.is_installed())
            except Exception:
                return True

        actions.append(
            InstallAction(
                type="call",
                description="Finalizing...",
                progress=99,
                fn=_final_check,
            )
        )

        return InstallPlan(actions=actions, already_installed=False, ok_status="Done")

    @staticmethod
    def get_settings_schema(engine: Optional[str] = None) -> List[dict]:
        engine = engine or SpeechRecognition._recognizer_type
        inst = SpeechRecognition._get_recognizer_snapshot()
        if not inst or engine != SpeechRecognition._recognizer_type:
            inst = SpeechRecognition._new_instance(engine)
        if not inst:
            return []
        try:
            if hasattr(inst, "settings_spec"):
                return inst.settings_spec() or []
        except Exception as e:
            logger.warning(f"settings_spec error for {engine}: {e}")
        return []

    @staticmethod
    def apply_settings(engine: str, settings: dict):
        inst = SpeechRecognition._get_recognizer_snapshot()
        if inst and engine == SpeechRecognition._recognizer_type and hasattr(inst, "apply_settings"):
            try:
                inst.apply_settings(settings or {})
            except Exception as e:
                logger.warning(f"apply_settings error: {e}")

        try:
            if "silence_threshold" in settings:
                SpeechRecognition.VAD_THRESHOLD = float(settings["silence_threshold"])
            if "silence_duration" in settings:
                SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC = float(settings["silence_duration"])
        except Exception:
            pass

    @staticmethod
    def check_model_installed(recognizer_type: Optional[str] = None, settings: Optional[dict] = None) -> bool:
        engine = recognizer_type or SpeechRecognition._recognizer_type
        settings = settings or {}

        SpeechRecognition._ensure_instance()
        inst = SpeechRecognition._get_recognizer_snapshot()
        if not inst or engine != SpeechRecognition._recognizer_type:
            inst = SpeechRecognition._new_instance(engine)

        if not inst:
            return False

        try:
            if hasattr(inst, "apply_settings"):
                inst.apply_settings(settings)
        except Exception:
            pass

        try:
            return inst.is_installed()
        except Exception as e:
            logger.warning(f"is_installed error: {e}")
            return False

    @staticmethod
    async def install_model(recognizer_type: Optional[str] = None) -> bool:
        engine = recognizer_type or SpeechRecognition._recognizer_type
        SpeechRecognition._ensure_instance()
        inst = SpeechRecognition._get_recognizer_snapshot()
        if not inst or engine != SpeechRecognition._recognizer_type:
            inst = SpeechRecognition._new_instance(engine)
        if inst:
            return await inst.install()
        return False

    @staticmethod
    async def _init_vad_dependencies():
        try:
            if SpeechRecognition._torch is None:
                import torch
                SpeechRecognition._torch = torch
            if SpeechRecognition._sd is None:
                import sounddevice as sd
                SpeechRecognition._sd = sd
            if SpeechRecognition._np is None:
                import numpy as np
                SpeechRecognition._np = np

            if SpeechRecognition._silero_vad_loader is None:
                try:
                    from silero_vad import load_silero_vad
                except ImportError:
                    SpeechRecognition._init_pip()
                    SpeechRecognition._pip_installer.install_package(
                        ["silero-vad"], description=_("Установка Silero VAD...", "Installing Silero VAD...")
                    )
                    from silero_vad import load_silero_vad
                SpeechRecognition._silero_vad_loader = load_silero_vad

            if SpeechRecognition._silero_vad_model is None:
                model = SpeechRecognition._silero_vad_loader()
                SpeechRecognition._silero_vad_model = model

            return True
        except Exception as e:
            logger.error(f"Ошибка инициализации VAD: {e}")
            return False

    @staticmethod
    async def live_recognition():
        max_retries = 3
        retry = 0
        eb = get_event_bus()
        try:
            while retry < max_retries and SpeechRecognition.active:
                try:
                    SpeechRecognition._ensure_instance()
                    inst = SpeechRecognition._get_recognizer_snapshot()
                    if not inst:
                        retry += 1
                        await asyncio.sleep(1)
                        continue

                    if not inst.is_installed():
                        logger.warning("ASR-модель не установлена. Остановлено распознавание.")
                        return

                    eb.emit(Events.Speech.ASR_MODEL_INIT_STARTED)

                    ok = await inst.init()
                    if not ok:
                        logger.error("Не удалось инициализировать распознаватель.")
                        return

                    eb.emit(Events.Speech.ASR_MODEL_INITIALIZED)

                    retry = 0
                    if SpeechRecognition._recognizer_type == "google":
                        await inst.live_recognition(
                            SpeechRecognition.microphone_index,
                            SpeechRecognition._handle_voice_message,
                            None,
                            lambda: SpeechRecognition.active,
                            chunk_size=SpeechRecognition.CHUNK_SIZE
                        )
                    else:
                        if not await SpeechRecognition._init_vad_dependencies():
                            logger.error("Не удалось инициализировать VAD.")
                            return
                        await inst.live_recognition(
                            SpeechRecognition.microphone_index,
                            SpeechRecognition._handle_voice_message,
                            SpeechRecognition._silero_vad_model,
                            lambda: SpeechRecognition.active,
                            sample_rate=SpeechRecognition.VOSK_SAMPLE_RATE,
                            chunk_size=SpeechRecognition.CHUNK_SIZE,
                            vad_threshold=SpeechRecognition.VAD_THRESHOLD,
                            silence_timeout=SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC,
                            pre_buffer_duration=SpeechRecognition.VAD_PRE_BUFFER_DURATION_SEC
                        )
                    break

                except asyncio.CancelledError:
                    logger.info("Задача распознавания отменена.")
                    break
                except Exception as e:
                    retry += 1
                    logger.error(
                        f"Ошибка в цикле распознавания (попытка {retry}/{max_retries}): {e}",
                        exc_info=True
                    )
                    if retry < max_retries and SpeechRecognition.active:
                        await asyncio.sleep(2)
                    else:
                        logger.error("Превышено число попыток. Остановлено.")
                        break
        finally:
            SpeechRecognition._is_running = False
            logger.info("Цикл распознавания речи остановлен.")

    @staticmethod
    async def _handle_voice_message(text: str):
        if text and text.strip():
            get_event_bus().emit(Events.Speech.SPEECH_TEXT_RECOGNIZED, {'text': text.strip()})

    @staticmethod
    async def speech_recognition_start_async():
        await SpeechRecognition.live_recognition()

    @staticmethod
    def speech_recognition_start(device_id: int, loop):
        if SpeechRecognition._is_running:
            SpeechRecognition.speech_recognition_stop()
            time.sleep(0.2)
        SpeechRecognition._is_running = True
        SpeechRecognition.active = True
        SpeechRecognition.microphone_index = device_id or 0
        SpeechRecognition._recognition_task = asyncio.run_coroutine_threadsafe(
            SpeechRecognition.speech_recognition_start_async(), loop
        )
        logger.info(f"Запущено распознавание речи на устройстве {device_id}")

    @staticmethod
    def speech_recognition_stop():
        if not SpeechRecognition._is_running:
            return
        SpeechRecognition.active = False
        try:
            inst = SpeechRecognition._get_recognizer_snapshot()
            if inst:
                inst.cleanup()
        except Exception:
            pass

        task = SpeechRecognition._recognition_task
        if task:
            try:
                if not task.done():
                    task.cancel()
                    task.result(timeout=3)
            except Exception:
                pass

        SpeechRecognition._is_running = False
        SpeechRecognition._recognition_task = None

    @staticmethod
    def receive_text() -> str:
        with SpeechRecognition._text_lock:
            result = " ".join(SpeechRecognition._text_buffer).strip()
            SpeechRecognition._text_buffer.clear()
            SpeechRecognition._current_text = ""
            return result


register_asr_install_events()