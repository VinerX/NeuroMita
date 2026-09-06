from __future__ import annotations
from core.error_utils import format_exception

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from core.unity_installation import find_unity_executable, unity_install_dir
from main_logger import logger
from services.update_transaction import atomic_write_json, read_json


@dataclass(frozen=True, slots=True)
class UnityProcessSnapshot:
    state: str = "stopped"
    pid: int = 0
    exit_code: int | None = None
    error: str = ""


class HomePageController(QObject):
    """Application operations consumed by the passive launcher home view."""

    process_state_changed = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._snapshot = UnityProcessSnapshot()
        self._launched_executable: Path | None = None
        self._tracked_create_time = 0.0
        self._external_poll = QTimer(self)
        self._external_poll.setInterval(1000)
        self._external_poll.timeout.connect(self._poll_external_process)
        self._process.started.connect(self._on_process_started)
        self._process.finished.connect(self._on_process_finished)
        self._process.errorOccurred.connect(self._on_process_error)
        self._recover_process_marker()

    @property
    def process_snapshot(self) -> UnityProcessSnapshot:
        return self._snapshot

    def _publish_process_state(self, **changes: Any) -> None:
        values = {
            "state": self._snapshot.state,
            "pid": self._snapshot.pid,
            "exit_code": self._snapshot.exit_code,
            "error": self._snapshot.error,
            **changes,
        }
        self._snapshot = UnityProcessSnapshot(**values)
        self.process_state_changed.emit(self._snapshot)

    def _process_marker_path(self) -> Path:
        base = self.base_dir()
        root = Path(base) if base else Path(sys.argv[0]).resolve().parent
        return root / "_update_state" / "unity-process.json"

    def _write_process_marker(self, executable: Path, pid: int, create_time: float) -> None:
        atomic_write_json(
            self._process_marker_path(),
            {
                "schema": 1,
                "pid": int(pid),
                "executable": str(executable.resolve()),
                "create_time": float(create_time),
                "recorded_at": int(time.time()),
            },
        )

    def _clear_process_marker(self) -> None:
        self._process_marker_path().unlink(missing_ok=True)

    @staticmethod
    def _matching_process(pid: int, executable: Path, create_time: float = 0.0):
        try:
            import psutil

            process = psutil.Process(int(pid))
            actual_executable = Path(process.exe()).resolve()
            if os.path.normcase(str(actual_executable)) != os.path.normcase(str(executable.resolve())):
                return None
            actual_create_time = float(process.create_time())
            if create_time and abs(actual_create_time - float(create_time)) > 1.0:
                return None
            return process
        except Exception:
            return None

    def _attach_external_process(self, process, executable: Path) -> None:
        self._launched_executable = executable.resolve()
        self._tracked_create_time = float(process.create_time())
        pid = int(process.pid)
        self._write_process_marker(executable, pid, self._tracked_create_time)
        self._publish_process_state(state="running", pid=pid, exit_code=None, error="")
        if not self._external_poll.isActive():
            self._external_poll.start()

    def _recover_process_marker(self) -> None:
        state = read_json(self._process_marker_path())
        executable_text = str(state.get("executable") or "")
        pid = int(state.get("pid") or 0)
        if not executable_text or pid <= 0:
            return
        executable = Path(executable_text)
        process = self._matching_process(pid, executable, float(state.get("create_time") or 0.0))
        if process is None:
            self._clear_process_marker()
            return
        self._attach_external_process(process, executable)

    def refresh_process_state(self, configured: str | None = None) -> UnityProcessSnapshot:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            return self._snapshot
        if self._snapshot.state in {"running", "stopping"} and self._snapshot.pid > 0:
            self._poll_external_process()
            if self._snapshot.state in {"running", "stopping"}:
                return self._snapshot
        executable = self.find_unity_executable(configured)
        if executable is None:
            return self._snapshot
        try:
            import psutil

            expected = os.path.normcase(str(executable.resolve()))
            for process in psutil.process_iter(("pid", "exe", "create_time")):
                actual = str(process.info.get("exe") or "")
                if actual and os.path.normcase(str(Path(actual).resolve())) == expected:
                    self._attach_external_process(process, executable)
                    break
        except Exception:
            logger.debug("Could not scan for an already running Unity process", exc_info=True)
        return self._snapshot

    def _poll_external_process(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._external_poll.stop()
            return
        pid = int(self._snapshot.pid or 0)
        executable = self._launched_executable
        if pid <= 0 or executable is None:
            self._external_poll.stop()
            return
        if self._matching_process(pid, executable, self._tracked_create_time) is not None:
            return
        self._external_poll.stop()
        self._tracked_create_time = 0.0
        self._clear_process_marker()
        self._publish_process_state(state="stopped", pid=0, exit_code=None, error="")

    @staticmethod
    def base_dir() -> str | None:
        return os.environ.get("NEUROMITA_BASE_DIR") or None

    def unity_install_dir(self, configured: str | None = None) -> Path:
        return unity_install_dir(configured)

    def find_unity_executable(self, configured: str | None = None) -> Path | None:
        return find_unity_executable(self.unity_install_dir(configured))

    def open_unity_folder(self, configured: str | None = None) -> None:
        directory = self.unity_install_dir(configured)
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(directory)])

    def launch_unity(self, configured: str | None = None) -> Path:
        self.refresh_process_state(configured)
        if self._process.state() != QProcess.ProcessState.NotRunning or self._snapshot.state in {
            "starting",
            "running",
            "stopping",
        }:
            raise RuntimeError("Unity is already running or starting")
        executable = self.find_unity_executable(configured)
        if executable is None:
            raise FileNotFoundError("Unity executable is not installed")
        self._process.setWorkingDirectory(str(executable.parent))
        self._process.setProgram(str(executable))
        self._process.setArguments([])
        self._launched_executable = executable.resolve()
        self._publish_process_state(state="starting", pid=0, exit_code=None, error="")
        self._process.start()
        return executable

    def stop_unity(self, *, force_after_ms: int = 5000) -> bool:
        if self._process.state() == QProcess.ProcessState.NotRunning:
            pid = int(self._snapshot.pid or 0)
            executable = self._launched_executable
            process = (
                self._matching_process(pid, executable, self._tracked_create_time)
                if pid > 0 and executable is not None
                else None
            )
            if process is None:
                self._poll_external_process()
                return False
            self._publish_process_state(state="stopping", error="")
            process.terminate()

            def force_external_if_needed() -> None:
                current = self._matching_process(pid, executable, self._tracked_create_time)
                if current is not None:
                    logger.warning("Unity did not close gracefully; killing the external process")
                    current.kill()

            QTimer.singleShot(max(1000, int(force_after_ms)), force_external_if_needed)
            if not self._external_poll.isActive():
                self._external_poll.start()
            return True
        stopping_pid = int(self._process.processId() or 0)
        self._publish_process_state(state="stopping", error="")
        self._process.terminate()

        def force_if_needed() -> None:
            if (
                self._process.state() != QProcess.ProcessState.NotRunning
                and int(self._process.processId() or 0) == stopping_pid
            ):
                logger.warning("Unity did not close gracefully; killing the process")
                self._process.kill()

        QTimer.singleShot(max(1000, int(force_after_ms)), force_if_needed)
        return True

    def _on_process_started(self) -> None:
        pid = int(self._process.processId() or 0)
        create_time = 0.0
        if self._launched_executable is not None:
            process = self._matching_process(pid, self._launched_executable)
            if process is not None:
                create_time = float(process.create_time())
            self._tracked_create_time = create_time
            self._write_process_marker(self._launched_executable, pid, create_time)
        self._publish_process_state(
            state="running",
            pid=pid,
            exit_code=None,
            error="",
        )

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        crashed = exit_status == QProcess.ExitStatus.CrashExit
        self._tracked_create_time = 0.0
        self._clear_process_marker()
        self._publish_process_state(
            state="failed" if crashed else "stopped",
            pid=0,
            exit_code=int(exit_code),
            error=(
                self._process.errorString() or f"Unity crashed with exit code {exit_code}"
                if crashed
                else ""
            ),
        )

    def _on_process_error(self, error) -> None:
        message = self._process.errorString() or format_exception(error)
        state = "failed" if self._process.state() == QProcess.ProcessState.NotRunning else self._snapshot.state
        if state == "failed":
            self._clear_process_marker()
        self._publish_process_state(state=state, error=message)

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
        on_verify_progress: Callable[[int, int], None],
        on_stage: Callable[[str, str, int, int, bool], None],
        stop_event: Any,
    ) -> dict[str, Any]:
        from updater import check_for_unity_updates, check_for_updates

        base_dir = self.base_dir()
        results: dict[str, dict[str, Any]] = {}
        python_pending_restart = False
        if update_python:
            python_result = check_for_updates(
                base_dir=base_dir,
                logger=logger_adapter,
                channel=channel,
                tester_code=tester_code,
                on_progress=on_progress,
                on_extract_progress=on_extract_progress,
                on_stage=lambda name, index, total, can_cancel: on_stage(
                    "python", name, index, total, can_cancel
                ),
                auto_update=True,
                restart_on_success=False,
                update_mode=update_mode or "diff",
                preserve_prompts=bool(preserve_prompts),
                stop_event=stop_event,
            )
            results["python"] = python_result.as_dict()
            python_pending_restart = bool(python_result.restart_required)
        # Python is applied in-place and needs a later application restart, but
        # that must not cut a multi-component request short.  Continue with the
        # selected Unity install and let the view model offer one restart only
        # after the whole requested sequence has reached its outcome.
        if update_unity and not stop_event.is_set():
            unity_result = check_for_unity_updates(
                base_dir=base_dir,
                logger=logger_adapter,
                unity_dir=unity_dir or None,
                channel=channel,
                tester_code=tester_code,
                on_progress=on_progress,
                on_extract_progress=on_extract_progress,
                on_verify_progress=on_verify_progress,
                on_stage=lambda name, index, total, can_cancel: on_stage(
                    "unity", name, index, total, can_cancel
                ),
                auto_update=True,
                stop_event=stop_event,
            )
            results["unity"] = unity_result.as_dict()
        python_result = results.get("python", {})
        selected_results = list(results.values())
        return {
            "ok": bool(selected_results) and all(bool(item.get("ok")) for item in selected_results),
            "python_applied": bool(python_result.get("changed")),
            "python_pending_restart": python_pending_restart,
            "cancelled": bool(stop_event.is_set()) or any(bool(item.get("cancelled")) for item in selected_results),
            "results": results,
        }

    @staticmethod
    def restart_application() -> bool:
        from utils.app_restart import restart_app

        return bool(restart_app())
