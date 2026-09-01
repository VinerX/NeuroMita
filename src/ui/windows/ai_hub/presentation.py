from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class AIHubState:
    rows: tuple[Any, ...] = ()
    hardware: Any = ()
    loaded_once: bool = False
    refreshing: bool = False
    last_check_ts: dt.datetime | None = None
    queue_state: Any = ()
    task_status: str = ""
    checking_component_ids: frozenset[str] = frozenset()
    install_bar_visible: bool = False
    install_logs_visible: bool = False
    install_title: str = ""
    install_progress: int | None = None
    install_detail: str = ""
    error: str | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class RefreshAIHub(UiIntent):
    force: bool = False
    include_status: bool | None = None
    status_category: str | None = None


@dataclass(frozen=True, slots=True)
class CancelQueuedInstall(UiIntent):
    task_id: str


@dataclass(frozen=True, slots=True)
class CancelRunningInstall(UiIntent):
    task_id: str


@dataclass(frozen=True, slots=True)
class ActivateAIHub(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class ClearInstallCache(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class RequestComponentAction(UiIntent):
    component_id: str
    action: str
    clean: bool = False


@dataclass(frozen=True, slots=True)
class ComponentActionContext:
    component_id: str
    action: str
    extra: Any = ()
    preview: Any = ()


@dataclass(frozen=True, slots=True)
class SubmitComponentAction(UiIntent):
    context: ComponentActionContext
    install_window: Any
    callbacks: Any


@dataclass(frozen=True, slots=True)
class ConfirmBackendInstall(UiEffect):
    context: ComponentActionContext


@dataclass(frozen=True, slots=True)
class PrepareComponentInstall(UiEffect):
    context: ComponentActionContext


@dataclass(frozen=True, slots=True)
class ComponentAdmissionFailed(UiEffect):
    task_id: str
    message: str
    install_window: Any = None


@dataclass(frozen=True, slots=True)
class AIHubShowError(UiEffect):
    title: str
    message: str
