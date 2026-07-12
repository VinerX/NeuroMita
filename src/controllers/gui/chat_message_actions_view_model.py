from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.chat.message_actions_presentation import (
    DeleteChatMessage,
    EditChatMessage,
    RegenerateChat,
    RegenerateChatFrom,
)
from ui.presentation import UiTopic


@dataclass(frozen=True, slots=True)
class _ChatMessageActionsState:
    revision: int = 0


class ChatMessageActionsViewModel(IntentViewModel[_ChatMessageActionsState]):
    def __init__(self, *, events, parent=None) -> None:
        super().__init__(_ChatMessageActionsState(), parent)
        self._events = events

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, DeleteChatMessage):
            self._events.publish(
                UiTopic.CHAT_DELETE_MESSAGE,
                {
                    "message_id": intent.message_id,
                    "character_id": intent.character_id,
                },
            )
            return
        if isinstance(intent, EditChatMessage):
            self._events.publish(
                UiTopic.CHAT_DELETE_MESSAGES_FROM,
                {
                    "message_id": intent.message_id,
                    "character_id": intent.character_id,
                    "edit_mode": True,
                },
            )
            return
        if isinstance(intent, RegenerateChat):
            self._events.publish(
                UiTopic.CHAT_REGENERATE,
                {"character_id": intent.character_id},
            )
            return
        if isinstance(intent, RegenerateChatFrom):
            self._events.publish(
                UiTopic.CHAT_REGENERATE_FROM,
                {
                    "message_id": intent.message_id,
                    "character_id": intent.character_id,
                },
            )
