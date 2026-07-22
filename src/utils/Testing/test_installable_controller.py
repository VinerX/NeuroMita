from __future__ import annotations

import unittest
from unittest.mock import patch

from controllers.installable_controller import InstallableController
from core.backends import BackendKind
from core.events import Event
from core.install_types import DEFAULT_INSTALL_TIMEOUT_SEC, InstallPlan
from core.installables import ComponentCategory, ComponentMetadata, ComponentStatusCode
from core.services import services
from game_connections.services import beat_backend_spec
from installables.registry_builder import LazyInstallableRegistry, build_installable_registry
from services.contracts import InstallAdmission, InstallQueueService
from services.installable_catalog_service import DefaultInstallableCatalogService


class _CatalogStub:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def list_rows(self, **kwargs):
        self.calls.append(dict(kwargs))
        return list(self.rows)

    def require_component(self, component_id: str, *, refresh: bool = False):
        raise KeyError(component_id)

    def invalidate(self, component_id=None):
        return None


class _BrokenStatusComponent:
    category = ComponentCategory.DEPENDENCY
    legacy_kind = "deps"
    item_id = "broken_status"
    id = "dependency:broken_status"

    def metadata(self):
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title="Broken Status",
            description="Status will fail",
            backend=BackendKind.NONE,
            legacy_kind=self.legacy_kind,
        )

    def status(self, ctx=None):
        raise RuntimeError("status exploded")


class _InstallComponent:
    category = ComponentCategory.TTS
    legacy_kind = "tts"
    item_id = "direct"
    id = "tts:direct"

    def build_install_plan(self, _ctx):
        return InstallPlan(actions=[])

    def build_uninstall_plan(self, _ctx):
        return InstallPlan(actions=[])

    def build_initialize_plan(self, _ctx):
        return InstallPlan(actions=[])

    def metadata(self):
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title="Direct",
            description="Direct admission",
            backend=BackendKind.NONE,
            legacy_kind=self.legacy_kind,
        )


class _InstallCatalog(_CatalogStub):
    def __init__(self):
        super().__init__([])
        self.component = _InstallComponent()

    def require_component(self, component_id: str, *, refresh: bool = False):
        if component_id != self.component.id:
            raise KeyError(component_id)
        return self.component

    def build_operation_plan(self, component_id, operation, *, clean=False, execution_ctx=None):
        component = self.require_component(component_id)
        if operation == "install":
            return component.build_install_plan(dict(execution_ctx or {}))
        if operation == "uninstall":
            return component.build_uninstall_plan(dict(execution_ctx or {}))
        return component.build_initialize_plan(dict(execution_ctx or {}))


class _QueueService(InstallQueueService):
    def __init__(self):
        self.payload = None

    def enqueue(self, payload, *, with_ui: bool):
        self.payload = (payload, with_ui)
        return InstallAdmission(True, str(payload["task_id"]))


class InstallableControllerTests(unittest.TestCase):
    def test_on_list_uses_catalog_without_backend_registry(self):
        rows = [{"metadata": {"id": "dependency:ffmpeg", "category": "dependency"}}]
        catalog = _CatalogStub(rows)
        controller = InstallableController(catalog=catalog)

        result = controller._on_list(
            Event(
                name="installable_list",
                data={"include_status": False, "status_category": "dependency"},
            )
        )

        self.assertEqual(result, rows)
        self.assertEqual(catalog.calls[0]["status_category"], "dependency")
        self.assertFalse(catalog.calls[0]["include_status"])

    def test_catalog_status_failure_is_returned_as_failed_row(self):
        catalog = DefaultInstallableCatalogService()
        broken = _BrokenStatusComponent()

        with patch.object(catalog, "require_component", return_value=broken):
            rows = catalog.list_rows(
                include_status=True,
                category="dependency",
                status_category="dependency",
            )

        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(row["status"]["code"], ComponentStatusCode.FAILED.value)
            self.assertIn("status exploded", row["status"]["message"])

    def test_lazy_registry_keeps_other_groups_when_one_group_fails(self):
        original = LazyInstallableRegistry._resolve_loader

        def resolve(path: str):
            if "beat_install" in path:
                raise RuntimeError("beat boom")
            return original(path)

        with patch.object(LazyInstallableRegistry, "_resolve_loader", side_effect=resolve):
            registry = build_installable_registry()
            self.assertIsNone(registry.get("beats:beat_this"))
            self.assertIsNotNone(registry.get("dependency:ffmpeg"))
            self.assertIsNotNone(registry.get("voices:all"))

    def test_beat_gpu_detect_reuses_shared_gpu_probe(self):
        with patch("game_connections.services.beat_backend_spec.platform.system", return_value="Windows"), \
             patch("game_connections.services.beat_backend_spec.check_gpu_provider", return_value="AMD") as gpu_probe:
            vendor = beat_backend_spec._detect_gpu_vendor()

        self.assertEqual(vendor, "AMD")
        gpu_probe.assert_called_once_with()

    def test_install_uses_typed_queue_service_without_nested_event_command(self):
        queue = _QueueService()
        registration = services().register_owned(
            InstallQueueService,
            queue,
            replace=True,
        )
        controller = InstallableController(catalog=_InstallCatalog())
        try:
            admission = controller.install(
                {
                    "component_id": "tts:direct",
                    "task_id": "tts:direct:install",
                    "with_ui": True,
                }
            )
        finally:
            registration.close()

        self.assertTrue(admission.accepted)
        self.assertIsNotNone(queue.payload)
        payload, with_ui = queue.payload
        self.assertTrue(with_ui)
        self.assertEqual(payload["task_id"], "tts:direct:install")
        self.assertEqual(payload["timeout_sec"], DEFAULT_INSTALL_TIMEOUT_SEC)
        self.assertTrue(callable(payload["runner"]))


if __name__ == "__main__":
    unittest.main()
