from __future__ import annotations
from core.error_utils import format_exception

import threading
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from core.runtime_environments import RuntimeEnvironmentManager
from core.events import Events, get_event_bus
from core.services import services
from services.contracts import (
    AIEngineAdministrationService,
    AIEnvironmentMaintenanceService,
    InstallQueueAdministrationService,
    InstallableCatalogService,
)


class MaintenanceState(str, Enum):
    IDLE = "idle"
    VALIDATING = "validating"
    DRAINING_INSTALLS = "draining_installs"
    STOPPING_WORKERS = "stopping_workers"
    DELETING = "deleting"
    RECONCILING = "reconciling"
    RESTARTING = "restarting"
    COMPLETED = "completed"
    FAILED = "failed"


_TRANSITIONS = {
    MaintenanceState.IDLE: {MaintenanceState.VALIDATING},
    MaintenanceState.COMPLETED: {MaintenanceState.VALIDATING},
    MaintenanceState.FAILED: {MaintenanceState.VALIDATING},
    MaintenanceState.VALIDATING: {MaintenanceState.DRAINING_INSTALLS, MaintenanceState.FAILED},
    MaintenanceState.DRAINING_INSTALLS: {MaintenanceState.STOPPING_WORKERS, MaintenanceState.FAILED},
    MaintenanceState.STOPPING_WORKERS: {MaintenanceState.DELETING, MaintenanceState.FAILED},
    MaintenanceState.DELETING: {MaintenanceState.RECONCILING, MaintenanceState.FAILED},
    MaintenanceState.RECONCILING: {MaintenanceState.RESTARTING, MaintenanceState.FAILED},
    MaintenanceState.RESTARTING: {MaintenanceState.COMPLETED, MaintenanceState.FAILED},
}


class DefaultAIEnvironmentMaintenanceService(AIEnvironmentMaintenanceService):
    def __init__(self, environments: RuntimeEnvironmentManager) -> None:
        self._environments = environments
        self._operation_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._state = MaintenanceState.IDLE
        self._message = ""
        self._error = ""
        self._revision = 0

    def snapshot(self) -> dict[str, Any]:
        return self._snapshot(include_size=True)

    def _snapshot(self, *, include_size: bool) -> dict[str, Any]:
        root = self._environments.environment_root
        size = self._directory_size(root) if include_size else None
        with self._state_lock:
            state = self._state
            message = self._message
            error = self._error
            revision = self._revision
        return {
            "state": state.value,
            "busy": state not in {
                MaintenanceState.IDLE,
                MaintenanceState.COMPLETED,
                MaintenanceState.FAILED,
            },
            "message": message,
            "error": error,
            "revision": revision,
            "path": str(root),
            "exists": root.exists(),
            "size_bytes": size,
        }

    @staticmethod
    def _directory_size(root: Path) -> int:
        total = 0
        try:
            for path in root.rglob("*"):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except OSError:
                    continue
        except OSError:
            return total
        return total

    def _transition(
        self,
        state: MaintenanceState,
        message: str,
        progress: Callable[[dict[str, Any]], None] | None,
        *,
        error: str = "",
    ) -> None:
        with self._state_lock:
            if state not in _TRANSITIONS.get(self._state, set()):
                raise RuntimeError(
                    f"Invalid AI maintenance transition: {self._state.value} -> {state.value}"
                )
            self._state = state
            self._message = str(message)
            self._error = format_exception(error) if error else ""
            self._revision += 1
        if progress is not None:
            progress(self._snapshot(include_size=False))

    def reset_all(
        self,
        *,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not self._operation_lock.acquire(blocking=False):
            return self.snapshot()

        queue: InstallQueueAdministrationService | None = None
        engine: AIEngineAdministrationService | None = None
        queue_paused = False
        try:
            self._transition(MaintenanceState.VALIDATING, "Проверка пути AI-окружений", progress)
            engine = services().get_optional(AIEngineAdministrationService)
            if engine is None:
                raise RuntimeError("AI engine administration service is unavailable")

            self._transition(
                MaintenanceState.DRAINING_INSTALLS, "Остановка очереди установок", progress,
            )
            queue = services().get_optional(InstallQueueAdministrationService)
            if queue is not None:
                queue_paused = True
                if not queue.quiesce(timeout=30.0):
                    raise TimeoutError("Install queue did not stop within 30 seconds")

            self._transition(
                MaintenanceState.STOPPING_WORKERS, "Принудительная остановка AI-процессов", progress,
            )
            with engine.maintenance_session(timeout=15.0):
                self._transition(
                    MaintenanceState.DELETING, "Удаление управляемых AI-пакетов", progress,
                )
                self._environments.reset_managed_storage()
                self._transition(
                    MaintenanceState.RECONCILING, "Обновление каталога установленных компонентов", progress,
                )
                catalog = services().get_optional(InstallableCatalogService)
                if catalog is not None:
                    catalog.invalidate()
                self._transition(
                    MaintenanceState.RESTARTING, "Перезапуск AI-процессов", progress,
                )

            if queue is not None:
                queue.resume()
                queue_paused = False
            get_event_bus().emit(
                Events.Install.CATALOG_CHANGED, {"reason": "environment_reset"},
            )
            self._transition(
                MaintenanceState.COMPLETED, "AI-окружения удалены. Процессы перезапущены.", progress,
            )
        except Exception as exc:
            if queue_paused and queue is not None:
                try:
                    queue.resume()
                except Exception:
                    pass
            self._transition(
                MaintenanceState.FAILED, "Удаление AI-окружений не завершено", progress,
                error=format_exception(exc),
            )
        finally:
            self._operation_lock.release()
        return self.snapshot()
