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
from handlers.asr_models.whisper_recognizer import WhisperRecognizer
from handlers.asr_models.whisper_onnx_recognizer import WhisperOnnxRecognizer
from core.events import get_event_bus, Events


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


class SpeechRecognition:
    microphone_index = 0
    active = True
    _recognizer_type = "google"

    # глобальные VAD-параметры (для движков, которые их используют)
    VOSK_SAMPLE_RATE = 16000
    CHUNK_SIZE = 512
    VAD_THRESHOLD = 0.5
    VAD_SILENCE_TIMEOUT_SEC = 1.0
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
            # Если движок тот же — ничего не делаем
            if engine == SpeechRecognition._recognizer_type:
                return
            if SpeechRecognition._recognizer_instance:
                SpeechRecognition._recognizer_instance.cleanup()
                SpeechRecognition._recognizer_instance = None
            SpeechRecognition._recognizer_type = engine
        logger.info(f"Тип распознавателя установлен на: {engine}")

    # ——— универсальные настройки
    @staticmethod
    def get_settings_schema(engine: Optional[str] = None) -> List[dict]:
        engine = engine or SpeechRecognition._recognizer_type
        # используем текущий инстанс если совпадает
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
        # применяем только если этот движок активный/инициализирован
        inst = SpeechRecognition._get_recognizer_snapshot()
        if inst and engine == SpeechRecognition._recognizer_type and hasattr(inst, "apply_settings"):
            try:
                inst.apply_settings(settings or {})
            except Exception as e:
                logger.warning(f"apply_settings error: {e}")

        # глобальные VAD (если в настройках переданы такие ключи)
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

    # ——— поток распознавания
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

                    # уведомляем GUI, что инициализация началась
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
                    logger.error(f"Ошибка в цикле распознавания (попытка {retry}/{max_retries}): {e}", exc_info=True)
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
        # аккуратно закрыть ресурсы движка
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
                    # дождаться корректного завершения корутины
                    task.result(timeout=3)
            except Exception:
                pass

        SpeechRecognition._is_running = False
        SpeechRecognition._recognition_task = None

    # utils
    @staticmethod
    def receive_text() -> str:
        with SpeechRecognition._text_lock:
            result = " ".join(SpeechRecognition._text_buffer).strip()
            SpeechRecognition._text_buffer.clear()
            SpeechRecognition._current_text = ""
            return result