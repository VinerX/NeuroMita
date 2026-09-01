from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiIntent


@dataclass(frozen=True, slots=True)
class SubmitTelegramAuth(UiIntent):
    request_id: str
    value: str


@dataclass(frozen=True, slots=True)
class RejectTelegramAuth(UiIntent):
    request_id: str
    reason: str