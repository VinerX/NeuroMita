from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class RagPresetState:
    names: tuple[str, ...] = ()
    selected: str = "Custom"
    can_apply: bool = False
    can_delete: bool = False
    busy: bool = False


@dataclass(frozen=True, slots=True)
class ActivateRagPresets(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class SelectRagPreset(UiIntent):
    name: str


@dataclass(frozen=True, slots=True)
class RequestApplyRagPreset(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class ApplyRagPreset(UiIntent):
    name: str
    save_current_as: str | None = None


@dataclass(frozen=True, slots=True)
class RequestSaveRagPreset(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class SaveRagPreset(UiIntent):
    name: str


@dataclass(frozen=True, slots=True)
class RequestDeleteRagPreset(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class DeleteRagPreset(UiIntent):
    name: str


@dataclass(frozen=True, slots=True)
class InstallMissingRagModels(UiIntent):
    targets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfirmApplyRagPreset(UiEffect):
    name: str


@dataclass(frozen=True, slots=True)
class PromptSaveRagPreset(UiEffect):
    pass


@dataclass(frozen=True, slots=True)
class ConfirmDeleteRagPreset(UiEffect):
    name: str


@dataclass(frozen=True, slots=True)
class OfferMissingRagModels(UiEffect):
    missing: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class RagPresetShowError(UiEffect):
    title: str
    message: str