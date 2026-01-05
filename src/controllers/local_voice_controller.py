# File: src/controllers/local_voice_controller.py
import os
import sys
import uuid
import asyncio
from typing import Any, Dict, Optional

from main_logger import logger
from core.events import get_event_bus, Events, Event
from utils import getTranslationVariant as _


class LocalVoiceController:
    """
    Runtime controller for local voiceover.
    - owns LocalVoice runtime handler
    - handles Audio.LOCAL_SEND_VOICE_REQUEST, select/init/change language
    - provides GET_TRITON_STATUS / GET_ALL_LOCAL_MODEL_CONFIGS for UI/backends
    """

    def __init__(self, main_controller):
        self.main_controller = main_controller
        self.settings = main_controller.settings
        self.event_bus = get_event_bus()

        self._local_voice = None

        self._triton_status_cache: Optional[Dict[str, Any]] = None
        self._triton_check_error_logged: bool = False

        self._subscribe_to_events()
        logger.notify("LocalVoiceController успешно инициализирован.")

    def _get_local_voice(self):
        if self._local_voice is None:
            from handlers.local_voice_handler import LocalVoice
            self._local_voice = LocalVoice(self.main_controller)
        return self._local_voice

    def _subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Audio.OPEN_VOICE_MODEL_SETTINGS, self._on_open_voice_model_settings, weak=False)
        eb.subscribe(Events.Audio.GET_TRITON_STATUS, self._on_get_triton_status, weak=False)
        eb.subscribe(Events.Audio.REFRESH_TRITON_STATUS, self._on_refresh_triton_status, weak=False)
        eb.subscribe(Events.Audio.GET_ALL_LOCAL_MODEL_CONFIGS, self._on_get_all_local_model_configs, weak=False)

        eb.subscribe(Events.Audio.CHECK_MODEL_INSTALLED, self._on_check_model_installed, weak=False)
        eb.subscribe(Events.Audio.CHECK_MODEL_INITIALIZED, self._on_check_model_initialized, weak=False)
        eb.subscribe(Events.Audio.SELECT_VOICE_MODEL, self._on_select_voice_model, weak=False)
        eb.subscribe(Events.Audio.INIT_VOICE_MODEL, self._on_init_voice_model, weak=False)
        eb.subscribe(Events.Audio.CHANGE_VOICE_LANGUAGE, self._on_change_voice_language, weak=False)

        eb.subscribe(Events.Audio.LOCAL_SEND_VOICE_REQUEST, self._on_local_send_voice_request, weak=False)

    def _on_open_voice_model_settings(self, event: Event):
        try:
            return {'config_dir': "Settings", 'settings': self.settings}
        except Exception as e:
            logger.error(f"_on_open_voice_model_settings: {e}", exc_info=True)
            return None

    def _ensure_libs_on_path(self):
        lib_path = os.path.abspath("Lib")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

    def _compute_triton_status(self) -> dict:
        self._ensure_libs_on_path()
        self._triton_status_cache = None

        # Runtime-only probe: don't do UI here, just detect import and basic flags if available
        status = {
            "cuda_found": False,
            "winsdk_found": False,
            "msvc_found": False,
            "triton_installed": False,
            "triton_checks_performed": False,
        }

        try:
            import importlib
            importlib.invalidate_caches()
            import triton  # noqa: F401

            status["triton_installed"] = True

            if os.name == "nt":
                try:
                    from triton.windows_utils import find_cuda, find_winsdk, find_msvc
                    cuda_result = find_cuda()
                    if isinstance(cuda_result, (tuple, list)) and len(cuda_result) >= 1:
                        cuda_path = cuda_result[0]
                        status["cuda_found"] = bool(cuda_path and os.path.exists(str(cuda_path)))
                    winsdk_result = find_winsdk(False)
                    if isinstance(winsdk_result, (tuple, list)) and len(winsdk_result) >= 1:
                        winsdk_paths = winsdk_result[0]
                        status["winsdk_found"] = isinstance(winsdk_paths, list) and bool(winsdk_paths)
                    msvc_result = find_msvc(False)
                    cl_path = None
                    inc_paths, lib_paths = [], []
                    if isinstance(msvc_result, (tuple, list)):
                        if len(msvc_result) >= 1:
                            cl_path = msvc_result[0]
                        if len(msvc_result) >= 2:
                            inc_paths = msvc_result[1] or []
                        if len(msvc_result) >= 3:
                            lib_paths = msvc_result[2] or []
                    status["msvc_found"] = bool((cl_path and os.path.exists(str(cl_path))) or inc_paths or lib_paths)
                    status["triton_checks_performed"] = True
                except Exception as e:
                    if not self._triton_check_error_logged:
                        logger.warning(f"Triton dependency probe error: {e}")
                        self._triton_check_error_logged = True
        except Exception:
            pass

        self._triton_status_cache = status
        return status

    def _on_get_triton_status(self, event: Event):
        if self._triton_status_cache is not None:
            return self._triton_status_cache
        return self._compute_triton_status()

    def _on_refresh_triton_status(self, event: Event):
        return self._compute_triton_status()

    def _on_get_all_local_model_configs(self, event: Event):
        try:
            cfgs = self._get_local_voice().get_all_model_configs()
            if isinstance(cfgs, list) and cfgs:
                return cfgs
        except Exception as e:
            logger.warning(f"get_all_model_configs runtime error: {e}")

        # fallback: static configs (no runtime init required)
        
        logger.warning(f"ФОЛБЕК НА СТАТИКУ.")
        cfgs2 = self._get_static_model_configs()
        return cfgs2 if isinstance(cfgs2, list) else []

    def _on_check_model_installed(self, event: Event):
        model_id = (event.data or {}).get('model_id')
        try:
            return bool(self._get_local_voice().is_model_installed(model_id))
        except Exception:
            return False

    def _on_check_model_initialized(self, event: Event):
        model_id = (event.data or {}).get('model_id')
        try:
            return bool(self._get_local_voice().is_model_initialized(model_id))
        except Exception:
            return False

    def _on_select_voice_model(self, event: Event):
        model_id = (event.data or {}).get('model_id')
        if not model_id:
            return False
        try:
            lv = self._get_local_voice()
            lv.select_model(model_id)
            self.settings.set("NM_CURRENT_VOICEOVER", model_id)
            self.settings.save_settings()
            return True
        except Exception as e:
            logger.error(f'Не удалось активировать модель {model_id}: {e}', exc_info=True)
            return False

    def _on_init_voice_model(self, event: Event):
        model_id = (event.data or {}).get('model_id')
        progress_callback = (event.data or {}).get('progress_callback')
        if not model_id:
            return

        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
            'coroutine': self._async_init_model(str(model_id), progress_callback)
        })

    async def _async_init_model(self, model_id: str, progress_callback=None):
        try:
            if progress_callback:
                progress_callback("status", _("Инициализация модели...", "Initializing model..."))

            loop = asyncio.get_running_loop()
            lv = self._get_local_voice()

            ok = await loop.run_in_executor(None, lambda: lv.initialize_model(model_id, init=True))

            if ok:
                self.event_bus.emit(Events.Audio.FINISH_MODEL_LOADING, {'model_id': model_id})
            else:
                self.event_bus.emit(Events.Audio.UPDATE_MODEL_LOADING_STATUS, {'status': _("Ошибка инициализации!", "Initialization error!")})
                self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                    'title': _("Ошибка инициализации", "Initialization error"),
                    'message': _("Не удалось инициализировать модель. Проверьте логи.", "Failed to initialize model. Check logs.")
                })
                self.event_bus.emit(Events.Audio.CANCEL_MODEL_LOADING)
        except Exception as e:
            logger.error(f"init model failed: {e}", exc_info=True)
            self.event_bus.emit(Events.Audio.UPDATE_MODEL_LOADING_STATUS, {'status': _("Ошибка!", "Error!")})
            self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                'title': _("Ошибка", "Error"),
                'message': f"{_('Критическая ошибка при инициализации модели:', 'Critical init error:')} {e}"
            })
            self.event_bus.emit(Events.Audio.CANCEL_MODEL_LOADING)

    def _on_change_voice_language(self, event: Event):
        language = (event.data or {}).get('language')
        if not language:
            return False
        try:
            self._get_local_voice().change_voice_language(language)
            return True
        except Exception as e:
            logger.error(f"change language failed: {e}")
            return False

    def _on_local_send_voice_request(self, event: Event):
        data = event.data or {}
        text = data.get("text", "")
        future = data.get("future")

        character_id = data.get("character_id")
        voice_profile = data.get("voice_profile")

        if not text or future is None:
            return

        coro = self._async_local_voiceover(
            text=str(text),
            future=future,
            character_id=character_id,
            voice_profile=voice_profile,
        )

        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {"coroutine": coro})

    async def _async_local_voiceover(self, text: str, future, character_id: Optional[str] = None, voice_profile: Optional[dict] = None):
        try:
            resolved_profile = voice_profile if isinstance(voice_profile, dict) else None

            if not resolved_profile and isinstance(character_id, str) and character_id:
                character_res = self.event_bus.emit_and_wait(
                    Events.Character.GET,
                    {"character_id": character_id},
                    timeout=3.0
                )
                ch = character_res[0] if character_res else None
                if ch is not None and hasattr(ch, "to_voice_profile"):
                    resolved_profile = ch.to_voice_profile()

            if not resolved_profile:
                current_res = self.event_bus.emit_and_wait(
                    Events.Character.GET_CURRENT_PROFILE,
                    timeout=3.0
                )
                cc = current_res[0] if current_res else None
                if isinstance(cc, dict):
                    resolved_profile = cc

            output_file = f"MitaVoices/output_{uuid.uuid4()}.wav"
            absolute_audio_path = os.path.abspath(output_file)
            os.makedirs(os.path.dirname(absolute_audio_path), exist_ok=True)

            result_path = await self._get_local_voice().voiceover(
                text=text,
                output_file=absolute_audio_path,
                character=resolved_profile
            )

            if future and not future.done():
                if result_path:
                    future.set_result(result_path)
                else:
                    future.set_exception(Exception("Local voiceover failed: empty result"))
        except Exception as e:
            if future and not future.done():
                try:
                    future.set_exception(e)
                except Exception:
                    pass

    def _get_static_model_configs(self) -> list[dict]:
        cfgs: list[dict] = []

        def add_from(cls):
            try:
                items = getattr(cls, "MODEL_CONFIGS", None) or []
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict) and it.get("id"):
                            cfgs.append(it)
            except Exception:
                pass

        try:
            from handlers.voice_models.edge_tts_rvc_model import EdgeTTS_RVC_Model
            add_from(EdgeTTS_RVC_Model)
        except Exception:
            pass

        try:
            from handlers.voice_models.fish_speech_model import FishSpeechModel
            add_from(FishSpeechModel)
        except Exception:
            pass

        try:
            from handlers.voice_models.f5_tts_model import F5TTSModel
            add_from(F5TTSModel)
        except Exception:
            pass

        # unique by id
        out: list[dict] = []
        seen = set()
        for it in cfgs:
            mid = str(it.get("id") or "").strip()
            if not mid or mid in seen:
                continue
            out.append(it)
            seen.add(mid)
        return out