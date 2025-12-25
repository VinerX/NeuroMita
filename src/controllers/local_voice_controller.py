# File: src/controllers/local_voice_controller.py
import os
import sys
import uuid
import glob
import asyncio
import importlib
from typing import Any, Dict, List, Optional

from main_logger import logger
from core.events import get_event_bus, Events, Event
from handlers.local_voice_handler import LocalVoice


class LocalVoiceController:
    """
    Контроллер локальной озвучки (полная инкапсуляция LocalVoice).
    Аналог TelegramController: все операции выполняются по событиям EventBus.
    """
    def __init__(self, main_controller):
        self.main_controller = main_controller
        self.settings = main_controller.settings
        self.event_bus = get_event_bus()

        self.local_voice = LocalVoice(main_controller)

        self._triton_status_cache: Optional[Dict[str, Any]] = None  # +++
        self._triton_check_error_logged: bool = False               # +++
        self._triton_check_in_progress: bool = False                # +++

        self._subscribe_to_events()
        
        logger.info("LocalVoiceController начинает импорт модулей для озвучки...")
        try:
            # event не используется внутри _on_refresh_voice_modules
            self._on_refresh_voice_modules(event=None)
        except Exception as e:
            logger.warning(f"Первичный прогрев модулей локальной озвучки завершился с ошибкой: {e}")

        logger.notify("LocalVoiceController успешно инициализирован.")

    def _subscribe_to_events(self):
        eb = self.event_bus

        # Доступ к настройкам / окружению
        eb.subscribe(Events.Audio.OPEN_VOICE_MODEL_SETTINGS, self._on_open_voice_model_settings, weak=False)
        eb.subscribe(Events.Audio.GET_TRITON_STATUS, self._on_get_triton_status, weak=False)
        eb.subscribe(Events.Audio.REFRESH_VOICE_MODULES, self._on_refresh_voice_modules, weak=False)
        eb.subscribe(Events.Audio.GET_ALL_LOCAL_MODEL_CONFIGS, self._on_get_all_local_model_configs, weak=False)

        # ВАЖНО: НЕ подписываемся на VoiceModel.GET_MODEL_DATA и GET_DEPENDENCIES_STATUS,
        # чтобы не перехватывать данные для окна (иначе выпадают values в комбобоксах).
        # Оставляем только GET_INSTALLED_MODELS — нужно главному окну.
        eb.subscribe(Events.VoiceModel.GET_INSTALLED_MODELS, self._on_vm_get_installed_models, weak=False)

        # Управление моделями
        eb.subscribe(Events.Audio.CHECK_MODEL_INSTALLED, self._on_check_model_installed, weak=False)
        eb.subscribe(Events.Audio.CHECK_MODEL_INITIALIZED, self._on_check_model_initialized, weak=False)
        eb.subscribe(Events.Audio.SELECT_VOICE_MODEL, self._on_select_voice_model, weak=False)
        eb.subscribe(Events.Audio.INIT_VOICE_MODEL, self._on_init_voice_model, weak=False)
        eb.subscribe(Events.Audio.CHANGE_VOICE_LANGUAGE, self._on_change_voice_language, weak=False)

        # Установка/удаление (вызываются из GUI-контроллера окна настроек)
        eb.subscribe(Events.Audio.LOCAL_INSTALL_MODEL, self._on_local_install_model, weak=False)
        eb.subscribe(Events.Audio.LOCAL_UNINSTALL_MODEL, self._on_local_uninstall_model, weak=False)

        # Собственно озвучка
        eb.subscribe(Events.Audio.LOCAL_SEND_VOICE_REQUEST, self._on_local_send_voice_request, weak=False)

        eb.subscribe(Events.Audio.REFRESH_TRITON_STATUS, self._on_refresh_triton_status, weak=False)

    # ---------- Обработчики событий ----------

    def _on_open_voice_model_settings(self, event: Event):
        """
        GUI запрашивает данные для окна «Локальные модели».
        Возвращаем только данные, без LocalVoice-объекта (инкапсулируем).
        """
        try:
            return {
                'config_dir': "Settings",
                'settings': self.settings
            }
        except Exception as e:
            logger.error(f"_on_open_voice_model_settings: {e}", exc_info=True)
            return None

    def _ensure_libs_on_path(self):
        lib_path = os.path.abspath("Lib")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

    def _compute_triton_status(self) -> dict:
        self._ensure_libs_on_path()

        # сбрасываем кэш и пересчитываем флаги в модели
        self._triton_status_cache = None

        # гарантируем «чистое» исходное состояние
        try:
            self.local_voice.cuda_found = False
            self.local_voice.winsdk_found = False
            self.local_voice.msvc_found = False
            self.local_voice.triton_installed = False
            self.local_voice.triton_checks_performed = False
        except Exception:
            pass

        # пробуем импортировать triton и выполнить штатные проверки модели
        try:
            import importlib
            importlib.invalidate_caches()
            import triton  # noqa: F401
            # импорт успешен
            try:
                self.local_voice._check_system_dependencies()
            except Exception as e:
                if not self._triton_check_error_logged:
                    logger.warning(f"_check_system_dependencies error: {e}")
                    self._triton_check_error_logged = True
        except Exception:
            # triton не установлен — статус из модели (все False)
            pass

        status = {}
        try:
            status = self.local_voice.get_triton_status() or {}
        except Exception as e:
            logger.error(f"get_triton_status error: {e}")
            status = {}

        # кэшируем и отдаем
        self._triton_status_cache = status
        return status

    def _on_get_triton_status(self, event: Event):
        # отдаем кэш, если есть; иначе считаем
        if self._triton_status_cache is not None:
            return self._triton_status_cache
        return self._compute_triton_status()

    def _on_refresh_triton_status(self, event: Event):
        # принудительный пересчет, игнорируем кэш
        return self._compute_triton_status()
    
    def _on_refresh_voice_modules(self, event: Event):
        logger.info("Обновление модулей локальной озвучки...")
        modules_to_check = {
            "tts_with_rvc": "TTS_RVC",
            "fish_speech_lib.inference": "FishSpeech",
            "f5_tts": None,
            "triton": None
        }

        lib_path = os.path.abspath("Lib")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        for module_name, class_name in modules_to_check.items():
            try:
                if module_name in sys.modules:
                    logger.debug(f"Перезагрузка модуля: {module_name}")
                    importlib.reload(sys.modules[module_name])
                else:
                    logger.debug(f"Импорт модуля: {module_name}")
                    importlib.import_module(module_name)

                if class_name:
                    actual_class = getattr(sys.modules[module_name], class_name)
                    if module_name == "tts_with_rvc":
                        self.local_voice.tts_rvc_module = actual_class
                    elif module_name == "fish_speech_lib.inference":
                        self.local_voice.fish_speech_module = actual_class

                logger.info(f"Модуль {module_name} успешно обработан.")
            except ImportError:
                logger.warning(f"Модуль {module_name} не найден или не установлен.")
                if module_name == "tts_with_rvc":
                    self.local_voice.tts_rvc_module = None
                elif module_name == "fish_speech_lib.inference":
                    self.local_voice.fish_speech_module = None
            except Exception as e:
                logger.error(f"Ошибка при обработке модуля {module_name}: {e}", exc_info=True)

        # Инвалидация кэшей
        self._triton_status_cache = None
        self._triton_check_error_logged = False
        self._installed_models_cache = None
        self._installed_models_cache_ts = 0.0

        self.event_bus.emit(Events.GUI.CHECK_TRITON_DEPENDENCIES)


    def _on_get_all_local_model_configs(self, event: Event):
        try:
            return self.local_voice.get_all_model_configs()
        except Exception as e:
            logger.error(f"Ошибка получения списка конфигураций моделей: {e}")
            return []

    # ---- VoiceModel.*: только INSTALLED для главного окна ----

    def _on_vm_get_installed_models(self, event: Event):
        import time as _time

        # Ленивая инициализация полей кэша
        if not hasattr(self, "_installed_models_cache"):
            self._installed_models_cache = None
            self._installed_models_cache_ts = 0.0

        # Отдаём кэш, если он свежий (сильно снижает дергание is_installed())
        if self._installed_models_cache is not None and (_time.time() - self._installed_models_cache_ts) < 2.0:
            return set(self._installed_models_cache)

        installed = set()
        try:
            for m in self.local_voice.get_all_model_configs():
                mid = m.get("id")
                if not mid:
                    continue
                try:
                    if self.local_voice.is_model_installed(mid):
                        installed.add(mid)
                except Exception as e:
                    logger.error(f"_on_vm_get_installed_models: {e}", exc_info=False)
        except Exception as e:
            logger.error(f"_on_vm_get_installed_models: {e}", exc_info=True)

        # Кэшируем результат
        self._installed_models_cache = installed.copy()
        self._installed_models_cache_ts = _time.time()
        return installed

    # ---- Прочие хендлеры ----

    def _on_check_model_installed(self, event: Event):
        model_id = event.data.get('model_id')
        if model_id and self.local_voice:
            return self.local_voice.is_model_installed(model_id)
        return False

    def _on_check_model_initialized(self, event: Event):
        model_id = event.data.get('model_id')
        if model_id and self.local_voice:
            return self.local_voice.is_model_initialized(model_id)
        return False

    def _on_select_voice_model(self, event: Event):
        model_id = event.data.get('model_id')
        if model_id and self.local_voice:
            try:
                self.local_voice.select_model(model_id)
                self.settings.set("NM_CURRENT_VOICEOVER", model_id)
                self.settings.save_settings()
                return True
            except Exception as e:
                logger.error(f'Не удалось активировать модель {model_id}: {e}')
                return False
        return False

    def _on_init_voice_model(self, event: Event):
        model_id = event.data.get('model_id')
        progress_callback = event.data.get('progress_callback')

        if not model_id:
            return

        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
            'coroutine': self._async_init_model(model_id, progress_callback)
        })

    async def _async_init_model(self, model_id: str, progress_callback=None):
        try:
            if progress_callback:
                progress_callback("status", "Инициализация модели...")

            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                None,
                self.local_voice.initialize_model,
                model_id,
                True
            )
            if success:
                self.event_bus.emit(Events.Audio.FINISH_MODEL_LOADING, {
                    'model_id': model_id
                })
            else:
                self.event_bus.emit(Events.Audio.UPDATE_MODEL_LOADING_STATUS, {
                    'status': "Ошибка инициализации!"
                })
                self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                    'title': "Ошибка инициализации",
                    'message': "Не удалось инициализировать модель. Проверьте логи."
                })
                self.event_bus.emit(Events.Audio.CANCEL_MODEL_LOADING)

        except Exception as e:
            logger.error(f"Ошибка при инициализации модели {model_id}: {e}", exc_info=True)
            self.event_bus.emit(Events.Audio.UPDATE_MODEL_LOADING_STATUS, {
                'status': "Ошибка!"
            })
            self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                'title': "Ошибка",
                'message': f"Критическая ошибка при инициализации модели: {e}"
            })
            self.event_bus.emit(Events.Audio.CANCEL_MODEL_LOADING)

    def _on_change_voice_language(self, event: Event):
        language = event.data.get('language')
        if language and hasattr(self.local_voice, 'change_voice_language'):
            try:
                self.local_voice.change_voice_language(language)
                return True
            except Exception as e:
                logger.error(f"Ошибка при изменении языка озвучки: {e}")
                return False
        return False

    def _on_local_install_model(self, event: Event):
        data = event.data or {}
        model_id = data.get('model_id')
        progress_cb = data.get('progress_callback')
        status_cb = data.get('status_callback')
        log_cb = data.get('log_callback')

        # Инвалидируем кэш установленных перед установкой (будет пересчитан)
        self._installed_models_cache = None
        self._installed_models_cache_ts = 0.0

        try:
            ok = self.local_voice.download_model(
                model_id, progress_cb, status_cb, log_cb
            )
            return ok
        except Exception as e:
            logger.error(f"Ошибка установки модели {model_id}: {e}", exc_info=True)
            if log_cb:
                log_cb(f"Ошибка: {e}")
            return False

    def _on_local_uninstall_model(self, event: Event):
        data = event.data or {}
        model_id = data.get('model_id')
        status_cb = data.get('status_callback')
        log_cb = data.get('log_callback')

        # Инвалидируем кэш установленных перед удалением
        self._installed_models_cache = None
        self._installed_models_cache_ts = 0.0

        try:
            ok = self.local_voice.uninstall_model(model_id, status_cb, log_cb)
            return ok
        except Exception as e:
            logger.error(f"Ошибка удаления модели {model_id}: {e}", exc_info=True)
            if log_cb:
                log_cb(f"Ошибка: {e}")
            return False

    def _on_local_send_voice_request(self, event: Event):
        data = event.data or {}
        text = data.get('text', '')
        future = data.get('future')

        if not text or not future:
            if future and not future.done():
                future.set_exception(Exception("Invalid voice request arguments"))
            return

        coro = self._async_local_voiceover(text, future)

        def handle_result(result, error):
            if error and future and not future.done():
                future.set_exception(error)

        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
            'coroutine': coro,
            'callback': handle_result
        })

    async def _async_local_voiceover(self, text: str, future):
        try:
            character_result = self.event_bus.emit_and_wait(Events.Model.GET_CURRENT_CHARACTER, timeout=3.0)
            character = character_result[0] if character_result else None

            output_file = f"MitaVoices/output_{uuid.uuid4()}.wav"
            absolute_audio_path = os.path.abspath(output_file)
            os.makedirs(os.path.dirname(absolute_audio_path), exist_ok=True)

            logger.notify(f"Локальная озвучка текста: {text[:50]}...")

            result_path = await self.local_voice.voiceover(
                text=text,
                output_file=absolute_audio_path,
                character=character
            )

            if future and not future.done():
                if result_path:
                    future.set_result(result_path)
                else:
                    future.set_exception(Exception("Local voiceover failed: empty result"))

        except Exception as e:
            #logger.error(f"Ошибка локальной озвучки: {e}", exc_info=False)
            if future and not future.done():
                future.set_exception(e)