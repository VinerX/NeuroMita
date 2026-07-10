from __future__ import annotations

import threading

from main_logger import logger
from core.events import get_event_bus, Events, Event, shutdown_event_bus
from core.app_paths import settings_dir, settings_path
from core.executors import executors
from startup.startup_profiler import startup_trace
from core.services import services
from services.character_registry import SettingsOnlyCharacterRegistry
from services.contracts import (
    AIEngineService,
    ApiPresetService,
    AppVarsService,
    CharacterRegistry,
    EmbeddingPresetService,
    EmbeddingService,
    GameLinkService,
    LoopService,
    ProtocolBuilderService,
    SettingsService,
    TaskService,
    TelegramService,
)
from services.game_link_service import DisconnectedGameLinkService, ServerGameLinkService
from services.loop_service import NoLoopService
from services.telegram_service import UnavailableTelegramService
from services.settings_service import DefaultAppVarsService



class MainController:
    def __init__(
        self,
        view,
        startup_mode: str = "full",
        settings_controller: SettingsController | None = None,
    ):
        startup_trace.mark("controller.main.start", startup_mode=startup_mode)
        self.view = view
        self.event_bus = get_event_bus()
        self.startup_mode = self._normalize_startup_mode(startup_mode)
        self.backend_enabled = self.startup_mode in {"full", "headless"}
        self.headless = self.startup_mode == "headless"

        self.dialog_active = False
        self._close_lock = threading.Lock()
        self._closing_started = False
        self.gui_fallback_controller = None

        self.loop_controller = None
        self.gui_controller = None
        self.telegram_controller = None

        target_folder = str(settings_dir(create=True))
        self.config_path = str(settings_path("settings.json", create_parent=True))

        # Композиционный корень: инфраструктурные сервисы регистрируются
        # в порядке зависимостей до создания остальных контроллеров.
        if settings_controller is None:
            from controllers.settings_controller import SettingsController

            settings_controller = SettingsController(self.config_path)
        self.settings_controller = settings_controller
        self.settings = self.settings_controller.settings
        startup_trace.mark("controller.settings.ready")
        settings_service = services().get(SettingsService)

        if self.backend_enabled:
            self.game_link = ServerGameLinkService()
        else:
            self.game_link = DisconnectedGameLinkService()
        services().register(GameLinkService, self.game_link, replace=True)
        services().register(
            AppVarsService, DefaultAppVarsService(settings_service, self.game_link), replace=True
        )

        if not self.backend_enabled:
            services().register(LoopService, NoLoopService(), replace=True)
            services().register(
                CharacterRegistry, SettingsOnlyCharacterRegistry(settings_service), replace=True
            )
            from controllers.gui_fallback_controller import GuiFallbackController

            self.gui_fallback_controller = GuiFallbackController(self.settings)
            logger.notify("GuiFallbackController initialized.")
            self._subscribe_to_events()
            logger.notify("MainController initialized in GUI-only mode.")
            return

        from controllers.ai_engine_controller import AIEngineController
        from controllers.api_presets_controller import ApiPresetsController
        from controllers.capture_controller import CaptureController
        from controllers.character_controller import CharacterController
        from controllers.chat_controller import ChatController
        from controllers.embedding_controller import EmbeddingController
        from controllers.embedding_presets_controller import EmbeddingPresetsController
        from controllers.graph_controller import GraphController
        from controllers.history_controller import HistoryController
        from controllers.install_controller import InstallController
        from controllers.installable_controller import InstallableController
        from controllers.local_voice_controller import LocalVoiceController
        from controllers.loop_controller import LoopController
        from controllers.model_controller import ModelController
        from controllers.prompt_controller import PromptController
        from controllers.protocols_controller import ProtocolsController
        from controllers.task_controller import TaskController
        from controllers.voice_model_controller import VoiceModelController
        from utils.pip_installer import PipInstaller

        self.loop_controller = LoopController()
        logger.notify("LoopController initialized.")
        self.telegram_controller = None
        try:
            from controllers.telegram_controller import TelegramController

            self.telegram_controller = TelegramController()
            services().register(TelegramService, self.telegram_controller, replace=True)
            logger.notify("TelegramController initialized.")
        except Exception as exc:
            services().register(
                TelegramService,
                UnavailableTelegramService(str(exc)),
                replace=True,
            )
            logger.warning(f"Telegram disabled: {exc}")

        try:
            self.pip_installer = PipInstaller(
                update_log=logger.info
            )
            logger.notify("PipInstaller успешно инициализирован.")
        except Exception as e:
            logger.error(f"Не удалось инициализировать PipInstaller: {e}", exc_info=True)
            self.pip_installer = None

        self._check_and_perform_pending_update()

        self.install_controller = InstallController()
        logger.notify("InstallController успешно инициализирован.")

        self.installable_controller = InstallableController()
        logger.notify("InstallableController initialized.")

        startup_trace.mark("controller.ai_engine.start")
        self.ai_engine_controller = AIEngineController()
        startup_trace.mark("controller.ai_engine.created")
        services().register(AIEngineService, self.ai_engine_controller, replace=True)
        logger.notify(
            f"AIEngineController успешно инициализирован (mode={getattr(self.ai_engine_controller, 'mode', 'unknown')})."
        )

        self.local_voice_controller = LocalVoiceController()
        logger.notify("LocalVoiceController успешно инициализирован.")

        self.task_controller = TaskController()
        services().register(TaskService, self.task_controller, replace=True)
        logger.notify("TaskController успешно инициализирован.")

        self.history_controller = HistoryController()
        logger.notify("HistoryController успешно инициализирован.")

        self.graph_controller = GraphController()
        logger.notify("GraphController успешно инициализирован.")

        self.prompt_controller = PromptController()
        logger.notify("PromptController успешно инициализирован.")

        self.protocols_controller = ProtocolsController()
        services().register(ProtocolBuilderService, self.protocols_controller, replace=True)
        logger.notify("ProtocolsController успешно инициализирован.")

        self.api_presets_controller = ApiPresetsController()
        services().register(ApiPresetService, self.api_presets_controller, replace=True)
        logger.notify("ApiPresetsController успешно инициализирован.")

        self.embedding_presets_controller = EmbeddingPresetsController()
        services().register(EmbeddingPresetService, self.embedding_presets_controller, replace=True)
        logger.notify("EmbeddingPresetsController успешно инициализирован.")

        self.audio_controller = None
        try:
            from controllers.audio_controller import AudioController

            self.audio_controller = AudioController(self)
            logger.notify("AudioController успешно инициализирован.")
        except Exception as exc:
            logger.warning(f"Audio playback disabled: {exc}")

        self.voice_model_controller = VoiceModelController(config_dir=target_folder)
        logger.notify("VoiceModelController (backend) успешно инициализирован.")

        startup_trace.mark("controller.characters.start")
        self.character_controller = CharacterController(self.settings)
        startup_trace.mark(
            "controller.characters.ready",
            loaded=len(self.character_controller.character_manager.characters),
        )
        logger.notify("CharacterController успешно инициализирован.")

        startup_trace.mark("controller.model.start")
        self.model_controller = ModelController(self.settings)
        startup_trace.mark("controller.model.ready")
        logger.notify("ModelController успешно инициализирован.")

        self.embedding_controller = EmbeddingController()
        services().register(EmbeddingService, self.embedding_controller, replace=True)
        logger.notify("EmbeddingController успешно инициализирован.")

        self.capture_controller = CaptureController(self.settings)
        logger.notify("CaptureController успешно инициализирован.")

        from controllers.reminder_controller import ReminderController
        self.reminder_controller = ReminderController(
            self.settings,
            character_resources=self.character_controller.character_manager.resources,
        )
        logger.notify("ReminderController успешно инициализирован.")

        self.speech_controller = None
        try:
            from controllers.speech_controller import SpeechController

            self.speech_controller = SpeechController()
            logger.notify("SpeechController успешно инициализирован.")
        except Exception as exc:
            logger.warning(f"Speech recognition disabled: {exc}")

        startup_trace.mark("controller.server.start")
        self._init_server_controller()
        startup_trace.mark("controller.server.ready")

        self.chat_controller = ChatController(self.settings)
        logger.notify("ChatController успешно инициализирован.")

        audio_controller = getattr(self, "audio_controller", None)
        if audio_controller is not None:
            audio_controller.delete_all_sound_files()

        self._subscribe_to_events()
        if self.headless:
            self.settings_controller.load_api_settings(False)
        logger.notify("MainController подписался на события")
        startup_trace.mark("controller.main.ready", headless=self.headless)
        startup_trace.write()

    @staticmethod
    def _normalize_startup_mode(startup_mode: str | None) -> str:
        mode = str(startup_mode or "full").strip().lower()
        if mode in {"gui-only", "gui_only", "ui-only", "ui_only"}:
            return "gui_only"
        if mode in {"headless", "server", "server-only", "server_only", "no-gui", "no_gui"}:
            return "headless"
        return "full"

    def _init_server_controller(self):
        # Старый серверный API (ServerControllerOld / server_old.py) удалён —
        # всегда используем новый. Настройка USE_NEW_API больше ни на что не
        # влияет и оставлена только для совместимости со старыми settings.json.
        if getattr(self, 'server_controller', None):
            return

        from controllers.server_controller import ServerController

        self.server_controller = ServerController(self.game_link)
        logger.notify("ServerController (новый API) успешно инициализирован.")

    def update_view(self, view):
        if self.headless:
            raise RuntimeError("Headless runtime does not support GUI attachment")
        if not self.gui_controller:
            from controllers.gui_controller import GuiController

            self.view = view
            try:
                setattr(view, "main_controller", self)
                setattr(view, "backend_enabled", bool(self.backend_enabled))
                setattr(view, "startup_mode", self.startup_mode)
            except Exception:
                pass
            self.gui_controller = GuiController(self, view)
            setattr(view, "backend_ready", True)
            setattr(view, "backend_startup_error", "")
            try:
                from ui.widgets.chat_panel import update_send_button_state

                update_send_button_state(view)
            except Exception:
                pass
            logger.notify("GuiController успешно инициализирован.")
            if self.backend_enabled:
                self.settings_controller.load_api_settings(False)

            self.event_bus.emit(Events.GUI.VOICEOVER_REFRESH)


    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Model.SCHEDULE_G4F_UPDATE, self._on_schedule_g4f_update, weak=False)

        self.event_bus.subscribe(Events.Telegram.REQUEST_TG_CODE, self._on_request_tg_code, weak=False)
        self.event_bus.subscribe(Events.Telegram.REQUEST_TG_PASSWORD, self._on_request_tg_password, weak=False)

        self.event_bus.subscribe(Events.GUI.SHOW_LOADING_POPUP, self._on_show_loading_popup, weak=False)
        self.event_bus.subscribe(Events.GUI.CLOSE_LOADING_POPUP, self._on_close_loading_popup, weak=False)

        self.event_bus.subscribe(Events.Server.SET_DIALOG_ACTIVE, self._on_set_dialog_active, weak=False)

    def close_app(self):
        with self._close_lock:
            if self._closing_started:
                return
            self._closing_started = True

        logger.info("Начинаем закрытие приложения...")

        def shutdown_step(name: str, callback) -> None:
            try:
                callback()
            except Exception as exc:
                logger.error(f"Ошибка при остановке {name}: {exc}", exc_info=True)

        if self.event_bus is not None:
            shutdown_step(
                "speech recognition",
                lambda: self.event_bus.emit(Events.Speech.STOP_SPEECH_RECOGNITION, sync=True),
            )

        server_controller = getattr(self, "server_controller", None)
        if server_controller is not None:
            shutdown_step("server", server_controller.destroy)

        capture_controller = getattr(self, "capture_controller", None)
        if capture_controller is not None:
            shutdown_step("capture controller", capture_controller.shutdown)

        ai_engine = getattr(self, "ai_engine_controller", None)
        if ai_engine is not None:
            shutdown_step("AI engine", lambda: ai_engine.shutdown(timeout=5.0))

        audio_controller = getattr(self, "audio_controller", None)
        if audio_controller is not None:
            shutdown_step("audio cleanup", audio_controller.delete_all_sound_files)

        loop_controller = getattr(self, "loop_controller", None)
        if loop_controller is not None:
            shutdown_step("async loop", loop_controller.stop_loop)

        character_controller = getattr(self, "character_controller", None)
        character_manager = getattr(character_controller, "character_manager", None)
        if character_manager is not None:
            shutdown_step("character resources", character_manager.shutdown)

        settings = getattr(self, "settings", None)
        close_settings = getattr(settings, "close", None)
        if callable(close_settings):
            shutdown_step("settings writer", close_settings)

        shutdown_step("EventBus", shutdown_event_bus)
        shutdown_step("executor pools", lambda: executors().shutdown_all(wait=False))
        logger.info("Закрываемся")

    def _check_and_perform_pending_update(self):
        if not self.pip_installer:
            logger.warning("PipInstaller не инициализирован, проверка отложенного обновления пропущена.")
            return

        update_pending = self.settings.get("G4F_UPDATE_PENDING", False)
        target_version = self.settings.get("G4F_TARGET_VERSION", None)

        if update_pending and target_version:
            logger.info(f"Обнаружено запланированное обновление g4f до версии: {target_version}")
            package_spec = f"g4f=={target_version}" if target_version != "latest" else "g4f"
            description = f"Запланированное обновление g4f до {target_version}..."

            success = False
            try:
                success = self.pip_installer.install_package(
                    package_spec,
                    description=description,
                    extra_args=["--force-reinstall", "--upgrade"]
                )
                if success:
                    logger.success(f"Запланированное обновление g4f до {target_version} успешно завершено.")
                    try:
                        import importlib
                        importlib.invalidate_caches()
                        logger.info("Кэш импорта очищен после запланированного обновления.")
                    except Exception as e_invalidate:
                        logger.error(f"Ошибка при очистке кэша импорта после обновления: {e_invalidate}")
                else:
                    logger.error(f"Запланированное обновление g4f до {target_version} не удалось (ошибка pip).")
            except Exception as e_install:
                logger.error(f"Исключение во время запланированного обновления g4f: {e_install}", exc_info=True)
                success = False

            finally:
                logger.info("Сброс флагов запланированного обновления g4f.")
                self.settings.set("G4F_UPDATE_PENDING", False)
                self.settings.set("G4F_TARGET_VERSION", None)
                self.settings.save_settings()
        else:
            logger.info("Нет запланированных обновлений g4f.")

    def _on_schedule_g4f_update(self, event: Event):
        version = event.data.get('version', 'latest')

        try:
            self.settings.set("G4F_TARGET_VERSION", version)
            self.settings.set("G4F_UPDATE_PENDING", True)
            self.settings.set("G4F_VERSION", version)
            self.settings.save_settings()
            logger.info(f"Обновление g4f до версии '{version}' запланировано на следующий запуск.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении настроек для запланированного обновления: {e}", exc_info=True)
            return False

    def _on_request_tg_code(self, event: Event):
        code_future = event.data.get("future")
        if not code_future:
            return
        if self.headless:
            if not code_future.done():
                code_future.set_exception(RuntimeError("Telegram code input is unavailable in headless mode"))
            return
        self.event_bus.emit("show_tg_code_dialog", {"future": code_future})

    def _on_request_tg_password(self, event: Event):
        password_future = event.data.get("future")
        if not password_future:
            return
        if self.headless:
            if not password_future.done():
                password_future.set_exception(RuntimeError("Telegram password input is unavailable in headless mode"))
            return
        self.event_bus.emit("show_tg_password_dialog", {"future": password_future})

    def _on_show_loading_popup(self, event: Event):
        message = event.data.get("message", "Loading...")
        if self.headless:
            logger.info(f"Loading: {message}")
            return
        self.event_bus.emit("display_loading_popup", {"message": message})

    def _on_close_loading_popup(self, event: Event):
        if not self.headless:
            self.event_bus.emit("hide_loading_popup")

    def _on_set_dialog_active(self, event: Event):
        self.dialog_active = event.data.get('active', False)
