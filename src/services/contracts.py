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
from typing import Any, Coroutine, Dict, List, Optional

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
        """set + save + Events.Core.SETTING_CHANGED."""


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
    def run(self, coro: Coroutine) -> Future:
        """Запустить корутину в loop из любого потока."""


# ---------------------------------------------------------------------------
# Связь с игрой
# ---------------------------------------------------------------------------

class GameLinkService(ABC):
    @abstractmethod
    def is_connected(self) -> bool: ...


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
    request_timeout: float = 60.0


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
    отсюда напрямую, а не через emit_and_wait — синхронный сбор ответов шины на
    hot-path запрещён guardrail'ом."""

    @abstractmethod
    def get_full(self, preset_id: int) -> Optional[Dict[str, Any]]:
        """Эффективный словарь пресета (шаблон + пользовательские оверрайды) или None."""

    @abstractmethod
    def list_meta(self) -> Dict[str, Any]:
        """Метаданные пресетов: {"builtin": [...], "custom": [...]}."""


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
