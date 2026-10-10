from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from controllers.ai_engine_controller import AIEngineController
from controllers.gui.voiceover_controller import VoiceoverGuiController
from controllers.install_controller import InstallController
from controllers.server_controller import ServerController
from core.install_types import InstallPlan
from core.runtime_environments import MissingBackendLayer, RuntimeEnvironmentManager
from managers.character_manager import CharacterManager
from services.ai_environment_maintenance_service import DefaultAIEnvironmentMaintenanceService
from services.contracts import AIEngineAdministrationService
from services.installable_catalog_service import DefaultInstallableCatalogService


class Administration(AIEngineAdministrationService):
    def __init__(self, *, can_stop=True):
        self.suspended = False
        self.can_stop = can_stop
        self.order = []

    def topology_snapshot(self):
        return {"suspended": self.suspended}

    def switch_topology(self, mode, *, timeout=30.0):
        return {"ok": True}

    def suspend_for_maintenance(self, *, timeout=15.0):
        self.order.append("stop")
        self.suspended = self.can_stop
        return self.can_stop

    def resume_after_maintenance(self):
        self.order.append("resume")
        self.suspended = False
        return True


@pytest.mark.parametrize("can_stop", [True, False])
def test_full_reset_never_deletes_before_confirmed_stop(tmp_path, monkeypatch, can_stop):
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    engine = Administration(can_stop=can_stop)
    registry = Mock()
    registry.get_optional.side_effect = lambda contract: engine if contract is AIEngineAdministrationService else None
    monkeypatch.setattr("services.ai_environment_maintenance_service.services", lambda: registry)
    monkeypatch.setattr("services.ai_environment_maintenance_service.get_event_bus", lambda: Mock())
    removed = []

    def delete():
        assert engine.suspended
        engine.order.append("delete")
        removed.append(True)

    monkeypatch.setattr(manager, "reset_managed_storage", delete)
    snapshots = []
    result = DefaultAIEnvironmentMaintenanceService(manager).reset_all(progress=snapshots.append)
    assert bool(removed) == can_stop
    assert result["state"] == ("completed" if can_stop else "failed")
    assert all(not item["error"] for item in snapshots if item["state"] != "failed")
    if can_stop:
        assert engine.order == ["stop", "delete", "resume"]
        assert any(item["state"] == "deleting" and item["busy"] for item in snapshots)


def test_maintenance_holds_runtime_lock_through_filesystem_operation():
    engine = object.__new__(AIEngineController)
    engine._runtime_switch_lock = threading.RLock()
    engine.suspend_for_maintenance = Mock(return_value=True)
    engine.resume_after_maintenance = Mock(return_value=True)
    entered = threading.Event()
    acquired = threading.Event()

    def contender():
        entered.set()
        with engine._runtime_switch_lock:
            acquired.set()

    with engine.maintenance_session():
        thread = threading.Thread(target=contender)
        thread.start()
        assert entered.wait(1)
        assert not acquired.wait(0.05)
    thread.join(1)
    assert acquired.is_set()
    engine.resume_after_maintenance.assert_called_once()


def test_failed_stop_keeps_live_worker_registered():
    engine = object.__new__(AIEngineController)
    engine._lock = threading.RLock()
    worker = Mock(worker_name="shared")
    worker.stop.side_effect = RuntimeError("cannot kill")
    engine._workers = {"shared": worker}
    engine._service_to_worker = {"tts": "shared"}
    with pytest.raises(RuntimeError, match="did not stop"):
        engine._stop_runtime_workers(timeout=0)
    assert engine._workers["shared"] is worker
    assert engine._service_to_worker["tts"] == "shared"


@pytest.mark.parametrize("managed", [True, False])
def test_tts_uninstall_keeps_worker_stopped_until_artifacts_and_overlay_removed(monkeypatch, managed):
    engine = Administration()
    registry = Mock()
    registry.get_optional.side_effect = lambda contract: engine if contract is AIEngineAdministrationService else None
    monkeypatch.setattr("controllers.install_controller.services", lambda: registry)
    controller = object.__new__(InstallController)
    manager = Mock()
    manager.logical_id_from_meta.return_value = ("tts:model", "tts", "model")
    record = SimpleNamespace(category="tts", logical_id="tts:model")
    callbacks = Mock()

    def cleanup(*args, **kwargs):
        assert engine.suspended
        engine.order.append("artifacts")
        return True

    def remove(*args, **kwargs):
        assert engine.suspended
        engine.order.append("overlay")
        return True

    controller._execute_plan = cleanup
    controller._forget_environment_runtime = Mock()
    manager.remove_installed.side_effect = remove
    assert controller._uninstall_plan(
        InstallPlan(actions=[]), environment_manager=manager, active_environment=record,
        managed=managed, pip_installer=Mock(), callbacks=callbacks,
        ctx={"meta": {"category": "tts", "item_id": "model"}}, timeout=15,
    )
    assert engine.order == (["stop", "artifacts", "overlay", "resume"] if managed else ["stop", "artifacts", "resume"])


