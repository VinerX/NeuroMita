from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Any


@dataclass
class InstallCallbacks:
    progress: Callable[[int], None]
    status: Callable[[str], None]
    log: Callable[[str], None]


@dataclass
class InstallAction:
    type: str  # "pip" | "download_http" | "call" | "call_async"
    description: str = ""
    progress: int = 0
    progress_to: Optional[int] = None

    packages: Optional[list[str]] = None
    extra_args: Optional[list[str]] = None

    files: Optional[list[dict]] = None
    headers: Optional[dict[str, str]] = None

    fn: Optional[Callable[..., Any]] = None
    timeout_sec: Optional[float] = None


@dataclass
class InstallPlan:
    actions: list[InstallAction]
    already_installed: bool = False
    ok_status: str = "Done"
    already_installed_status: str = "Already installed"