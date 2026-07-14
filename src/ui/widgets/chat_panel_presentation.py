from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class ChatPanelState:
    character_id: str = ""
    blocked: bool = False
    warning: str = ""
    settings_category: str = "api"
    backend_ready: bool = False
    can_send: bool = False
    has_text: bool = False
    staged_count: int = 0
    revision: int = 0


@dataclass(frozen=True, slots=True)
class ChatPanelActions:
    reload_history: Callable[[], Any]
    clear_chat: Callable[[], Any]
    send_message: Callable[[], Any]
    open_settings: Callable[[str], Any]
    show_image: Callable[[bytes], Any]
    surface_ready: Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class ChatPanelActivated(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class ChatInputChanged(UiIntent):
    has_text: bool
    staged_count: int


@dataclass(frozen=True, slots=True)
class ChatOpenHistoryRequested(UiIntent):
    character_id: str = ""


@dataclass(frozen=True, slots=True)
class ChatStageFilesRequested(UiIntent):
    paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChatStageImageRequested(UiIntent):
    image_data: bytes


@dataclass(frozen=True, slots=True)
class ChatClearStagedRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class ChatCaptureScreenRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class ChatImagesStaged(UiEffect):
    images: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class ChatStagedCleared(UiEffect):
    pass


@dataclass(frozen=True, slots=True)
class ChatShowError(UiEffect):
    title: str
    message: str