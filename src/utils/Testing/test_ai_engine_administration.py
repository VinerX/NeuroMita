from __future__ import annotations

from pathlib import Path
import threading
from types import SimpleNamespace

from controllers.ai_engine_controller import AIEngineController
from core.runtime_environments import RuntimeEnvironmentManager
from services.ai_environment_maintenance_service import (
    DefaultAIEnvironmentMaintenanceService,
)
from services.contracts import (
    AIEngineAdministrationService,
    InstallQueueAdministrationService,
)
from services.hardware_inventory_service import WindowsHardwareInventoryService
import services.hardware_inventory_service as hardware_inventory
from ui.settings.ai_engine_settings import _sorted_accelerators


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


def test_hardware_inventory_keeps_primary_independent_from_cuda_ordinals(monkeypatch) -> None:
    monkeypatch.delenv("TEST_AS_AMD", raising=False)
    monkeypatch.delenv("TEST_AS_NVIDIA", raising=False)
    monkeypatch.setattr(hardware_inventory.platform, "system", lambda: "Windows")
    monkeypatch.setattr(hardware_inventory, "_dxgi_adapters", lambda: [
        {"index": 0, "name": "AMD Radeon", "vendor": "AMD"},
        {"index": 1, "name": "NVIDIA RTX A400", "vendor": "NVIDIA"},
        {"index": 2, "name": "NVIDIA GeForce RTX 5060 Ti", "vendor": "NVIDIA"},
    ])
    monkeypatch.setattr(hardware_inventory, "_nvidia_driver_inventory", lambda: {
        "available": True,
        "devices": [
            {"ordinal": 0, "device": "cuda:0", "name": "NVIDIA GeForce RTX 5060 Ti"},
            {"ordinal": 1, "device": "cuda:1", "name": "NVIDIA RTX A400"},
        ],
    })

    snapshot = WindowsHardwareInventoryService().snapshot(refresh=True)

    assert snapshot["primary"]["name"] == "NVIDIA RTX A400"
    assert snapshot["adapters"][2]["cuda"]["device"] == "cuda:0"
    assert len(snapshot["accelerators"]) == 3

    rendered = _sorted_accelerators(snapshot)
    assert [item["name"] for item in rendered] == [
        "NVIDIA GeForce RTX 5060 Ti",
        "NVIDIA RTX A400",
        "AMD Radeon",
    ]
    assert len({item["id"] for item in rendered}) == 3


def test_hardware_inventory_keeps_cuda_ordinals_when_dxgi_probe_fails(monkeypatch) -> None:
    monkeypatch.delenv("TEST_AS_AMD", raising=False)
    monkeypatch.delenv("TEST_AS_NVIDIA", raising=False)
    monkeypatch.setattr(hardware_inventory.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        hardware_inventory,
        "_dxgi_adapters",
        lambda: (_ for _ in ()).throw(OSError("DXGI unavailable")),
    )
    monkeypatch.setattr(
        hardware_inventory,
        "_nvidia_driver_inventory",
        lambda: {
            "available": True,
            "devices": [
                {
                    "ordinal": 1,
                    "device": "cuda:1",
                    "name": "NVIDIA GeForce RTX 5080",
                    "compute_capability": "sm_120",
                    "compute_major": 12,
                    "compute_minor": 0,
                }
            ],
        },
    )

    snapshot = WindowsHardwareInventoryService().snapshot(refresh=True)

    assert snapshot["cuda"]["available"] is True
    assert snapshot["cuda"]["devices"][0]["device"] == "cuda:1"
    assert snapshot["accelerators"][0]["cuda_device"] == "cuda:1"
    assert "DXGI unavailable" in snapshot["error"]


def test_cuda_device_association_falls_back_to_unique_name_without_luid() -> None:
    adapters = [
        {
            "index": 0,
            "name": "NVIDIA GeForce RTX 4060",
            "vendor": "NVIDIA",
            "luid": "",
        }
    ]
    devices = [
        {
            "ordinal": 1,
            "name": "NVIDIA GeForce RTX 4060",
            "luid": "",
            "compute_capability": "sm_89",
        }
    ]

    hardware_inventory._attach_cuda_devices_to_adapters(adapters, devices)

    assert adapters[0]["cuda"]["ordinal"] == 1


def test_shared_service_restart_accepts_supervisor_replacement_after_worker_death() -> None:
    controller = AIEngineController.__new__(AIEngineController)
    controller._lock = threading.RLock()
    controller._shutting_down = threading.Event()
    controller.mode = "shared"
    controller._service_to_worker = {"tts": "shared"}

    replacement = SimpleNamespace(wait_ready=lambda service, timeout=0: service == "tts")
    dead_proc = SimpleNamespace(is_alive=lambda: False)

    class OldWorker:
        proc = dead_proc

        def restart_service(self, service, timeout=0):
            controller._workers["shared"] = replacement
            return False

    old = OldWorker()
    controller._workers = {"shared": old}

    assert controller.restart_service("tts", timeout=0.1) is True


def test_shared_service_restart_does_not_cold_restart_live_worker_on_regular_failure() -> None:
    controller = AIEngineController.__new__(AIEngineController)
    controller._lock = threading.RLock()
    controller._shutting_down = threading.Event()
    controller.mode = "shared"
    controller._service_to_worker = {"tts": "shared"}
    live_proc = SimpleNamespace(is_alive=lambda: True)
    worker = SimpleNamespace(
        proc=live_proc,
        restart_service=lambda service, timeout=0: False,
    )
    controller._workers = {"shared": worker}

    assert controller.restart_service("tts", timeout=0.1) is False


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
