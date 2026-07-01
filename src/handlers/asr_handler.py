import time
import os
import asyncio
import concurrent.futures
from collections import deque
from threading import Lock, RLock, Event as ThreadEvent
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


def _on_install_asr_model_event(event: Event):
    data = event.data if isinstance(event.data, dict) else {}

    engine = data.get("model") or data.get("engine") or data.get("item_id")
    if not engine:
        logger.error("INSTALL_ASR_MODEL: missing 'model' in payload")
        return

    engine_settings = data.get("settings") or data.get("engine_settings") or {}
    with_ui = bool(data.get("with_ui", True))
    timeout_sec = float(data.get("timeout_sec", 3600.0) or 3600.0)

    from core.installables import ComponentCategory, make_component_id

    payload = {
        "component_id": make_component_id(ComponentCategory.ASR, str(engine)),
        "kind": "asr",
        "item_id": str(engine),
        "task_id": f"asr:install:{engine}",
        "title": _("Installing ASR model: ", "Installing ASR model: ") + str(engine),
        "initial_status": _("Preparing...", "Preparing..."),
        "timeout_sec": float(timeout_sec),
        "with_ui": with_ui,
        "ctx": {
            "engine_settings": engine_settings,
        },
        "meta": {
            "kind": "asr",
            "item_id": str(engine),
            "op": "install",
        },
    }

    eb = get_event_bus()
    eb.emit(Events.Installable.INSTALL, payload)


def _on_ai_engine_event(event: Event):
    data = event.data if isinstance(event.data, dict) else {}
    if data.get("service") != "asr":
        return
    ev = str(data.get("event") or "")
    if ev != "text":
        return
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    text = str(payload.get("text") or "").strip()
    if text:
        get_event_bus().emit(Events.Speech.SPEECH_TEXT_RECOGNIZED, {"text": text})


_ASR_ENGINE_BRIDGE_REGISTERED = False


def register_asr_engine_bridge():
    global _ASR_ENGINE_BRIDGE_REGISTERED
    if _ASR_ENGINE_BRIDGE_REGISTERED:
        return
    eb = get_event_bus()
    eb.subscribe(Events.AI.ENGINE_EVENT, _on_ai_engine_event, weak=False)
    _ASR_ENGINE_BRIDGE_REGISTERED = True


_ASR_INSTALL_EVENTS_REGISTERED = False


def register_asr_install_events() -> None:
    global _ASR_INSTALL_EVENTS_REGISTERED
    if _ASR_INSTALL_EVENTS_REGISTERED:
        return
    eb = get_event_bus()
    eb.subscribe(Events.Speech.INSTALL_ASR_MODEL, _on_install_asr_model_event, weak=False)
    _ASR_INSTALL_EVENTS_REGISTERED = True

register_asr_engine_bridge()

