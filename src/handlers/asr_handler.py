import time
import os
import asyncio
import concurrent.futures
from collections import deque
from threading import Lock, RLock, Event as ThreadEvent
from typing import TYPE_CHECKING, Optional, List, Dict

from main_logger import logger

from utils.pip_installer import PipInstaller
from utils import getTranslationVariant as _
from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from handlers.asr_models.registry import create_recognizer, engine_classes
from handlers.asr_audio_capture import AudioCaptureConfig, AudioCaptureService
from core.events import get_event_bus, Events, Event
from core.install_types import DEFAULT_INSTALL_TIMEOUT_SEC
from core.task_supervisor import task_supervisor


if TYPE_CHECKING:
    from core.install_types import InstallPlan


def _on_install_asr_model_event(event: Event):
    data = event.data if isinstance(event.data, dict) else {}

    engine = data.get("model") or data.get("engine") or data.get("item_id")
    if not engine:
        logger.error("INSTALL_ASR_MODEL: missing 'model' in payload")
        return

    engine_settings = data.get("settings") or data.get("engine_settings") or {}
    with_ui = bool(data.get("with_ui", True))
    timeout_sec = float(data.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC) or DEFAULT_INSTALL_TIMEOUT_SEC)

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

    from core.services import services
    from services.contracts import InstallableOperationsService

    operations = services().get_optional(InstallableOperationsService)
    if operations is None:
        logger.error("INSTALL_ASR_MODEL: installable operations service is unavailable")
        return
    return operations.install(payload)


