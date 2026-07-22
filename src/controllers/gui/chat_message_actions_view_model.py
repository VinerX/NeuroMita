from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.chat.message_actions_presentation import (
    DeleteChatMessage,
    EditChatMessage,
    RateChatSample,
    RegenerateChat,
    RegenerateChatFrom,
    RetryLastChat,
    ShowChatSampleContext,
    ShowChatSampleContextError,
    ViewChatSampleContext,
)
from controllers.gui.presentation_contracts import UiTopic


@dataclass(frozen=True, slots=True)
class _ChatMessageActionsState:
    revision: int = 0


class ChatMessageActionsViewModel(IntentViewModel[_ChatMessageActionsState]):
    def __init__(self, *, events, finetune, parent=None) -> None:
        super().__init__(_ChatMessageActionsState(), parent)
        self._events = events
        self._finetune = finetune

    def collection_enabled(self) -> bool:
        try:
            return bool(self._finetune.enabled())
        except Exception:
            return False

    def consume_pending_sample_id(self) -> str | None:
        if not self.collection_enabled():
            return None
        try:
            return self._finetune.pop_pending_sample_id()
        except Exception:
            return None

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
            return
        if isinstance(intent, RetryLastChat):
            self._events.publish(
                UiTopic.CHAT_RETRY_LAST,
                {"character_id": intent.character_id},
            )
            return
        if isinstance(intent, RateChatSample):
            self._finetune.update_rating(intent.sample_id, intent.rating)
            return
        if isinstance(intent, ViewChatSampleContext):
            self.run_latest(
                "chat-sample-context",
                lambda: self._load_context(intent.sample_id),
                lambda result: self._emit_context_result(result, intent.initial_tab),
                lambda error: self.emit_effect(
                    ShowChatSampleContextError(str(error), not_found=False)
                ),
            )

    def _load_context(self, sample_id: str) -> tuple[dict[str, Any] | None, bool]:
        normalized = str(sample_id or "").strip()
        if normalized:
            samples = self._finetune.load_samples()
            matched = next(
                (sample for sample in samples if str(sample.get("id") or "") == normalized),
                None,
            )
            if matched is not None:
                return dict(matched), False

        base = str(os.environ.get("NEUROMITA_BASE_DIR", "") or "").strip()
        path = (
            os.path.join(base, "SavedMessages", "last_request_context.json")
            if base
            else os.path.join("SavedMessages", "last_request_context.json")
        )
        if not os.path.isfile(path):
            return None, False
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return (dict(payload), True) if isinstance(payload, dict) else (None, False)

    def _emit_context_result(
        self,
        result: tuple[dict[str, Any] | None, bool],
        initial_tab: str,
    ) -> None:
        data, used_fallback = result
        if data is None:
            self.emit_effect(ShowChatSampleContextError("", not_found=True))
            return
        self.emit_effect(
            ShowChatSampleContext(
                data=data,
                initial_tab=str(initial_tab or "request"),
                used_fallback=bool(used_fallback),
            )
        )
