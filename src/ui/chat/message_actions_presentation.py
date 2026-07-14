from __future__ import annotations

from dataclasses import dataclass

from typing import Any

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class DeleteChatMessage(UiIntent):
    message_id: str
    character_id: str


@dataclass(frozen=True, slots=True)
class EditChatMessage(UiIntent):
    message_id: str
    character_id: str


@dataclass(frozen=True, slots=True)
class RegenerateChat(UiIntent):
    character_id: str


@dataclass(frozen=True, slots=True)
class RegenerateChatFrom(UiIntent):
    message_id: str
    character_id: str


@dataclass(frozen=True, slots=True)
class RateChatSample(UiIntent):
    sample_id: str
    rating: int


@dataclass(frozen=True, slots=True)
class ViewChatSampleContext(UiIntent):
    sample_id: str
    initial_tab: str = "request"


@dataclass(frozen=True, slots=True)
class ShowChatSampleContext(UiEffect):
    data: Any
    initial_tab: str
    used_fallback: bool = False


@dataclass(frozen=True, slots=True)
class ShowChatSampleContextError(UiEffect):
    message: str
    not_found: bool = False
