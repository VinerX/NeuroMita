from __future__ import annotations

import json
import os
import sys
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.torch_compile_runtime import (
    cache_directories,
    clear_compile_cache,
    compile_cache_metadata_path,
    compile_cache_status,
    configure_compile_environment,
    fish_speech_compile_environment,
    record_compile_target,
)


class TorchCompileRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self._environment = patch.dict(
            os.environ,
            {"NEUROMITA_ENVIRONMENT_DIR": str(self.root)},
        )
        self._environment.start()

    def tearDown(self) -> None:
        self._environment.stop()
        self._temporary.cleanup()

    def _create_cache_file(self, device: str | None = None) -> Path:
        cache_file = cache_directories(device)[0] / "compiled.bin"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(b"compiled")
        return cache_file

    def test_compile_cache_tracks_each_cuda_device(self) -> None:
        self._create_cache_file("cuda:0")
        self._create_cache_file("cuda:1")
        record_compile_target("cuda", gpu_name="GPU Zero", compute_capability="8.6")
        record_compile_target("cuda:1", gpu_name="GPU One", compute_capability="12.0")

        status = compile_cache_status()

        self.assertEqual(status["compile_metadata_state"], "current")
        self.assertEqual(status["compiled_devices"], ["cuda:0", "cuda:1"])
        self.assertEqual(
            [item["gpu_name"] for item in status["compiled_targets"]],
            ["GPU Zero", "GPU One"],
        )

    def test_legacy_single_target_metadata_is_migrated(self) -> None:
        self._create_cache_file()
        metadata_path = compile_cache_metadata_path()
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps({"device": "cuda", "gpu_name": "Legacy GPU"}),
            encoding="utf-8",
        )

        status = compile_cache_status()
        migrated = json.loads(metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(status["compile_metadata_state"], "migrated")
        self.assertEqual(status["compiled_devices"], ["cuda:0"])
        self.assertEqual(migrated["schema_version"], 3)
        self.assertIn("cuda:0", migrated["targets"])
        self.assertEqual(migrated["targets"]["cuda:0"]["cache_layout"], "shared")

    def test_cache_without_metadata_is_reported_as_legacy(self) -> None:
        self._create_cache_file()

        status = compile_cache_status()

        self.assertIs(status["cache_exists"], True)
        self.assertEqual(status["compile_metadata_state"], "legacy")
        self.assertEqual(status["compiled_targets"], [])

    def test_clear_compile_cache_removes_target_metadata(self) -> None:
        self._create_cache_file("cuda:1")
        self._create_cache_file()
        record_compile_target("cuda:1", gpu_name="GPU One")

        clear_compile_cache()

        self.assertIs(compile_cache_metadata_path().exists(), False)
        self.assertIs(compile_cache_status()["cache_exists"], False)

    def test_recompile_one_device_preserves_other_device_cache_and_metadata(self) -> None:
        zero = self._create_cache_file("cuda:0")
        one = self._create_cache_file("cuda:1")
        record_compile_target("cuda:0", gpu_name="GPU Zero")
        record_compile_target("cuda:1", gpu_name="GPU One")
        before = compile_cache_status()["compiled_targets"][0]

        clear_compile_cache("cuda:1")

        self.assertEqual(zero.read_bytes(), b"compiled")
        self.assertFalse(one.exists())
        self.assertEqual(compile_cache_status()["compiled_targets"], [before])
        self._create_cache_file("cuda:1")
        record_compile_target("cuda:1", gpu_name="GPU One")
        self.assertEqual(compile_cache_status()["compiled_devices"], ["cuda:0", "cuda:1"])

    def test_missing_device_cache_is_not_reported_as_compiled(self) -> None:
        self._create_cache_file("cuda:0")
        record_compile_target("cuda:0")
        record_compile_target("cuda:1")
        self.assertEqual(compile_cache_status()["compiled_devices"], ["cuda:0"])

    def test_device_environment_overrides_inherited_cache_paths(self) -> None:
        env = {"TORCHINDUCTOR_CACHE_DIR": "old", "TRITON_CACHE_DIR": "old"}
        configure_compile_environment(env=env, device="cuda:1")
        self.assertEqual(env["TORCHINDUCTOR_CACHE_DIR"], str(cache_directories("cuda:1")[0]))
        self.assertEqual(env["TRITON_CACHE_DIR"], str(cache_directories("cuda:1")[1]))

    def test_runtime_uses_selected_cache_and_restores_environment_on_error(self) -> None:
        with patch.dict(os.environ, {"TORCHINDUCTOR_CACHE_DIR": "original", "TRITON_CACHE_DIR": "original"}):
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                with fish_speech_compile_environment("cuda:1"):
                    self.assertEqual(os.environ["TORCHINDUCTOR_CACHE_DIR"], str(cache_directories("cuda:1")[0]))
                    self.assertEqual(os.environ["TRITON_CACHE_DIR"], str(cache_directories("cuda:1")[1]))
                    raise RuntimeError("inference failed")
            self.assertEqual(os.environ["TORCHINDUCTOR_CACHE_DIR"], "original")
            self.assertEqual(os.environ["TRITON_CACHE_DIR"], "original")

    def test_schema_two_shared_cache_remains_available_to_other_gpu(self) -> None:
        legacy = self._create_cache_file()
        metadata_path = compile_cache_metadata_path()
        metadata_path.write_text(json.dumps({
            "schema_version": 2,
            "targets": {"cuda:0": {"gpu_name": "Zero"}, "cuda:1": {"gpu_name": "One"}},
        }), encoding="utf-8")

        clear_compile_cache("cuda:1")
        self._create_cache_file("cuda:1")
        record_compile_target("cuda:1")

        self.assertEqual(legacy.read_bytes(), b"compiled")
        self.assertEqual(compile_cache_status()["compiled_devices"], ["cuda:0", "cuda:1"])
        with fish_speech_compile_environment("cuda:0") as paths:
            self.assertEqual(paths, cache_directories())
        with fish_speech_compile_environment("cuda:1") as paths:
            self.assertEqual(paths, cache_directories("cuda:1"))

    def test_invalid_device_cannot_escape_cache_root(self) -> None:
        for device in ("cuda:../other", "cuda:-1", "cpu", ""):
            with self.subTest(device=device), self.assertRaises(ValueError):
                clear_compile_cache(device)

    def test_concurrent_device_records_do_not_overwrite_each_other(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
        devices = [f"cuda:{index}" for index in range(4)]
        for device in devices:
            self._create_cache_file(device)
        processes = [subprocess.Popen([
            sys.executable, "-c",
            "import sys; from core.torch_compile_runtime import record_compile_target; record_compile_target(sys.argv[1])",
            device,
        ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for device in devices]
        for process in processes:
            _stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr.decode(errors="replace"))
        self.assertEqual(compile_cache_status()["compiled_devices"], devices)


if __name__ == "__main__":
    unittest.main()
