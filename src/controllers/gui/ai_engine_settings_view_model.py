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
)


@dataclass(frozen=True, slots=True)
class AIEngineSettingsState:
    hardware: dict[str, Any] = field(default_factory=dict)
    topology: dict[str, Any] = field(default_factory=dict)
    maintenance: dict[str, Any] = field(default_factory=dict)
    busy: bool = False
    error: str = ""


class AIEngineSettingsViewModel(IntentViewModel[AIEngineSettingsState]):
    def __init__(self, *, events, parent=None) -> None:
        super().__init__(AIEngineSettingsState(), parent)
        self._events = events

    def dispatch(self, intent: Any) -> None:
        del intent

    @staticmethod
    def _read_state(*, refresh_hardware: bool = False) -> dict[str, Any]:
        hardware = services().get_optional(HardwareInventoryService)
        engine = services().get_optional(AIEngineAdministrationService)
        maintenance = services().get_optional(AIEnvironmentMaintenanceService)
        return {
            "hardware": hardware.snapshot(refresh=refresh_hardware) if hardware is not None else {},
            "topology": engine.topology_snapshot() if engine is not None else {},
            "maintenance": maintenance.snapshot() if maintenance is not None else {},
        }

    def refresh(self, *, hardware: bool = False) -> None:
        self.update_state(busy=True, error="")

        def done(result: dict[str, Any]) -> None:
            self.update_state(**result, busy=False, error="")

        self.run_latest(
            "ai-engine-settings-refresh",
            lambda: self._read_state(refresh_hardware=hardware),
            done,
            lambda exc: self.update_state(busy=False, error=str(exc)),
        )

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
            return self._read_state()

        self.run_latest(
            "ai-engine-topology-switch",
            worker,
            lambda result: self.update_state(**result, busy=False, error=""),
            lambda exc: self.update_state(busy=False, error=str(exc)),
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
            return self._read_state()

        self.run_latest(
            "ai-environment-reset",
            worker,
            lambda result: self.update_state(**result, busy=False, error=""),
            lambda exc: self.update_state(busy=False, error=str(exc)),
        )

    def open_ai_hub(self) -> None:
        self._events.publish(
            UiTopic.GUI_SHOW_WINDOW,
            {"window_id": "ai_hub", "payload": {}},
        )
