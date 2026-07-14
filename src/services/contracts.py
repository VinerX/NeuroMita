"""Контракты сервисов рантайма.

Здесь только абстракции и типы данных: ни один контракт не тянет контроллеры,
UI или тяжёлые зависимости. Реализации живут рядом (services/*) либо у своего
владельца-контроллера.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, Iterable, List, Optional

from core.request_policy import RequestPolicy


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

class SettingsService(ABC):
    """Единственный источник значений настроек."""

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any: ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Записать в память (без сохранения на диск)."""

    @abstractmethod
    def save_settings(self) -> None: ...

    @abstractmethod
    def update(self, key: str, value: Any) -> None:
        """Atomically update the in-memory registry and schedule persistence."""

    def require(self, key: str) -> Any:
        value = self.get(key, None)
        if value is None:
            raise KeyError(key)
        return value

    def snapshot(self, keys: Iterable[str] | None = None) -> Dict[str, Any]:
        raise NotImplementedError

    def subscribe(
        self,
        callback: Callable[[Any], None],
        *,
        keys: Iterable[str] | None = None,
        replay: bool = False,
    ) -> Any:
        raise NotImplementedError


class ASRSettingsService(ABC):
    """Single owner of the selected ASR engine and per-engine settings."""

    @property
    @abstractmethod
    def revision(self) -> int: ...

    @abstractmethod
    def snapshot(self) -> Dict[str, Any]: ...

    @abstractmethod
    def selected_engine(self) -> str: ...

    @abstractmethod
    def model_settings(self, engine_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def set_selected_engine(self, engine_id: str) -> None: ...

    @abstractmethod
    def set_model_settings(self, engine_id: str, values: Dict[str, Any]) -> None: ...

    @abstractmethod
    def set_model_option(self, engine_id: str, key: str, value: Any) -> None: ...

    @abstractmethod
    def subscribe(self, callback: Callable[[Any], None], *, replay: bool = False) -> Any: ...


class InstallableCatalogService(ABC):
    """Canonical catalog, lifecycle status and readiness of AI components.

    UI and runtime consumers must not inspect packages, files or backends on
    their own.  They read the same component snapshot through this contract.
    """

    def close(self) -> None:
        """Release asynchronous probes and reject late lifecycle results."""

    @abstractmethod
    def list_rows(
        self,
        *,
        include_status: bool = False,
        refresh: bool = False,
        category: str | None = None,
        status_category: str | None = None,
        ctx: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]: ...

    def get_row(
        self,
        component_id: str,
        *,
        include_status: bool = True,
        refresh: bool = False,
        ctx: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        normalized = str(component_id or "").strip()
        category = normalized.split(":", 1)[0]
        for row in self.list_rows(
            include_status=include_status,
            refresh=refresh,
            category=category,
            status_category=category,
            ctx=ctx,
        ):
            metadata = row.get("metadata") if isinstance(row, dict) else None
            if isinstance(metadata, dict) and metadata.get("id") == normalized:
                return row
        raise KeyError(normalized)

    def get_status(
        self,
        component_id: str,
        *,
        refresh: bool = False,
        ctx: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return dict(
            self.get_row(
                component_id,
                include_status=True,
                refresh=refresh,
                ctx=ctx,
            ).get("status")
            or {}
        )

    def is_ready(
        self,
        component_id: str,
        *,
        refresh: bool = False,
        ctx: Dict[str, Any] | None = None,
    ) -> bool:
        return bool(self.get_status(component_id, refresh=refresh, ctx=ctx).get("ready"))

    def ready_item_ids(
        self,
        category: str,
        *,
        refresh: bool = False,
        ctx: Dict[str, Any] | None = None,
    ) -> tuple[str, ...]:
        result: list[str] = []
        for row in self.list_rows(
            include_status=True,
            refresh=refresh,
            category=category,
            status_category=category,
            ctx=ctx,
        ):
            metadata = row.get("metadata") if isinstance(row, dict) else None
            status = row.get("status") if isinstance(row, dict) else None
            if isinstance(metadata, dict) and isinstance(status, dict) and status.get("ready"):
                result.append(str(metadata.get("item_id") or ""))
        return tuple(item for item in result if item)

    def list_rows_async(
        self,
        callback: Callable[[List[Dict[str, Any]], BaseException | None], None],
        *,
        include_status: bool = False,
        refresh: bool = False,
        category: str | None = None,
        status_category: str | None = None,
        ctx: Dict[str, Any] | None = None,
    ) -> None:
        try:
            callback(
                self.list_rows(
                    include_status=include_status,
                    refresh=refresh,
                    category=category,
                    status_category=status_category,
                    ctx=ctx,
                ),
                None,
            )
        except BaseException as exc:
            callback([], exc)

    def get_status_async(
        self,
        component_id: str,
        callback: Callable[[Dict[str, Any], BaseException | None], None],
        *,
        refresh: bool = False,
        ctx: Dict[str, Any] | None = None,
    ) -> None:
        try:
            callback(self.get_status(component_id, refresh=refresh, ctx=ctx), None)
        except BaseException as exc:
            callback({}, exc)

    @abstractmethod
    def require_component(self, component_id: str, *, refresh: bool = False) -> Any: ...

    @abstractmethod
    def install_preview(
        self,
        component_id: str,
        *,
        ctx: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    def invalidate(self, component_id: str | None = None) -> None: ...

    @abstractmethod
    def settings_schema(self, component_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def load_settings(self, component_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def save_component_settings(
        self, component_id: str, values: Dict[str, Any]
    ) -> Dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class InstallAdmission:
    """Synchronous result of handing an install operation to its queue."""

    accepted: bool
    task_id: str
    duplicate: bool = False
    error: str = ""


class InstallQueueService(ABC):
    """Owns serialized install execution independently from EventBus delivery."""

    @abstractmethod
    def enqueue(
        self,
        payload: Dict[str, Any],
        *,
        with_ui: bool,
    ) -> InstallAdmission: ...


class InstallQueueAdministrationService(ABC):
    """Maintenance boundary for pausing all writes into AI environments."""

    @abstractmethod
    def quiesce(self, *, timeout: float = 30.0) -> bool: ...

    @abstractmethod
    def resume(self) -> None: ...


class InstallableOperationsService(ABC):
    """Typed command boundary for installable component lifecycle operations."""

    @abstractmethod
    def install(self, payload: Dict[str, Any]) -> InstallAdmission: ...

    @abstractmethod
    def uninstall(self, payload: Dict[str, Any]) -> InstallAdmission: ...

    @abstractmethod
    def initialize(self, payload: Dict[str, Any]) -> InstallAdmission: ...


class RuntimeFeatureService(ABC):
    """Lifecycle optional-компонентов. Не содержит предметной логики feature."""

    @abstractmethod
    def ensure_async(self, name: str) -> Future[Any]: ...

    @abstractmethod
    def ensure(self, name: str, *, timeout: float | None = None) -> Any: ...

    @abstractmethod
    def get(self, name: str, default: Any = None) -> Any: ...

    @abstractmethod
    def is_ready(self, name: str) -> bool: ...

    @abstractmethod
    def snapshot(self) -> Dict[str, Dict[str, Any]]: ...


class AppVarsService(ABC):
    """Флаги приложения, которые видит DSL промптов."""

    @abstractmethod
    def snapshot(self) -> Dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Персонажи
# ---------------------------------------------------------------------------

class CharacterRegistry(ABC):
    @abstractmethod
    def get(self, character_id: str) -> Any:
        """Ссылка на персонажа или None, если такого id нет."""

    @abstractmethod
    def all_ids(self) -> List[str]: ...

    @abstractmethod
    def current(self) -> Any: ...

    @abstractmethod
    def current_id(self) -> str: ...

    @abstractmethod
    def current_profile(self) -> Dict[str, Any]: ...

    @abstractmethod
    def current_name(self) -> str: ...

    def name_of(self, character_id: str) -> str:
        """Имя персонажа; если его нет — сам id (для подписей в UI)."""
        if not character_id:
            return ""
        ref = self.get(str(character_id))
        return str(getattr(ref, "name", "") or character_id)


# ---------------------------------------------------------------------------
# asyncio loop
# ---------------------------------------------------------------------------

class LoopService(ABC):
    @abstractmethod
    def loop(self) -> asyncio.AbstractEventLoop:
        """Живой loop. Если его нет — RuntimeError, а не None."""

    @abstractmethod
    def is_running(self) -> bool: ...

    @abstractmethod
    def run(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        """Запустить корутину в loop из любого потока."""


# ---------------------------------------------------------------------------
# Связь с игрой
# ---------------------------------------------------------------------------

class GameLinkService(ABC):
    @abstractmethod
    def is_connected(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    """Capabilities of the currently available game/runtime channel."""

    connected: bool | None = None
    remote_only: bool | None = None
    structured_segment_exclude_fields: tuple[str, ...] = ()


class RuntimeCapabilitiesService(ABC):
    """Single source of truth for runtime-dependent prompt capabilities."""

    @abstractmethod
    def snapshot(self) -> RuntimeCapabilities: ...


# ---------------------------------------------------------------------------
# История
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PreparedHistory:
    messages: List[Dict[str, Any]]
    summary: str = ""


class HistoryService(ABC):
    @abstractmethod
    def prepare_for_prompt(
        self,
        *,
        character: Any,
        memory_limit: int,
        is_game_master: bool,
        save_missed_history: bool,
        image_quality: Dict[str, Any],
    ) -> PreparedHistory: ...


# ---------------------------------------------------------------------------
# Промпт
# ---------------------------------------------------------------------------

@dataclass
class PromptBuildRequest:
    character: Any
    event_type: str
    policy: RequestPolicy
    user_input: str = ""
    system_input: str = ""
    rag_context: str = ""
    hidden_user_context: str = ""
    image_data: List[Any] = field(default_factory=list)
    memory_limit: int = 40
    is_game_master: bool = False
    save_missed_history: bool = True
    image_quality: Dict[str, Any] = field(default_factory=dict)
    separate_prompts: bool = True
    extra_system_infos: List[Any] = field(default_factory=list)
    game_state: Dict[str, Any] = field(default_factory=dict)
    sender: str = "Player"
    participants: List[str] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptBuildResult:
    messages: List[Dict[str, Any]]
    history_messages: List[Dict[str, Any]]
    user_message: Optional[Dict[str, Any]]


class PromptBuilderService(ABC):
    @abstractmethod
    def build(self, request: PromptBuildRequest) -> PromptBuildResult: ...


# ---------------------------------------------------------------------------
# Генерация
# ---------------------------------------------------------------------------

@dataclass
class ChatGenerationRequest:
    """Пользовательская генерация: chat / react / idle / camera и т.п."""

    character_id: Optional[str] = None
    user_input: str = ""
    system_input: str = ""
    image_data: List[Any] = field(default_factory=list)
    image_source: str = ""
    stream_callback: Optional[Any] = None
    event_type: str = "chat"
    sender: str = "Player"
    participants: List[str] = field(default_factory=list)
    req_id: Optional[str] = None
    origin_message_id: Optional[str] = None
    task_uid: Optional[str] = None
    policy: Optional[RequestPolicy] = None
    disable_history_compression: bool = False


@dataclass(frozen=True)
class ChatGenerationResult:
    text: str
    character_id: str
    voice_profile: Optional[Dict[str, Any]] = None
    target: str = "Player"
    targets: List[str] = field(default_factory=list)
    think: Optional[str] = None
    structured: Optional[Dict[str, Any]] = None
    message_id: str = ""


@dataclass
class UtilityGenerationRequest:
    """Служебная одноразовая генерация: сжатие истории, graph extraction.

    Никакой истории, персонажа-контекста и записи в историю — только один
    пользовательский запрос к провайдеру.
    """

    prompt: str
    character_id: str
    kind: str  # "compress" | "graph_extract"
    preset_id: Optional[int] = None
    max_attempts: int = 1
    retry_delay: float = 0.0
    request_timeout: float = 240.0


@dataclass(frozen=True)
class UtilityGenerationResult:
    ok: bool
    text: str = ""
    error: str = ""
    details: str = ""
    status_code: Optional[int] = None
    retryable: bool = False
    retry_after_sec: Optional[float] = None
    provider: Optional[str] = None


class GenerationService(ABC):
    @abstractmethod
    def generate_chat(self, request: ChatGenerationRequest) -> Optional[ChatGenerationResult]: ...

    @abstractmethod
    def generate_utility(self, request: UtilityGenerationRequest) -> UtilityGenerationResult: ...


# ---------------------------------------------------------------------------
# API-пресеты
# ---------------------------------------------------------------------------

class ApiPresetService(ABC):
    """Чтение эффективных API-пресетов. На пути генерации резолвер берёт пресет
    отсюда напрямую, а не через синхронный EventBus-запрос — синхронный сбор ответов шины на
    hot-path запрещён guardrail'ом."""

    @abstractmethod
    def get_full(self, preset_id: int) -> Optional[Dict[str, Any]]:
        """Эффективный словарь пресета (шаблон + пользовательские оверрайды) или None."""

    @abstractmethod
    def list_meta(self) -> Dict[str, Any]:
        """Метаданные пресетов: {"builtin": [...], "custom": [...]}."""

    @abstractmethod
    def current_id(self) -> Optional[int]:
        """Id текущего выбранного пресета или None."""

    @abstractmethod
    def save_custom(self, data: Dict[str, Any]) -> Optional[int]: ...

    @abstractmethod
    def delete_custom(self, preset_id: int) -> bool: ...

    @abstractmethod
    def save_order(self, order: Iterable[int]) -> bool: ...

    @abstractmethod
    def export_preset(self, preset_id: int, path: str) -> bool: ...

    @abstractmethod
    def import_preset(self, path: str) -> Optional[int]: ...

    @abstractmethod
    def save_state(self, preset_id: int, state: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def load_state(self, preset_id: int) -> Dict[str, Any]: ...

    @abstractmethod
    def set_current(self, preset_id: int | None) -> bool: ...


class TelegramService(ABC):
    """Typed Telegram relay API."""

    @abstractmethod
    def is_silero_connected(self) -> bool:
        """Подключён ли Silero-релей озвучки."""

    @abstractmethod
    async def send_voice(
        self, text: str, speaker_command: str, message_id: int = 0
    ) -> str: ...


class TelegramAuthService(ABC):
    @abstractmethod
    async def request(
        self, kind: str, *, error: str = "", attempt: int = 1
    ) -> str: ...

    @abstractmethod
    def resolve(self, request_id: str, value: str) -> bool: ...

    @abstractmethod
    def reject(self, request_id: str, reason: str = "Cancelled") -> bool: ...


class ModelStateService(ABC):
    @abstractmethod
    def debug_info(self, character_id: str | None = None) -> str: ...

    @abstractmethod
    def token_stats(self) -> Dict[str, Any]: ...

    @abstractmethod
    def schedule_g4f_update(self, version: str = "latest") -> bool: ...


class CaptureService(ABC):
    @abstractmethod
    def capture_screen(self, limit: int = 1) -> List[Any]: ...

    @abstractmethod
    def camera_frames(self, limit: int = 1) -> List[Any]: ...

    @abstractmethod
    def screen_capture_active(self) -> bool: ...

    @abstractmethod
    def camera_capture_active(self) -> bool: ...


class AudioStateService(ABC):
    @abstractmethod
    def is_waiting_answer(self) -> bool: ...


class LocalVoiceService(ABC):
    @abstractmethod
    def model_configs(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def is_installed(self, model_id: str) -> bool: ...

    @abstractmethod
    def check_initialized(self, model_id: str, *, strict: bool = False) -> bool: ...

    @abstractmethod
    def select_model(self, model_id: str) -> bool: ...

    @abstractmethod
    def initialize_model(self, model_id: str) -> Any: ...

    @abstractmethod
    def triton_status(self, *, refresh: bool = False) -> Dict[str, Any]: ...

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        character_id: Optional[str] = None,
        voice_profile: Optional[Dict[str, Any]] = None,
    ) -> str: ...


class VoiceModelService(ABC):
    @abstractmethod
    def model_catalog_snapshot(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def installed_models_snapshot(self) -> set[str]: ...

    @abstractmethod
    def dependencies_status(self) -> Dict[str, Any]: ...


class SpeechService(ABC):
    @abstractmethod
    def recognizer_settings_schema(self, engine: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def recognizer_settings(self, engine: str) -> Dict[str, Any]: ...

    @abstractmethod
    def mic_active(self) -> bool: ...

    @abstractmethod
    def microphone_list_async(
        self,
        callback: Callable[[List[str], BaseException | None], None],
    ) -> None: ...

    @abstractmethod
    def asr_models_glossary_async(
        self,
        callback: Callable[[List[Dict[str, Any]], BaseException | None], None],
        *,
        refresh: bool = False,
    ) -> None: ...

    @abstractmethod
    def asr_model_installed_async(
        self,
        engine: str,
        callback: Callable[[bool, BaseException | None], None],
    ) -> None: ...


class InstallService(ABC):
    @abstractmethod
    def run_blocking(self, payload: Dict[str, Any]) -> bool: ...


class GuiInteractionService(ABC):
    @abstractmethod
    def native_window_id(self) -> int | None: ...

    @abstractmethod
    def confirm(self, kind: str, payload: Dict[str, Any]) -> bool: ...


class TaskService(ABC):
    """Задачи диалога/idle игрового сервера. Обработчики TCP-действий живут в
    asyncio-loop сервера, где синхронный EventBus-запрос запрещён (блокирует весь loop) —
    они зовут это напрямую. Операции быстрые, в памяти."""

    @abstractmethod
    def create_task(self, task_type: str, data: Dict[str, Any]) -> Any:
        """Создать задачу и уведомить подписчиков (TASK_CREATED)."""

    @abstractmethod
    def get_task(self, uid: str) -> Optional[Any]:
        """Задача по uid или None."""

    @abstractmethod
    def update_task_status(
        self,
        uid: str,
        status: Any,
        result: Any = None,
        error: Any = None,
    ) -> Optional[Any]:
        """Обновить статус задачи и уведомить (TASK_STATUS_CHANGED)."""


class AIEngineService(ABC):
    """Доступ к оркестратору AI-engine (подпроцессы tts/asr/rag/beats).
    rag_client берёт движок отсюда, чтобы hot-path эмбеддинг не звал
    синхронный EventBus-запрос 'ai_get_engine' из пула генерации."""

    @abstractmethod
    def get_engine(self) -> Optional[Any]:
        """Оркестратор движка (умеет .call(service, method, payload)) или None."""


class AIEngineAdministrationService(ABC):
    """Administrative lifecycle boundary; inference clients never depend on it."""

    @abstractmethod
    def topology_snapshot(self) -> Dict[str, Any]: ...

    @abstractmethod
    def switch_topology(self, mode: str, *, timeout: float = 30.0) -> Dict[str, Any]: ...

    @abstractmethod
    def suspend_for_maintenance(self, *, timeout: float = 15.0) -> bool: ...

    @abstractmethod
    def resume_after_maintenance(self) -> bool: ...


class HardwareInventoryService(ABC):
    """Canonical, cached hardware inventory used by UI and backend selection."""

    @abstractmethod
    def snapshot(self, *, refresh: bool = False) -> Dict[str, Any]: ...


class AIEnvironmentMaintenanceService(ABC):
    """Owns the state machine for resetting all managed AI environments."""

    @abstractmethod
    def snapshot(self) -> Dict[str, Any]: ...

    @abstractmethod
    def reset_all(
        self,
        *,
        progress: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]: ...


class EmbeddingPresetService(ABC):
    """Application-scoped embedding preset registry."""

    @abstractmethod
    def get_full(self, preset_id: Any) -> Optional[Dict[str, Any]]:
        """Разрешённый конфиг пресета или None."""

    @abstractmethod
    def list_meta(self) -> Dict[str, Any]:
        """Lightweight metadata for built-in and custom presets."""

    @abstractmethod
    def save(self, data: Dict[str, Any]) -> Any: ...

    @abstractmethod
    def delete(self, preset_id: Any) -> bool: ...

    @abstractmethod
    def rename(self, preset_id: Any, name: str) -> bool: ...

    @abstractmethod
    def reorder(self, order: Iterable[Any]) -> bool: ...


class EmbeddingService(ABC):
    """Локальные эмбеддинги RAG. Реальный бэкенд живёт в AI-engine (service='rag');
    контроллер — мост к нему. RAG зовёт это напрямую вместо синхронного EventBus-запроса, чтобы
    hot-path эмбеддинг запроса не падал guardrail'ом в пуле генерации."""

    @abstractmethod
    def embed_one(self, text: str, prefix: str = "") -> Optional[Any]:
        """Один вектор (np.ndarray) или None (не-local провайдер / ошибка)."""

    @abstractmethod
    def embed_many(
        self,
        texts: List[str],
        prefix: str = "",
        batch_size: Optional[int] = None,
        priority: str = "hot",
    ) -> List[Optional[Any]]:
        """Список векторов (по одному на текст; None на позициях-ошибках)."""


class ProtocolBuilderService(ABC):
    """Сборка финального HTTP-запроса (url + headers) по правилам auth протокола.
    На пути генерации резолвер зовёт это напрямую, минуя шину."""

    @abstractmethod
    def build_http_request(
        self,
        *,
        protocol_id: str,
        url: str,
        api_key: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Возвращает {"url": str, "headers": dict, "safe_url": str}."""

    @abstractmethod
    def list_protocols(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_protocol(self, protocol_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def list_transforms(self) -> List[Dict[str, Any]]: ...
