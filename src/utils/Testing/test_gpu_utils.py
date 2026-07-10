from __future__ import annotations

import unittest
from unittest.mock import patch

from utils import gpu_utils


class GpuUtilsTests(unittest.TestCase):
    def setUp(self):
        gpu_utils._CUDA_INFO_CACHE = []
        gpu_utils._CUDA_INFO_TS = 0.0
        gpu_utils._GPU_INFO_CACHE = None
        gpu_utils._GPU_INFO_TS = 0.0

    def test_get_cuda_devices_uses_nvidia_smi_without_torch(self):
        with patch("utils.gpu_utils.check_gpu_provider", return_value="NVIDIA"), \
             patch(
                 "utils.gpu_utils.subprocess.check_output",
                 return_value="0, NVIDIA GeForce RTX 4090\n1, NVIDIA GeForce RTX 4080\n",
             ) as check_output_mock:
            devices = gpu_utils.get_cuda_devices()

        self.assertEqual(devices, ["cuda:0", "cuda:1"])
        check_output_mock.assert_called_once()

    def test_get_gpu_name_by_id_reads_cached_nvidia_smi_info(self):
        with patch("utils.gpu_utils.check_gpu_provider", return_value="NVIDIA"), \
             patch(
                 "utils.gpu_utils.subprocess.check_output",
                 return_value="0, NVIDIA GeForce RTX 4090\n1, NVIDIA GeForce RTX 4080\n",
             ):
            self.assertEqual(gpu_utils.get_gpu_name_by_id("cuda:1"), "NVIDIA GeForce RTX 4080")

    def test_get_cuda_devices_skips_probe_without_nvidia(self):
        with patch("utils.gpu_utils.check_gpu_provider", return_value="CPU"), \
             patch("utils.gpu_utils.subprocess.check_output") as check_output_mock:
            devices = gpu_utils.get_cuda_devices()

        self.assertEqual(devices, [])
        check_output_mock.assert_not_called()

    def test_get_primary_gpu_info_prefers_discrete_nvidia_name(self):
        with patch("utils.gpu_utils.platform.system", return_value="Windows"), patch(
            "utils.gpu_utils.subprocess.check_output",
            return_value="Name\nIntel(R) Iris(R) Xe Graphics\nNVIDIA GeForce RTX 4060 Laptop GPU\n",
        ):
            info = gpu_utils.get_primary_gpu_info()

        self.assertEqual(info["vendor"], "NVIDIA")
        self.assertEqual(info["name"], "NVIDIA GeForce RTX 4060 Laptop GPU")
        self.assertEqual(
            gpu_utils.format_primary_gpu_label(),
            "NVIDIA GeForce RTX 4060 Laptop GPU",
        )


if __name__ == "__main__":
    unittest.main()
