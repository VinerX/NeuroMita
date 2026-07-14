from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import weakref
from typing import Any, Callable

from core.events import Event, get_event_bus
from core.services import services, use
from services.contracts import (
    ApiPresetService,
    CaptureService,
    CharacterRegistry,
    EmbeddingPresetService,
    HistoryService,
    InstallableCatalogService,
    InstallableOperationsService,
    LocalVoiceService,
    SettingsService,
    TelegramAuthService,
    VoiceModelService,
)
from controllers.gui.presentation_contracts import UiEvent, UiSettingsDataKey, UiTopic


class _SettingsDataController:
    """Владелец кэша данных настроек: единственный экземпляр SettingsDataCache
    живёт здесь, а не модульным синглтоном."""

    def __init__(self) -> None:
        from controllers.gui.settings_data_prefetch import SettingsDataCache

        self._cache = SettingsDataCache()

    def get(self, key: UiSettingsDataKey | str, default: Any = None) -> Any:
        return self._cache.get(str(key), default)

    def request(
        self,
        target: Any,
        key: UiSettingsDataKey | str,
        worker: Callable[[], Any],
        on_ready: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        *,
        name: str | None = None,
        force: bool = False,
    ):
        return self._cache.request(
            target,
            str(key),
            worker,
            on_ready,
            on_error,
            name=name,
            force=force,
        )

    def clear(self, key: UiSettingsDataKey | str | None = None) -> None:
        self._cache.clear(str(key) if key is not None else None)

    def prefetch_section(self, gui: Any, category: str) -> None:
        from controllers.gui.settings_data_prefetch import prefetch_settings_section

        prefetch_settings_section(gui, str(category), self._cache)

    def embed_preset_items_from_meta(self, meta: Any) -> list[tuple[str, Any]]:
        from controllers.gui.settings_data_prefetch import embed_preset_items_from_meta

        return list(embed_preset_items_from_meta(meta))


class _ProviderOptionsController:
    def __init__(self, settings_data: "_SettingsDataController") -> None:
        self._settings_data = settings_data

    def current(self) -> list[Any]:
        from controllers.gui.provider_options import current_provider_options

        return list(current_provider_options(self._settings_data))

    def load(self) -> list[Any]:
        from controllers.gui.provider_options import load_provider_options

        return list(load_provider_options())

    def load_async(self, gui: Any, setting_keys: tuple[str, ...], *, name: str):
        from controllers.gui.provider_options import load_api_provider_options_async

        return load_api_provider_options_async(
            gui, setting_keys, settings_data=self._settings_data, name=name
        )


