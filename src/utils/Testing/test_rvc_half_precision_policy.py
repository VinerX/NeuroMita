from __future__ import annotations

import unittest
from unittest.mock import patch

from core.cuda_precision_policy import CudaHalfPrecisionDecision, evaluate_rvc_half_precision
from handlers.voice_models.edge_tts_rvc_model import EdgeTTSRVCCudaModel


class RvcHalfPrecisionPolicyTests(unittest.TestCase):
    def test_turing_gtx_16xx_is_blocked(self):
        decision = evaluate_rvc_half_precision(
            vendor="NVIDIA",
            compute_capability="sm_75",
            gpu_name="NVIDIA GeForce GTX 1660 Ti",
        )
        self.assertFalse(decision.allowed)

    def test_turing_rtx_and_t4_are_allowed(self):
        for name in (
            "NVIDIA GeForce RTX 2060",
            "NVIDIA Quadro RTX 5000",
            "Tesla T4",
            "NVIDIA T4",
        ):
            with self.subTest(name=name):
                decision = evaluate_rvc_half_precision(
                    vendor="NVIDIA",
                    compute_capability=(7, 5),
                    gpu_name=name,
                )
                self.assertTrue(decision.allowed)

    def test_turing_non_rtx_workstation_part_is_blocked(self):
        decision = evaluate_rvc_half_precision(
            vendor="NVIDIA",
            compute_capability=75,
            gpu_name="NVIDIA T1000",
        )
        self.assertFalse(decision.allowed)

    def test_ampere_and_newer_are_allowed_pascal_is_blocked(self):
        self.assertTrue(
            evaluate_rvc_half_precision(
                vendor="NVIDIA",
                compute_capability=86,
                gpu_name="NVIDIA GeForce RTX 3060",
            ).allowed
        )
        self.assertFalse(
            evaluate_rvc_half_precision(
                vendor="NVIDIA",
                compute_capability=61,
                gpu_name="NVIDIA GeForce GTX 1080",
            ).allowed
        )

    def test_unknown_compute_capability_fails_closed(self):
        decision = evaluate_rvc_half_precision(
            vendor="NVIDIA",
            compute_capability=None,
            gpu_name="NVIDIA GPU",
        )
        self.assertFalse(decision.allowed)

    def test_rvc_runtime_forces_saved_true_to_false_when_policy_blocks(self):
        handler = EdgeTTSRVCCudaModel.__new__(EdgeTTSRVCCudaModel)
        blocked = CudaHalfPrecisionDecision(
            allowed=False,
            reason="sm75_without_tensor_core_evidence",
            compute_capability=75,
            gpu_name="NVIDIA GeForce GTX 1660 Ti",
        )
        with patch(
            "handlers.voice_models.edge_tts_rvc_model.get_rvc_half_precision_decision",
            return_value=blocked,
        ):
            params = handler._rvc_params(
                pitch=0,
                index_rate=0.75,
                protect=0.33,
                filter_radius=3,
                rms_mix_rate=0.5,
                is_half=True,
                device="cuda:0",
                f0method="rmvpe",
            )
        self.assertFalse(params["is_half"])

    def test_rvc_runtime_keeps_true_when_policy_allows(self):
        handler = EdgeTTSRVCCudaModel.__new__(EdgeTTSRVCCudaModel)
        allowed = CudaHalfPrecisionDecision(
            allowed=True,
            reason="sm75_tensor_core_sku",
            compute_capability=75,
            gpu_name="NVIDIA GeForce RTX 2080",
        )
        with patch(
            "handlers.voice_models.edge_tts_rvc_model.get_rvc_half_precision_decision",
            return_value=allowed,
        ):
            params = handler._rvc_params(
                pitch=0,
                index_rate=0.75,
                protect=0.33,
                filter_radius=3,
                rms_mix_rate=0.5,
                is_half=True,
                device="cuda:0",
                f0method="rmvpe",
            )
        self.assertTrue(params["is_half"])


if __name__ == "__main__":
    unittest.main()
