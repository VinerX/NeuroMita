from __future__ import annotations

from pathlib import Path

from core.runtime_environments import RuntimeEnvironmentManager
from services.ai_environment_maintenance_service import (
    DefaultAIEnvironmentMaintenanceService,
)
from services.contracts import (
    AIEngineAdministrationService,
    InstallQueueAdministrationService,
)
from services.hardware_inventory_service import WindowsHardwareInventoryService


class _Engine(AIEngineAdministrationService):
    def __init__(self) -> None:
        self.suspended = False

    def topology_snapshot(self):
        return {}

    def switch_topology(self, mode: str, *, timeout: float = 30.0):
        return {"ok": True, "mode": mode}

    def suspend_for_maintenance(self, *, timeout: float = 15.0) -> bool:
        self.suspended = True
        return True

    def resume_after_maintenance(self) -> bool:
        self.suspended = False
        return True


class _Queue(InstallQueueAdministrationService):
    def __init__(self) -> None:
        self.paused = False

    def quiesce(self, *, timeout: float = 30.0) -> bool:
        self.paused = True
        return True

    def resume(self) -> None:
        self.paused = False


class _Services:
    def __init__(self, engine, queue) -> None:
        self._values = {
            AIEngineAdministrationService: engine,
            InstallQueueAdministrationService: queue,
        }

    def get_optional(self, contract):
        return self._values.get(contract)


def test_windows_inventory_test_vendor_uses_pci_id(monkeypatch) -> None:
    monkeypatch.setenv("TEST_AS_AMD", "TRUE")
    snapshot = WindowsHardwareInventoryService().snapshot(refresh=True)
    assert snapshot["vendor"] == "AMD"
    assert snapshot["primary"]["vendor_id"] == "1002"


def test_runtime_reset_never_deletes_main_core(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    core_marker = manager.main_core_root / "keep.bin"
    overlay_marker = manager.overlay_root / "delete.bin"
    core_marker.write_bytes(b"keep")
    overlay_marker.write_bytes(b"delete")

    manager.reset_managed_storage()

    assert core_marker.read_bytes() == b"keep"
    assert not overlay_marker.exists()
    assert manager.overlay_root.is_dir()


def test_maintenance_state_machine_orders_lifecycle(monkeypatch, tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    (manager.overlay_root / "delete.bin").write_bytes(b"delete")
    engine = _Engine()
    queue = _Queue()
    registry = _Services(engine, queue)
    monkeypatch.setattr(
        "services.ai_environment_maintenance_service.services",
        lambda: registry,
    )
    states: list[str] = []

    result = DefaultAIEnvironmentMaintenanceService(manager).reset_all(
        progress=lambda snapshot: states.append(snapshot["state"]),
    )

    assert result["state"] == "completed"
    assert states == [
        "validating",
        "draining_installs",
        "stopping_workers",
        "deleting",
        "reconciling",
        "restarting",
        "completed",
    ]
    assert not engine.suspended
    assert not queue.paused
