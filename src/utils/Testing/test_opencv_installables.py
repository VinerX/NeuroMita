from __future__ import annotations

import builtins
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.backends import BackendKind
from core.install_types import InstallCallbacks
from core.installables import ComponentCategory, ComponentStatusCode
from core.runtime_environments import RuntimeEnvironmentManager
from installables import opencv_component
from installables.catalog_manifest import CATALOG_ENTRIES, entries_for_category
from installables.registry_builder import LazyInstallableRegistry


@pytest.fixture(autouse=True)
def forbid_cv2_import(monkeypatch):
    original_import = builtins.__import__
    original_import_module = importlib.import_module

    def checked_import(name, *args, **kwargs):
        if name == "cv2" or name.startswith("cv2."):
            raise AssertionError("OpenCV catalog operations must not import cv2")
        return original_import(name, *args, **kwargs)

    def checked_import_module(name, *args, **kwargs):
        if name == "cv2" or name.startswith("cv2."):
            raise AssertionError("OpenCV catalog operations must not import cv2")
        return original_import_module(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(importlib, "import_module", checked_import_module)


@pytest.fixture
def component(monkeypatch):
    manager = Mock()
    manager.active_for.return_value = None
    monkeypatch.setattr(opencv_component, "runtime_environments", lambda: manager)
    monkeypatch.setattr(opencv_component, "_", lambda ru, en="": en or ru)
    return opencv_component.OpenCVInstallableComponent(), manager


def test_install_spec_preserves_numpy_126_compatibility(component, monkeypatch):
    subject, _manager = component
    monkeypatch.setattr(opencv_component.importlib.util, "find_spec", lambda name: None)

    plan = subject.build_install_plan()

    assert len(plan.actions) == 1
    assert plan.actions[0].packages == ["opencv-python==4.11.0.86"]
    assert plan.actions[0].extra_args == ["--no-deps"]


@pytest.mark.parametrize("language", ["RU", "EN"])
def test_opencv_is_registered_in_dependencies_with_matching_metadata(component, monkeypatch, language):
    monkeypatch.setattr(opencv_component, "_", lambda ru, en="": en if language == "EN" else ru)
    entries = [entry for entry in CATALOG_ENTRIES if entry.id == "dependency:opencv"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry in entries_for_category("dependency")

    registry = LazyInstallableRegistry()
    subject = registry.require("dependency:opencv")
    assert isinstance(subject, opencv_component.OpenCVInstallableComponent)
    assert registry.require("dependency:opencv") is subject
    declared = entry.metadata_en if language == "EN" else entry.metadata_ru
    actual = subject.metadata().as_dict()
    for key, value in declared.items():
        assert actual[key] == value, key
    assert subject.category == ComponentCategory.DEPENDENCY
    assert actual["backend"] == "none"
    assert actual["legacy_kind"] == "deps"


@pytest.mark.parametrize(
    "managed,core,installed",
    [(False, False, False), (False, True, True), (True, False, True), (True, True, True)],
    ids=["missing", "core", "managed", "managed-and-core"],
)
def test_status_uses_presence_without_loading_opencv(component, monkeypatch, managed, core, installed):
    subject, manager = component
    manager.active_for.return_value = object() if managed else None
    probe = Mock(return_value=object() if core else None)
    monkeypatch.setattr(opencv_component.importlib.util, "find_spec", probe)

    status = subject.status()

    assert status.id == "dependency:opencv"
    assert status.code == (ComponentStatusCode.INSTALLED if installed else ComponentStatusCode.NOT_INSTALLED)
    assert status.installed is installed
    assert status.ready is installed
    assert status.backend == BackendKind.NONE
    manager.active_for.assert_called_once_with(category="dependency", item_id="opencv")
    if managed:
        probe.assert_not_called()
    else:
        probe.assert_called_once_with("cv2")


def test_status_discovers_core_module_without_executing_it(component, tmp_path, monkeypatch):
    subject, _manager = component
    package = tmp_path / "cv2"
    package.mkdir()
    (package / "__init__.py").write_text("raise AssertionError('cv2 was executed')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "cv2", raising=False)

    assert subject.status().installed is True
    assert "cv2" not in sys.modules


@pytest.mark.parametrize("error", [ImportError("missing"), ValueError("bad spec"), RuntimeError("probe failed")])
def test_spec_probe_failure_is_reported_as_missing(component, monkeypatch, error):
    subject, _manager = component
    monkeypatch.setattr(opencv_component.importlib.util, "find_spec", Mock(side_effect=error))

    status = subject.status()

    assert status.code == ComponentStatusCode.NOT_INSTALLED
    assert status.installed is False
    assert status.ready is False
    assert subject.build_install_plan().actions[0].packages == ["opencv-python==4.11.0.86"]


@pytest.mark.parametrize("core", [False, True])
def test_registry_failure_falls_back_to_core_presence(component, monkeypatch, core):
    subject, manager = component
    manager.active_for.side_effect = OSError("registry unavailable")
    monkeypatch.setattr(opencv_component.importlib.util, "find_spec", lambda name: object() if core else None)

    assert subject.status().installed is core
    assert subject.status().ready is core


@pytest.mark.parametrize("managed,core", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("clean", [False, True])
def test_install_and_clean_plans_only_own_opencv(component, monkeypatch, managed, core, clean):
    subject, manager = component
    manager.active_for.return_value = object() if managed else None
    monkeypatch.setattr(opencv_component.importlib.util, "find_spec", lambda name: object() if core else None)
    ctx = {"clean": clean, "libs_dir": "core-must-not-be-mutated"}

    plan = subject.build_install_plan(ctx)

    if (managed or core) and not clean:
        assert plan.already_installed is True
        assert plan.actions == []
    else:
        assert plan.already_installed is False
        assert plan.environment_managed is True
        assert plan.required_backend in (None, BackendKind.NONE)
        assert len(plan.actions) == 1
        action = plan.actions[0]
        assert action.type == "pip"
        assert action.packages == ["opencv-python==4.11.0.86"]
        assert action.extra_args == ["--no-deps"]
        assert action.fn is None
    assert ctx == {"clean": clean, "libs_dir": "core-must-not-be-mutated"}


@pytest.mark.parametrize("managed,core", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("clean", [False, True])
def test_uninstall_never_mutates_core_packages(component, monkeypatch, managed, core, clean):
    subject, manager = component
    manager.active_for.return_value = object() if managed else None
    monkeypatch.setattr(opencv_component.importlib.util, "find_spec", lambda name: object() if core else None)

    plan = subject.build_uninstall_plan({"clean": clean})

    assert plan.actions == []
    assert plan.already_installed is (not managed)
    assert plan.environment_managed is True
    if not managed and core:
        assert "core" in plan.already_installed_status
    assert subject.build_initialize_plan() is None


def _write_opencv_layer(target: Path, version: str = "4.11.0.86") -> None:
    package = target / "cv2"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("raise AssertionError('test layer must not be imported')\n", encoding="utf-8")
    dist = target / f"opencv_python-{version}.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(f"Name: opencv-python\nVersion: {version}\n", encoding="utf-8")
    (dist / "top_level.txt").write_text("cv2\n", encoding="utf-8")
    (dist / "RECORD").write_text("cv2/__init__.py,,\n", encoding="utf-8")


@pytest.fixture
def managed_layer(tmp_path, monkeypatch):
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    meta = {"category": "dependency", "item_id": "opencv"}
    transaction = manager.begin(
        meta=meta, requested_specs=("opencv-python==4.11.0.86",),
        required_backend=BackendKind.NONE, backend_context={},
    )
    _write_opencv_layer(transaction.site_packages)
    record = transaction.commit(meta)
    transaction.finalize()
    core_file = tmp_path / "Lib" / "core" / "numpy" / "__init__.py"
    core_file.parent.mkdir(parents=True)
    core_file.write_text("VERSION = '1.26.0'\n", encoding="utf-8")
    monkeypatch.setattr(opencv_component, "runtime_environments", lambda: manager)
    monkeypatch.setattr(opencv_component.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(opencv_component, "_", lambda ru, en="": en or ru)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("NEUROMITA_MAIN_ENVIRONMENT_PATHS", "")
    return manager, record, core_file


def test_managed_opencv_is_visible_to_main_runtime_and_excluded_from_ai(managed_layer):
    manager, record, _core_file = managed_layer

    assert manager.should_manage({"category": "dependency", "item_id": "opencv"}) is True
    assert manager.should_manage({"category": "dependency", "item_id": "ffmpeg"}) is False
    assert manager.main_runtime_paths() == (str(record.site_packages),)
    assert record.probe_modules == ("cv2",)
    composition = manager.runtime_composition()
    assert record not in composition.records
    assert str(record.site_packages) not in composition.paths
    assert opencv_component.OpenCVInstallableComponent().status().ready is True


def test_clean_reinstall_stages_separately_and_can_preserve_previous_layer(managed_layer):
    manager, record, core_file = managed_layer
    subject = opencv_component.OpenCVInstallableComponent()
    original = (record.site_packages / "cv2" / "__init__.py").read_bytes()
    plan = subject.build_install_plan({"clean": True})
    transaction = manager.begin(
        meta={"category": "dependency", "item_id": "opencv"},
        requested_specs=plan.actions[0].packages,
        required_backend=plan.required_backend, backend_context={},
    )
    try:
        assert transaction.site_packages != record.site_packages
        assert manager.active_for(category="dependency", item_id="opencv") == record
        assert (record.site_packages / "cv2" / "__init__.py").read_bytes() == original
    finally:
        transaction.abort()

    assert manager.active_for(category="dependency", item_id="opencv") == record
    assert core_file.read_text(encoding="utf-8") == "VERSION = '1.26.0'\n"


def test_uninstall_execution_removes_only_managed_layer(managed_layer):
    from controllers.install_controller import InstallController

    manager, record, core_file = managed_layer
    controller = InstallController.__new__(InstallController)
    pip_installer = Mock()
    callbacks = InstallCallbacks(progress=lambda value: None, status=lambda value: None, log=lambda value: None)
    plan = opencv_component.OpenCVInstallableComponent().build_uninstall_plan()
    InstallController._activate_main_environment(record)
    assert str(record.site_packages) in sys.path

    assert controller._uninstall_plan(
        plan, environment_manager=manager, active_environment=record, managed=True,
        pip_installer=pip_installer, callbacks=callbacks,
        ctx={"meta": {"category": "dependency", "item_id": "opencv", "op": "uninstall"}},
        timeout=5.0,
    ) is True

    assert manager.active_for(category="dependency", item_id="opencv") is None
    assert manager.main_runtime_paths() == ()
    assert not record.root.exists()
    assert str(record.site_packages) not in sys.path
    assert str(record.site_packages) not in os.environ["NEUROMITA_MAIN_ENVIRONMENT_PATHS"].split(os.pathsep)
    assert core_file.read_text(encoding="utf-8") == "VERSION = '1.26.0'\n"
    assert pip_installer.mock_calls == []
    assert opencv_component.OpenCVInstallableComponent().status().installed is False


def test_uninstall_failure_reactivates_previous_main_layer(managed_layer, monkeypatch):
    from controllers.install_controller import InstallController

    manager, record, core_file = managed_layer
    controller = InstallController.__new__(InstallController)
    callbacks = InstallCallbacks(progress=lambda value: None, status=lambda value: None, log=lambda value: None)
    InstallController._activate_main_environment(record)
    monkeypatch.setattr(manager, "remove_installed", Mock(side_effect=OSError("registry write failed")))

    with pytest.raises(OSError, match="registry write failed"):
        controller._uninstall_plan(
            opencv_component.OpenCVInstallableComponent().build_uninstall_plan(),
            environment_manager=manager, active_environment=record, managed=True,
            pip_installer=Mock(), callbacks=callbacks,
            ctx={"meta": {"category": "dependency", "item_id": "opencv", "op": "uninstall"}},
            timeout=5.0,
        )

    assert manager.active_for(category="dependency", item_id="opencv") == record
    assert str(record.site_packages) in sys.path
    assert str(record.site_packages) in os.environ["NEUROMITA_MAIN_ENVIRONMENT_PATHS"].split(os.pathsep)
    assert record.root.exists()
    assert core_file.read_text(encoding="utf-8") == "VERSION = '1.26.0'\n"


@pytest.mark.parametrize("state", ["missing", "managed", "clean"])
def test_install_controller_respects_opencv_layer_ownership(managed_layer, monkeypatch, state):
    from controllers.install_controller import InstallController

    manager, previous, core_file = managed_layer
    if state == "missing":
        assert manager.remove_installed(previous.logical_id)
    requests = []

    class Installer:
        def __init__(self, target):
            self.libs_path_abs = str(target)
            self.script_path = sys.executable

        def install_environment_lock(self, specs, *, core_overrides, core_packages, extra_args):
            requests.append((self.libs_path_abs, list(specs), list(extra_args)))
            assert not core_packages
            assert not core_overrides
            _write_opencv_layer(Path(self.libs_path_abs))
            return True

        def cancel(self):
            pass

    class Controller(InstallController):
        def __init__(self):
            self.environment_manager = manager
            self.event_bus = Mock()

        def _make_pip_installer(self, callbacks, target_path=None):
            return Installer(target_path)

    monkeypatch.setattr(Controller, "_validate_main_environment", staticmethod(lambda record, timeout: True))
    subject = opencv_component.OpenCVInstallableComponent()
    clean = state == "clean"
    controller = Controller()

    assert controller.run_task(
        task_id="dependency:opencv:install",
        runner=lambda **kwargs: subject.build_install_plan({"clean": clean}),
        meta={"category": "dependency", "item_id": "opencv", "op": "install", "clean": clean},
        callbacks=InstallCallbacks(progress=lambda value: None, status=lambda value: None, log=lambda value: None),
        timeout_sec=5.0,
    ) is True

    record = manager.active_for(category="dependency", item_id="opencv")
    assert record is not None
    if state == "managed":
        assert requests == []
        assert record == previous
    else:
        assert len(requests) == 1
        target, specs, args = requests[0]
        assert specs == ["opencv-python==4.11.0.86"]
        assert "--no-deps" in args
        assert Path(target).is_relative_to(manager.staging_root)
        assert Path(target) != previous.site_packages
        assert str(record.site_packages) in sys.path
    assert "opencv-python" in record.packages
    assert "numpy" not in record.packages
    assert manager.main_runtime_paths() == (str(record.site_packages),)
    assert core_file.read_text(encoding="utf-8") == "VERSION = '1.26.0'\n"