class SpeechRecognition:
    microphone_index = 0
    active = True
    _recognizer_type = "google"
    _engine_settings: Dict[str, dict] = {}
    _remote_asr_mode: bool = True

    VOSK_SAMPLE_RATE = 16000
    CHUNK_SIZE = 512
    VAD_THRESHOLD = 0.5
    VAD_SILENCE_TIMEOUT_SEC = 0.15
    VAD_PRE_BUFFER_DURATION_SEC = 0.3
    MAX_SPEECH_DURATION_SEC = 30.0

    FAILED_AUDIO_DIR = "FailedAudios"

    _text_lock = Lock()
    _start_lock = Lock()
    _text_buffer = deque(maxlen=15)
    _current_text = ""
    _is_running = False
    _running_event = ThreadEvent()
    _stopped_event = ThreadEvent()
    _stopped_event.set()
    _recognition_task = None

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
            SpeechRecognition._pip_installer = PipInstaller(update_log=logger.info)

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
            logger.warning(f"Unknown ASR engine: {engine}")
            return
        with SpeechRecognition._rec_instance_lock:
            if engine == SpeechRecognition._recognizer_type:
                return
            if SpeechRecognition._recognizer_instance:
                SpeechRecognition._recognizer_instance.cleanup()
                SpeechRecognition._recognizer_instance = None
            SpeechRecognition._recognizer_type = engine
        logger.info(f"Recognizer type set to: {engine}")

    @staticmethod
    def build_install_plan(
        engine: str,
        *,
        pip_installer: PipInstaller,
        engine_settings: Optional[dict] = None,
        callbacks: Optional[object] = None,
        timeout_sec: float = 3600.0,
    ) -> "InstallPlan":
        from utils.gpu_utils import check_gpu_provider

        engine_settings = engine_settings or {}

        try:
            gpu_vendor = check_gpu_provider() or "CPU"
        except Exception:
            gpu_vendor = "CPU"

        ctx = {
            "gpu_vendor": gpu_vendor,
            "device": engine_settings.get("device"),
            "libs_dir": os.environ.get("NEUROMITA_LIB_DIR"),
        }

        reg = getattr(SpeechRecognition, "_registry", {}) or {}
        cls = reg.get(engine)
        if not cls:
            from core.install_types import InstallAction, InstallPlan

            return InstallPlan(
                actions=[InstallAction(type="call", description="Failed", progress=1, fn=lambda: False)],
                already_installed=False,
            )

        recognizer = cls(pip_installer, logger)
        return recognizer.build_install_plan({
            **ctx,
            "timeout_sec": float(timeout_sec or 3600.0),
            "engine_settings": dict(engine_settings or {}),
        })

    @staticmethod
    def create_installable_components() -> list[SpeechRecognizerInterface]:
        components: list[SpeechRecognizerInterface] = []
        for engine_id, cls in (SpeechRecognition._registry or {}).items():
            try:
                instance = cls(None, logger)
                config_id = getattr(instance, "item_id", "")
                if config_id and str(config_id) != str(engine_id):
                    logger.warning(f"ASR installable id mismatch: registry='{engine_id}' component='{config_id}'")
                components.append(instance)
            except Exception as exc:
                logger.error(f"Failed to create ASR installable for '{engine_id}': {exc}", exc_info=True)
        return components

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
        settings = settings or {}
        SpeechRecognition._engine_settings[str(engine or "").strip()] = dict(settings)

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
            if "max_speech_duration" in settings:
                SpeechRecognition.MAX_SPEECH_DURATION_SEC = float(settings["max_speech_duration"])
            if "MAX_SPEECH_DURATION_SEC" in settings:
                SpeechRecognition.MAX_SPEECH_DURATION_SEC = float(settings["MAX_SPEECH_DURATION_SEC"])
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
    async def live_recognition():
        max_retries = 3
        retry = 0
        eb = get_event_bus()
        inst_for_cleanup: Optional[SpeechRecognizerInterface] = None
        try:
            while retry < max_retries and SpeechRecognition.active:
                try:
                    SpeechRecognition._ensure_instance()
                    inst = SpeechRecognition._get_recognizer_snapshot()
                    if not inst:
                        retry += 1
                        await asyncio.sleep(1)
                        continue
                    inst_for_cleanup = inst

                    if not inst.is_installed():
                        logger.warning("ASR model is not set. Stopping recognition.")
                        return

                    eb.emit(Events.Speech.ASR_MODEL_INIT_STARTED)

                    ok = await inst.init()
                    if not ok:
                        logger.error("Failed to initialize recognizer.")
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
                        logger.error(
                            f"Local ASR mode is disabled for engine '{SpeechRecognition._recognizer_type}'. "
                            "Use ai_engine ASR worker instead."
                        )
                        return
                    break

                except asyncio.CancelledError:
                    logger.info("Recognition task cancelled.")
                    break
                except Exception as e:
                    retry += 1
                    logger.error(
                        f"Recognition loop error (attempt {retry}/{max_retries}): {e}",
                        exc_info=True
                    )
                    if retry < max_retries and SpeechRecognition.active:
                        await asyncio.sleep(2)
                    else:
                        logger.error("Retry limit exceeded. Stopping recognition.")
                        break
        finally:
            SpeechRecognition._is_running = False
            SpeechRecognition._running_event.clear()
            SpeechRecognition._stopped_event.set()
            if inst_for_cleanup is not None:
                try:
                    inst_for_cleanup.cleanup()
                except Exception:
                    pass
        logger.info("Speech recognition loop stopped.")

    @staticmethod
    async def _handle_voice_message(text: str):
        if text and text.strip():
            get_event_bus().emit(Events.Speech.SPEECH_TEXT_RECOGNIZED, {'text': text.strip()})

    @staticmethod
    def _get_ai_engine():
        try:
            res = get_event_bus().emit_and_wait(Events.AI.GET_ENGINE, timeout=0.8)
            return res[0] if res else None
        except Exception:
            return None

    @staticmethod
    def speech_recognition_start(device_id: int, loop) -> bool:
        with SpeechRecognition._start_lock:
            if SpeechRecognition._is_running:
                SpeechRecognition.speech_recognition_stop()
                time.sleep(0.2)

        engine_id = SpeechRecognition._recognizer_type
        use_remote = SpeechRecognition._remote_asr_mode and engine_id != "google"

        if use_remote:
            eng = SpeechRecognition._get_ai_engine()
            if not eng:
                logger.error("ASR engine not available. Local fallback is disabled.")
            else:
                vad = {
                    "sample_rate": SpeechRecognition.VOSK_SAMPLE_RATE,
                    "chunk_size": SpeechRecognition.CHUNK_SIZE,
                    "vad_threshold": SpeechRecognition.VAD_THRESHOLD,
                    "silence_timeout": SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC,
                    "pre_buffer_duration": SpeechRecognition.VAD_PRE_BUFFER_DURATION_SEC,
                    "max_speech_duration": SpeechRecognition.MAX_SPEECH_DURATION_SEC,
                }
                settings = SpeechRecognition._engine_settings.get(engine_id, {}) or {}
                # Mirror the in-process path so the GUI gets consistent
                # init signals. Without these the remote (subprocess) engines
                # never reported "initialized": asr_is_ready stayed False and
                # the status pill was stuck on "Инициализация ASR..." forever
                # (the 35s timeout guard is only armed by INIT_STARTED).
                eb = get_event_bus()
                eb.emit(Events.Speech.ASR_MODEL_INIT_STARTED)
                fut = eng.call("asr", "start_live", {
                    "engine_id": engine_id,
                    "microphone_index": int(device_id or 0),
                    "engine_settings": settings,
                    "vad": vad,
                })
                try:
                    # Загрузка модели на CUDA (GigaAM/Whisper + инициализация
                    # CUDA-контекста) легко занимает больше 10 c, поэтому ждём
                    # долго. Вызов выполняется в фоновом потоке (см.
                    # SpeechController), так что шину событий это не блокирует.
                    ok = bool(fut.result(timeout=300.0))
                    if ok:
                        with SpeechRecognition._start_lock:
                            SpeechRecognition._is_running = True
                            SpeechRecognition._running_event.set()
                            SpeechRecognition._stopped_event.clear()
                            SpeechRecognition.active = True
                            SpeechRecognition.microphone_index = device_id or 0
                        eb.emit(Events.Speech.ASR_MODEL_INITIALIZED)
                        logger.info(f"ASR started (engine:{engine_id}) on device {device_id}")
                        return True
                    logger.error("ASR engine start failed. Local fallback is disabled.")
                except concurrent.futures.TimeoutError:
                    logger.error(
                        f"ASR engine start timed out (engine:{engine_id}): модель не "
                        "инициализировалась за 300 c. Попробуйте ещё раз или проверьте лог движка."
                    )
                except Exception as e:
                    logger.error(f"ASR engine start exception ({type(e).__name__}): {e}", exc_info=True)
            return False

        with SpeechRecognition._start_lock:
            SpeechRecognition._is_running = True
            SpeechRecognition._running_event.set()
            SpeechRecognition._stopped_event.clear()
            SpeechRecognition.active = True
            SpeechRecognition.microphone_index = device_id or 0

        SpeechRecognition._recognition_task = asyncio.run_coroutine_threadsafe(
            SpeechRecognition.speech_recognition_start_async(), loop
        )
        logger.info(f"Speech recognition started (local) on device {device_id}")
        return True

    @staticmethod
    async def speech_recognition_start_async():
        await SpeechRecognition.live_recognition()

    @staticmethod
    def speech_recognition_stop():
        if not SpeechRecognition._is_running:
            return

        SpeechRecognition.active = False

        # stop remote if used
        engine_id = SpeechRecognition._recognizer_type
        use_remote = SpeechRecognition._remote_asr_mode and engine_id != "google"
        if use_remote:
            eng = SpeechRecognition._get_ai_engine()
            if eng:
                try:
                    f = eng.call("asr", "stop_live", {})
                    try:
                        f.result(timeout=3.0)
                    except Exception:
                        pass
                except Exception:
                    pass

        task = SpeechRecognition._recognition_task
        if task:
            try:
                if not task.done():
                    task.cancel()
                    task.result(timeout=5)
            except concurrent.futures.CancelledError:
                pass
            except concurrent.futures.TimeoutError:
                logger.warning("ASR local task stop timeout.")
            except Exception:
                pass

        try:
            inst = SpeechRecognition._get_recognizer_snapshot()
            if inst:
                inst.cleanup()
        except Exception:
            pass

        SpeechRecognition._is_running = False
        SpeechRecognition._running_event.clear()
        SpeechRecognition._stopped_event.set()
        SpeechRecognition._recognition_task = None

    @staticmethod
    def receive_text() -> str:
        with SpeechRecognition._text_lock:
            result = " ".join(SpeechRecognition._text_buffer).strip()
            SpeechRecognition._text_buffer.clear()
            SpeechRecognition._current_text = ""
            return result


register_asr_install_events()
