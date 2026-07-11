from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.backends import BackendKind
from core.install_types import InstallAction, InstallPlan
from core.installables.types import ComponentCategory, ComponentMetadata
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


class _PreviewComponent:
    id = "tts:preview"

    def metadata(self):
        return ComponentMetadata(
            id=self.id,
            item_id="preview",
            category=ComponentCategory.TTS,
            title="Preview TTS",
            size="1 GB",
        )

    def build_install_plan(self, ctx):
        return InstallPlan(
            actions=[InstallAction(type="pip", description="Install model")],
            required_backend=BackendKind.CUDA,
            backend_context=dict(ctx or {}),
        )


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

    def test_install_preview_discloses_missing_backend_and_packages(self):
        service = DefaultInstallableCatalogService()
        backend_service = SimpleNamespace(
            build_requirement=lambda value: SimpleNamespace(kind=value)
        )
        spec = SimpleNamespace(
            group="torch",
            layer_id="torch-cuda",
            packages=("torch==2.7.1+cu128", "torchaudio==2.7.1+cu128"),
            capabilities=("torch.cpu", "torch.cuda"),
        )
        manager = SimpleNamespace(
            core_layer_specs=lambda _kind, _ctx: (spec,),
            get_core_layer=lambda _layer_id: None,
            find_core_layer=lambda **_kwargs: None,
        )

        with patch.object(service, "require_component", return_value=_PreviewComponent()), \
             patch("core.backends.get_backend_service", return_value=backend_service), \
             patch("core.runtime_environments.runtime_environments", return_value=manager), \
             patch("utils.gpu_utils.check_gpu_provider", return_value="NVIDIA"), \
             patch("utils.gpu_utils.format_primary_gpu_label", return_value="RTX 4060"):
            preview = service.install_preview("tts:preview")

        self.assertTrue(preview["backend_will_install"])
        self.assertEqual(preview["backend_kind"], "cuda")
        self.assertEqual(preview["gpu"], "RTX 4060")
        self.assertEqual(preview["additional_components"][0]["id"], "backend:cuda")
        self.assertIn("torch==2.7.1+cu128", preview["backend_packages"])
        self.assertEqual(preview["actions"], ["Install model"])

    def test_install_preview_does_not_claim_backend_install_when_layer_exists(self):
        service = DefaultInstallableCatalogService()
        backend_service = SimpleNamespace(
            build_requirement=lambda value: SimpleNamespace(kind=value)
        )
        spec = SimpleNamespace(
            group="torch",
            layer_id="torch-cuda",
            packages=("torch==2.7.1+cu128",),
            capabilities=("torch.cpu", "torch.cuda"),
        )
        manager = SimpleNamespace(
            core_layer_specs=lambda _kind, _ctx: (spec,),
            get_core_layer=lambda _layer_id: object(),
            find_core_layer=lambda **_kwargs: object(),
        )

        with patch.object(service, "require_component", return_value=_PreviewComponent()), \
             patch("core.backends.get_backend_service", return_value=backend_service), \
             patch("core.runtime_environments.runtime_environments", return_value=manager), \
             patch("utils.gpu_utils.check_gpu_provider", return_value="NVIDIA"), \
             patch("utils.gpu_utils.format_primary_gpu_label", return_value="RTX 4060"):
            preview = service.install_preview("tts:preview")

        self.assertTrue(preview["backend_ready"])
        self.assertFalse(preview["backend_will_install"])
        self.assertEqual(preview["additional_components"], [])


if __name__ == "__main__":
    unittest.main()
