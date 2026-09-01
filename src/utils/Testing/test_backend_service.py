from __future__ import annotations

import shutil
import unittest
import uuid
import os
import json
from pathlib import Path
from unittest.mock import Mock, patch

from core.backends import (
    BACKEND_NUMPY_SPEC,
    BackendRequirement,
    BackendStatus,
    BackendKind,
    BackendService,
    CUDA_INDEX_URL,
    ONNX_DIRECTML_PACKAGE,
    ONNX_DIRECTML_SPEC,
    ONNX_PACKAGE,
    TORCH_CUDA_PACKAGES,
    TORCH_VERSION,
    get_backend_service,
)
from core.backends.service import ONNX_VERSION
from core.install_requirements import InstallRequirement, check_requirements
from core.install_types import InstallAction, InstallPlan
from handlers.asr_handler import SpeechRecognition


_TMP_ROOT = Path(__file__).resolve().parents[3] / ".tmp_test_backend_service_runtime"


def _write_dist_info(root: Path, dist_name: str, version: str) -> None:
    dist_dir = root / f"{dist_name}-{version}.dist-info"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "METADATA").write_text(
        "\n".join(
            (
                "Metadata-Version: 2.1",
                f"Name: {dist_name}",
                f"Version: {version}",
                "",
            )
        ),
        encoding="utf-8",
    )


def _write_module(root: Path, module_name: str) -> None:
    parts = [part for part in str(module_name or "").split(".") if part]
    if not parts:
        return

    module_dir = root
    for part in parts:
        module_dir /= part
        module_dir.mkdir(parents=True, exist_ok=True)
        init_path = module_dir / "__init__.py"
        if not init_path.exists():
            init_path.write_text("", encoding="utf-8")


def _install_fake_dist(
    root: Path,
    *,
    dist_name: str,
    version: str,
    module_name: str | None = None,
) -> None:
    _write_dist_info(root, dist_name, version)
    if module_name:
        _write_module(root, module_name)


def _install_torch_cpu_stack(root: Path) -> None:
    _install_fake_dist(root, dist_name="torch", version=TORCH_VERSION, module_name="torch")
    _install_fake_dist(root, dist_name="torchaudio", version=TORCH_VERSION, module_name="torchaudio")
    _install_fake_dist(root, dist_name="numpy", version="1.26.0", module_name="numpy")


class _FakeBackendAwareRecognizer:
    def __init__(self, pip_installer, logger):
        self.pip_installer = pip_installer
        self.logger = logger

    def apply_settings(self, settings):
        self.settings = dict(settings or {})

    def is_installed(self):
        return False

    def pip_install_steps(self, ctx):
        return [
            {
                "description": "Installing recognizer package...",
                "progress": 20,
                "packages": ["faster-whisper"],
            }
        ]

    def required_backend(self, ctx):
        return get_backend_service().preferred_torch_kind(ctx)

    def build_install_plan(self, ctx):
        return InstallPlan(
            required_backend=self.required_backend(ctx),
            backend_context=dict(ctx or {}),
            actions=[
                InstallAction(
                    type="pip",
                    description="Installing recognizer package...",
                    progress=20,
                    packages=["faster-whisper"],
                )
            ],
        )

    async def install(self):
        return True


