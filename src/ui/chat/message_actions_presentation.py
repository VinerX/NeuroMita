from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiIntent


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