class _SettingsSectionsController:
    def __init__(self, presentation: "UiPresentationHub") -> None:
        self._presentation = presentation

    def build_section(self, gui: Any, category: str, parent: Any) -> None:
        key = str(category or "").strip().lower()
        if key == "general":
            from ui.settings.general_settings import setup_general_settings_controls

            setup_general_settings_controls(gui, parent)
            return
        if key == "language":
            from ui.settings.language_settings import setup_language_settings_controls

            setup_language_settings_controls(gui, parent)
            return
        if key == "api":
            from ui.settings.api_settings import setup_api_controls

            setup_api_controls(gui, parent, wire_api=self.wire_api)
            return
        if key == "characters":
            from ui.settings.character_settings import setup_mita_controls

            setup_mita_controls(
                gui,
                parent,
                wire_characters=self.wire_characters,
            )
            return
        if key == "voice":
            from ui.settings.voiceover_settings import setup_voiceover_controls

            owner = self._section_owner(gui, parent)
            actions = self._own_view_model(
                self._presentation.view_models.voiceover_settings(gui),
                owner,
            )
            setup_voiceover_controls(
                gui,
                parent,
                actions=actions,
                wire_voiceover=self.wire_voiceover,
            )
            return
        if key == "microphone":
            from ui.settings.microphone_settings import setup_microphone_controls

            setup_microphone_controls(
                gui,
                parent,
                wire_microphone=self.wire_microphone,
            )
            return
        if key == "ai_engine":
            from ui.settings.ai_engine_settings import setup_ai_engine_settings_controls

            owner = self._section_owner(gui, parent)
            view_model = self._own_view_model(
                self._presentation.view_models.ai_engine_settings(gui),
                owner,
            )
            setup_ai_engine_settings_controls(
                gui,
                parent,
                view_model=view_model,
            )
            return
        if key == "game":
            from ui.settings.game_settings import setup_game_controls

            owner = self._section_owner(gui, parent)
            view_model = self._own_view_model(
                self._presentation.view_models.beat_settings(gui),
                owner,
            )
            setup_game_controls(gui, parent, beat_view_model=view_model)
            return
        if key == "models":
            from PyQt6.QtWidgets import QMessageBox
            from ui.settings.model_interaction_settings import (
                setup_model_interaction_controls,
            )
            from ui.settings.rag_install_presentation import RagInstallShowError

            owner = self._section_owner(gui, parent)
            runtime_options = self._runtime_options_view_model(gui)
            embed_provider = self._own_view_model(
                self._presentation.view_models.embed_provider(gui),
                owner,
            )
            rag_preset = self._own_view_model(
                self._presentation.view_models.rag_preset(gui),
                owner,
            )
            rag_install = self._own_view_model(
                self._presentation.view_models.rag_install(gui),
                owner,
            )

            def show_rag_error(effect) -> None:
                if isinstance(effect, RagInstallShowError):
                    QMessageBox.critical(gui, effect.title, effect.message)

            rag_install.effect_emitted.connect(show_rag_error)
            setup_model_interaction_controls(
                gui,
                parent,
                runtime_options_view_model=runtime_options,
                build_memory_section=self._presentation.rag.build_memory_section,
                build_rag_section=lambda target, layout, providers: self._presentation.rag.build_rag_section(
                    target,
                    layout,
                    providers,
                    rag_preset_view_model=rag_preset,
                    embed_provider_view_model=embed_provider,
                    rag_install_view_model=rag_install,
                ),
            )
            return
        if key == "screen":
            from ui.settings.screen_analysis_settings import (
                setup_screen_analysis_controls,
            )

            setup_screen_analysis_controls(
                gui,
                parent,
                runtime_options_view_model=self._runtime_options_view_model(gui),
            )
            return
        if key == "updates":
            self.build_updates(gui, parent)
            return
        raise KeyError(f"Unknown settings section: {category}")

    @staticmethod
    def _section_owner(gui: Any, parent: Any):
        try:
            owner = parent.parentWidget()
        except Exception:
            owner = None
        return owner or getattr(gui, "settings_page", None) or gui

    @staticmethod
    def _own_view_model(view_model, owner):
        view_model.setParent(owner)
        owner.destroyed.connect(lambda *_args, vm=view_model: vm.close())
        return view_model

    def _runtime_options_view_model(self, gui: Any):
        page = getattr(gui, "settings_page", None) or gui
        view_model = getattr(page, "runtime_options_view_model", None)
        if view_model is None or view_model.is_closed:
            view_model = self._own_view_model(
                self._presentation.view_models.settings_runtime_options(gui),
                page,
            )
            page.runtime_options_view_model = view_model
        return view_model

    def wire_api(self, gui: Any):
        from controllers.gui.api_settings import ApiSettingsController

        controller = ApiSettingsController(
            gui,
            settings_data=self._presentation.settings_data,
        )
        setattr(gui, "api_settings_logic", controller)
        return controller

    def wire_characters(self, gui: Any):
        from controllers.gui.character_settings_logic import wire_character_settings_logic

        return wire_character_settings_logic(
            gui,
            settings_data=self._presentation.settings_data,
        )

    def wire_microphone(self, gui: Any):
        from controllers.gui.microphone_settings_logic import wire_microphone_settings_logic

        return wire_microphone_settings_logic(gui)

    def load_microphone(self, gui: Any) -> None:
        from controllers.gui.microphone_settings_logic import load_mic_settings

        load_mic_settings(gui)

    def wire_voiceover(self, gui: Any):
        from controllers.gui.voiceover_settings_logic import wire_voiceover_settings_logic

        return wire_voiceover_settings_logic(gui)

    def build_updates(self, gui: Any, parent: Any) -> None:
        from controllers.gui.updates_settings_controller import setup_updates_settings_controls

        setup_updates_settings_controls(
            gui,
            parent,
            pending_restart_version=lambda: self._presentation.app.pending_restart_version,
            set_pending_restart_version=self._presentation.app.set_pending_restart_version,
        )


