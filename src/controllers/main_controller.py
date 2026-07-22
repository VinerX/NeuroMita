from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from main_logger import logger
from core.events import Event, EventDelivery, Events, get_event_bus, shutdown_event_bus
from core.app_paths import settings_dir, settings_path
from core.executors import executors
from core.runtime_environments import runtime_environments
from core.task_supervisor import task_supervisor
from startup.startup_profiler import startup_trace
from core.services import services
from services.character_registry import SettingsOnlyCharacterRegistry
from services.contracts import (
    AIEngineAdministrationService,
    AIEnvironmentMaintenanceService,
    AIEngineService,
    ApiPresetService,
    AppVarsService,
    CharacterRegistry,
    EmbeddingPresetService,
    EmbeddingService,
    GameLinkService,
    AudioStateService,
    CaptureService,
    GuiInteractionService,
    InstallService,
    LocalVoiceService,
    ModelStateService,
    RuntimeFeatureService,
    RuntimeCapabilitiesService,
    SpeechService,
    VoiceModelService,
    InstallableCatalogService,
    InstallableOperationsService,
    LoopService,
    ProtocolBuilderService,
    SettingsService,
    TaskService,
    TelegramAuthService,
    TelegramService,
)
from services.game_link_service import DisconnectedGameLinkService, ServerGameLinkService
from services.loop_service import NoLoopService
from services.telegram_service import UnavailableTelegramService
from services.settings_service import DefaultAppVarsService
from services.runtime_features import FeatureSpec, RuntimeFeatureManager
from services.runtime_capabilities import DefaultRuntimeCapabilitiesService

