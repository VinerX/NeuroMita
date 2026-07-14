from __future__ import annotations

import threading
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

from core.task_supervisor import task_supervisor
from main_logger import logger
from startup.startup_profiler import startup_trace


class GuiBackendLoader(QObject):
    """Build the interaction runtime off the GUI thread, then attach on Qt's thread."""

    _ready = pyqtSignal(object)
    _failed = pyqtSignal(object)

    def __init__(
        self,
        *,
        runtime: Any,
        startup_mode: str,
        settings_controller: Any,
        on_ready: Callable[[Any], None],
        on_failed: Callable[[BaseException], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._startup_mode = str(startup_mode or "full")
        self._settings_controller = settings_controller
        self._on_ready_callback = on_ready
        self._on_failed_callback = on_failed

        self._lock = threading.RLock()
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._controller: Any = None
        self._started = False

        self._ready.connect(
            self._deliver_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self._failed.connect(
            self._deliver_failure,
            Qt.ConnectionType.QueuedConnection,
        )

    @property
    def controller(self) -> Any:
        with self._lock:
            return self._controller

    @property
    def is_running(self) -> bool:
        with self._lock:
            thread = self._thread
            return bool(thread is not None and thread.is_alive())

    @pyqtSlot()
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread = task_supervisor().start_thread(
                self,
                "gui-backend-startup",
                self._build_backend,
                cancel_event=self._stop_requested,
            )
        startup_trace.mark("gui.backend_thread.starting")

    def _build_backend(self) -> None:
        controller = None
        try:
            startup_trace.mark("gui.backend_thread.started")
            if self._startup_mode == "full":
                with startup_trace.phase("gui.backend_bootstrap"):
                    self._runtime.ensure_backend_bootstrap()

            if self._stop_requested.is_set():
                return

            with startup_trace.phase("gui.controller_import"):
                from controllers.main_controller import MainController

            with startup_trace.phase("gui.main_controller_create"):
                controller = MainController(
                    None,
                    startup_mode=self._startup_mode,
                    settings_controller=self._settings_controller,
                )

            self._initialize_collectors()

            with self._lock:
                self._controller = controller

            if self._stop_requested.is_set():
                controller.close_app()
                return

            startup_trace.mark("gui.backend_thread.ready")
            startup_trace.write()
            self._ready.emit(controller)
        except BaseException as exc:
            logger.error(f"GUI backend startup failed: {exc}", exc_info=True)
            startup_trace.mark(
                "gui.backend_thread.failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            startup_trace.write()
            if controller is not None:
                try:
                    controller.close_app()
                except Exception:
                    logger.exception("Failed to close partially initialized GUI backend")
            if not self._stop_requested.is_set():
                self._failed.emit(exc)

    @staticmethod
    def _initialize_collectors() -> None:
        try:
            from managers.finetune_collector import FineTuneCollector
            from managers.generation_input_collector import GenerationInputCollector

            FineTuneCollector.instance = FineTuneCollector()
            GenerationInputCollector.instance = GenerationInputCollector()
        except Exception as exc:
            logger.warning(f"Runtime collectors are unavailable: {exc}")

    @pyqtSlot(object)
    def _deliver_ready(self, controller: Any) -> None:
        if self._stop_requested.is_set():
            try:
                controller.close_app()
            except Exception:
                logger.exception("Failed to close GUI backend after shutdown request")
            return
        self._on_ready_callback(controller)

    @pyqtSlot(object)
    def _deliver_failure(self, error: BaseException) -> None:
        if not self._stop_requested.is_set():
            self._on_failed_callback(error)

    @pyqtSlot()
    def request_shutdown(self) -> None:
        self._stop_requested.set()
        controller = self.controller
        if controller is not None:
            try:
                controller.close_app()
            except Exception:
                logger.exception("GUI backend shutdown failed")
        task_supervisor().cancel_owner(self, timeout=1.0)

    def wait(self, timeout: float = 5.0) -> bool:
        with self._lock:
            thread = self._thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(max(0.0, float(timeout)))
        return not thread.is_alive()
