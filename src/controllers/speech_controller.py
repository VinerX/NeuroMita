from core.error_utils import format_exception
import os
import time
import re
import threading
import uuid
from itertools import count
from difflib import SequenceMatcher
import sounddevice as sd

from handlers.asr_handler import SpeechRecognition
from main_logger import logger
from core.events import get_event_bus, Events, Event
from core.performance_trace import perf_mark, perf_mark_once, performance_traces
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
from managers.speaking_window import SpeakingWindow
from services.asr_settings_service import ensure_asr_settings_service
from utils import getTranslationVariant as _


class SpeechController(SpeechService):
    _SETTING_KEYS = frozenset({
        "MIC_ACTIVE", "RECOGNIZER_TYPE", "SILENCE_THRESHOLD",
        "VAD_THRESHOLD", "SILENCE_DURATION", "VAD_SILENCE_TIMEOUT_SEC",
        "VOSK_SAMPLE_RATE", "CHUNK_SIZE", "VAD_PRE_BUFFER_DURATION_SEC",
        "MAX_SPEECH_DURATION_SEC", "MIN_SPEECH_DURATION_SEC",
        "NM_MICROPHONE_ID", "NM_MICROPHONE_NAME",
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

        # Старт и стоп — не два независимых задания, а одно: привести реальное
        # состояние микрофона к желаемому (MIC_ACTIVE + выбранный движок).
        # Раньше «стоп» и «старт» были разными потоками, и общий замок лишь
        # выстраивал их в очередь: протухший старт, дождавшись замка, включал
        # микрофон обратно уже после выключения. Теперь замок держит один
        # реконсилятор, который перед каждым шагом заново читает желаемое
        # состояние, а поколение (_desired_generation) гарантирует, что после
        # любого изменения будет ещё один проход.
        self._lifecycle_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._desired_generation = 0
        self._applied_generation = 0
        self._reconcile_pending = False
        # Явный перезапуск (сменили микрофон): движок тот же, но живой цикл надо
        # поднять заново.
        self._restart_requested = False
        # Движок, загруженный в SpeechRecognition, и движок живого цикла
        # (None — распознавание не запущено).
        self._configured_engine: str | None = None
        self._running_engine: str | None = None
        self._shutting_down = False
        # Имена фоновых задач обязаны быть уникальными: супервизор считает
        # совпадение имени попыткой запустить вторую копию и бросает RuntimeError.
        # Метка времени тут не годится — на Windows монотонные часы тикают раз в
        # ~15 мс, и два быстрых щелчка тумблером давали одно и то же имя.
        self._task_seq = count(1)

        self._glossary_lock = threading.RLock()
        self._glossary_cache: list[dict] | None = None
        self._glossary_loading = False
        self._glossary_callbacks: list = []

        self._last_text = ""
        self._last_text_norm = ""
        self._last_text_time = 0.0

        # «Мита говорит» — чтобы ASR не засчитывал её собственный голос из
        # микрофона (см. _on_speech_text_recognized / _is_mita_speaking).
        self._speaking_window = SpeakingWindow(tail_sec=self._MUTE_TAIL_SEC)

        # Фразы, отданные в игру и ещё не вернувшиеся как недоставленные.
        # Пока id здесь — десктоп-чат фразу не берёт, а забрав, снимает id,
        # поэтому повторный «недоставлен» уже не сработает. Это защита от
        # раздвоения хода внутри Python; приняла ли фразу игра, отсюда не видно:
        # ACK по utterance_id в протоколе мода нет, маршрутизация best-effort.
        self._turns_lock = threading.Lock()
        self._turns_in_game: dict[str, float] = {}

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
        eb.subscribe(Events.Server.CLIENT_DISCONNECTED, self._on_client_disconnected, weak=False)
        eb.subscribe(Events.Server.ASR_TEXT_UNDELIVERED, self._on_asr_text_undelivered, weak=False)

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
        # Событие означает «живое распознавание подтверждено движком», поэтому
        # тут же поднимаем и mic_recognition_active: подписчики (индикатор ASR)
        # читают mic_active() синхронно внутри этого emit, а вызывающий код
        # присваивает флаг только ПОСЛЕ возврата из speech_recognition_start —
        # иначе статус залипал на «ASR не готов».
        self.mic_recognition_active = True
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
            SpeechRecognition.MIN_SPEECH_DURATION_SEC = float(self.settings.get("MIN_SPEECH_DURATION_SEC", SpeechRecognition.MIN_SPEECH_DURATION_SEC))
        except Exception:
            pass

        self._configured_engine = engine
        logger.info(f"Тип распознавателя установлен на: {engine}")
        if self.selected_microphone:
            logger.info(f"Загружен микрофон из настроек: {self.selected_microphone} (ID: {self.device_id})")

        self._request_reconcile("settings snapshot")

    # ——— settings changed
    def _on_setting_changed(self, change):
        key = change.key
        value = change.value

        if key == "MIC_ACTIVE":
            if not bool(value):
                # Флаги гасим сразу, чтобы статус не врал; сам стоп ждёт живой
                # цикл до 8 секунд и уходит в реконсилятор с полосы наблюдателей.
                self.mic_recognition_active = False
                self.asr_is_ready = False
            self._request_reconcile(f"MIC_ACTIVE={bool(value)}")
            self.events_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

        elif key == "RECOGNIZER_TYPE":
            engine = str(value)
            self.asr_settings.set_selected_engine(engine)
            # Настройки движка могли поменяться и без смены самого движка —
            # заставляем реконсилятор перезалить их в SpeechRecognition.
            with self._state_lock:
                self._configured_engine = None
            self._request_reconcile(f"RECOGNIZER_TYPE={engine}")

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

        elif key == "MIN_SPEECH_DURATION_SEC":
            try:
                SpeechRecognition.MIN_SPEECH_DURATION_SEC = float(value)
            except Exception:
                pass

    # ——— реконсилятор состояния микрофона
    def _desired_mic_active(self) -> bool:
        if self._shutting_down or not self.settings:
            return False
        try:
            return bool(self.settings.get("MIC_ACTIVE", False))
        except Exception:
            return False

    def _desired_engine(self) -> str:
        return str(self._asr_settings.get("engine", "google") or "google")

    def _task_name(self, prefix: str) -> str:
        return f"{prefix}-{next(self._task_seq)}"

    def _request_reconcile(self, reason: str = "") -> None:
        """Просит привести микрофон к текущему желаемому состоянию.

        Поколение растёт при каждом запросе: реконсилятор, уже держащий замок,
        обязательно сделает ещё один проход и увидит последнее значение настроек.
        Поэтому исход последовательности True→False→True определяется последним
        щелчком, а не тем, какой поток первым дождался замка.
        """
        if self._shutting_down:
            return
        with self._state_lock:
            self._desired_generation += 1
            # Уже есть поток, который ещё не начал применять состояние, — он
            # увидит новое поколение сам, второй заводить незачем.
            if self._reconcile_pending:
                return
            self._reconcile_pending = True
        if reason:
            logger.debug(f"ASR reconcile requested: {reason}")
        # Проходы намеренно могут накладываться: пока предыдущий держит
        # _lifecycle_lock, новый поток просто ждёт на нём. Поэтому у каждого своё
        # имя — иначе супервизор принял бы их за повтор одной задачи и уронил
        # RuntimeError прямо в наблюдателя настроек.
        task_supervisor().start_thread(
            self,
            self._task_name("speech-reconcile"),
            self._reconcile_worker,
        )

    def _reconcile_worker(self) -> None:
        while True:
            with self._lifecycle_lock:
                with self._state_lock:
                    self._reconcile_pending = False
                    generation = self._desired_generation
                    if generation == self._applied_generation:
                        return

                try:
                    self._reconcile_once()
                except Exception as e:
                    logger.error(f"ASR reconcile failed: {format_exception(e)}", exc_info=True)

                with self._state_lock:
                    self._applied_generation = generation
                    if self._desired_generation == generation:
                        return
            # Настройки поменялись, пока мы применяли предыдущее состояние —
            # отпускаем замок и идём ещё круг.

    def _reconcile_once(self) -> None:
        desired_active = self._desired_mic_active()
        desired_engine = self._desired_engine()
        with self._state_lock:
            force_restart = self._restart_requested
            self._restart_requested = False

        # Живой цикл держит старый распознаватель: выключение, смена движка и
        # явный перезапуск (сменили микрофон) начинаются с остановки.
        if self._running_engine is not None and (
            not desired_active or force_restart or self._running_engine != desired_engine
        ):
            self._stop_running()

        if self._configured_engine != desired_engine:
            SpeechRecognition.set_recognizer_type(desired_engine)
            SpeechRecognition.apply_settings(
                desired_engine, self._asr_settings["models"].get(desired_engine, {})
            )
            self._configured_engine = desired_engine
            logger.info(f"Тип распознавателя установлен на: {desired_engine}")

        if not desired_active:
            return
        if self._running_engine == desired_engine and self.mic_recognition_active:
            return

        # Остановка и перенастройка движка занимают заметное время: за них
        # тумблер успевают выключить. Перечитываем перед стартом, чтобы не
        # поднимать модель ради немедленной остановки следующим проходом.
        if not self._desired_mic_active():
            return

        self._start_maybe_install()
        self._running_engine = desired_engine if self.mic_recognition_active else None

    def _stop_running(self) -> None:
        try:
            SpeechRecognition.speech_recognition_stop()
            time.sleep(0.2)
        except Exception as e:
            logger.error(f"Остановка распознавания не удалась: {format_exception(e)}", exc_info=True)
        self.mic_recognition_active = False
        self.asr_is_ready = False
        self._running_engine = None

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

            self._set_mic_desired(False)

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
        self._set_mic_desired(False)
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
        self._shutting_down = True
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
        self._running_engine = None
        # Подписки weak=False держат сильную ссылку на bound method: без снятия
        # выключенный контроллер продолжает реагировать на события шины.
        self.events_bus.unsubscribe_owner(self)
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
            self._task_name(f"asr-installed-check:{model_type}"),
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
        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            return False
        return catalog.is_ready(f"asr:{str(model_type or '').strip()}")

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
        """Окно «Мита говорит»: локальное воспроизведение или speech_state от мода."""
        data = event.data or {}
        if "active" not in data:
            return

        # Одна реплика — одна аренда. Ключ реплики даёт мод (speech_id), иначе
        # различаем хотя бы по персонажу: две Миты одного клиента говорят
        # независимо, и конец одной не открывает микрофон посреди другой.
        source = str(data.get("source") or "").strip() or "local"
        speech_id = str(data.get("speech_id") or data.get("character") or "").strip()
        if bool(data.get("active")):
            self._speaking_window.open(
                source=source,
                speech_id=speech_id,
                duration_sec=data.get("duration_sec", 0.0),
            )
        else:
            self._speaking_window.close(source=source, speech_id=speech_id)

    def _on_client_disconnected(self, event: Event):
        client_id = str((event.data or {}).get("client_id") or "")
        if client_id:
            self._speaking_window.close_source(client_id)

    def _is_mita_speaking(self) -> bool:
        return self._speaking_window.is_active()

    def _on_speech_text_recognized(self, event: Event):
        data = event.data or {}
        text = data.get("text", "").strip()
        trace_id = str(data.get("trace_id") or "").strip() or None
        perf_mark_once(trace_id, "asr.text_ready")
        if not text or not self.settings:
            performance_traces().finish(trace_id, "ignored", error_stage="asr.empty") if trace_id else None
            return
        if not bool(self.settings.get("MIC_ACTIVE")):
            performance_traces().finish(trace_id, "ignored", error_stage="asr.inactive") if trace_id else None
            return

        # Не засчитываем то, что говорит сама Мита (её голос ловит микрофон),
        # пока активно окно её речи. Распознавание при этом не выключается.
        if bool(self.settings.get("MIC_MUTE_WHILE_SPEAKING", True)) and self._is_mita_speaking():
            performance_traces().finish(trace_id, "ignored", error_stage="asr.mita_speaking") if trace_id else None
            logger.debug(f"ASR заглушён (Мита говорит): игнор '{text}'")
            return

        now = time.time()
        if self._is_asr_duplicate(text, now):
            performance_traces().finish(trace_id, "ignored", error_stage="asr.duplicate") if trace_id else None
            return
        self._last_text = text
        self._last_text_norm = self._normalize_asr_text(text)
        self._last_text_time = now

        autosend, delay_sec = self._instant_send_policy()

        # Ветки взаимоисключающие: у реплики игрока ровно один владелец. Раньше
        # текст при подключённой игре уходил и в мод, и в десктоп-чат — игрок
        # получал два хода из одной фразы.
        # Адресат фиксируется здесь же, где принято решение «ход у игры»: пока
        # фраза дойдёт до отправки, активной может стать другая сессия мода.
        turn_owner = self._player_turn_owner()
        if turn_owner:
            utterance_id = uuid.uuid4().hex
            self._claim_game_turn(utterance_id)
            logger.info(f"Распознано (в игру): {text}")
            self.events_bus.emit(Events.Server.SEND_ASR_TEXT, {
                "id": utterance_id,
                "client_id": turn_owner,
                "text": text,
                "engine": str(self._asr_settings.get("engine", "") or ""),
                "ts": time.time(),
                "final": True,
                # Эти поля остаются только внутри Python для возврата реплики в
                # desktop-чат, если выбранная игровая сессия успела отключиться.
                "autosend": autosend,
                "delay_sec": delay_sec,
            })
            perf_mark(trace_id, "asr.sent_to_game")
            performance_traces().finish(trace_id, "sent_to_game") if trace_id else None
            return

        logger.info(f"Распознано: {text}")
        self._route_to_desktop(text, autosend, delay_sec, trace_id=trace_id)

    _MAX_TURNS_IN_GAME = 64

    def _claim_game_turn(self, utterance_id: str) -> None:
        if not utterance_id:
            return
        with self._turns_lock:
            self._turns_in_game[utterance_id] = time.time()
            while len(self._turns_in_game) > self._MAX_TURNS_IN_GAME:
                oldest = min(self._turns_in_game, key=self._turns_in_game.get)
                self._turns_in_game.pop(oldest, None)

    def _release_game_turn(self, utterance_id: str) -> bool:
        """True — ход по этой фразе освободился и его можно отдать десктоп-чату."""
        if not utterance_id:
            # Событие без id: старый эмиттер, дедуплицировать нечем.
            return True
        with self._turns_lock:
            return self._turns_in_game.pop(utterance_id, None) is not None

    def _on_asr_text_undelivered(self, event: Event):
        """Мод отвалился между проверкой связи и отправкой — фраза не должна пропасть."""
        data = event.data or {}
        text = str(data.get("text") or "").strip()
        if not text:
            return
        utterance_id = str(data.get("id") or "")
        if not self._release_game_turn(utterance_id):
            logger.debug(f"asr_text {utterance_id}: ход уже отдан, повтор игнорирую")
            return
        self._route_to_desktop(
            text,
            bool(data.get("autosend", False)),
            float(data.get("delay_sec", 0.0) or 0.0),
            trace_id=str(data.get("trace_id") or "").strip() or None,
        )

    def _route_to_desktop(self, text: str, autosend: bool, delay_sec: float, trace_id: str | None = None):
        if autosend and delay_sec <= 0:
            audio = services().get_optional(AudioStateService)
            if not (audio and audio.is_waiting_answer()):
                self._send_instant(text, trace_id=trace_id)
                return
            # Ответ ещё генерируется: не теряем сказанное, а кладём в поле ввода.

        performance_traces().finish(trace_id, "routed_to_input") if trace_id else None
        self.events_bus.emit(Events.GUI.INSERT_TEXT_TO_INPUT, {
            "text": text,
            "autosend_after": delay_sec if autosend else 0.0,
        })

    def _instant_send_policy(self) -> tuple[bool, float]:
        """(отправлять ли автоматически, пауза до отправки в секундах)."""
        if not bool(self.settings.get("MIC_INSTANT_SENT")):
            return False, 0.0
        if not bool(self.settings.get("MIC_INSTANT_SEND_DELAY_ENABLED", False)):
            return True, 0.0
        try:
            delay = float(self.settings.get("MIC_INSTANT_SEND_DELAY_SEC", 3.0) or 3.0)
        except (TypeError, ValueError):
            delay = 3.0
        return True, max(0.0, delay)

    def _player_turn_owner(self) -> str:
        """Сессия мода, которой принадлежит ход игрока ("" — ход у десктоп-чата).

        Ход у игры, когда связь жива и запросы игры не заглушены: при полной
        блокировке сервер отбросит create_task, порождённый автоотправкой,
        поэтому в таком режиме голос остаётся в десктоп-чате."""
        link = use(GameLinkService)
        if not link.is_connected():
            return ""
        if bool(self.settings.get("IGNORE_GAME_REQUESTS", False)) and (
            str(self.settings.get("GAME_BLOCK_LEVEL", "Idle events")) == "All events"
        ):
            return ""
        return link.player_turn_owner()

    def _send_instant(self, text, trace_id: str | None = None):
        # Через GUI-отправку, а не напрямую SEND_MESSAGE: так подхватываются
        # авто-захват экрана, прикреплённые и кадры камеры (иначе ASR-отправка
        # игнорировала изображения). GUI сам рисует сообщение пользователя.
        self.events_bus.emit(Events.GUI.SEND_TEXT_MESSAGE, {'text': text, 'trace_id': trace_id})

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

    # Команды START/STOP/RESTART меняют ЖЕЛАЕМОЕ состояние и будят реконсилятор,
    # а не дёргают движок сами. Прямой старт не знал текущего MIC_ACTIVE: пока
    # он ждал остановки, пользователь успевал выключить микрофон, реконсилятор
    # применял выключение — и протухшая команда поднимала распознавание при
    # снятом чекбоксе. Замок это не лечит: он выстраивает операции в очередь, но
    # не отменяет устаревшее намерение. Владелец жизненного цикла ровно один.
    def _set_mic_desired(self, active: bool) -> None:
        if not self.settings:
            return
        try:
            if bool(self.settings.get("MIC_ACTIVE", False)) != bool(active):
                self.settings.set("MIC_ACTIVE", bool(active))
                self.settings.save_settings()
        except Exception as e:
            logger.error(f"Не удалось записать MIC_ACTIVE={active}: {format_exception(e)}", exc_info=True)

    def _on_start_speech_recognition(self, event: Event):
        dev_id = (event.data or {}).get('device_id')
        if dev_id is not None:
            self.device_id = dev_id
        self._set_mic_desired(True)
        self._request_reconcile("explicit start")

    def _on_stop_speech_recognition(self, _event: Event):
        # Движок остановился сам (ошибка рантайма) или остановки просит внешний
        # код — в обоих случаях микрофон должен быть выключен и в настройках,
        # иначе чекбокс горит при мёртвом распознавании.
        self.mic_recognition_active = False
        self.asr_is_ready = False
        self._set_mic_desired(False)
        self._request_reconcile("explicit stop")

    def _on_restart_speech_recognition(self, event: Event):
        dev_id = (event.data or {}).get('device_id')
        if dev_id is not None:
            self.device_id = dev_id
        with self._state_lock:
            self._restart_requested = True
        self._request_reconcile("explicit restart")

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
                logger.error(f"Ошибка получения списка микрофонов: {format_exception(e)}")
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
            self._task_name("speech-background"),
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
                logger.error(f"GET_ASR_MODELS_GLOSSARY error: {format_exception(exc)}", exc_info=True)
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
