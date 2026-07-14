import os
import time
import re
import threading
from difflib import SequenceMatcher
import sounddevice as sd

from handlers.asr_handler import SpeechRecognition
from main_logger import logger
from core.events import get_event_bus, Events, Event
from core.services import services, use
from core.task_supervisor import task_supervisor
from services.contracts import (
    AudioStateService,
    GameLinkService,
    InstallableCatalogService,
    LoopService,
    SettingsService,
    SpeechService,
)
from services.asr_settings_service import ensure_asr_settings_service
from utils import getTranslationVariant as _


class SpeechController(SpeechService):
    _SETTING_KEYS = frozenset({
        "MIC_ACTIVE", "RECOGNIZER_TYPE", "SILENCE_THRESHOLD",
        "VAD_THRESHOLD", "SILENCE_DURATION", "VAD_SILENCE_TIMEOUT_SEC",
        "VOSK_SAMPLE_RATE", "CHUNK_SIZE", "VAD_PRE_BUFFER_DURATION_SEC",
        "MAX_SPEECH_DURATION_SEC", "NM_MICROPHONE_ID", "NM_MICROPHONE_NAME",
    })

    # Хвост после конца реплики: гасим затухание звука и задержку VAD,
    # который выдаёт текст уже после паузы.
    _MUTE_TAIL_SEC = 0.4

    def __init__(self):
        self.settings = use(SettingsService)
        self.device_id = 0
        self.selected_microphone = ""
        self.mic_recognition_active = False
        self.asr_is_ready = False
        self.instant_send = False
        self.events_bus = get_event_bus()
        self.asr_settings = ensure_asr_settings_service()

        self._glossary_lock = threading.RLock()
        self._glossary_cache: list[dict] | None = None
        self._glossary_loading = False
        self._glossary_callbacks: list = []

        self._last_text = ""
        self._last_text_norm = ""
        self._last_text_time = 0.0

        # «Мита говорит» — чтобы ASR не засчитывал её собственный голос из
        # микрофона (см. _on_speech_text_recognized / _is_mita_speaking).
        self._mita_speaking = False        # открытое окно (локальное воспроизведение)
        self._mita_speaking_until = 0.0    # окно по таймеру (монотонные секунды)

        self._settings_subscription = self.settings.subscribe(
            self._on_setting_changed, keys=self._SETTING_KEYS
        )
        self._subscribe_to_events()
        self._apply_settings_snapshot()

    # ——— settings json
    def _load_asr_settings(self):
        self._sanitize_asr_models()

    @property
    def _asr_settings(self) -> dict:
        return self.asr_settings.snapshot()

    def _sanitize_asr_models(self) -> bool:
        """Чинит устаревшие/битые значения «model» в asr_settings.json.

        Пример из жизни: у gigaam оставалось model=v3_ssl — SSL-чекпоинт,
        который не умеет распознавать речь: модель «запускалась», но каждый
        сегмент падал и текст не приходил. Возвращает True, если что-то
        поменяли и файл надо пересохранить."""
        models = self._asr_settings.get("models")
        if not isinstance(models, dict):
            return False

        changed = False
        for engine, cls in SpeechRecognition._registry.items():
            valid = getattr(cls, "VALID_MODELS", None)
            default = getattr(cls, "DEFAULT_MODEL", None)
            if not valid or not default:
                continue
            cfg = models.get(engine)
            if not isinstance(cfg, dict):
                continue
            model = str(cfg.get("model") or "").strip()
            if model and model not in valid:
                logger.warning(
                    f"ASR: модель '{model}' недопустима для '{engine}' — заменяю на '{default}'."
                )
                cfg["model"] = default
                self.asr_settings.set_model_settings(engine, cfg)
                changed = True
        return changed

    # ——— subscriptions
    def _subscribe_to_events(self):
        eb = self.events_bus
        eb.subscribe("speech_settings_loaded", self._on_speech_settings_loaded, weak=False)

        eb.subscribe(Events.Speech.SET_INSTANT_SEND_STATUS, self._on_set_instant_send_status, weak=False)
        eb.subscribe(Events.Speech.SPEECH_TEXT_RECOGNIZED, self._on_speech_text_recognized, weak=False)
        eb.subscribe(Events.Audio.MITA_SPEAKING_WINDOW, self._on_mita_speaking_window, weak=False)

        eb.subscribe(Events.Speech.SET_MICROPHONE, self._on_set_microphone, weak=False)
        eb.subscribe(Events.Speech.START_SPEECH_RECOGNITION, self._on_start_speech_recognition, weak=False)
        eb.subscribe(Events.Speech.STOP_SPEECH_RECOGNITION, self._on_stop_speech_recognition, weak=False)
        eb.subscribe(Events.Speech.RESTART_SPEECH_RECOGNITION, self._on_restart_speech_recognition, weak=False)

        eb.subscribe(Events.Speech.REFRESH_MICROPHONE_LIST, self._on_refresh_microphone_list, weak=False)


        eb.subscribe(Events.Speech.SET_RECOGNIZER_OPTION, self._on_set_recognizer_option, weak=False)
        eb.subscribe(Events.Speech.APPLY_RECOGNIZER_SETTINGS, self._on_apply_recognizer_settings, weak=False)

        # INSTALL_ASR_MODEL и state queries не проходят через EventBus.
        # Установка живёт в InstallController, чтение состояния — в SpeechService.

        eb.subscribe(Events.Speech.ASR_MODEL_INIT_STARTED, self._on_asr_init_started_backend, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INITIALIZED, self._on_asr_initialized_backend, weak=False)
        eb.subscribe(Events.Speech.ASR_FAILED, self._on_asr_failed_backend, weak=False)

    # ——— readiness tracking
    def _on_asr_init_started_backend(self, _event: Event):
        self.asr_is_ready = False
        self.events_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    def _on_asr_initialized_backend(self, _event: Event):
        self.asr_is_ready = True
        self.events_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    def _on_asr_failed_backend(self, _event: Event):
        self.asr_is_ready = False
        self.events_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    # ——— settings loaded
    def _on_speech_settings_loaded(self, event: Event):
        supplied = (event.data or {}).get('settings')
        if supplied is not None:
            self.settings = supplied
        self._apply_settings_snapshot()

    def _apply_settings_snapshot(self):
        self._load_asr_settings()

        engine = self.settings.get("RECOGNIZER_TYPE", self._asr_settings.get("engine", "google"))
        self.asr_settings.set_selected_engine(engine)

        SpeechRecognition.set_recognizer_type(engine)
        SpeechRecognition.apply_settings(engine, self._asr_settings["models"].get(engine, {}))

        self.device_id = self.settings.get("NM_MICROPHONE_ID", 0)
        self.selected_microphone = self.settings.get("NM_MICROPHONE_NAME", "")

        try:
            SpeechRecognition.VOSK_SAMPLE_RATE = int(self.settings.get("VOSK_SAMPLE_RATE", SpeechRecognition.VOSK_SAMPLE_RATE))
            SpeechRecognition.CHUNK_SIZE = int(self.settings.get("CHUNK_SIZE", SpeechRecognition.CHUNK_SIZE))
            SpeechRecognition.VAD_THRESHOLD = float(self.settings.get("VAD_THRESHOLD", SpeechRecognition.VAD_THRESHOLD))
            SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC = float(self.settings.get("VAD_SILENCE_TIMEOUT_SEC", SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC))
            SpeechRecognition.VAD_PRE_BUFFER_DURATION_SEC = float(self.settings.get("VAD_PRE_BUFFER_DURATION_SEC", SpeechRecognition.VAD_PRE_BUFFER_DURATION_SEC))
            SpeechRecognition.MAX_SPEECH_DURATION_SEC = float(self.settings.get("MAX_SPEECH_DURATION_SEC", SpeechRecognition.MAX_SPEECH_DURATION_SEC))
        except Exception:
            pass

        logger.info(f"Тип распознавателя установлен на: {engine}")
        if self.selected_microphone:
            logger.info(f"Загружен микрофон из настроек: {self.selected_microphone} (ID: {self.device_id})")

        if self.settings.get("MIC_ACTIVE", False) and not self.mic_recognition_active:
            def _delayed_start():
                try:
                    self._start_maybe_install()
                except Exception as e:
                    logger.error(f"Автозапуск распознавания не удался: {e}")
            task_supervisor().start_thread(
                self, "speech-delayed-start", _delayed_start, replace=True
            )

    # ——— settings changed
    def _on_setting_changed(self, change):
        key = change.key
        value = change.value

        if key == "MIC_ACTIVE":
            if bool(value):
                self._start_maybe_install_async()
            else:
                SpeechRecognition.speech_recognition_stop()
                self.mic_recognition_active = False
                self.asr_is_ready = False
            self.events_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

        elif key == "RECOGNIZER_TYPE":
            engine = str(value)
            current = self._asr_settings.get("engine", "google")

            if engine == current:
                logger.info(f"Тип распознавателя установлен на: {engine}")
                SpeechRecognition.apply_settings(engine, self._asr_settings["models"].get(engine, {}))
                return

            self.asr_settings.set_selected_engine(engine)

            if self.mic_recognition_active:
                SpeechRecognition.speech_recognition_stop()
                self.mic_recognition_active = False
                self.asr_is_ready = False
                time.sleep(0.2)

            SpeechRecognition.set_recognizer_type(engine)
            SpeechRecognition.apply_settings(engine, self._asr_settings["models"].get(engine, {}))

            logger.info(f"Тип распознавателя установлен на: {engine}")

            if self.settings and self.settings.get("MIC_ACTIVE", False):
                self._start_maybe_install_async()

        elif key in ("SILENCE_THRESHOLD", "VAD_THRESHOLD"):
            try:
                SpeechRecognition.VAD_THRESHOLD = float(value)
            except Exception:
                pass

        elif key in ("SILENCE_DURATION", "VAD_SILENCE_TIMEOUT_SEC"):
            try:
                SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC = float(value)
            except Exception:
                pass

        elif key == "VOSK_SAMPLE_RATE":
            try:
                SpeechRecognition.VOSK_SAMPLE_RATE = int(value)
            except Exception:
                pass

        elif key == "CHUNK_SIZE":
            try:
                SpeechRecognition.CHUNK_SIZE = int(value)
            except Exception:
                pass

        elif key == "VAD_PRE_BUFFER_DURATION_SEC":
            try:
                SpeechRecognition.VAD_PRE_BUFFER_DURATION_SEC = float(value)
            except Exception:
                pass

        elif key == "MAX_SPEECH_DURATION_SEC":
            try:
                SpeechRecognition.MAX_SPEECH_DURATION_SEC = float(value)
            except Exception:
                pass

    def _start_maybe_install_async(self):
        """Run the (potentially slow) ASR start off the caller's thread.

        Settings observers may run on the caller thread; starting ASR loads a
        model and can block for many seconds. Always do it on a worker thread."""
        def _worker():
            try:
                self._start_maybe_install()
            except Exception as e:
                logger.error(f"Запуск распознавания не удался: {e}")
        task_supervisor().start_thread(
            self, "speech-start", _worker, replace=True
        )

    def _start_maybe_install(self):
        if self.mic_recognition_active:
            return

        engine = self._asr_settings.get("engine", "google")

        if not self._check_model_installed(engine):
            self.events_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                'title': _('Требуется установка', 'Installation required'),
                'message': _(
                    'ASR-модель не установлена. Установите её через AI Hub.',
                    'ASR model is not installed. Install it via AI Hub.'
                )
            })

            try:
                if self.settings:
                    self.settings.set("MIC_ACTIVE", False)
                    self.settings.save_settings()
            except Exception:
                pass

            try:
                self.events_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
            except Exception:
                pass

            return

        loop_service = use(LoopService)
        if not loop_service.is_running():
            logger.error("Не удалось получить event loop для запуска распознавания речи")
            self._handle_start_failure()
            return

        self.asr_is_ready = False
        started = bool(SpeechRecognition.speech_recognition_start(self.device_id or 0, loop_service.loop()))
        self.mic_recognition_active = started
        if not started:
            self._handle_start_failure()

    def _handle_start_failure(self):
        """Старт распознавания не удался: раньше MIC_ACTIVE оставался
        включённым и чекбокс «микрофон» горел при мёртвом распознавании."""
        self.mic_recognition_active = False
        self.asr_is_ready = False
        try:
            if self.settings and bool(self.settings.get("MIC_ACTIVE", False)):
                self.settings.set("MIC_ACTIVE", False)
                self.settings.save_settings()
        except Exception:
            pass
        try:
            self.events_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
        except Exception:
            pass
        self.events_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
            'title': _('Распознавание речи', 'Speech recognition'),
            'message': _(
                'Не удалось запустить распознавание речи. Подробности в логе.',
                'Failed to start speech recognition. See the log for details.'
            )
        })

    def shutdown(self) -> None:
        subscription = self._settings_subscription
        self._settings_subscription = None
        if subscription is not None:
            subscription.close()
        try:
            SpeechRecognition.speech_recognition_stop()
        except Exception:
            pass
        self.mic_recognition_active = False
        self.asr_is_ready = False
        with self._glossary_lock:
            self._glossary_callbacks.clear()
        task_supervisor().cancel_owner(self, timeout=1.0)

    def recognizer_settings_schema(self, engine: str) -> list[dict]:
        return list(self._on_get_recognizer_settings_schema(Event(Events.Speech.GET_RECOGNIZER_SETTINGS_SCHEMA, {"engine": engine})) or [])

    def recognizer_settings(self, engine: str) -> dict:
        return dict(self._on_get_recognizer_settings(Event(Events.Speech.GET_RECOGNIZER_SETTINGS, {"engine": engine})) or {})

    def mic_active(self) -> bool:
        return bool(self.mic_recognition_active and self.asr_is_ready)

    def microphone_list_async(self, callback) -> None:
        self._on_get_microphone_list(
            Event(Events.Speech.GET_MICROPHONE_LIST, {"callback": callback})
        )

    def asr_models_glossary_async(self, callback, *, refresh: bool = False) -> None:
        self._on_get_asr_models_glossary(
            Event(
                Events.Speech.GET_ASR_MODELS_GLOSSARY,
                {"callback": callback, "refresh": refresh},
            )
        )

    def asr_model_installed_async(self, engine: str, callback) -> None:
        model_type = str(engine or self._asr_settings.get("engine", "google"))

        def worker() -> None:
            try:
                callback(bool(self._check_model_installed(model_type)), None)
            except BaseException as exc:
                try:
                    callback(False, exc)
                except Exception:
                    pass

        task_supervisor().start_thread(
            self,
            f"asr-installed-check:{model_type}:{time.monotonic_ns()}",
            worker,
        )

    # —— universal ASR settings IO
    def _on_get_recognizer_settings_schema(self, event: Event):
        if not self._asr_settings or not self._asr_settings.get("models"):
            self._load_asr_settings()
        engine = (event.data or {}).get('engine') or self._asr_settings.get("engine", "google")
        return SpeechRecognition.get_settings_schema(engine)

    def _on_get_recognizer_settings(self, event: Event):
        if not self._asr_settings or not self._asr_settings.get("models"):
            self._load_asr_settings()
        engine = (event.data or {}).get('engine') or self._asr_settings.get("engine", "google")
        model_map = self._asr_settings.get("models", {})
        return model_map.get(engine, {})

    def _on_set_recognizer_option(self, event: Event):
        data = event.data or {}
        engine = data.get('engine') or self._asr_settings.get("engine", "google")
        key = data.get('key')
        value = data.get('value')
        if key is None:
            return
        self.asr_settings.set_model_option(engine, key, value)
        if engine == self._asr_settings.get("engine"):
            SpeechRecognition.apply_settings(engine, self.asr_settings.model_settings(engine))

    def _on_apply_recognizer_settings(self, event: Event):
        data = event.data or {}
        engine = data.get('engine') or self._asr_settings.get("engine", "google")
        settings = data.get('settings', {})
        self.asr_settings.set_model_settings(engine, settings)
        if engine == self._asr_settings.get("engine"):
            SpeechRecognition.apply_settings(engine, settings)

    # —— install/check
    def _check_model_installed(self, model_type: str) -> bool:
        engine_settings = {}
        try:
            engine_settings = (self._asr_settings.get("models", {}) or {}).get(model_type, {}) or {}
        except Exception:
            engine_settings = {}
        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            return False
        return catalog.is_ready(
            f"asr:{str(model_type or '').strip()}",
            ctx={"engine_settings": dict(engine_settings)},
        )

    def _on_get_asr_engines_list(self, _event: Event):
        return list(SpeechRecognition._registry.keys())

    # —— mic & pipeline glue
    def _on_get_instant_send_status(self, _event: Event):
        try:
            return bool(self.settings.get("MIC_INSTANT_SENT"))
        except Exception:
            return False

    def _on_set_instant_send_status(self, event: Event):
        self.instant_send = event.data.get('status', False)

    @staticmethod
    def _normalize_asr_text(text: str) -> str:
        lowered = (text or "").strip().lower().replace("\u0451", "\u0435")
        lowered = re.sub(r"[^\w\s]+", " ", lowered, flags=re.UNICODE)
        return re.sub(r"\s+", " ", lowered, flags=re.UNICODE).strip()

    def _is_asr_duplicate(self, text: str, now: float) -> bool:
        norm = self._normalize_asr_text(text)
        if not norm:
            return True

        age = now - self._last_text_time
        if self._last_text_norm and age < 2.0 and norm == self._last_text_norm:
            return True

        if self._last_text_norm and age < 1.5 and min(len(norm), len(self._last_text_norm)) >= 20:
            ratio = SequenceMatcher(None, norm, self._last_text_norm).ratio()
            if ratio >= 0.92:
                logger.debug(f"ASR dedup (fuzzy): ignore '{text}'")
                return True

        return False

    def _on_mita_speaking_window(self, event: Event):
        data = event.data or {}
        now = time.monotonic()
        if "active" in data:
            if bool(data.get("active")):
                self._mita_speaking = True
            else:
                # Закрыли открытое окно — держим ещё хвост на затухание/VAD.
                self._mita_speaking = False
                self._mita_speaking_until = max(self._mita_speaking_until, now + self._MUTE_TAIL_SEC)
        if "duration" in data:
            dur = 0.0
            try:
                dur = float(data.get("duration") or 0.0)
            except Exception:
                dur = 0.0
            if dur > 0:
                self._mita_speaking_until = max(self._mita_speaking_until, now + dur + self._MUTE_TAIL_SEC)

    def _is_mita_speaking(self) -> bool:
        return self._mita_speaking or time.monotonic() < self._mita_speaking_until

    def _on_speech_text_recognized(self, event: Event):
        text = (event.data or {}).get('text', '').strip()
        if not text or not self.settings:
            return
        if not bool(self.settings.get("MIC_ACTIVE")):
            return

        # Не засчитываем то, что говорит сама Мита (её голос ловит микрофон),
        # пока активно окно её речи. Распознавание при этом не выключается.
        if bool(self.settings.get("MIC_MUTE_WHILE_SPEAKING", True)) and self._is_mita_speaking():
            logger.debug(f"ASR заглушён (Мита говорит): игнор '{text}'")
            return

        now = time.time()
        if self._is_asr_duplicate(text, now):
            return
        self._last_text = text
        self._last_text_norm = self._normalize_asr_text(text)
        self._last_text_time = now

        if use(GameLinkService).is_connected():
            self.events_bus.emit(Events.Server.BROADCAST_ASR_TEXT, {
                "text": text,
                "engine": str(self._asr_settings.get("engine", "") or ""),
                "ts": time.time(),
            })

        if bool(self.settings.get("MIC_INSTANT_SENT")):
            audio = services().get_optional(AudioStateService)
            waiting_answer = bool(audio and audio.is_waiting_answer())
            if not waiting_answer:
                self._send_instant(text)
        else:
            logger.info(f"Распознано: {text}")
            self.events_bus.emit(Events.GUI.INSERT_TEXT_TO_INPUT, {"text": text})


    def _send_instant(self, text):
        # Через GUI-отправку, а не напрямую SEND_MESSAGE: так подхватываются
        # авто-захват экрана, прикреплённые и кадры камеры (иначе ASR-отправка
        # игнорировала изображения). GUI сам рисует сообщение пользователя.
        self.events_bus.emit(Events.GUI.SEND_TEXT_MESSAGE, {'text': text})

    def _on_get_mic_status(self, event: Event):
        data = event.data or {}
        cb = data.get("callback")

        res = bool(self.mic_recognition_active and self.asr_is_ready)

        if cb:
            try:
                cb(res, None)
            except Exception:
                pass
            return None

        return res

    def _on_set_microphone(self, event: Event):
        name = event.data.get('name')
        dev_id = event.data.get('device_id')
        if name and dev_id is not None:
            self.selected_microphone = name
            self.device_id = dev_id
            if self.settings:
                self.settings.set("NM_MICROPHONE_ID", dev_id)
                self.settings.set("NM_MICROPHONE_NAME", name)
                self.settings.save_settings()
            logger.info(f"Выбран микрофон: {name} (ID: {dev_id})")

    def _on_start_speech_recognition(self, event: Event):
        dev_id = event.data.get('device_id', self.device_id)
        loop_service = use(LoopService)
        if not loop_service.is_running():
            logger.error("Не удалось получить event loop для запуска распознавания речи")
            self._handle_start_failure()
            return

        self.asr_is_ready = False
        started = bool(SpeechRecognition.speech_recognition_start(dev_id, loop_service.loop()))
        self.mic_recognition_active = started
        if not started:
            self._handle_start_failure()

    def _on_stop_speech_recognition(self, _event: Event):
        SpeechRecognition.speech_recognition_stop()
        self.mic_recognition_active = False
        self.asr_is_ready = False

    def _on_restart_speech_recognition(self, event: Event):
        dev_id = event.data.get('device_id', self.device_id)

        def restart():
            try:
                self.events_bus.emit(Events.Speech.STOP_SPEECH_RECOGNITION)
                SpeechRecognition._stopped_event.wait(timeout=5.0)
                self.events_bus.emit(Events.Speech.START_SPEECH_RECOGNITION, {'device_id': dev_id})
            except Exception as e:
                logger.error(f"Ошибка перезапуска распознавания: {e}")

        task_supervisor().start_thread(
            self, "speech-restart", restart, replace=True
        )

    def _on_get_microphone_list(self, event: Event):
        data = event.data or {}
        cb = data.get("callback")

        def compute():
            try:
                devices = sd.query_devices()
                result = []
                for i, d in enumerate(devices):
                    if d.get('max_input_channels', 0) > 0:
                        name = d.get('name', f"Device {i}")
                        result.append(f"{name} ({i})")
                return result or ["Микрофоны не найдены"]
            except Exception as e:
                logger.error(f"Ошибка получения списка микрофонов: {e}")
                return ["Ошибка загрузки"]

        if not cb:
            return compute()

        def worker():
            try:
                lst = compute()
                try:
                    cb(lst, None)
                except Exception:
                    pass
            except Exception as e:
                try:
                    cb(["Ошибка загрузки"], e)
                except Exception:
                    pass

        task_supervisor().start_thread(
            self,
            f"speech-background-{time.monotonic_ns()}",
            worker,
        )
        return None

    def _on_refresh_microphone_list(self, event: Event):
        return self._on_get_microphone_list(event)

    def _on_get_asr_models_glossary(self, event: Event):
        data = event.data or {}
        callback = data.get("callback")
        refresh = bool(data.get("refresh", False))

        with self._glossary_lock:
            if self._glossary_cache is not None and not refresh:
                cached = [dict(item) for item in self._glossary_cache]
                if callable(callback):
                    try:
                        callback(cached, None)
                    except Exception:
                        pass
                    return None
                return cached

            if callable(callback):
                self._glossary_callbacks.append(callback)

            if self._glossary_loading:
                return [] if not callable(callback) else None

            self._glossary_loading = True

        def worker() -> None:
            error = None
            try:
                result = self._compute_asr_models_glossary(refresh=refresh)
            except Exception as exc:
                logger.error(f"GET_ASR_MODELS_GLOSSARY error: {exc}", exc_info=True)
                result = []
                error = exc

            with self._glossary_lock:
                self._glossary_cache = [dict(item) for item in result]
                self._glossary_loading = False
                callbacks = self._glossary_callbacks
                self._glossary_callbacks = []

            for cb in callbacks:
                try:
                    cb([dict(item) for item in result], error)
                except Exception:
                    pass

        task_supervisor().start_thread(
            self,
            "asr-glossary-catalog",
            worker,
            replace=True,
        )
        return [] if not callable(callback) else None

    def _compute_asr_models_glossary(self, *, refresh: bool = False) -> list[dict]:
        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            return []

        rows = catalog.list_rows(
            include_status=True,
            refresh=bool(refresh),
            category="asr",
            status_category="asr",
        )
        result: list[dict] = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row, dict) else None
            status = row.get("status") if isinstance(row, dict) else None
            if not isinstance(metadata, dict) or not isinstance(status, dict):
                continue

            details = status.get("details")
            details = dict(details) if isinstance(details, dict) else {}
            missing_required = list(details.get("missing_required") or ())
            if not bool(status.get("backend_ok", True)) and "backend" not in missing_required:
                missing_required.append("backend")

            result.append(
                {
                    "id": str(metadata.get("item_id") or ""),
                    "component_id": str(metadata.get("id") or ""),
                    "name": str(metadata.get("title") or metadata.get("item_id") or ""),
                    "description": str(metadata.get("description") or ""),
                    "languages": list(metadata.get("languages") or ()),
                    "gpu_vendor": [],
                    "tags": list(metadata.get("tags") or ()),
                    "links": [],
                    "installed": bool(status.get("ready", False)),
                    "ready": bool(status.get("ready", False)),
                    "status": dict(status),
                    "missing_required": missing_required,
                    "missing_optional": list(details.get("missing_optional") or ()),
                    "details": [dict(status)],
                }
            )
        return result
