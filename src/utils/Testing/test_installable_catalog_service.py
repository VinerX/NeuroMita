from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import unittest
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.backends import BackendKind
from core.install_types import InstallAction, InstallPlan
from core.installables.types import ComponentCategory, ComponentMetadata
from installables.registry_builder import LazyInstallableRegistry
from handlers.voice_models.fish_speech_model import FishSpeechInstallSpec
from services.installable_catalog_service import DefaultInstallableCatalogService
from services.asr_settings_service import FileASRSettingsService


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
    def test_public_query_contract_has_no_caller_context(self):
        from services.contracts import InstallableCatalogService

        for method_name in (
            "list_rows",
            "get_row",
            "get_status",
            "is_ready",
            "ready_item_ids",
            "list_rows_async",
            "get_status_async",
            "install_preview",
        ):
            self.assertNotIn(
                "ctx",
                inspect.signature(getattr(InstallableCatalogService, method_name)).parameters,
                method_name,
            )

    def test_operation_plan_rejects_hardware_and_settings_from_executor(self):
        hardware = SimpleNamespace(
            snapshot=lambda refresh=False: {
                "vendor": "NVIDIA",
                "platform": "Windows",
                "primary": {"name": "RTX"},
                "cuda": {"devices": [{"ordinal": 0}]},
            }
        )
        service = DefaultInstallableCatalogService(hardware=hardware)
        self.addCleanup(service.close)
        observed = {}
        component = SimpleNamespace(
            build_install_plan=lambda ctx: observed.setdefault("ctx", dict(ctx)) or InstallPlan(),
        )

        with patch.object(service, "require_component", return_value=component), \
             patch("core.runtime_environments.runtime_environments", return_value=SimpleNamespace(
                 component_context=lambda **kwargs: dict(kwargs["ctx"]),
             )):
            service.build_operation_plan(
                "asr:google",
                "install",
                execution_ctx={
                    "gpu_vendor": "AMD",
                    "engine_settings": {"device": "cuda"},
                    "target_dir": "X:/staging",
                },
            )

        self.assertEqual(observed["ctx"]["gpu_vendor"], "NVIDIA")
        self.assertNotEqual(observed["ctx"]["engine_settings"], {"device": "cuda"})
        self.assertEqual(observed["ctx"]["target_dir"], "X:/staging")

    def test_asr_setting_change_does_not_leave_unreachable_cache_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            asr_settings = FileASRSettingsService(str(Path(tmp) / "asr.json"))
            service = DefaultInstallableCatalogService(asr_settings=asr_settings)
            self.addCleanup(service.close)
            calls = []

            def inspect(entry, _ctx):
                calls.append(entry.id)
                return {
                    "id": entry.id,
                    "code": "ready",
                    "installed": True,
                    "ready": True,
                    "backend": entry.declared_backend,
                    "backend_ok": True,
                    "details": {},
                }

            with patch.object(service, "_prepare_runtime_registry"), \
                 patch.object(service, "_component_context", wraps=service._component_context), \
                 patch("core.runtime_environments.runtime_environments", return_value=SimpleNamespace(
                     component_context=lambda **kwargs: dict(kwargs["ctx"]),
                 )), \
                 patch.object(service, "_inspect_component", side_effect=inspect):
                service.get_status("asr:google")
                service.get_status("asr:gigaam")
                self.assertEqual(len(service._status_cache), 2)

                asr_settings.set_model_option("google", "language", "ru-RU")
                self.assertEqual(
                    {key[0] for key in service._status_cache},
                    {"asr:gigaam"},
                )

                service.get_status("asr:gigaam")
                service.get_status("asr:google")

            self.assertEqual(len(service._status_cache), 2)
            self.assertEqual(calls.count("asr:gigaam"), 1)
            self.assertEqual(calls.count("asr:google"), 2)

    def test_status_context_is_owned_by_catalog(self):
        hardware = SimpleNamespace(
            snapshot=lambda refresh=False: {
                "vendor": "AMD",
                "platform": "Windows",
                "primary": {"name": "Radeon"},
                "cuda": {"devices": []},
            }
        )
        service = DefaultInstallableCatalogService(hardware=hardware)
        self.addCleanup(service.close)
        calls = []

        def inspect(entry, ctx):
            calls.append(dict(ctx))
            return {
                "id": entry.id,
                "code": "ready",
                "installed": True,
                "ready": True,
                "backend": "cpu",
                "backend_ok": True,
                "details": {},
            }

        with patch.object(service, "_prepare_runtime_registry"), \
             patch("core.runtime_environments.runtime_environments", return_value=SimpleNamespace(
                 component_context=lambda **kwargs: dict(kwargs["ctx"]),
             )), \
             patch.object(service, "_inspect_component", side_effect=inspect):
            status = service.get_status("asr:google")
            status_again = service.get_status("asr:google")
            with self.assertRaises(TypeError):
                service.get_status("asr:google", ctx={"gpu_vendor": "NVIDIA"})

        self.assertTrue(status["ready"])
        self.assertEqual(status_again, status)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["gpu_vendor"], "AMD")

    def test_invalidation_rejects_late_probe_result(self):
        service = DefaultInstallableCatalogService(status_timeout_sec=2.0)
        self.addCleanup(service.close)
        started = threading.Event()
        release = threading.Event()
        observed = {}
        probe_count = 0

        def inspect(entry, _ctx):
            nonlocal probe_count
            probe_count += 1
            if probe_count == 1:
                started.set()
                release.wait(2.0)
                code = "stale"
            else:
                code = "fresh"
            return {
                "id": entry.id,
                "code": code,
                "installed": True,
                "ready": code == "fresh",
                "backend": "cpu",
                "backend_ok": code == "fresh",
                "details": {},
            }

        def read_status():
            try:
                observed["status"] = service.get_status("asr:google")
            except Exception as exc:
                observed["error"] = exc

        with patch.object(service, "_prepare_runtime_registry"), \
             patch.object(service, "_component_context", return_value={}), \
             patch.object(service, "_inspect_component", side_effect=inspect):
            thread = threading.Thread(target=read_status)
            thread.start()
            self.assertTrue(started.wait(1.0))
            service.invalidate("asr:google")
            release.set()
            thread.join(2.0)
            self.assertFalse(thread.is_alive())
            self.assertIn("error", observed)
            fresh = service.get_status("asr:google")

        self.assertEqual(fresh["code"], "fresh")
        self.assertTrue(fresh["ready"])

    def test_probe_timeout_does_not_block_catalog_or_shutdown(self):
        service = DefaultInstallableCatalogService(status_timeout_sec=0.05)
        release = threading.Event()

        def inspect(_entry, _ctx):
            release.wait(2.0)
            return {
                "id": "asr:google",
                "code": "ready",
                "installed": True,
                "ready": True,
                "backend": "cpu",
                "backend_ok": True,
                "details": {},
            }

        try:
            with patch.object(service, "_prepare_runtime_registry"), \
                 patch.object(service, "_component_context", return_value={}), \
                 patch.object(service, "_inspect_component", side_effect=inspect):
                started_at = time.monotonic()
                status = service.get_status("asr:google")
                elapsed = time.monotonic() - started_at
                self.assertFalse(service._status_cache)
                release.set()
                deadline = time.monotonic() + 1.0
                while service._inflight and time.monotonic() < deadline:
                    time.sleep(0.01)
                status_after_completion = service.get_status("asr:google")
            self.assertEqual(status["code"], "unknown")
            self.assertEqual(status["probe_state"], "timeout")
            self.assertEqual(status_after_completion["code"], "ready")
            self.assertLess(elapsed, 0.5)
        finally:
            release.set()
            service.close()

    def test_fish_speech_compatibility_is_driven_by_cuda_and_compute_capability(self):
        def service_for(vendor, capability=None):
            devices = []
            if capability is not None:
                devices.append(
                    {
                        "ordinal": 0,
                        "compute_major": capability // 10,
                        "compute_minor": capability % 10,
                    }
                )
            hardware = SimpleNamespace(
                snapshot=lambda refresh=False: {
                    "vendor": vendor,
                    "platform": "Windows",
                    "primary": {"name": vendor},
                    "cuda": {"available": bool(devices), "devices": devices},
                }
            )
            instance = DefaultInstallableCatalogService(hardware=hardware)
            self.addCleanup(instance.close)
            return instance

        amd = service_for("AMD")
        old_nvidia = service_for("NVIDIA", 75)
        modern_nvidia = service_for("NVIDIA", 89)

        self.assertFalse(amd.get_row("tts:medium", include_status=False)["compatibility"]["supported"])
        with patch.object(amd, "require_component") as require_component:
            with self.assertRaises(RuntimeError):
                amd.build_operation_plan("tts:medium", "install")
            require_component.assert_not_called()
        old_verdict = old_nvidia.get_row("tts:medium+", include_status=False)["compatibility"]
        self.assertTrue(old_verdict["supported"])
        self.assertFalse(old_verdict["recommended"])
        self.assertEqual(old_verdict["compute_capability"], "sm_75")
        self.assertEqual(old_verdict["hardware_tags"][0]["label"], "RTX 30+")
        self.assertTrue(
            modern_nvidia.get_row("tts:medium+", include_status=False)["compatibility"]["recommended"]
        )

    def test_fish_install_plan_has_no_private_vendor_gate(self):
        with patch.object(FishSpeechInstallSpec, "is_installed", return_value=False):
            plan = FishSpeechInstallSpec.build_install_plan("medium", {"gpu_vendor": "AMD"})

        self.assertEqual(plan.required_backend, BackendKind.CUDA)
        self.assertTrue(plan.actions)
        self.assertNotIn("NVIDIA GPU", str(plan.actions[0].description))

    def test_component_readiness_has_one_cached_snapshot_for_all_consumers(self):
        service = DefaultInstallableCatalogService()
        self.addCleanup(service.close)
        status = {
            "id": "asr:google",
            "code": "backend_missing",
            "installed": True,
            "ready": False,
            "backend": "cpu",
            "backend_ok": False,
            "details": {},
        }
        with patch.object(service, "_prepare_runtime_registry"), \
             patch.object(service, "_component_context", return_value={}), \
             patch.object(service, "_inspect_component", return_value=status) as inspect:
            self.assertFalse(service.is_ready("asr:google"))
            self.assertFalse(service.get_status("asr:google")["ready"])
            self.assertFalse(service.get_row("asr:google")["status"]["ready"])
            self.assertEqual(inspect.call_count, 1)

        completed = threading.Event()
        observed = {}

        def callback(status, error):
            observed["status"] = status
            observed["error"] = error
            completed.set()

        with patch.object(service, "_component_context", return_value={}):
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
        self.addCleanup(service.close)
        component = _ConfigurableComponent()
        service._status_cache[("tts:test", "ctx")] = {"ready": True}

        with patch.object(service, "require_component", return_value=component):
            self.assertEqual(service.settings_schema("tts:test")[0]["key"], "quality")
            self.assertEqual(service.load_settings("tts:test"), {"quality": "high"})
            self.assertTrue(service.save_component_settings("tts:test", {"quality": "low"})["ok"])
            self.assertEqual(component.saved, {"quality": "low"})
            self.assertFalse(any(key[0] == "tts:test" for key in service._status_cache))

    def test_install_preview_discloses_missing_backend_and_packages(self):
        hardware = SimpleNamespace(
            snapshot=lambda refresh=False: {
                "vendor": "NVIDIA",
                "primary": {"name": "RTX 4060"},
            }
        )
        service = DefaultInstallableCatalogService(hardware=hardware)
        self.addCleanup(service.close)
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
             patch("core.backends.get_backend_service", return_value=backend_service):
            preview = service.install_preview("tts:edge_tts_rvc_cuda")

        self.assertTrue(preview["backend_will_install"])
        self.assertEqual(preview["backend_kind"], "cuda")
        self.assertEqual(preview["gpu"], "RTX 4060")
        self.assertEqual(preview["additional_components"][0]["id"], "backend:cuda")
        self.assertIn("torch==2.7.1+cu128", preview["backend_packages"])
        self.assertEqual(preview["actions"], ["Install model"])

    def test_install_preview_does_not_claim_backend_install_when_layer_exists(self):
        hardware = SimpleNamespace(
            snapshot=lambda refresh=False: {
                "vendor": "NVIDIA",
                "primary": {"name": "RTX 4060"},
            }
        )
        service = DefaultInstallableCatalogService(hardware=hardware)
        self.addCleanup(service.close)
        backend_service = SimpleNamespace(
            build_requirement=lambda value: SimpleNamespace(kind=value)
        )
        backend_status = {
            "ready": True,
            "details": {"install_packages": ["torch==2.7.1+cu128"]},
        }

        with patch.object(service, "require_component", return_value=_PreviewComponent()), \
             patch.object(service, "get_status", return_value=backend_status), \
             patch("core.backends.get_backend_service", return_value=backend_service):
            preview = service.install_preview("tts:edge_tts_rvc_cuda")

        self.assertTrue(preview["backend_ready"])
        self.assertFalse(preview["backend_will_install"])
        self.assertEqual(preview["additional_components"], [])


if __name__ == "__main__":
    unittest.main()
