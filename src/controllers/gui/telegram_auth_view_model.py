from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.dialogs.telegram_auth_presentation import (
    RejectTelegramAuth,
    SubmitTelegramAuth,
)


@dataclass(frozen=True, slots=True)
class TelegramAuthState:
    revision: int = 0


class TelegramAuthViewModel(IntentViewModel[TelegramAuthState]):
    def __init__(self, *, auth, parent=None) -> None:
        super().__init__(TelegramAuthState(), parent)
        self._auth = auth

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, SubmitTelegramAuth):
            self._auth.resolve(intent.request_id, intent.value)
            return
        if isinstance(intent, RejectTelegramAuth):
            self._auth.reject(intent.request_id, intent.reason)