class _RagController:
    def __init__(self) -> None:
        from controllers.gui.rag_memory_controller import RagSettingsCoordinator

        self._coordinator = RagSettingsCoordinator()

    def build_memory_section(self, gui: Any, parent: Any, provider_options: list[Any]) -> None:
        self._coordinator.build_memory_section(gui, parent, provider_options)

    def build_rag_section(
        self,
        gui: Any,
        parent: Any,
        provider_options: list[Any],
        *,
        rag_preset_view_model,
        embed_provider_view_model,
        rag_install_view_model,
    ) -> None:
        self._coordinator.build_rag_section(
            gui,
            parent,
            provider_options,
            rag_preset_view_model=rag_preset_view_model,
            embed_provider_view_model=embed_provider_view_model,
            rag_install_view_model=rag_install_view_model,
        )

    def download_embed_model(self) -> None:
        from controllers.gui.rag_install_view_model import open_rag_ai_hub
        from managers.rag.install_spec import TARGET_EMBEDDINGS

        open_rag_ai_hub(TARGET_EMBEDDINGS)

    def is_embed_model_downloaded(self) -> bool:
        return bool(use(InstallableCatalogService).is_ready("rag:embeddings"))

    def embed_status_text(self) -> str:
        from controllers.gui.rag_memory_controller import _get_embed_status_text

        return str(_get_embed_status_text())


