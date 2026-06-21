from __future__ import annotations

import unittest
from unittest.mock import patch

from controllers.installable_controller import InstallableController
from core.backends import BackendKind
from core.events import Event
from core.installables import ComponentCategory, ComponentMetadata, ComponentStatus, ComponentStatusCode
from game_connections.services import beat_backend_spec
from installables.registry_builder import build_installable_registry


class _RegistryStub:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)

    def by_category(self, category):
        value = str(category or "").strip().lower()
        return [item for item in self._items if str(item.category.value).strip().lower() == value]


class _GoodComponent:
    category = ComponentCategory.DEPENDENCY
    legacy_kind = "deps"
    item_id = "ffmpeg"
    id = "dependency:ffmpeg"

    def metadata(self):
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title="FFmpeg",
            description="Audio tool",
            backend=BackendKind.NONE,
            legacy_kind=self.legacy_kind,
        )

    def status(self, ctx=None):
        return ComponentStatus(
            id=self.id,
            code=ComponentStatusCode.READY,
            installed=True,
            ready=True,
            message="Ready",
            backend=BackendKind.NONE,
            backend_ok=True,
        )


class _BrokenMetadataComponent(_GoodComponent):
    item_id = "broken_meta"
    id = "dependency:broken_meta"

    def metadata(self):
        raise RuntimeError("metadata exploded")


class _BrokenStatusComponent(_GoodComponent):
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


class InstallableControllerTests(unittest.TestCase):
    def test_on_list_survives_broken_components(self):
        controller = InstallableController()
        stub_registry = _RegistryStub([
            _GoodComponent(),
            _BrokenMetadataComponent(),
            _BrokenStatusComponent(),
        ])
        event = Event(name="installable_list", data={"include_status": True})

        with patch("controllers.installable_controller.get_installable_registry", return_value=stub_registry):
            rows = controller._on_list(event)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["metadata"]["id"], "dependency:ffmpeg")
        self.assertEqual(rows[1]["metadata"]["id"], "dependency:broken_meta")
        self.assertEqual(rows[1]["metadata"]["title"], "broken_meta")
        self.assertEqual(rows[2]["status"]["code"], ComponentStatusCode.FAILED.value)
        self.assertIn("status exploded", rows[2]["status"]["message"])

    def test_registry_builder_keeps_ffmpeg_when_one_group_fails(self):
        with patch("installables.registry_builder.create_beat_installable_components", side_effect=RuntimeError("beat boom")):
            registry = build_installable_registry()

        self.assertIsNotNone(registry.get("dependency:ffmpeg"))
        self.assertIsNotNone(registry.get("voices:all"))

    def test_beat_gpu_detect_reuses_shared_gpu_probe(self):
        with patch("game_connections.services.beat_backend_spec.platform.system", return_value="Windows"), \
             patch("game_connections.services.beat_backend_spec.check_gpu_provider", return_value="AMD") as gpu_probe:
            vendor = beat_backend_spec._detect_gpu_vendor()

        self.assertEqual(vendor, "AMD")
        gpu_probe.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
