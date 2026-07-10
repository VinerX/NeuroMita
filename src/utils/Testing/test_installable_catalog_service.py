from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from installables.registry_builder import LazyInstallableRegistry
from services.installable_catalog_service import DefaultInstallableCatalogService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _ConfigurableComponent:
    def settings_schema(self):
        return [{"key": "quality", "type": "entry"}]

    def load_settings(self):
        return {"quality": "high"}

    def validate_settings(self, values):
        return SimpleNamespace(ok="quality" in values, errors={} if "quality" in values else {"quality": "required"})

    def save_settings(self, values):
        self.saved = dict(values)


class InstallableCatalogServiceTests(unittest.TestCase):
    def test_metadata_phase_does_not_import_work_registry_or_model_modules(self):
        code = """
import sys
from services.installable_catalog_service import DefaultInstallableCatalogService
rows = DefaultInstallableCatalogService().list_rows()
assert len(rows) == 30
for name in (
    'installables.registry_builder',
    'handlers.voice_models.edge_tts_rvc_model',
    'handlers.asr_handler',
    'managers.rag.install_spec',
):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(PROJECT_ROOT)},
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_lazy_registry_loads_only_requested_component_group(self):
        registry = LazyInstallableRegistry()
        calls: list[str] = []

        def resolve(path: str):
            calls.append(path)
            component_id = "dependency:ffmpeg"
            return lambda: [SimpleNamespace(id=component_id)]

        with patch.object(registry, "_resolve_loader", side_effect=resolve):
            component = registry.get("dependency:ffmpeg")

        self.assertIsNotNone(component)
        self.assertEqual(getattr(component, "id", None), "dependency:ffmpeg")
        self.assertEqual(calls, ["installables.ffmpeg_component:create_ffmpeg_installable_components"])

    def test_component_settings_are_available_without_install_controller(self):
        service = DefaultInstallableCatalogService()
        component = _ConfigurableComponent()

        with patch.object(service, "require_component", return_value=component):
            self.assertEqual(service.settings_schema("tts:test")[0]["key"], "quality")
            self.assertEqual(service.load_settings("tts:test"), {"quality": "high"})
            self.assertTrue(service.save_component_settings("tts:test", {"quality": "low"})["ok"])
            self.assertEqual(component.saved, {"quality": "low"})


if __name__ == "__main__":
    unittest.main()
