from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from core.backends import BackendKind


DEFAULT_INSTALL_TIMEOUT_SEC = 7_200_000.0
DEFAULT_INSTALL_NO_ACTIVITY_SEC = 3_600_000.0


@dataclass
class InstallCallbacks:
    progress: Callable[[int], None]
    status: Callable[[str], None]
    log: Callable[[str], None]
    raw_log: Optional[Callable[[str], None]] = None


@dataclass
class InstallAction:
    type: str  # "pip" | "download_http" | "call" | "call_async"
    description: str = ""
    progress: int = 0
    progress_to: Optional[int] = None

    packages: Optional[list[str]] = None
    extra_args: Optional[list[str]] = None
    uv_overrides: Optional[list[str]] = None

    files: Optional[list[dict]] = None
    headers: Optional[dict[str, str]] = None

    fn: Optional[Callable[..., Any]] = None
    timeout_sec: Optional[float] = None
    environment_mutation: bool = False


@dataclass
class InstallPlan:
    actions: list[InstallAction]
    already_installed: bool = False
    ok_status: str = "Done"
    already_installed_status: str = "Already installed"
    required_backend: Optional["BackendKind"] = None
    backend_context: dict[str, Any] = field(default_factory=dict)
    environment_id: Optional[str] = None
    environment_managed: bool = True
