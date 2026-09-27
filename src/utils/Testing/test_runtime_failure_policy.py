from __future__ import annotations

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from handlers.ai_engine import runtime_failure_policy as policy
from handlers.ai_engine import worker_process as wp


class _CollectingQueue:
    def __init__(self):
        self.items: list = []

    def put(self, message, *args):
        del args
        self.items.append(message)

    def put_nowait(self, message):
        self.items.append(message)


class RuntimeFailurePolicyTests(unittest.TestCase):
    def test_device_side_assert_is_fatal_but_oom_is_not(self):
        self.assertTrue(
            policy.is_cuda_context_poisoned(
                RuntimeError("CUDA error: device-side assert triggered")
            )
        )
        self.assertTrue(
            policy.is_cuda_context_poisoned(
                RuntimeError("CUDA error: an illegal memory access was encountered")
            )
        )
        self.assertFalse(
            policy.is_cuda_context_poisoned(
                RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
            )
        )

    def test_probe_detects_sticky_cuda_failure_without_importing_torch(self):
        class _Cuda:
            @staticmethod
            def is_available():
                return True

            @staticmethod
            def synchronize():
                raise RuntimeError("CUDA error: device-side assert triggered")

        fake_torch = SimpleNamespace(cuda=_Cuda())
        with patch.dict(sys.modules, {"torch": fake_torch}):
            error = policy.probe_cuda_context()

        self.assertIsInstance(error, RuntimeError)
        self.assertTrue(policy.is_cuda_context_poisoned(error))

    def test_dispatch_recycles_worker_on_direct_fatal_cuda_error(self):
        async def scenario():
            responses = _CollectingQueue()
            logs = _CollectingQueue()
            exits: list[int] = []

            class _Boom:
                async def handle(self, method, payload):
                    del method, payload
                    raise RuntimeError("CUDA error: device-side assert triggered")

            with patch.object(
                wp.runtime_failure_policy,
                "terminate_poisoned_worker",
                side_effect=lambda: exits.append(policy.CUDA_CONTEXT_POISONED_EXIT_CODE),
            ):
                await wp._dispatch(_Boom(), "tts", "synthesize", {}, "r1", responses, logs)
            return responses.items, logs.items, exits

        responses, logs, exits = asyncio.run(scenario())
        self.assertEqual(responses, [])
        self.assertEqual(exits, [policy.CUDA_CONTEXT_POISONED_EXIT_CODE])
        self.assertTrue(any("fatal CUDA runtime failure" in item["message"] for item in logs))

    def test_dispatch_probes_failure_shaped_result_for_swallowed_cuda_error(self):
        async def scenario():
            responses = _CollectingQueue()
            logs = _CollectingQueue()
            exits: list[int] = []

            class _Swallowed:
                async def handle(self, method, payload):
                    del method, payload
                    return None

            poison = RuntimeError("CUDA error: device-side assert triggered")
            with patch.object(
                wp.runtime_failure_policy,
                "probe_cuda_context",
                return_value=poison,
            ), patch.object(
                wp.runtime_failure_policy,
                "terminate_poisoned_worker",
                side_effect=lambda: exits.append(policy.CUDA_CONTEXT_POISONED_EXIT_CODE),
            ):
                await wp._dispatch(_Swallowed(), "tts", "synthesize", {}, "r2", responses, logs)
            return responses.items, exits

        responses, exits = asyncio.run(scenario())
        self.assertEqual(responses, [])
        self.assertEqual(exits, [policy.CUDA_CONTEXT_POISONED_EXIT_CODE])


if __name__ == "__main__":
    unittest.main()
