from __future__ import annotations

from dataclasses import dataclass, field

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class HomeUpdateState:
    available: bool = False
    installable: bool = False
    selected: bool = False
    latest_version: str = ""


@dataclass(frozen=True, slots=True)
class HomeNewsItemState:
    title: str
    summary: str
    item_id: str = ""
    timestamp: str = ""
    full_text: str = ""


@dataclass(frozen=True, slots=True)
class HomeState:
    backend_status: str = ""
    unity_status: str = ""
    unity_installed: bool = False
    unity_process_state: str = "stopped"
    unity_process_error: str = ""
    python_update: HomeUpdateState = field(default_factory=HomeUpdateState)
    unity_update: HomeUpdateState = field(default_factory=HomeUpdateState)
    primary_action: str = "install"
    primary_label: str = ""
    primary_icon_name: str = "fa6s.download"
    operation: str | None = None
    operation_component: str = ""
    operation_stage: str = ""
    operation_item_index: int = 0
    operation_item_total: int = 0
    progress_visible: bool = False
    progress_text: str = ""
    progress_value: int = 0
    progress_maximum: int = 100
    progress_busy: bool = False
    can_cancel: bool = False
    news: tuple[HomeNewsItemState, ...] = ()
    update_checking: bool = False
    pending_restart_version: str = ""
    error: str | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class HomeActivated(UiIntent):
    force_update_check: bool = False


@dataclass(frozen=True, slots=True)
class HomeLanguageChanged(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeRefreshUpdates(UiIntent):
    force: bool = False
    show_result: bool = False


@dataclass(frozen=True, slots=True)
class HomeRefreshNews(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeExternalProgress(UiIntent):
    text: str
    value: int
    maximum: int
    busy: bool = False


@dataclass(frozen=True, slots=True)
class HomeHideProgress(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeToggleUpdate(UiIntent):
    component: str
    selected: bool


@dataclass(frozen=True, slots=True)
class HomePrimaryRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeInstallUnityRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeApplyUpdatesRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeOpenUnityFolderRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeCancelRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeStopUnityRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class HomeTesterCodeSubmitted(UiIntent):
    continuation: str
    code: str | None


@dataclass(frozen=True, slots=True)
class HomeRestartDecision(UiIntent):
    accepted: bool


@dataclass(frozen=True, slots=True)
class HomeOpenReleaseRequested(UiIntent):
    release_id: str


@dataclass(frozen=True, slots=True)
class HomePromptTesterCode(UiEffect):
    continuation: str


@dataclass(frozen=True, slots=True)
class HomePromptRestart(UiEffect):
    pass


@dataclass(frozen=True, slots=True)
class HomeShowError(UiEffect):
    title: str
    message: str


@dataclass(frozen=True, slots=True)
class HomeOpenRelease(UiEffect):
    release_id: str


@dataclass(frozen=True, slots=True)
class HomeRefreshSidebar(UiEffect):
    pass