def test_tts_uninstall_refuses_cleanup_when_worker_cannot_stop(monkeypatch):
    engine = Administration(can_stop=False)
    registry = Mock()
    registry.get_optional.side_effect = lambda contract: engine if contract is AIEngineAdministrationService else None
    monkeypatch.setattr("controllers.install_controller.services", lambda: registry)
    controller = object.__new__(InstallController)
    controller._execute_plan = Mock()
    manager = Mock()
    manager.logical_id_from_meta.return_value = ("tts:model", "tts", "model")
    with pytest.raises(RuntimeError, match="could not be stopped"):
        controller._uninstall_plan(
            InstallPlan(actions=[]), environment_manager=manager, active_environment=None,
            managed=False, pip_installer=Mock(), callbacks=Mock(),
            ctx={"meta": {"category": "tts", "item_id": "model"}}, timeout=15,
        )
    controller._execute_plan.assert_not_called()


def test_missing_backend_is_inspectable_but_cannot_be_executed(tmp_path, monkeypatch):
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "probe"}, requested_specs=(),
        required_backend=None, backend_context={},
    )
    record = transaction.commit()
    monkeypatch.setattr(manager, "runtime_paths", Mock(side_effect=MissingBackendLayer("torch", ["torch.cpu"])))
    with pytest.raises(MissingBackendLayer):
        manager.component_context(category="tts", item_id="probe")
    context = manager.component_context(category="tts", item_id="probe", require_runtime=False)
    assert context["target_dir"] == str(record.site_packages)
    service = DefaultInstallableCatalogService()
    try:
        entry = SimpleNamespace(id="tts:probe", declared_backend="cpu")
        status = service._inspect_component(entry, context)
        assert status["code"] == "backend_missing"
        assert status["installed"] and not status["ready"]
    finally:
        service.close()


def test_voice_disabled_clears_indicator_before_catalog_work():
    controller = object.__new__(VoiceoverGuiController)
    controller.view = SimpleNamespace(use_voice_checkbox=SimpleNamespace(isChecked=lambda: False))
    controller.event_bus = Mock()
    controller._apply_voiceover_visibility_from_widgets = Mock()
    controller._set_local_voice_loading_placeholders = Mock()
    controller._effective_method = lambda: "Local"
    controller._run_async = Mock()
    controller._sync_everything(allow_autoload=False)
    payload = controller.event_bus.emit.call_args.args[1]
    assert payload["state"] is None
    controller._run_async.call_args.args[2](RuntimeError("catalog failed"))
    assert controller.event_bus.emit.call_args.args[1]["state"] is None


def test_statistics_query_does_not_materialize_character(monkeypatch):
    manager = object.__new__(CharacterManager)
    manager._lock = threading.RLock()
    manager.characters = {}
    manager._definitions = {"Kind": SimpleNamespace(storage_name="KindMita")}
    manager.resources = Mock()
    manager.resources.history_for.return_value.load_variables.return_value = {"attitude": 81, "stress": "invalid"}
    manager._create_character = Mock()
    assert manager.get_character_stats("Kind") == {"attitude": 81.0, "boredom": 10.0, "stress": 5.0}
    manager._create_character.assert_not_called()
    assert not manager.characters
    registry = Mock()
    registry.stats_of.side_effect = manager.get_character_stats
    monkeypatch.setattr("controllers.server_controller.use", lambda contract: registry)
    controller = object.__new__(ServerController)
    assert controller._get_character_stats("Kind")["attitude"] == 81
    registry.get.assert_not_called()