class _ViewModelFactory:
    def __init__(self, presentation: "UiPresentationHub") -> None:
        self._presentation = presentation

    def home(self, host: Any, *, parent: Any = None):
        from controllers.gui.home_page_view_model import HomePageViewModel

        return HomePageViewModel(
            host=host,
            app=self._presentation.app,
            home_controller=self._presentation.home,
            news_controller=self._presentation.news,
            settings=self._presentation.settings,
            parent=parent,
        )

    def sandbox(self, host: Any, *, parent: Any = None):
        from controllers.gui.sandbox_page_view_model import SandboxPageViewModel

        return SandboxPageViewModel(
            host=host,
            controller=self._presentation.sandbox,
            parent=parent,
        )

    def character_state(self, host: Any, *, parent: Any = None):
        from controllers.gui.character_state_view_model import CharacterStateViewModel

        return CharacterStateViewModel(
            current_character=self._presentation.characters.current,
            parent=parent,
        )

    def chat_panel(self, host: Any, *, parent: Any = None):
        from controllers.gui.chat_panel_view_model import ChatPanelViewModel

        return ChatPanelViewModel(
            host=host,
            backend_ready=lambda: bool(self._presentation.app.backend_ready),
            parent=parent,
        )

    def beat_settings(self, host: Any, *, parent: Any = None):
        from controllers.gui.beat_settings_view_model import BeatSettingsViewModel

        return BeatSettingsViewModel(
            controller=self._presentation.beats,
            settings=self._presentation.settings,
            parent=parent,
        )

    def finetune_data(self, host: Any, *, parent: Any = None):
        from controllers.gui.finetune_data_view_model import FineTuneDataViewModel

        return FineTuneDataViewModel(
            finetune=self._presentation.finetune,
            parent=parent,
        )

    def embed_provider(self, host: Any, *, parent: Any = None):
        from controllers.gui.embed_provider_view_model import EmbedProviderViewModel

        return EmbedProviderViewModel(
            host=host,
            presentation=self._presentation,
            parent=parent,
        )

    def voiceover_settings(self, host: Any, *, parent: Any = None):
        from controllers.gui.voiceover_settings_view_model import (
            VoiceoverSettingsViewModel,
        )

        return VoiceoverSettingsViewModel(
            events=self._presentation.events,
            open_settings=lambda category: host.show_settings_category(
                category,
                force=True,
            ),
            parent=parent,
        )

    def ai_engine_settings(self, host: Any, *, parent: Any = None):
        from controllers.gui.ai_engine_settings_view_model import (
            AIEngineSettingsViewModel,
        )

        return AIEngineSettingsViewModel(
            events=self._presentation.events,
            parent=parent,
        )

    def chat_message_actions(self, host: Any, *, parent: Any = None):
        from controllers.gui.chat_message_actions_view_model import (
            ChatMessageActionsViewModel,
        )

        return ChatMessageActionsViewModel(
            events=self._presentation.events,
            finetune=self._presentation.finetune,
            parent=parent,
        )

    def news_page(self, host: Any, *, parent: Any = None):
        from controllers.gui.news_page_view_model import NewsPageViewModel

        return NewsPageViewModel(
            host=host,
            news=self._presentation.news,
            parent=parent,
        )

    def ai_hub_settings(self, host: Any, *, parent: Any = None):
        from controllers.gui.ai_hub_settings_view_model import (
            AIHubSettingsViewModel,
        )

        return AIHubSettingsViewModel(
            catalog=self._presentation.installables,
            parent=parent,
        )

    def settings_runtime_options(self, host: Any, *, parent: Any = None):
        from controllers.gui.settings_runtime_options_view_model import (
            SettingsRuntimeOptionsViewModel,
        )

        return SettingsRuntimeOptionsViewModel(
            providers=self._presentation.providers,
            settings=self._presentation.settings,
            parent=parent,
        )

    def rag_install(self, host: Any, *, parent: Any = None):
        from controllers.gui.rag_install_view_model import RagInstallViewModel

        return RagInstallViewModel(
            settings_data=self._presentation.settings_data,
            parent=parent,
        )

    def rag_preset(self, host: Any, *, parent: Any = None):
        from controllers.gui.rag_preset_view_model import RagPresetViewModel

        return RagPresetViewModel(
            settings=use(SettingsService),
            parent=parent,
        )

    def settings_page(self, host: Any, *, parent: Any = None):
        from controllers.gui.settings_page_view_model import SettingsPageViewModel

        return SettingsPageViewModel(
            host=host,
            app=self._presentation.app,
            settings_data=self._presentation.settings_data,
            parent=parent,
        )

    def logs_page(self, host: Any, *, parent: Any = None):
        from controllers.gui.logs_page_view_model import LogsPageViewModel

        return LogsPageViewModel(parent=parent)


class _NewsController:
    """Владелец кэша ленты релизов (NewsReleasesStore)."""

    def __init__(self) -> None:
        from controllers.gui.news_controller import NewsReleasesStore

        self._store = NewsReleasesStore()

    @property
    def repository(self) -> str:
        from controllers.gui.news_controller import NEWS_REPO

        return str(NEWS_REPO)

    def invalidate(self) -> None:
        self._store.invalidate()

    def load_async(self, target: Any, on_ready: Callable[[list[dict[str, Any]]], None]) -> None:
        from controllers.gui.news_controller import load_news_releases_async

        load_news_releases_async(self._store, target, on_ready)

    def get_releases(self) -> list[dict[str, Any]]:
        from controllers.gui.news_controller import get_news_releases

        return list(get_news_releases(self._store))

    def get_content(self) -> str:
        from controllers.gui.news_controller import get_news_content

        return str(get_news_content(self._store))

    def build_items(self, *, limit: int | None = 8):
        from controllers.gui.news_controller import build_release_news_items

        return list(build_release_news_items(self._store, limit=limit))


