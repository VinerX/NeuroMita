from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class RagInstallTargetState:
    """Статус установки одной цели RAG (эмбеддинги или реранкер)."""

    backend: str = ""
    index: str = ""
    model: str = ""
    loaded: str = ""
    button_visible: bool = False
    button_busy: bool = False
    loading: bool = True


@dataclass(frozen=True, slots=True)
class RagInstallState:
    embeddings: RagInstallTargetState = RagInstallTargetState()
    reranker: RagInstallTargetState = RagInstallTargetState()


@dataclass(frozen=True, slots=True)
class ActivateRagInstall(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class RefreshRagInstall(UiIntent):
    force: bool = False


@dataclass(frozen=True, slots=True)
class OpenRagAiHub(UiIntent):
    target: str = ""


@dataclass(frozen=True, slots=True)
class RagInstallShowError(UiEffect):
    title: str = ""
    message: str = ""
