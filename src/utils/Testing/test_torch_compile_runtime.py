from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.torch_compile_runtime import (
    clear_compile_cache,
    compile_cache_metadata_path,
    compile_cache_status,
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

    def _create_cache_file(self) -> None:
        cache_file = self.root / "cache" / "torchinductor" / "compiled.bin"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(b"compiled")

    def test_compile_cache_tracks_each_cuda_device(self) -> None:
        self._create_cache_file()
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
        self.assertEqual(migrated["schema_version"], 2)
        self.assertIn("cuda:0", migrated["targets"])

    def test_cache_without_metadata_is_reported_as_legacy(self) -> None:
        self._create_cache_file()

        status = compile_cache_status()

        self.assertIs(status["cache_exists"], True)
        self.assertEqual(status["compile_metadata_state"], "legacy")
        self.assertEqual(status["compiled_targets"], [])

    def test_clear_compile_cache_removes_target_metadata(self) -> None:
        self._create_cache_file()
        record_compile_target("cuda:1", gpu_name="GPU One")

        clear_compile_cache()

        self.assertIs(compile_cache_metadata_path().exists(), False)
        self.assertIs(compile_cache_status()["cache_exists"], False)


if __name__ == "__main__":
    unittest.main()
