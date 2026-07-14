import os
import uuid
import asyncio
from typing import Any, Dict, Optional

from main_logger import logger
from core.events import get_event_bus, Events, Event
from core.services import use
from services.contracts import (
    CharacterRegistry,
    InstallableCatalogService,
    LocalVoiceService,
    LoopService,
    SettingsService,
)
from utils import getTranslationVariant as _


class LocalVoiceController(LocalVoiceService):
    """
    GUI-side proxy для локальной озвучки.
    Вся тяжёлая часть живёт в ai worker service='tts'.
    """

    def __init__(self):
        self.event_bus = get_event_bus()

        self._engine = None

        self._model_configs_cache: Optional[list] = None
        self._installed_cache: Dict[str, bool] = {}
        self._initialized_cache: Dict[str, bool] = {}

        self._triton_status_cache: Optional[Dict[str, Any]] = None

        self._subscribe_to_events()
        logger.notify("LocalVoiceController успешно инициализирован (engine-proxy).")

        try:
            eng = self._get_engine()
            if eng:
                eng.call("tts", "ping", {})
        except Exception:
            pass

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        # Через AIEngineService, а не через синхронный EventBus-запрос (см. rag_client/beat_worker).
        try:
            from services.contracts import AIEngineService
            self._engine = use(AIEngineService).get_engine()
        except Exception:
            self._engine = None
        return self._engine

    def _get_setting(self, key: str, default=None):
        return use(SettingsService).get(key, default)

    def _get_settings_obj(self):
        return use(SettingsService)

    def _save_setting(self, key: str, value: Any) -> None:
        use(SettingsService).update(key, value)

    def _subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Audio.OPEN_VOICE_MODEL_SETTINGS, self._on_open_voice_model_settings, weak=False)
        eb.subscribe(Events.Audio.REFRESH_TRITON_STATUS, self._on_refresh_triton_status, weak=False)

        eb.subscribe(Events.Audio.CHECK_MODEL_INSTALLED, self._on_check_model_installed, weak=False)
        eb.subscribe(Events.Audio.CHECK_MODEL_INITIALIZED, self._on_check_model_initialized, weak=False)
        eb.subscribe(Events.Audio.SELECT_VOICE_MODEL, self._on_select_voice_model, weak=False)
        eb.subscribe(Events.Audio.CHANGE_VOICE_LANGUAGE, self._on_change_voice_language, weak=False)

        eb.subscribe(Events.AI.SERVICE_RESTARTED, self._on_ai_service_restarted, weak=False)

    def _on_open_voice_model_settings(self, _event: Event):
        st = self._get_settings_obj()
        if st is None:
            return None
        return {"config_dir": "Settings", "settings": st}

    def _voice_language(self) -> str:
        return str(self._get_setting("VOICE_LANGUAGE", "ru") or "ru").strip().lower()

    async def _ensure_model_environment(
        self,
        model_id: str,
        *,
        initialize: bool = False,
    ) -> None:
        engine = self._get_engine()
        activate = getattr(engine, "activate_environment", None) if engine is not None else None
        if not callable(activate):
            raise RuntimeError("AI engine does not support managed runtime environments")
        validation_method = "init_model" if initialize else None
        validation_payload = (
            {"model_id": str(model_id), "warmup": True}
            if initialize
            else None
        )
        ok = await asyncio.to_thread(
            activate,
            "tts",
            str(model_id),
            category="tts",
            timeout=20.0,
            validation_method=validation_method,
            validation_payload=validation_payload,
            validation_timeout=3600.0 if initialize else 20.0,
        )
        if not ok:
            raise RuntimeError(f"Failed to activate runtime environment for voice model '{model_id}'")

    async def _engine_call_async(self, method: str, payload: Optional[dict] = None, timeout: Optional[float] = None):
        eng = self._get_engine()
        if eng is None:
            raise RuntimeError("AI engine not available")

        fut = eng.call("tts", method, payload or {})
        return await asyncio.wait_for(asyncio.wrap_future(fut), timeout=timeout)

    def model_configs(self) -> list[dict[str, Any]]:
        return list(self._on_get_all_local_model_configs(Event(Events.Audio.GET_ALL_LOCAL_MODEL_CONFIGS)) or [])

    def is_installed(self, model_id: str) -> bool:
        return bool(self._on_check_model_installed(Event(Events.Audio.CHECK_MODEL_INSTALLED, {"model_id": model_id})))

    def check_initialized(self, model_id: str, *, strict: bool = False) -> bool:
        return bool(self._on_check_model_initialized(Event(Events.Audio.CHECK_MODEL_INITIALIZED, {"model_id": model_id, "strict": strict})))

    def select_model(self, model_id: str) -> bool:
        return bool(self._on_select_voice_model(Event(Events.Audio.SELECT_VOICE_MODEL, {"model_id": model_id})))

    def initialize_model(self, model_id: str):
        normalized = str(model_id or "").strip()
        if not normalized:
            raise ValueError("model_id is required")
        return use(LoopService).run(self._async_init_model(normalized))

    def triton_status(self, *, refresh: bool = False) -> dict[str, Any]:
        event = Event(Events.Audio.REFRESH_TRITON_STATUS if refresh else Events.Audio.GET_TRITON_STATUS)
        handler = self._on_refresh_triton_status if refresh else self._on_get_triton_status
        result = handler(event)
        return dict(result or {})

    # -------------------- model configs --------------------

    def _on_get_all_local_model_configs(self, _event: Event):
        if self._model_configs_cache is not None:
            return self._model_configs_cache

        try:
            eng = self._get_engine()
            if not eng:
                return []
            cfut = eng.call("tts", "list_models", {"voice_language": self._voice_language()})

            def _done(f):
                try:
                    cfgs = f.result()
                    if isinstance(cfgs, list):
                        self._model_configs_cache = cfgs
                        self.event_bus.emit(Events.GUI.VOICEOVER_REFRESH)
                except Exception:
                    pass

            cfut.add_done_callback(_done)
        except Exception:
            pass

        return []

    # -------------------- installed/initialized checks --------------------

    def _on_check_model_installed(self, event: Event):
        model_id = str((event.data or {}).get("model_id") or "").strip()
        if not model_id:
            return False

        try:
            ready = bool(use(InstallableCatalogService).is_ready(f"tts:{model_id}"))
        except Exception:
            ready = False
        self._installed_cache[model_id] = ready
        return ready

    def _on_check_model_initialized(self, event: Event):
        model_id = str((event.data or {}).get("model_id") or "").strip()
        if not model_id:
            return False

        strict = bool((event.data or {}).get("strict", False))

        cached = self._initialized_cache.get(model_id)
        if cached is not None and not strict:
            return bool(cached)

        eng = self._get_engine()
        if not eng:
            return False if strict else (bool(cached) if cached is not None else False)

        if strict:
            try:
                f = eng.call("tts", "check_initialized", {"model_id": model_id})
                ok = bool(f.result(timeout=1.0))
                self._initialized_cache[model_id] = ok
                return ok
            except Exception:
                self._initialized_cache[model_id] = False
                return False

        try:
            cfut = eng.call("tts", "check_initialized", {"model_id": model_id})

            def _done(f):
                try:
                    ok = bool(f.result())
                    self._initialized_cache[model_id] = ok
                    self.event_bus.emit(Events.GUI.VOICEOVER_REFRESH)
                except Exception:
                    self._initialized_cache.setdefault(model_id, False)

            cfut.add_done_callback(_done)
        except Exception:
            pass

        return bool(cached) if cached is not None else False

    # -------------------- select/init/lang --------------------

    def _on_select_voice_model(self, event: Event):
        model_id = str((event.data or {}).get("model_id") or "").strip()
        if not model_id:
            return False

        self._save_setting("NM_CURRENT_VOICEOVER", model_id)

        self._initialized_cache.pop(model_id, None)
        return True

    async def _async_init_model(self, model_id: str):
        try:
            logger.info(f"LocalVoiceController init start: model_id='{model_id}'")
            self.event_bus.emit(
                Events.Audio.UPDATE_MODEL_LOADING_STATUS,
                {"status": _("Инициализация модели...", "Initializing model...")},
            )

            await self._ensure_model_environment(model_id, initialize=True)
            ok = True

            if ok:
                logger.info(f"LocalVoiceController init done: model_id='{model_id}'")
                self._initialized_cache[model_id] = True
                self.event_bus.emit(Events.Audio.FINISH_MODEL_LOADING, {"model_id": model_id})
            else:
                logger.error(f"LocalVoiceController init failed: model_id='{model_id}'")
                self._initialized_cache[model_id] = False
                self.event_bus.emit(Events.Audio.UPDATE_MODEL_LOADING_STATUS, {
                    "status": _("Ошибка инициализации!", "Initialization error!")
                })
                self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                    "title": _("Ошибка инициализации", "Initialization error"),
                    "message": _(
                        "Не удалось инициализировать модель {}. Причина записана в логах TTS/инициализации.",
                        "Failed to initialize model {}. The reason was written to the TTS/init logs."
                    ).format(model_id)
                })
                self.event_bus.emit(Events.Audio.CANCEL_MODEL_LOADING)

        except Exception as e:
            logger.error(f"init model failed (tts engine): {e}", exc_info=True)
            self._initialized_cache[model_id] = False
            self.event_bus.emit(Events.Audio.UPDATE_MODEL_LOADING_STATUS, {"status": _("Ошибка!", "Error!")})
            self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                "title": _("Ошибка", "Error"),
                "message": f"{_('Критическая ошибка при инициализации модели:', 'Critical init error:')} {e}"
            })
            self.event_bus.emit(Events.Audio.CANCEL_MODEL_LOADING)

    def _on_change_voice_language(self, event: Event):
        language = str((event.data or {}).get("language") or "").strip().lower()
        if not language:
            return False

        self._save_setting("VOICE_LANGUAGE", language)

        try:
            eng = self._get_engine()
            if eng:
                eng.call("tts", "set_language", {"voice_language": language})
        except Exception:
            pass

        self._model_configs_cache = None
        self._initialized_cache.clear()
        return True

    # -------------------- triton status --------------------

    def _default_triton_status(self):
        return {
            "cuda_found": False,
            "winsdk_found": False,
            "msvc_found": False,
            "triton_installed": False,
            "triton_checks_performed": False,
        }

    def _on_get_triton_status(self, _event: Event):
        if self._triton_status_cache is not None:
            return self._triton_status_cache

        try:
            eng = self._get_engine()
            if not eng:
                return self._default_triton_status()

            cfut = eng.call("tts", "get_triton_status", {})

            def _done(f):
                try:
                    st = f.result()
                    if isinstance(st, dict):
                        self._triton_status_cache = st
                except Exception:
                    pass

            cfut.add_done_callback(_done)
        except Exception:
            pass

        return self._default_triton_status()

    def _on_refresh_triton_status(self, _event: Event):
        self._triton_status_cache = None
        try:
            eng = self._get_engine()
            if eng:
                cfut = eng.call("tts", "refresh_triton_status", {})

                def _done(f):
                    try:
                        st = f.result()
                        if isinstance(st, dict):
                            self._triton_status_cache = st
                    except Exception:
                        pass

                cfut.add_done_callback(_done)
        except Exception:
            pass

        return self._on_get_triton_status(_event)

    # -------------------- voiceover request --------------------

    def _on_ai_service_restarted(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        if str(data.get("service") or "").strip().lower() != "tts":
            return

        ok = bool(data.get("ok", False))

        self._model_configs_cache = None
        self._installed_cache.clear()
        self._initialized_cache.clear()
        self._triton_status_cache = None

        self._engine = None

        # Пересинхронизируем UI
        self.event_bus.emit(Events.GUI.VOICEOVER_REFRESH)

        if not ok:
            logger.warning(f"TTS engine restart reported failure: {data.get('error')}")

    def _on_local_send_voice_request(self, event: Event):
        data = event.data or {}
        text = str(data.get("text") or "")
        future = data.get("future")

        character_id = data.get("character_id")
        voice_profile = data.get("voice_profile")

        if not text or future is None:
            return

        coro = self._async_local_voiceover(
            text=text,
            future=future,
            character_id=character_id,
            voice_profile=voice_profile,
        )
        use(LoopService).run(coro)

    async def synthesize(
        self,
        text: str,
        *,
        character_id: Optional[str] = None,
        voice_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        resolved_profile = voice_profile if isinstance(voice_profile, dict) else None
        registry = use(CharacterRegistry)

        if not resolved_profile and isinstance(character_id, str) and character_id:
            character = registry.get(character_id)
            if character is not None and hasattr(character, "to_voice_profile"):
                resolved_profile = character.to_voice_profile()
        if not resolved_profile:
            resolved_profile = registry.current_profile() or None

        output_file = f"MitaVoices/output_{uuid.uuid4()}.wav"
        absolute_audio_path = os.path.abspath(output_file)
        os.makedirs(os.path.dirname(absolute_audio_path), exist_ok=True)
        model_id = str(self._get_setting("NM_CURRENT_VOICEOVER", "") or "").strip() or "low"

        initialize = not bool(self._initialized_cache.get(model_id, False))
        await self._ensure_model_environment(model_id, initialize=initialize)
        if initialize:
            self._initialized_cache[model_id] = True
        result_path = await self._engine_call_async(
            "synthesize",
            {
                "text": text,
                "output_file": absolute_audio_path,
                "character": resolved_profile,
                "model_id": model_id,
            },
            timeout=3600.0,
        )
        if not result_path:
            raise RuntimeError("Local voiceover failed: empty result")
        return str(result_path)

    async def _async_local_voiceover(
        self,
        text: str,
        future,
        character_id: Optional[str] = None,
        voice_profile: Optional[dict] = None,
    ):
        try:
            result = await self.synthesize(
                text, character_id=character_id, voice_profile=voice_profile
            )
            if future and not future.done():
                future.set_result(result)
        except Exception as exc:
            if future and not future.done():
                try:
                    future.set_exception(exc)
                except Exception:
                    pass
