from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from main_logger import logger


class HomePageController:
    """Application operations consumed by the passive launcher home view."""

    @staticmethod
    def base_dir() -> str | None:
        return os.environ.get("NEUROMITA_BASE_DIR") or None

    def unity_install_dir(self, configured: str | None = None) -> Path:
        if configured:
            return Path(str(configured))
        base_dir = os.environ.get("NEUROMITA_BASE_DIR", "")
        if base_dir:
            return Path(base_dir) / "NeuroMita-Unity"
        return Path(sys.argv[0]).resolve().parent / "NeuroMita-Unity"

    def find_unity_executable(self, configured: str | None = None) -> Path | None:
        root = self.unity_install_dir(configured)
        if not root.exists() or not root.is_dir():
            return None

        executable_files = list(root.glob("*.exe")) + list(root.glob("*/*.exe"))
        if not executable_files:
            return None

        preferred = ("NeuroMita.exe", "NeuroMita-Unity.exe", "Unity.exe")
        by_name = {path.name.lower(): path for path in executable_files}
        for name in preferred:
            hit = by_name.get(name.lower())
            if hit is not None:
                return hit

        for path in executable_files:
            name = path.name.lower()
            if "neuromita" in name or "unity" in name:
                return path
        return executable_files[0]

    def open_unity_folder(self, configured: str | None = None) -> None:
        directory = self.unity_install_dir(configured)
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(directory)])

    def launch_unity(self, configured: str | None = None) -> Path:
        executable = self.find_unity_executable(configured)
        if executable is None:
            raise FileNotFoundError("Unity executable is not installed")
        subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return executable

    def update_info(
        self,
        *,
        channel: str,
        unity_dir: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from updater import get_python_update_info, get_unity_update_info

        base_dir = self.base_dir()
        return (
            dict(get_python_update_info(base_dir=base_dir, channel=channel) or {}),
            dict(
                get_unity_update_info(
                    base_dir=base_dir,
                    unity_dir=unity_dir or None,
                    channel=channel,
                )
                or {}
            ),
        )

    def install_unity(
        self,
        *,
        channel: str,
        tester_code: str | None,
        unity_dir: str | None,
        logger_adapter: Any,
        on_progress: Callable[[int, int], None],
        on_extract_progress: Callable[[int, int], None],
        stop_event: Any,
    ) -> dict[str, Any]:
        from updater import check_for_unity_updates, get_unity_update_info

        base_dir = self.base_dir()
        info = dict(
            get_unity_update_info(
                base_dir=base_dir,
                unity_dir=unity_dir or None,
                channel=channel,
            )
            or {}
        )
        if not info.get("ok"):
            return {"ok": False, "error": info.get("error") or "unknown error"}
        if not info.get("available") and self.find_unity_executable(unity_dir) is not None:
            return {"ok": True, "already_installed": True}

        check_for_unity_updates(
            base_dir=base_dir,
            logger=logger_adapter,
            unity_dir=unity_dir or None,
            channel=channel,
            tester_code=tester_code or None,
            on_progress=on_progress,
            on_extract_progress=on_extract_progress,
            auto_update=True,
            stop_event=stop_event,
        )
        return {"ok": True, "cancelled": bool(stop_event.is_set())}

    def apply_updates(
        self,
        *,
        update_python: bool,
        update_unity: bool,
        channel: str,
        tester_code: str,
        unity_dir: str | None,
        update_mode: str,
        preserve_prompts: bool,
        logger_adapter: Any,
        on_progress: Callable[[int, int], None],
        on_extract_progress: Callable[[int, int], None],
        stop_event: Any,
    ) -> dict[str, Any]:
        from updater import check_for_unity_updates, check_for_updates

        base_dir = self.base_dir()
        python_applied = False
        if update_python:
            python_applied = bool(
                check_for_updates(
                    base_dir=base_dir,
                    logger=logger_adapter,
                    channel=channel,
                    tester_code=tester_code,
                    on_progress=on_progress,
                    auto_update=True,
                    restart_on_success=False,
                    update_mode=update_mode or "diff",
                    preserve_prompts=bool(preserve_prompts),
                )
            )
        if update_unity and not stop_event.is_set():
            check_for_unity_updates(
                base_dir=base_dir,
                logger=logger_adapter,
                unity_dir=unity_dir or None,
                channel=channel,
                tester_code=tester_code,
                on_progress=on_progress,
                on_extract_progress=on_extract_progress,
                auto_update=True,
                stop_event=stop_event,
            )
        return {
            "python_applied": python_applied,
            "cancelled": bool(stop_event.is_set()),
        }

    @staticmethod
    def restart_application() -> bool:
        from utils.app_restart import restart_app

        return bool(restart_app())
