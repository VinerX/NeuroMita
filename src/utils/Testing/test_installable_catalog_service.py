from __future__ import annotations

import subprocess
import sys
import threading
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
    def test_component_readiness_has_one_cached_snapshot_for_all_consumers(self):
        service = DefaultInstallableCatalogService()
        service._status_cache["asr:google"] = {
            "id": "asr:google",
            "code": "backend_missing",
            "installed": True,
            "ready": False,
            "backend": "cpu",
            "backend_ok": False,
            "details": {},
        }

        self.assertFalse(service.is_ready("asr:google"))
        self.assertFalse(service.get_status("asr:google")["ready"])
        self.assertFalse(service.get_row("asr:google")["status"]["ready"])

        completed = threading.Event()
        observed = {}

        def callback(status, error):
            observed["status"] = status
            observed["error"] = error
            completed.set()

        service.get_status_async("asr:google", callback)
        self.assertTrue(completed.wait(2.0))
        self.assertIsNone(observed["error"])
        self.assertFalse(observed["status"]["ready"])

    def test_metadata_phase_does_not_import_work_registry_or_model_modules(self):
        code = """
import sys
from services.installable_catalog_service import DefaultInstallableCatalogService
rows = DefaultInstallableCatalogService().list_rows()
# RAG embed/reranker модели теперь идут отдельной карточкой на модель и
# строятся из пресетов, поэтому точное число зависит от набора пресетов.
assert len(rows) >= 30
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
        service._status_cache["tts:test"] = {"ready": True}

        with patch.object(service, "require_component", return_value=component):
            self.assertEqual(service.settings_schema("tts:test")[0]["key"], "quality")
            self.assertEqual(service.load_settings("tts:test"), {"quality": "high"})
            self.assertTrue(service.save_component_settings("tts:test", {"quality": "low"})["ok"])
            self.assertEqual(component.saved, {"quality": "low"})
            self.assertNotIn("tts:test", service._status_cache)

    def test_install_preview_discloses_missing_backend_and_packages(self):
        service = DefaultInstallableCatalogService()
        backend_service = SimpleNamespace(
            build_requirement=lambda value: SimpleNamespace(kind=value)
        )
        backend_status = {
            "ready": False,
            "details": {
                "install_packages": [
                    "torch==2.7.1+cu128",
                    "torchaudio==2.7.1+cu128",
                ]
            },
        }

        with patch.object(service, "require_component", return_value=_PreviewComponent()), \
             patch.object(service, "get_status", return_value=backend_status), \
             patch("core.backends.get_backend_service", return_value=backend_service), \
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
        backend_status = {
            "ready": True,
            "details": {"install_packages": ["torch==2.7.1+cu128"]},
        }

        with patch.object(service, "require_component", return_value=_PreviewComponent()), \
             patch.object(service, "get_status", return_value=backend_status), \
             patch("core.backends.get_backend_service", return_value=backend_service), \
             patch("utils.gpu_utils.check_gpu_provider", return_value="NVIDIA"), \
             patch("utils.gpu_utils.format_primary_gpu_label", return_value="RTX 4060"):
            preview = service.install_preview("tts:preview")

        self.assertTrue(preview["backend_ready"])
        self.assertFalse(preview["backend_will_install"])
        self.assertEqual(preview["additional_components"], [])


if __name__ == "__main__":
    unittest.main()
