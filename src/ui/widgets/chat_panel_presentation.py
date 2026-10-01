from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from ui.mvvm import UiEffect, UiIntent
from services.contracts import ASRCaptureState, DialogueRuntimeSnapshot


@dataclass(frozen=True, slots=True)
class ChatPanelState:
    character_id: str = ""
    blocked: bool = False
    warning: str = ""
    settings_category: str = "api"
    backend_ready: bool = False
    can_send: bool = False
    active_generation_count: int = 0
    has_text: bool = False
    staged_count: int = 0
    revision: int = 0
    dialogue_snapshot: DialogueRuntimeSnapshot | None = None
    capture: ASRCaptureState = ASRCaptureState()
    capture_owned: bool = False

    @property
    def asr_busy(self) -> bool:
        return self.capture.enabled and self.capture.phase == "recognizing"

    @property
    def can_submit(self) -> bool:
        return self.can_send and not self.asr_busy


@dataclass(frozen=True, slots=True)
class ChatMicrophoneToggled(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class ChatPanelActions:
    reload_history: Callable[[], Any]
    clear_chat: Callable[[], Any]
    send_message: Callable[[], Any]
    cancel_active_generations: Callable[[], Any]
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
