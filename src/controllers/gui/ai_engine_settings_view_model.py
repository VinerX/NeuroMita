from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from controllers.gui.presentation_contracts import UiTopic
from core.services import services
from services.contracts import (
    AIEngineAdministrationService,
    AIEnvironmentMaintenanceService,
    HardwareInventoryService,
    InstallableCatalogService,
)


@dataclass(frozen=True, slots=True)
class AIEngineSettingsState:
    hardware: dict[str, Any] = field(default_factory=dict)
    topology: dict[str, Any] = field(default_factory=dict)
    maintenance: dict[str, Any] = field(default_factory=dict)
    backends: tuple[dict[str, Any], ...] = ()
    hardware_loading: bool = False
    topology_loading: bool = False
    maintenance_loading: bool = False
    backends_loading: bool = False
    hardware_error: str = ""
    topology_error: str = ""
    maintenance_error: str = ""
    backends_error: str = ""
    busy: bool = False
    error: str = ""


class AIEngineSettingsViewModel(IntentViewModel[AIEngineSettingsState]):
    def __init__(self, *, events, parent=None) -> None:
        super().__init__(AIEngineSettingsState(), parent)
        self._events = events
        try:
            self.track_subscription(
                events.subscribe(
                    UiTopic.INSTALL_CATALOG_CHANGED,
                    self._on_catalog_changed,
                    weak=False,
                )
            )
        except Exception:
            pass

    def dispatch(self, intent: Any) -> None:
        del intent

    @staticmethod
    def _read_hardware(*, refresh: bool = False) -> dict[str, Any]:
        hardware = services().get_optional(HardwareInventoryService)
        return hardware.snapshot(refresh=refresh) if hardware is not None else {}

    @staticmethod
    def _read_topology() -> dict[str, Any]:
        engine = services().get_optional(AIEngineAdministrationService)
        return engine.topology_snapshot() if engine is not None else {}

    @staticmethod
    def _read_maintenance() -> dict[str, Any]:
        maintenance = services().get_optional(AIEnvironmentMaintenanceService)
        return maintenance.snapshot() if maintenance is not None else {}

    @staticmethod
    def _read_backends(*, refresh: bool = False) -> tuple[dict[str, Any], ...]:
        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            return ()
        rows = catalog.list_rows(
            include_status=True,
            refresh=refresh,
            category="backend",
            status_category="backend",
        )
        return tuple(dict(row or {}) for row in rows or ())

    def refresh(self, *, hardware: bool = False) -> None:
        self.refresh_hardware(force=hardware)
        self.refresh_topology()
        self.refresh_maintenance()
        self.refresh_backends()

    def refresh_hardware(self, *, force: bool = False) -> None:
        self.update_state(hardware_loading=True, hardware_error="", error="")
        self.run_latest(
            "ai-engine-hardware-refresh",
            lambda: self._read_hardware(refresh=force),
            lambda result: self.update_state(
                hardware=result,
                hardware_loading=False,
                hardware_error="",
            ),
            lambda exc: self.update_state(
                hardware_loading=False,
                hardware_error=str(exc),
                error=str(exc),
            ),
        )

    def refresh_topology(self) -> None:
        self.update_state(topology_loading=True, topology_error="", error="")
        self.run_latest(
            "ai-engine-topology-refresh",
            self._read_topology,
            lambda result: self.update_state(
                topology=result,
                topology_loading=False,
                topology_error="",
            ),
            lambda exc: self.update_state(
                topology_loading=False,
                topology_error=str(exc),
                error=str(exc),
            ),
        )

    def refresh_maintenance(self) -> None:
        self.update_state(maintenance_loading=True, maintenance_error="", error="")
        self.run_latest(
            "ai-engine-maintenance-refresh",
            self._read_maintenance,
            lambda result: self.update_state(
                maintenance=result,
                maintenance_loading=False,
                maintenance_error="",
            ),
            lambda exc: self.update_state(
                maintenance_loading=False,
                maintenance_error=str(exc),
                error=str(exc),
            ),
        )

    def refresh_backends(self, *, force: bool = False) -> None:
        self.update_state(backends_loading=True, backends_error="", error="")
        self.run_latest(
            "ai-engine-backends-refresh",
            lambda: self._read_backends(refresh=force),
            lambda result: self.update_state(
                backends=result,
                backends_loading=False,
                backends_error="",
            ),
            lambda exc: self.update_state(
                backends_loading=False,
                backends_error=str(exc),
                error=str(exc),
            ),
        )

    def _on_catalog_changed(self, _event) -> None:
        self._post_ui(lambda: self.refresh_backends(force=True))

    def switch_mode(self, mode: str) -> None:
        requested = str(mode or "").strip().lower()
        self.update_state(busy=True, error="")

        def worker() -> dict[str, Any]:
            engine = services().get_optional(AIEngineAdministrationService)
            if engine is None:
                raise RuntimeError("AI engine is still starting")
            result = engine.switch_topology(requested)
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "Topology switch failed"))
            return engine.topology_snapshot()

        self.run_latest(
            "ai-engine-topology-switch",
            worker,
            lambda result: self.update_state(
                topology=result,
                topology_loading=False,
                topology_error="",
                busy=False,
                error="",
            ),
            lambda exc: self.update_state(
                busy=False,
                topology_error=str(exc),
                error=str(exc),
            ),
        )

    def reset_environments(self) -> None:
        self.update_state(busy=True, error="")

        def progress(snapshot: dict[str, Any]) -> None:
            self._post_ui(
                lambda snapshot=dict(snapshot): self.update_state(
                    maintenance=snapshot,
                    busy=True,
                    error=str(snapshot.get("error") or ""),
                )
            )

        def worker() -> dict[str, Any]:
            maintenance = services().get_optional(AIEnvironmentMaintenanceService)
            if maintenance is None:
                raise RuntimeError("AI environment maintenance service is unavailable")
            result = maintenance.reset_all(progress=progress)
            if result.get("state") == "failed":
                raise RuntimeError(str(result.get("error") or "AI environment reset failed"))
            return {
                "topology": self._read_topology(),
                "maintenance": self._read_maintenance(),
                "backends": self._read_backends(refresh=True),
            }

        self.run_latest(
            "ai-environment-reset",
            worker,
            lambda result: self.update_state(
                **result,
                busy=False,
                topology_error="",
                maintenance_error="",
                backends_error="",
                error="",
            ),
            lambda exc: self.update_state(
                busy=False,
                maintenance_error=str(exc),
                error=str(exc),
            ),
        )

    def open_ai_hub(self) -> None:
        self._events.publish(
            UiTopic.GUI_SHOW_WINDOW,
            {"window_id": "ai_hub", "payload": {}},
        )