class _EventsController:
    def __init__(self) -> None:
        self._bus = get_event_bus()

    def publish(self, topic: UiTopic, data: Any = None) -> None:
        self._bus.emit(str(topic), data)

    def subscribe(
        self,
        topic: UiTopic,
        callback: Callable[[UiEvent], None],
        *,
        weak: bool = False,
    ):
        # weak=True опасен для лямбд и локальных замыканий: weakref умирает
        # сразу после подписки, и колбэк молча перестаёт получать события.
        # Слабую подписку нужно запрашивать явно и только для bound-методов.
        normalized = UiTopic(topic)
        callback_ref = None
        strong_callback = callback
        if weak:
            try:
                callback_ref = (
                    weakref.WeakMethod(callback)
                    if getattr(callback, "__self__", None) is not None
                    else weakref.ref(callback)
                )
                strong_callback = None
            except TypeError:
                callback_ref = None

        subscription_box: dict[str, Any] = {}

        def forward(event: Event) -> None:
            target = callback_ref() if callback_ref is not None else strong_callback
            if target is None:
                subscription = subscription_box.get("subscription")
                if subscription is not None:
                    subscription.close()
                return
            target(UiEvent(normalized, event.data, event.timestamp))

        subscription = self._bus.subscribe(str(normalized), forward, weak=False)
        subscription_box["subscription"] = subscription
        return subscription


class _SettingsController:
    def __init__(self) -> None:
        self._service = use(SettingsService)

    def get(self, key: str, default: Any = None) -> Any:
        return self._service.get(str(key), default)

    def set(self, key: str, value: Any) -> None:
        self._service.update(str(key), value)

    def save(self) -> None:
        self._service.save_settings()

    def snapshot(self, keys: tuple[str, ...] | None = None) -> dict[str, Any]:
        return dict(self._service.snapshot(keys))

    def subscribe(self, callback, *, keys=None, replay: bool = False):
        return self._service.subscribe(callback, keys=keys, replay=replay)


class _ApiPresetController:
    @staticmethod
    def _service() -> ApiPresetService:
        return use(ApiPresetService)

    def list_meta(self):
        return self._service().list_meta()

    def get_full(self, preset_id: int):
        return self._service().get_full(int(preset_id))

    def set_current(self, preset_id: int) -> None:
        self._service().set_current(int(preset_id))

    def save_custom(self, payload: dict[str, Any]):
        return self._service().save_custom(dict(payload))

    def delete(self, preset_id: int):
        return self._service().delete_custom(int(preset_id))

    def reorder(self, order: list[int]):
        return self._service().save_order([int(item) for item in order])


class _EmbeddingPresetController:
    @staticmethod
    def _service() -> EmbeddingPresetService:
        return use(EmbeddingPresetService)

    def list_meta(self):
        return self._service().list_meta()

    def get_full(self, preset_id: str):
        return self._service().get_full(str(preset_id))

    def save(self, payload: dict[str, Any]):
        return self._service().save(dict(payload))

    def delete(self, preset_id: str):
        return self._service().delete(str(preset_id))

    def reorder(self, custom_ids: list[str]):
        return self._service().reorder([str(item) for item in custom_ids])

    def local_model_names(self) -> list[str]:
        from handlers.embedding_presets import list_preset_names

        return [str(item) for item in list_preset_names() if str(item) != "Custom"]


class _CharacterController:
    @staticmethod
    def _service() -> CharacterRegistry:
        return use(CharacterRegistry)

    def current_id(self) -> str:
        return str(self._service().current_id() or "")

    def current(self):
        return self._service().current()

    def current_profile(self) -> dict[str, Any]:
        return dict(self._service().current_profile() or {})

    def all_ids(self) -> list[str]:
        return [str(item) for item in self._service().all_ids()]

    def get(self, character_id: str):
        return self._service().get(str(character_id))

    def name_of(self, character_id: str) -> str:
        return self._service().name_of(str(character_id))

    def prepare_history(self, **kwargs):
        return use(HistoryService).prepare_for_prompt(**kwargs)

    def open_db_viewer(self, gui: Any) -> None:
        from controllers.gui.character_settings_logic import open_db_viewer

        open_db_viewer(gui)


class _CaptureController:
    def capture_screen(self, count: int = 1) -> list[Any]:
        service = services().get_optional(CaptureService)
        if service is None:
            return []
        return list(service.capture_screen(int(count)) or [])


