from __future__ import annotations

import unittest
from unittest.mock import patch

from utils import gpu_utils


class _Inventory:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self, *, refresh=False):
        del refresh
        return self._snapshot


class GpuUtilsTests(unittest.TestCase):
    def test_get_cuda_devices_uses_canonical_inventory(self):
        inventory = _Inventory(
            {
                "cuda": {
                    "available": True,
                    "devices": [
                        {"ordinal": 0, "name": "NVIDIA GeForce RTX 4090"},
                        {"ordinal": 1, "name": "NVIDIA GeForce RTX 4080"},
                    ],
                }
            }
        )
        with patch("utils.gpu_utils._inventory", return_value=inventory):
            self.assertEqual(gpu_utils.get_cuda_devices(), ["cuda:0", "cuda:1"])
            self.assertEqual(
                gpu_utils.get_gpu_name_by_id("cuda:1"),
                "NVIDIA GeForce RTX 4080",
            )

    def test_get_cuda_devices_without_cuda_driver(self):
        with patch(
            "utils.gpu_utils._inventory",
            return_value=_Inventory({"cuda": {"available": False, "devices": []}}),
        ):
            self.assertEqual(gpu_utils.get_cuda_devices(), [])

    def test_primary_gpu_info_is_adapter_snapshot_adapter(self):
        snapshot = {
            "vendor": "NVIDIA",
            "source": "dxgi+ctypes",
            "primary": {"name": "NVIDIA GeForce RTX 4060 Laptop GPU"},
            "adapters": [
                {"name": "Intel(R) Iris(R) Xe Graphics"},
                {"name": "NVIDIA GeForce RTX 4060 Laptop GPU"},
            ],
        }
        with patch(
            "utils.gpu_utils._inventory",
            return_value=_Inventory(snapshot),
        ):
            info = gpu_utils.get_primary_gpu_info()
            label = gpu_utils.format_primary_gpu_label()

        self.assertEqual(info["vendor"], "NVIDIA")
        self.assertEqual(info["name"], "NVIDIA GeForce RTX 4060 Laptop GPU")
        self.assertEqual(label, "NVIDIA GeForce RTX 4060 Laptop GPU")


if __name__ == "__main__":
    unittest.main()