def test_maintenance_ui_shows_stage_and_disables_deletion_until_complete():
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from controllers.gui.ai_engine_settings_view_model import AIEngineSettingsState
    from ui.settings.ai_engine_settings import setup_ai_engine_settings_controls

    app = QApplication.instance() or QApplication([])

    class ViewModel(QObject):
        state_changed = pyqtSignal(object)
        refresh = Mock()
        refresh_hardware = Mock()
        open_ai_hub = Mock()
        switch_mode = Mock()
        reset_environments = Mock()

    vm = ViewModel()
    vm.state = AIEngineSettingsState(
        maintenance={"state": "deleting", "busy": True, "path": "Lib/environment", "message": "Удаление управляемых AI-пакетов"},
        topology={"suspended": True, "workers": {}}, busy=True,
    )
    panel = QWidget()
    setup_ai_engine_settings_controls(panel, QVBoxLayout(panel), view_model=vm)
    try:
        assert not panel.ai_maintenance_progress.isHidden()
        assert not panel.ai_environment_reset.isEnabled()
        assert "Удаление" in panel.ai_maintenance_status.text()
        assert panel.ai_engine_status.text() in ("Процессы не запущены", "Processes are not running")
        vm.state_changed.emit(AIEngineSettingsState(
            maintenance={"state": "completed", "busy": False, "path": "Lib/environment", "message": "Удаление завершено"},
        ))
        assert panel.ai_maintenance_progress.isHidden()
        assert panel.ai_environment_reset.isEnabled()
        assert panel.ai_maintenance_status.text() == "Удаление завершено"
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_stale_maintenance_refresh_cannot_hide_deletion_progress():
    from controllers.gui.ai_engine_settings_view_model import AIEngineSettingsViewModel

    vm = SimpleNamespace(
        state=SimpleNamespace(maintenance={"revision": 7, "state": "deleting"}, reset_running=False),
        update_state=Mock(),
    )
    AIEngineSettingsViewModel._apply_maintenance_refresh(vm, {"revision": 2, "state": "idle"})
    vm.update_state.assert_called_once_with(maintenance_loading=False)


def test_runtime_recovery_does_not_spawn_during_maintenance():
    from controllers.ai_engine_controller import _RuntimeSwitchGate

    engine = object.__new__(AIEngineController)
    engine._runtime_switch_lock = threading.RLock()
    engine._recovery_lock = threading.RLock()
    engine._runtime_switching = _RuntimeSwitchGate()
    engine._runtime_switching.begin(waitable=False)
    engine._recover_worker(Mock(), 1)
    assert engine.restart_service("tts") is False
    assert engine.restart_worker_for_service("tts") is False


def test_delete_button_immediately_shows_progress_and_blocks_repeat_click(monkeypatch):
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QMessageBox
    from controllers.gui.ai_engine_settings_view_model import AIEngineSettingsViewModel
    from ui.settings.ai_engine_settings import setup_ai_engine_settings_controls

    app = QApplication.instance() or QApplication([])
    vm = AIEngineSettingsViewModel(events=Mock())
    vm.refresh = Mock()
    vm.run_latest = Mock()
    vm.update_state(maintenance={"revision": 1, "state": "idle", "path": "Lib/environment"})
    panel = QWidget()
    setup_ai_engine_settings_controls(panel, QVBoxLayout(panel), view_model=vm)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    try:
        assert panel.ai_environment_reset.isEnabled()
        assert panel.ai_maintenance_progress.isHidden()
        panel.ai_environment_reset.click()
        assert not panel.ai_environment_reset.isEnabled()
        assert not panel.ai_maintenance_progress.isHidden()
        assert panel.ai_maintenance_status.text() == "Подготовка к удалению…"
        panel.ai_environment_reset.click()
        vm.reset_environments()
        vm.run_latest.assert_called_once()
        vm._apply_maintenance_refresh({"revision": 1, "state": "idle", "path": "Lib/environment"})
        assert vm.state.maintenance["state"] == "validating"
        vm.run_latest.call_args.args[3](RuntimeError("cannot stop worker"))
        assert panel.ai_environment_reset.isEnabled()
        assert panel.ai_maintenance_progress.isHidden()
        assert not vm.state.reset_running
        assert "cannot stop worker" in panel.ai_maintenance_status.text()
        panel.ai_environment_reset.click()
        vm.run_latest.call_args.args[2]({
            "maintenance": {"revision": 2, "state": "completed", "busy": False,
                            "path": "Lib/environment", "message": "Удаление завершено"},
            "topology": {}, "backends": (),
        })
        assert panel.ai_environment_reset.isEnabled()
        assert panel.ai_maintenance_progress.isHidden()
        assert not vm.state.reset_running
    finally:
        vm.close()
        panel.close()
        panel.deleteLater()
        app.processEvents()
