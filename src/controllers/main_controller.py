import os
import threading
import time
from pathlib import Path
from PyQt6.QtCore import QTimer

from controllers.gui_fallback_controller import GuiFallbackController
from controllers.gui_controller import GuiController
from controllers.audio_controller import AudioController
from controllers.telegram_controller import TelegramController
from controllers.capture_controller import CaptureController
from controllers.model_controller import ModelController
from controllers.character_controller import CharacterController
from controllers.speech_controller import SpeechController
from controllers.settings_controller import SettingsController
from controllers.chat_controller import ChatController
from controllers.loop_controller import LoopController
from controllers.task_controller import TaskController
from controllers.api_presets_controller import ApiPresetsController
from controllers.embedding_presets_controller import EmbeddingPresetsController
from controllers.local_voice_controller import LocalVoiceController
from controllers.prompt_controller import PromptController
from controllers.history_controller import HistoryController
from controllers.graph_controller import GraphController
from controllers.voice_model_controller import VoiceModelController
from controllers.install_controller import InstallController
from controllers.installable_controller import InstallableController
from controllers.protocols_controller import ProtocolsController
from controllers.embedding_controller import EmbeddingController
from controllers.ai_engine_controller import AIEngineController

from main_logger import logger
from utils.ffmpeg_installer import install_ffmpeg
from utils.pip_installer import PipInstaller
from core.events import get_event_bus, Events, Event, shutdown_event_bus
from core.executors import executors
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
from services.settings_service import DefaultAppVarsService

from controllers.server_controller import ServerController


class MainController:
    def __init__(self, view, startup_mode: str = "full"):
        self.view = view
        self.event_bus = get_event_bus()
        self.startup_mode = self._normalize_startup_mode(startup_mode)
        self.backend_enabled = self.startup_mode == "full"

        self.dialog_active = False
        self._close_lock = threading.Lock()
        self._closing_started = False
        self.gui_fallback_controller = None

        self.loop_controller = None
        logger.notify("LoopController успешно инициализирован.")

        self.gui_controller = None

        self.telegram_controller = None
        logger.notify("TelegramController успешно инициализирован.")

        target_folder = "Settings"
        os.makedirs(target_folder, exist_ok=True)
        self.config_path = os.path.join(target_folder, "settings.json")

        # Композиционный корень: инфраструктурные сервисы регистрируются
        # в порядке зависимостей до создания остальных контроллеров.
        self.settings_controller = SettingsController(self.config_path)
        self.settings = self.settings_controller.settings
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
            self.gui_fallback_controller = GuiFallbackController(self.settings)
            logger.notify("GuiFallbackController initialized.")
            self._subscribe_to_events()
            logger.notify("MainController initialized in GUI-only mode.")
            return

        self.loop_controller = LoopController()
        logger.notify("LoopController initialized.")
        self.telegram_controller = TelegramController()
        services().register(TelegramService, self.telegram_controller, replace=True)
        logger.notify("TelegramController initialized.")

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

        self.ai_engine_controller = AIEngineController()
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

        self.audio_controller = AudioController(self)
        logger.notify("AudioController успешно инициализирован.")

        self.voice_model_controller = VoiceModelController(config_dir="Settings")
        logger.notify("VoiceModelController (backend) успешно инициализирован.")

        self.character_controller = CharacterController(self.settings)
        logger.notify("CharacterController успешно инициализирован.")

        self.model_controller = ModelController(self.settings)
        logger.notify("ModelController успешно инициализирован.")

        self.embedding_controller = EmbeddingController()
        services().register(EmbeddingService, self.embedding_controller, replace=True)
        logger.notify("EmbeddingController успешно инициализирован.")

        self.capture_controller = CaptureController(self.settings)
        logger.notify("CaptureController успешно инициализирован.")

        from controllers.reminder_controller import ReminderController
        self.reminder_controller = ReminderController(self.settings)
        logger.notify("ReminderController успешно инициализирован.")

        self.speech_controller = SpeechController()
        logger.notify("SpeechController успешно инициализирован.")

        self._init_server_controller()

        self.chat_controller = ChatController(self.settings)
        logger.notify("ChatController успешно инициализирован.")

        audio_controller = getattr(self, "audio_controller", None)
        if audio_controller is not None:
            audio_controller.delete_all_sound_files()

        self._subscribe_to_events()
        logger.notify("MainController подписался на события")

    @staticmethod
    def _normalize_startup_mode(startup_mode: str | None) -> str:
        mode = str(startup_mode or "full").strip().lower()
        if mode in {"gui-only", "gui_only", "ui-only", "ui_only"}:
            return "gui_only"
        return "full"

    def _init_server_controller(self):
        # Старый серверный API (ServerControllerOld / server_old.py) удалён —
        # всегда используем новый. Настройка USE_NEW_API больше ни на что не
        # влияет и оставлена только для совместимости со старыми settings.json.
        if getattr(self, 'server_controller', None):
            return

        self.server_controller = ServerController(self.game_link)
        logger.notify("ServerController (новый API) успешно инициализирован.")

    def update_view(self, view):
        if not self.gui_controller:
            self.view = view
            try:
                setattr(view, "main_controller", self)
                setattr(view, "backend_enabled", bool(self.backend_enabled))
                setattr(view, "startup_mode", self.startup_mode)
            except Exception:
                pass
            self.gui_controller = GuiController(self, view)
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

        self.event_bus.emit(Events.Speech.STOP_SPEECH_RECOGNITION)
        start = time.time()
        try:
            while True:
                mic_status = self.event_bus.emit_and_wait(Events.Speech.GET_MIC_STATUS, timeout=0.5)
                active = bool(mic_status and mic_status[0])
                if not active:
                    break
                if time.time() - start > 1.5:
                    break
                time.sleep(0.1)
        except Exception:
            pass

        try:
            self.event_bus.emit(Events.Server.STOP_SERVER)
        except Exception as e:
            logger.error(f"Ошибка при остановке сервера: {e}", exc_info=True)

        try:
            if getattr(self, "capture_controller", None):
                self.capture_controller.shutdown()
        except Exception as e:
            logger.error(f"РћС€РёР±РєР° РїСЂРё РѕСЃС‚Р°РЅРѕРІРєРµ capture controller: {e}", exc_info=True)

        self.audio_controller.delete_all_sound_files()

        try:
            if getattr(self, "ai_engine_controller", None):
                self.ai_engine_controller.shutdown(timeout=5.0)
        except Exception as e:
            logger.error(f"Ошибка при остановке AI engine: {e}", exc_info=True)

        if self.loop_controller is not None:
            self.loop_controller.stop_loop()

        try:
            shutdown_event_bus()
        except Exception as e:
            logger.error(f"Ошибка при остановке EventBus: {e}", exc_info=True)

        try:
            executors().shutdown_all(wait=False)
        except Exception as e:
            logger.error(f"Ошибка при остановке пулов: {e}", exc_info=True)

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
        code_future = event.data.get('future')
        if code_future:
            self.event_bus.emit("show_tg_code_dialog", {'future': code_future})

    def _on_request_tg_password(self, event: Event):
        password_future = event.data.get('future')
        if password_future:
            self.event_bus.emit("show_tg_password_dialog", {'future': password_future})

    def _on_show_loading_popup(self, event: Event):
        message = event.data.get('message', 'Loading...')
        self.event_bus.emit("display_loading_popup", {"message": message})

    def _on_close_loading_popup(self, event: Event):
        self.event_bus.emit("hide_loading_popup")

    def _on_set_dialog_active(self, event: Event):
        self.dialog_active = event.data.get('active', False)