class BackendServiceTests(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.libs_dir = _TMP_ROOT / f"case_{uuid.uuid4().hex}"
        self.libs_dir.mkdir(parents=True, exist_ok=False)
        self.service = BackendService()
        self._old_lib_dir = os.environ.get("NEUROMITA_LIB_DIR")
        os.environ["NEUROMITA_LIB_DIR"] = str(self.libs_dir)

    def tearDown(self):
        if self._old_lib_dir is None:
            os.environ.pop("NEUROMITA_LIB_DIR", None)
        else:
            os.environ["NEUROMITA_LIB_DIR"] = self._old_lib_dir
        shutil.rmtree(self.libs_dir, ignore_errors=True)

    def test_cpu_backend_status_is_ready_for_fake_lib(self):
        _install_torch_cpu_stack(self.libs_dir)

        status = self.service.get_status(
            BackendKind.CPU,
            ctx={"gpu_vendor": "CPU", "libs_dir": str(self.libs_dir)},
        )

        self.assertTrue(status.ok)
        self.assertEqual(status.action, "skip")
        self.assertEqual(status.variant, "torch_cpu")
        self.assertEqual(status.provider, "cpu")
        self.assertEqual(status.resolved_kind, BackendKind.CPU)

    def test_cuda_backend_plan_requests_reinstall_for_cpu_runtime_on_nvidia(self):
        _install_torch_cpu_stack(self.libs_dir)

        plan = self.service.build_install_plan(
            BackendKind.CUDA,
            ctx={"gpu_vendor": "NVIDIA", "libs_dir": str(self.libs_dir)},
        )

        self.assertFalse(plan.ok)
        self.assertEqual(plan.action, "reinstall")
        self.assertEqual(plan.status.variant, "torch_cpu")
        self.assertEqual(plan.uninstall_packages, ("torch", "torchaudio"))
        self.assertEqual(plan.install_packages, TORCH_CUDA_PACKAGES + (BACKEND_NUMPY_SPEC,))
        self.assertIn("--extra-index-url", plan.extra_args)
        self.assertIn(CUDA_INDEX_URL, plan.extra_args)

    def test_onnx_backend_status_prefers_dml_on_amd(self):
        _install_torch_cpu_stack(self.libs_dir)
        _install_fake_dist(
            self.libs_dir,
            dist_name=ONNX_DIRECTML_PACKAGE,
            version="1.20.1",
            module_name="onnxruntime",
        )

        status = self.service.get_status(
            BackendKind.ONNX,
            ctx={"gpu_vendor": "AMD", "libs_dir": str(self.libs_dir)},
        )

        self.assertTrue(status.ok)
        self.assertEqual(status.variant, "onnx_dml")
        self.assertEqual(status.provider, "dml")
        self.assertIn("DmlExecutionProvider", status.onnx_providers)

    def test_windows_onnx_backend_always_selects_directml_distribution(self):
        for vendor in ("NVIDIA", "AMD", "INTEL", "CPU"):
            with self.subTest(vendor=vendor):
                self.assertEqual(
                    self.service.preferred_onnx_provider(
                        {
                            "platform": "Windows",
                            "gpu_vendor": vendor,
                            "device": "cpu",
                        }
                    ),
                    "dml",
                )

    def test_plain_onnxruntime_is_replaced_by_directml_on_windows(self):
        _install_torch_cpu_stack(self.libs_dir)
        _install_fake_dist(
            self.libs_dir,
            dist_name=ONNX_PACKAGE,
            version=ONNX_VERSION,
            module_name="onnxruntime",
        )
        self.service._write_backend_marker(
            str(self.libs_dir),
            BackendKind.ONNX,
            "cpu",
        )

        status = self.service.get_status(
            BackendKind.ONNX,
            ctx={
                "platform": "Windows",
                "gpu_vendor": "NVIDIA",
                "device": "cpu",
                "libs_dir": str(self.libs_dir),
            },
        )

        self.assertFalse(status.ok)
        self.assertEqual(status.action, "reinstall")
        self.assertIn(ONNX_DIRECTML_SPEC, status.install_packages)
        self.assertEqual(
            status.uninstall_packages,
            (ONNX_PACKAGE, ONNX_DIRECTML_PACKAGE),
        )

    def test_uv_overrides_pin_installed_backend_managed_packages(self):
        _install_torch_cpu_stack(self.libs_dir)

        overrides = self.service.build_uv_overrides(
            BackendKind.CUDA,
            requested_specs=["faster-whisper"],
        )

        self.assertEqual(
            overrides,
            (
                f"torch=={TORCH_VERSION}",
                f"torchaudio=={TORCH_VERSION}",
                "numpy==1.26.0",
            ),
        )

    def test_uv_overrides_use_authoritative_core_versions_despite_stale_metadata(self):
        _install_fake_dist(self.libs_dir, dist_name="torch", version="2.6.0", module_name="torch")
        _install_fake_dist(self.libs_dir, dist_name="torchaudio", version="2.6.0", module_name="torchaudio")
        _install_fake_dist(self.libs_dir, dist_name="numpy", version="2.0.0", module_name="numpy")

        overrides = self.service.build_uv_overrides(
            BackendKind.ONNX,
            requested_specs=["tts-with-rvc-onnx[dml]"],
        )

        self.assertIn(f"torch=={TORCH_VERSION}", overrides)
        self.assertIn(f"torchaudio=={TORCH_VERSION}", overrides)
        self.assertIn("numpy==1.26.0", overrides)
        self.assertNotIn("torch==2.6.0", overrides)
        self.assertNotIn("numpy==2.0.0", overrides)

    def test_target_distribution_version_chooses_highest_duplicate_metadata(self):
        _write_dist_info(self.libs_dir, "torchaudio", "2.6.0")
        _write_dist_info(self.libs_dir, "torchaudio", "2.7.1")

        self.assertEqual(
            self.service._dist_version_in_target("torchaudio", str(self.libs_dir)),
            "2.7.1",
        )

    def test_backend_requirement_fails_when_runtime_missing(self):
        result = check_requirements(
            [
                InstallRequirement(
                    id="backend_cpu",
                    kind="backend",
                    backend_kind=BackendKind.CPU,
                    required=True,
                )
            ],
            ctx={"gpu_vendor": "CPU", "libs_dir": str(self.libs_dir)},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_required"], ["backend_cpu"])

    def test_asr_install_plan_carries_backend_prerequisite(self):
        original_registry = getattr(SpeechRecognition, "_registry", {})
        SpeechRecognition._registry = {"dummy": _FakeBackendAwareRecognizer}
        try:
            with patch("utils.gpu_utils.check_gpu_provider", return_value="NVIDIA"):
                plan = SpeechRecognition.build_install_plan(
                    "dummy",
                    pip_installer=object(),
                    engine_settings={"device": "auto"},
                )
        finally:
            SpeechRecognition._registry = original_registry

        self.assertEqual(plan.required_backend, BackendKind.CUDA)
        self.assertEqual(plan.backend_context["gpu_vendor"], "NVIDIA")
        self.assertEqual(plan.actions[0].type, "pip")

    def test_install_backend_accepts_backend_kind_for_onnx_marker_write(self):
        pending = BackendStatus(
            requirement=BackendRequirement(kind=BackendKind.ONNX),
            requested_kind=BackendKind.ONNX,
            resolved_kind=BackendKind.ONNX,
            ok=False,
            action="install",
            reason="Installing ONNX backend...",
            variant="missing",
            provider="missing",
            cuda_available=False,
            onnx_providers=(),
            install_packages=(ONNX_DIRECTML_PACKAGE,),
            uninstall_packages=(),
            extra_args=(),
            managed_dist_names=("onnxruntime-directml",),
            target_dir=str(self.libs_dir),
        )
        ready = BackendStatus(
            requirement=BackendRequirement(kind=BackendKind.ONNX),
            requested_kind=BackendKind.ONNX,
            resolved_kind=BackendKind.ONNX,
            ok=True,
            action="skip",
            reason="ONNX backend is ready.",
            variant="onnx_dml",
            provider="dml",
            cuda_available=False,
            onnx_providers=("DmlExecutionProvider", "CPUExecutionProvider"),
            install_packages=(),
            uninstall_packages=(),
            extra_args=(),
            managed_dist_names=("onnxruntime-directml",),
            target_dir=str(self.libs_dir),
        )
        pip_installer = Mock()
        pip_installer.install_package.return_value = True

        with patch.object(self.service, "get_status", side_effect=[pending, ready]), \
             patch.object(self.service, "_onnx_variant", return_value="onnx_dml"), \
             patch.object(self.service, "preferred_onnx_provider", return_value="cpu") as preferred:
            status = self.service.install_backend(
                BackendKind.ONNX,
                pip_installer=pip_installer,
                ctx={"gpu_vendor": "AMD", "libs_dir": str(self.libs_dir)},
            )

        self.assertTrue(status.ok)
        marker_path = self.libs_dir / ".neuromita_backends.json"
        self.assertTrue(marker_path.exists())
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertEqual(marker["onnx"]["provider"], "dml")
        preferred.assert_not_called()

    def test_write_backend_marker_uses_atomic_replace(self):
        with patch("core.backends.service.os.replace", wraps=os.replace) as replace_mock:
            self.service._write_backend_marker(str(self.libs_dir), BackendKind.CPU, "cpu")

        marker_path = self.libs_dir / ".neuromita_backends.json"
        self.assertTrue(marker_path.exists())
        self.assertTrue(replace_mock.called)
        self.assertEqual(replace_mock.call_args[0][1], str(marker_path))


if __name__ == "__main__":
    unittest.main()