def _on_ai_engine_event(event: Event):
    data = event.data if isinstance(event.data, dict) else {}
    if data.get("service") != "asr":
        return
    ev = str(data.get("event") or "")
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}

    if ev == "text":
        text = str(payload.get("text") or "").strip()
        if text:
            get_event_bus().emit(Events.Speech.SPEECH_TEXT_RECOGNIZED, {"text": text})
        return

    # Аварийная смерть цикла распознавания в engine-процессе. Раньше эти
    # события игнорировались, и GUI бесконечно считал ASR работающим.
    if ev == "error" or (ev == "status" and payload.get("running") is False):
        if not SpeechRecognition._is_running:
            return
        message = str(payload.get("message") or "")
        if ev == "error":
            logger.error(f"ASR engine reported an error: {message}")
        else:
            logger.warning("ASR engine stopped unexpectedly (status: running=false).")

        get_event_bus().emit(Events.Speech.ASR_FAILED, {
            "engine": SpeechRecognition._recognizer_type,
            "message": message,
            "phase": "runtime",
        })

        def _shutdown():
            # Отдельный поток обязателен: этот обработчик выполняется в
            # result-loop потоке AI-движка, а speech_recognition_stop ждёт
            # ответ на stop_live через этот же поток.
            try:
                eb = get_event_bus()
                eb.emit(Events.Speech.STOP_SPEECH_RECOGNITION)
                eb.emit(Events.GUI.UPDATE_STATUS_COLORS)
                if ev == "error":
                    eb.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                        "title": _("Распознавание речи", "Speech recognition"),
                        "message": _(
                            "Распознавание речи остановлено из-за ошибки: ",
                            "Speech recognition stopped due to an error: "
                        ) + message,
                    })
            except Exception:
                logger.error("ASR engine failure handling error", exc_info=True)

        task_supervisor().start_thread(
            SpeechRecognition,
            "asr-engine-failure-shutdown",
            _shutdown,
            replace=True,
        )


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

    _registry: Dict[str, type[SpeechRecognizerInterface]] = engine_classes()

    @staticmethod
    def _init_pip():
        if SpeechRecognition._pip_installer is None:
            SpeechRecognition._pip_installer = PipInstaller(update_log=logger.info)

    @staticmethod
    def _new_instance(engine: str) -> Optional[SpeechRecognizerInterface]:
        if engine not in SpeechRecognition._registry:
            return None
        SpeechRecognition._init_pip()
        return create_recognizer(engine, SpeechRecognition._pip_installer, logger)

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
        timeout_sec: float = DEFAULT_INSTALL_TIMEOUT_SEC,
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
            "timeout_sec": float(timeout_sec or DEFAULT_INSTALL_TIMEOUT_SEC),
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

                    if not inst.status().ready:
                        logger.warning("ASR model is not set. Stopping recognition.")
                        return

                    eb.emit(Events.Speech.ASR_MODEL_INIT_STARTED,
                            {"engine": SpeechRecognition._recognizer_type})

                    ok = await inst.init()
                    if not ok:
                        logger.error("Failed to initialize recognizer.")
                        return

                    eb.emit(Events.Speech.ASR_MODEL_INITIALIZED)

                    retry = 0
                    if SpeechRecognition._recognizer_type == "google":
                        from silero_vad import load_silero_vad
                        import numpy as np
                        import torch

                        vad_model = await asyncio.to_thread(load_silero_vad)

                        def speech_probability(audio: np.ndarray, sample_rate: int) -> float:
                            tensor = torch.from_numpy(np.asarray(audio, dtype=np.float32))
                            return float(vad_model(tensor, sample_rate).item())

                        async def transcribe_segment(audio: np.ndarray, sample_rate: int) -> None:
                            text = await inst.transcribe(audio, sample_rate)
                            if text:
                                await SpeechRecognition._handle_voice_message(text)

                        capture = AudioCaptureService(logger)
                        await capture.run(
                            microphone_index=SpeechRecognition.microphone_index,
                            config=AudioCaptureConfig(
                                sample_rate=SpeechRecognition.VOSK_SAMPLE_RATE,
                                chunk_size=SpeechRecognition.CHUNK_SIZE,
                                vad_threshold=SpeechRecognition.VAD_THRESHOLD,
                                silence_timeout=SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC,
                                pre_buffer_duration=SpeechRecognition.VAD_PRE_BUFFER_DURATION_SEC,
                                max_speech_duration=SpeechRecognition.MAX_SPEECH_DURATION_SEC,
                            ),
                            is_active=lambda: SpeechRecognition.active,
                            speech_probability=speech_probability,
                            on_segment=transcribe_segment,
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
        # Через AIEngineService, а не sync EventBus RPC: ASR-цикл может крутиться в
        # asyncio-loop, где синхронный сбор ответов шины запрещён guardrail'ом.
        try:
            from core.services import use
            from services.contracts import AIEngineService
            return use(AIEngineService).get_engine()
        except Exception:
            return None

    @staticmethod
    def speech_recognition_start(device_id: int, loop) -> bool:
        with SpeechRecognition._start_lock:
            if SpeechRecognition._is_running:
                SpeechRecognition.speech_recognition_stop()
                time.sleep(0.2)

        engine_id = SpeechRecognition._recognizer_type
        use_remote = SpeechRecognition._remote_asr_mode

        if use_remote:
            eb = get_event_bus()
            eb.emit(Events.Speech.ASR_MODEL_INIT_STARTED, {"engine": engine_id})

            def _emit_start_failure(message: str) -> None:
                eb.emit(Events.Speech.ASR_FAILED, {
                    "engine": engine_id,
                    "message": message,
                    "phase": "startup",
                })

            eng = SpeechRecognition._get_ai_engine()
            if not eng:
                logger.error("ASR engine not available. Local fallback is disabled.")
                _emit_start_failure(_(
                    "Сервис ASR недоступен. Подробности в логе.",
                    "The ASR service is unavailable. See the log for details.",
                ))
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
                start_payload = {
                    "engine_id": engine_id,
                    "microphone_index": int(device_id or 0),
                    "engine_settings": settings,
                    "vad": vad,
                }
                activate = getattr(eng, "activate_environment", None)
                try:
                    activated = callable(activate) and activate(
                        "asr",
                        engine_id,
                        category="asr",
                        timeout=30.0,
                        validation_method="start_live",
                        validation_payload=start_payload,
                        validation_timeout=300.0,
                    )
                except Exception as exc:
                    logger.error(
                        f"Managed ASR environment startup failed for engine "
                        f"'{engine_id}': {exc}",
                        exc_info=True,
                    )
                    activated = False

                if not activated:
                    logger.error(
                        f"Managed ASR environment could not be initialized for "
                        f"engine '{engine_id}'."
                    )
                    _emit_start_failure(_(
                        "Не удалось открыть выбранный микрофон или запустить ASR. Подробности в логе.",
                        "Failed to open the selected microphone or start ASR. See the log for details.",
                    ))
                    return False
                with SpeechRecognition._start_lock:
                    SpeechRecognition._is_running = True
                    SpeechRecognition._running_event.set()
                    SpeechRecognition._stopped_event.clear()
                    SpeechRecognition.active = True
                    SpeechRecognition.microphone_index = device_id or 0
                eb.emit(Events.Speech.ASR_MODEL_INITIALIZED)
                logger.info(f"ASR started (engine:{engine_id}) on device {device_id}")
                return True
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
        # Сразу помечаем «не запущено»: событие status(running=false), которое
        # придёт от штатного stop_live, не должно трактоваться мостом
        # _on_ai_engine_event как аварийная смерть цикла.
        SpeechRecognition._is_running = False

        # stop remote if used
        engine_id = SpeechRecognition._recognizer_type
        use_remote = SpeechRecognition._remote_asr_mode
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