class _FineTuneController:
    @staticmethod
    def _instance():
        from managers.finetune_collector import FineTuneCollector

        return FineTuneCollector.instance

    def available(self) -> bool:
        return self._instance() is not None

    def enabled(self) -> bool:
        collector = self._instance()
        return bool(collector and collector.is_enabled())

    def pop_pending_sample_id(self) -> str | None:
        collector = self._instance()
        return collector.pop_pending_sample_id() if collector else None

    def update_rating(self, sample_id: str, rating: int) -> bool:
        collector = self._instance()
        return bool(collector and collector.update_rating(str(sample_id), int(rating)))

    def get_stats(self) -> dict[str, Any]:
        collector = self._instance()
        return dict(collector.get_stats()) if collector else {}

    def load_samples(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        collector = self._instance()
        return list(collector.load_samples(filters) or []) if collector else []

    def export_sharegpt(self, samples: list[dict[str, Any]], path: str) -> int:
        collector = self._instance()
        if collector is None:
            raise RuntimeError("Fine-tune collector is unavailable")
        return int(collector.export_sharegpt(samples, str(path)))

    def export_raw_jsonl(self, samples: list[dict[str, Any]], path: str) -> int:
        collector = self._instance()
        if collector is None:
            raise RuntimeError("Fine-tune collector is unavailable")
        return int(collector.export_raw_jsonl(samples, str(path)))

    def clear_all(self) -> int:
        collector = self._instance()
        return int(collector.clear_all()) if collector else 0

    def enforce_limit(self) -> None:
        collector = self._instance()
        if collector is not None:
            collector.enforce_limit()

    def set_data_directory(self, path: str) -> None:
        from pathlib import Path

        collector = self._instance()
        if collector is None:
            return
        collector.data_dir = Path(path)
        collector.data_dir.mkdir(parents=True, exist_ok=True)


class _PromptController:
    def list_sets(self, *args, **kwargs):
        from managers.prompt_catalogue_manager import list_prompt_sets

        return list_prompt_sets(*args, **kwargs)

    def read_info(self, *args, **kwargs):
        from managers.prompt_catalogue_manager import read_info_json

        return read_info_json(*args, **kwargs)


class _TelegramController:
    @staticmethod
    def _service() -> TelegramAuthService:
        return use(TelegramAuthService)

    def resolve(self, request_id: str, value: str) -> bool:
        return bool(self._service().resolve(str(request_id), str(value)))

    def reject(self, request_id: str, reason: str) -> None:
        self._service().reject(str(request_id), str(reason))


class _VoiceController:
    def voice_models(self) -> VoiceModelService | None:
        return services().get_optional(VoiceModelService)

    def local_voice(self) -> LocalVoiceService | None:
        return services().get_optional(LocalVoiceService)

    def triton_status(self, *, refresh: bool = False) -> dict[str, Any]:
        service = self.local_voice()
        return dict(service.triton_status(refresh=refresh) or {}) if service is not None else {}

    def open_documentation(self, path: str) -> None:
        get_event_bus().emit("open_voice_model_doc", str(path))


class _InstallableController:
    def __init__(self) -> None:
        # Владелец сервиса — композиционный корень (__main__ / main_controller);
        # хаб только потребляет. Отсутствие — ошибка порядка старта.
        self._catalog = use(InstallableCatalogService)

    def list_rows(self, **kwargs):
        return self._catalog.list_rows(**kwargs)

    def install_preview(self, component_id: str):
        return self._catalog.install_preview(str(component_id))

    def settings_schema(self, component_id: str):
        return self._catalog.settings_schema(str(component_id))

    def load_settings(self, component_id: str):
        return self._catalog.load_settings(str(component_id))

    def save_settings(self, component_id: str, values: dict[str, Any]):
        return self._catalog.save_component_settings(str(component_id), dict(values))

    def admit(self, action: str, payload: dict[str, Any]):
        operations = services().get(InstallableOperationsService)
        normalized = str(action).strip().lower()
        if normalized == "uninstall":
            return operations.uninstall(dict(payload))
        if normalized == "initialize":
            return operations.initialize(dict(payload))
        return operations.install(dict(payload))

    def cancel_queued(self, task_id: str) -> None:
        get_event_bus().emit("install_cancel_queued", {"task_id": str(task_id)})

    def cancel_running(self, task_id: str) -> None:
        from core.events import EventDelivery

        get_event_bus().emit(
            "install_cancel_running",
            {"task_id": str(task_id)},
            delivery=EventDelivery.COMMAND,
        )

    def purge_cache(self) -> bool:
        from utils.pip_installer import PipInstaller
        from main_logger import logger

        return bool(PipInstaller(update_log=logger.info).purge_cache())


@dataclass(slots=True)
class _ApplicationController:
    _main_controller: Any = None
    _startup_error: str = ""
    # Единый источник истины для «Python обновлён, нужен перезапуск» и
    # троттлинга проверки обновлений. Раньше это состояние жило атрибутами
    # на окне (_pending_python_restart_version) и читалось тремя слоями.
    _pending_restart_version: str = ""
    _last_update_check_ts: float = 0.0

    @property
    def main_controller(self):
        return self._main_controller

    @property
    def pending_restart_version(self) -> str:
        return self._pending_restart_version

    def set_pending_restart_version(self, version: str | None) -> None:
        self._pending_restart_version = str(version or "").strip()

    @property
    def last_update_check_ts(self) -> float:
        return self._last_update_check_ts

    def mark_update_check(self, timestamp: float) -> None:
        self._last_update_check_ts = float(timestamp)

    @property
    def backend_ready(self) -> bool:
        return self._main_controller is not None and not bool(
            getattr(self._main_controller, "_closing_started", False)
        )

    @property
    def startup_error(self) -> str:
        return self._startup_error

    def attach_backend(self, controller: Any) -> None:
        self._main_controller = controller
        self._startup_error = ""

    def detach_backend(self) -> None:
        self._main_controller = None

    def mark_failed(self, message: str) -> None:
        self._main_controller = None
        self._startup_error = str(message or "")

    def gui_controller(self):
        controller = self._main_controller
        return getattr(controller, "gui_controller", None) if controller is not None else None

    def ensure_feature_async(self, feature: str):
        controller = self._main_controller
        if controller is None:
            raise RuntimeError(self._startup_error or "Main controller is not ready")
        return controller.ensure_feature_async(str(feature))

    def ensure_optional_gui(self, feature: str) -> None:
        gui_controller = self.gui_controller()
        if gui_controller is None:
            raise RuntimeError(self._startup_error or "GUI controller is not ready")
        gui_controller.ensure_optional_gui(str(feature))


class UiPresentationHub:
    """Application-facing controllers owned by the GUI composition root.

    Coordinators and ViewModel factories use this hub to assemble passive Qt
    views. Views receive only their narrow state/action dependencies and never
    resolve this hub, EventBus, service implementations, managers or databases.
    """

    def __init__(self) -> None:
        self.events = _EventsController()
        self.settings = _SettingsController()
        self.app = _ApplicationController()
        self.settings_data = _SettingsDataController()
        self.providers = _ProviderOptionsController(self.settings_data)
        self.settings_sections = _SettingsSectionsController(self)
        self.rag = _RagController()
        self.view_models = _ViewModelFactory(self)

    @cached_property
    def api_presets(self):
        return _ApiPresetController()

    @cached_property
    def embeddings(self):
        return _EmbeddingPresetController()

    @cached_property
    def characters(self):
        return _CharacterController()

    @cached_property
    def capture(self):
        return _CaptureController()

    @cached_property
    def finetune(self):
        return _FineTuneController()

    @cached_property
    def prompts(self):
        return _PromptController()

    @cached_property
    def telegram(self):
        return _TelegramController()

    @cached_property
    def voice(self):
        return _VoiceController()

    @cached_property
    def installables(self):
        return _InstallableController()

    @cached_property
    def beats(self):
        from controllers.gui.beat_settings_controller import BeatSettingsController

        return BeatSettingsController()

    @cached_property
    def home(self):
        from controllers.gui.home_page_controller import HomePageController

        return HomePageController()

    @cached_property
    def sandbox(self):
        from controllers.gui.sandbox_page_controller import SandboxPageController

        return SandboxPageController()

    @cached_property
    def news(self):
        return _NewsController()
