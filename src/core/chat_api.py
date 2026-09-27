from __future__ import annotations

from typing import List, Optional

from core.services import use
from services.contracts import ChatService


class ChatAPI:
    """Static application facade for semantic character turns."""

    @staticmethod
    def reply(
        *,
        character_id: str,
        message_id: str,
        user_input: str = "",
        system_input: str = "",
        sender: str = "Player",
        participants: Optional[List[str]] = None,
    ) -> bool:
        return use(ChatService).reply(
            character_id=character_id,
            message_id=message_id,
            user_input=user_input,
            system_input=system_input,
            sender=sender,
            participants=participants,
        )

    @staticmethod
    def react(
        *,
        character_id: str,
        instruction: str,
        visible: bool = True,
        sender: str = "Player",
        participants: Optional[List[str]] = None,
    ) -> bool:
        return use(ChatService).react(
            character_id=character_id,
            instruction=instruction,
            visible=visible,
            sender=sender,
            participants=participants,
        )

    @staticmethod
    def initiate(
        *,
        character_id: str,
        instruction: str,
        sender: str = "System",
        participants: Optional[List[str]] = None,
    ) -> bool:
        return use(ChatService).initiate(
            character_id=character_id,
            instruction=instruction,
            sender=sender,
            participants=participants,
        )