if TYPE_CHECKING:
    from controllers.settings_controller import SettingsController


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
        self.server_controller = None
        self.gui_controller = None
        self.telegram_controller = None
        self.install_controller = None
        self.installable_controller = None
        self.local_voice_controller = None
        self.audio_controller = None
        self.voice_model_controller = None
        self.embedding_controller = None
        self.capture_controller = None
        self.reminder_controller = None
        self.speech_controller = None
        self.graph_controller = None
        self.feature_manager = None

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
        from services.asr_settings_service import ensure_asr_settings_service

        ensure_asr_settings_service()
        if not services().is_registered(InstallableCatalogService):
            from services.installable_catalog_service import DefaultInstallableCatalogService

            services().register(
                InstallableCatalogService,
                DefaultInstallableCatalogService(settings_service),
            )

        if self.backend_enabled:
            self.game_link = ServerGameLinkService()
        else:
            self.game_link = DisconnectedGameLinkService()
        services().register(GameLinkService, self.game_link, replace=True)
        services().register(
            RuntimeCapabilitiesService,
            DefaultRuntimeCapabilitiesService(settings_service, self.game_link),
            replace=True,
        )
        services().register(
            AppVarsService, DefaultAppVarsService(settings_service, self.game_link), replace=True
        )
        # The early server may receive a client before the full character runtime
        # is materialized. Keep a settings-backed registry available until
        # CharacterController atomically replaces it with the managed registry.
        services().register(
            CharacterRegistry,
            SettingsOnlyCharacterRegistry(settings_service),
            replace=True,
        )
        services().register(
            TelegramService,
            UnavailableTelegramService("Telegram feature is disabled"),
            replace=True,
        )
        from services.telegram_auth_service import DefaultTelegramAuthService

        services().register(
            TelegramAuthService,
            DefaultTelegramAuthService(available=not self.headless),
            replace=True,
        )

        if not self.backend_enabled:
            services().register(LoopService, NoLoopService(), replace=True)
            from controllers.gui_fallback_controller import GuiFallbackController

            self.gui_fallback_controller = GuiFallbackController(self.settings)
            logger.notify("GuiFallbackController initialized.")
            self._subscribe_to_events()
            logger.notify("MainController initialized in GUI-only mode.")
            return

        with startup_trace.phase("controller.core_imports"):
            from controllers.ai_engine_controller import AIEngineController
            from controllers.api_presets_controller import ApiPresetsController
            from controllers.character_controller import CharacterController
            from controllers.chat_controller import ChatController
            from controllers.embedding_presets_controller import EmbeddingPresetsController
            from controllers.history_controller import HistoryController
            from controllers.loop_controller import LoopController
            from controllers.model_controller import ModelController
            from controllers.prompt_controller import PromptController
            from controllers.protocols_controller import ensure_protocols_controller
            from controllers.task_controller import TaskController

        self.loop_controller = self._build_component("loop", LoopController)
        logger.notify("LoopController initialized.")

        with startup_trace.phase("controller.pending_update"):
            self._check_and_perform_pending_update()

        self.ai_engine_controller = self._build_component("ai_engine", AIEngineController)
        services().register(AIEngineService, self.ai_engine_controller, replace=True)
        services().register(
            AIEngineAdministrationService,
            self.ai_engine_controller,
            replace=True,
        )
        from services.ai_environment_maintenance_service import (
            DefaultAIEnvironmentMaintenanceService,
        )

        services().register(
            AIEnvironmentMaintenanceService,
            DefaultAIEnvironmentMaintenanceService(runtime_environments()),
            replace=True,
        )
        logger.notify(
            f"AIEngineController успешно инициализирован (mode={getattr(self.ai_engine_controller, 'mode', 'unknown')})."
        )

        self.task_controller = self._build_component("task", TaskController)
        services().register(TaskService, self.task_controller, replace=True)
        logger.notify("TaskController успешно инициализирован.")

        self.history_controller = self._build_component("history", HistoryController)
        logger.notify("HistoryController успешно инициализирован.")

        self.prompt_controller = self._build_component("prompt", PromptController)
        logger.notify("PromptController успешно инициализирован.")

        self.protocols_controller = self._build_component(
            "protocols", ensure_protocols_controller
        )
        services().register(ProtocolBuilderService, self.protocols_controller, replace=True)
        self.api_presets_controller = self._build_component("api_presets", ApiPresetsController)
        services().register(ApiPresetService, self.api_presets_controller, replace=True)
        logger.notify("ApiPresetsController успешно инициализирован.")

        self.embedding_presets_controller = self._build_component(
            "embedding_presets", EmbeddingPresetsController
        )
        services().register(EmbeddingPresetService, self.embedding_presets_controller, replace=True)
        logger.notify("EmbeddingPresetsController успешно инициализирован.")

        self.character_controller = self._build_component(
            "characters", lambda: CharacterController(self.settings)
        )
        startup_trace.mark(
            "controller.characters.materialized",
            loaded=len(self.character_controller.character_manager.characters),
        )
        logger.notify("CharacterController успешно инициализирован.")

        self.model_controller = self._build_component(
            "model", lambda: ModelController(self.settings)
        )
        services().register(ModelStateService, self.model_controller, replace=True)
        logger.notify("ModelController успешно инициализирован.")

        self.chat_controller = self._build_component(
            "chat", lambda: ChatController(self.settings)
        )
        logger.notify("ChatController успешно инициализирован.")

        with startup_trace.phase("controller.optional_features.configure"):
            self._configure_optional_features(target_folder, settings_service)
        with startup_trace.phase("controller.optional_features.schedule"):
            self.feature_manager.start_enabled()

        self._subscribe_to_events()
        logger.notify("MainController подписался на события")
        # External requests are accepted only after every mandatory service and
        # event handler used by the game protocol has been registered.
        self._build_component("server", self._init_server_controller)
        startup_trace.mark("controller.main.ready", headless=self.headless)
        startup_trace.write()

    @staticmethod
    def _build_component(name: str, factory):
        with startup_trace.phase(f"controller.{name}"):
            return factory()

    def _configure_optional_features(self, target_folder: str, settings_service) -> None:
        feature_manager = RuntimeFeatureManager(settings_service, max_workers=2)
        self.feature_manager = feature_manager
        services().register(RuntimeFeatureService, feature_manager, replace=True)

        def enabled(*keys: str):
            return lambda settings: any(bool(settings.get(key, False)) for key in keys)

        def voice_enabled(settings) -> bool:
            return bool(settings.get("USE_VOICEOVER", False))

        def local_voice_enabled(settings) -> bool:
            return voice_enabled(settings) and str(
                settings.get("VOICEOVER_METHOD", "Local") or "Local"
            ).strip().lower() == "local"

        def telegram_enabled(settings) -> bool:
            return voice_enabled(settings) and str(
                settings.get("VOICEOVER_METHOD", "Local") or "Local"
            ).strip().lower() in {"tg", "telegram"}

        feature_manager.register(
            FeatureSpec(
                name="telegram",
                setting_keys=(
                    "USE_VOICEOVER",
                    "VOICEOVER_METHOD",
                    "TG_AUTOCONNECT",
                    "NM_TELEGRAM_API_ID",
                    "NM_TELEGRAM_API_HASH",
                    "NM_TELEGRAM_PHONE",
                ),
                enabled=telegram_enabled,
                factory=self._create_telegram_controller,
                provided_services=(TelegramService,),
                priority=20,
                required_modules=("telethon",),
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="audio",
                setting_keys=("USE_VOICEOVER", "VOICEOVER_METHOD"),
                enabled=voice_enabled,
                factory=self._create_audio_controller,
                provided_services=(AudioStateService,),
                shutdown=lambda controller: controller.delete_all_sound_files(),
                priority=30,
                required_modules=("pygame",),
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="local_voice",
                setting_keys=("USE_VOICEOVER", "VOICEOVER_METHOD"),
                enabled=local_voice_enabled,
                factory=self._create_local_voice_controller,
                provided_services=(LocalVoiceService,),
                priority=35,
                stop_when_disabled=False,
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="voice_models",
                setting_keys=(
                    "USE_VOICEOVER",
                    "VOICEOVER_METHOD",
                    "LOCAL_VOICE_LOAD_LAST",
                ),
                enabled=local_voice_enabled,
                factory=lambda: self._create_voice_model_controller(target_folder),
                provided_services=(VoiceModelService,),
                depends_on=("local_voice",),
                priority=40,
                stop_when_disabled=False,
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="speech",
                setting_keys=("MIC_ACTIVE",),
                enabled=enabled("MIC_ACTIVE"),
                factory=self._create_speech_controller,
                provided_services=(SpeechService,),
                shutdown=self._shutdown_speech_controller,
                priority=50,
                required_modules=("sounddevice",),
                stop_when_disabled=False,
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="capture",
                setting_keys=(
                    "ENABLE_IMAGE_ANALYSIS",
                    "ENABLE_SCREEN_ANALYSIS",
                    "ENABLE_CAMERA_CAPTURE",
                    "AUTO_ATTACH_IMAGES",
                ),
                enabled=lambda settings: bool(settings.get("ENABLE_IMAGE_ANALYSIS", False))
                and any(
                    bool(settings.get(key, False))
                    for key in (
                        "ENABLE_SCREEN_ANALYSIS",
                        "ENABLE_CAMERA_CAPTURE",
                        "AUTO_ATTACH_IMAGES",
                    )
                ),
                factory=self._create_capture_controller,
                provided_services=(CaptureService,),
                shutdown=lambda controller: controller.shutdown(),
                priority=60,
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="reminders",
                setting_keys=("REMINDERS_ENABLED",),
                enabled=lambda settings: bool(settings.get("REMINDERS_ENABLED", True)),
                factory=self._create_reminder_controller,
                priority=65,
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="embedding",
                setting_keys=("RAG_ENABLED",),
                enabled=enabled("RAG_ENABLED"),
                factory=self._create_embedding_controller,
                provided_services=(EmbeddingService,),
                priority=70,
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="graph",
                setting_keys=("GRAPH_EXTRACTION_ENABLED",),
                enabled=enabled("GRAPH_EXTRACTION_ENABLED"),
                factory=self._create_graph_controller,
                priority=75,
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="install",
                enabled=lambda _settings: True,
                factory=self._create_install_controller,
                provided_services=(InstallService,),
                startup=False,
                priority=90,
            )
        )
        feature_manager.register(
            FeatureSpec(
                name="installables",
                enabled=lambda _settings: True,
                factory=self._create_installable_controller,
                provided_services=(InstallableOperationsService,),
                startup=False,
                priority=95,
            )
        )

    def ensure_feature_async(self, name: str):
        manager = self.feature_manager
        if manager is None:
            raise RuntimeError("Optional feature runtime is unavailable")
        return manager.ensure_async(name)

    def ensure_feature(self, name: str, *, timeout: float | None = None):
        manager = self.feature_manager
        if manager is None:
            raise RuntimeError("Optional feature runtime is unavailable")
        return manager.ensure(name, timeout=timeout)

    def feature_status(self) -> dict:
        manager = self.feature_manager
        return manager.snapshot() if manager is not None else {}

    def _create_telegram_controller(self):
        from controllers.telegram_controller import TelegramController

        controller = TelegramController()
        self.telegram_controller = controller
        return controller

    def _create_audio_controller(self):
        from controllers.audio_controller import AudioController

        controller = AudioController(self)
        self.audio_controller = controller
        controller.delete_all_sound_files()
        return controller

    def _create_local_voice_controller(self):
        from controllers.local_voice_controller import LocalVoiceController

        controller = LocalVoiceController()
        self.local_voice_controller = controller
        return controller

    def _create_voice_model_controller(self, target_folder: str):
        from controllers.voice_model_controller import VoiceModelController

        controller = VoiceModelController(config_dir=target_folder)
        self.voice_model_controller = controller
        self.event_bus.emit(Events.VoiceModel.REFRESH_MODEL_PANELS)
        return controller

    def _create_speech_controller(self):
        from controllers.speech_controller import SpeechController

        controller = SpeechController()
        self.speech_controller = controller
        return controller

    def _create_capture_controller(self):
        from controllers.capture_controller import CaptureController

        controller = CaptureController()
        self.capture_controller = controller
        return controller

    def _create_reminder_controller(self):
        from controllers.reminder_controller import ReminderController

        controller = ReminderController(
            self.settings,
            character_resources=self.character_controller.character_manager.resources,
        )
        self.reminder_controller = controller
        return controller

    def _create_embedding_controller(self):
        from controllers.embedding_controller import EmbeddingController

        controller = EmbeddingController()
        self.embedding_controller = controller
        return controller

    def _create_graph_controller(self):
        from controllers.graph_controller import GraphController

        controller = GraphController()
        self.graph_controller = controller
        return controller

    def _create_install_controller(self):
        from controllers.install_controller import InstallController

        controller = InstallController()
        self.install_controller = controller
        return controller

    def _create_installable_controller(self):
        from controllers.installable_controller import InstallableController

        controller = InstallableController(
            services().get(InstallableCatalogService)
        )
        self.installable_controller = controller
        return controller

    def _shutdown_speech_controller(self, controller) -> None:
        shutdown = getattr(controller, "shutdown", None)
        if callable(shutdown):
            shutdown()
            return
        self.event_bus.emit(
            Events.Speech.STOP_SPEECH_RECOGNITION,
            delivery=EventDelivery.CRITICAL,
        )

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
        if self.gui_controller is None:
            from controllers.gui_controller import GuiController

            self.view = view
            self.gui_controller = GuiController(self, view)
            services().register(GuiInteractionService, self.gui_controller, replace=True)
            logger.notify("GuiController успешно инициализирован.")
            if self.feature_manager is not None and self.feature_manager.is_ready("voice_models"):
                self.event_bus.emit(Events.GUI.VOICEOVER_REFRESH)
        return self.gui_controller


    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Model.SCHEDULE_G4F_UPDATE, self._on_schedule_g4f_update, weak=False)

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

        server_controller = getattr(self, "server_controller", None)
        if server_controller is not None:
            shutdown_step("server", server_controller.destroy)

        history_controller = getattr(self, "history_controller", None)
        if history_controller is not None:
            close_history = getattr(history_controller, "close", None)
            if callable(close_history):
                shutdown_step("history timers", close_history)

        gui_controller = getattr(self, "gui_controller", None)
        if gui_controller is not None:
            close_gui = getattr(gui_controller, "close", None)
            if callable(close_gui):
                shutdown_step("GUI controllers", close_gui)

        api_presets_controller = getattr(self, "api_presets_controller", None)
        if api_presets_controller is not None:
            close_api_presets = getattr(api_presets_controller, "close", None)
            if callable(close_api_presets):
                shutdown_step("API preset HTTP transport", close_api_presets)

        model_controller = getattr(self, "model_controller", None)
        if model_controller is not None:
            shutdown_model = getattr(model_controller, "shutdown", None)
            if callable(shutdown_model):
                shutdown_step("model subscriptions", shutdown_model)

        feature_manager = getattr(self, "feature_manager", None)
        if feature_manager is not None:
            shutdown_step("optional features", feature_manager.shutdown)

        catalog = services().get_optional(InstallableCatalogService)
        if catalog is not None:
            shutdown_step("installable catalog", catalog.close)

        if services().is_registered(TelegramAuthService):
            auth_service = services().get(TelegramAuthService)
            close_auth = getattr(auth_service, "close", None)
            if callable(close_auth):
                shutdown_step("Telegram auth prompts", close_auth)

        ai_engine = getattr(self, "ai_engine_controller", None)
        if ai_engine is not None:
            shutdown_step("AI engine", lambda: ai_engine.shutdown(timeout=5.0))

        loop_controller = getattr(self, "loop_controller", None)
        if loop_controller is not None:
            shutdown_step("async loop", loop_controller.stop_loop)

        character_controller = getattr(self, "character_controller", None)
        character_manager = getattr(character_controller, "character_manager", None)
        if character_manager is not None:
            shutdown_step("character resources", character_manager.shutdown)

        settings_controller = getattr(self, "settings_controller", None)
        if settings_controller is not None:
            close_controller = getattr(settings_controller, "close", None)
            if callable(close_controller):
                shutdown_step("settings subscriptions", close_controller)

        settings = getattr(self, "settings", None)
        close_settings = getattr(settings, "close", None)
        if callable(close_settings):
            shutdown_step("settings writer", close_settings)

        shutdown_step("EventBus", shutdown_event_bus)
        shutdown_step("background tasks", lambda: task_supervisor().shutdown(timeout=3.0))
        shutdown_step("executor pools", lambda: executors().shutdown_all(wait=False))
        logger.info("Закрываемся")

    def _check_and_perform_pending_update(self):
        update_pending = self.settings.get("G4F_UPDATE_PENDING", False)
        if not update_pending:
            return
        self.settings.set("G4F_UPDATE_PENDING", False)
        self.settings.set("G4F_TARGET_VERSION", None)
        self.settings.save_settings()
        logger.warning("Сброшено устаревшее запланированное обновление g4f.")

    def _on_schedule_g4f_update(self, event: Event):
        logger.warning(
            "Запрос обновления g4f отклонён: автоматическая установка отключена."
        )
        return False


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
