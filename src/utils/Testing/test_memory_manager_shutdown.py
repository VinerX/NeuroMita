from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.memory_manager import MemoryManager


class _ExecutorStub:
    def __init__(self) -> None:
        self.submitted = []
        self.shutdown_calls = []

    def submit(self, job):
        self.submitted.append(job)

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.shutdown_calls.append((wait, cancel_futures))


class MemoryEmbeddingShutdownTests(unittest.TestCase):
    def setUp(self) -> None:
        with MemoryManager._EMBED_EXECUTOR_LOCK:
            self._original_executor = MemoryManager._EMBED_EXECUTOR
            self._original_shutdown = MemoryManager._EMBED_EXECUTOR_SHUTDOWN
            self.executor = _ExecutorStub()
            MemoryManager._EMBED_EXECUTOR = self.executor
            MemoryManager._EMBED_EXECUTOR_SHUTDOWN = False

    def tearDown(self) -> None:
        with MemoryManager._EMBED_EXECUTOR_LOCK:
            MemoryManager._EMBED_EXECUTOR = self._original_executor
            MemoryManager._EMBED_EXECUTOR_SHUTDOWN = self._original_shutdown

    def test_shutdown_rejects_late_jobs_without_recreating_executor(self) -> None:
        MemoryManager.shutdown_executor()

        accepted = MemoryManager._submit_embed_job(lambda: None)

        self.assertFalse(accepted)
        self.assertEqual(self.executor.shutdown_calls, [(False, True)])
        self.assertEqual(self.executor.submitted, [])
        self.assertIsNone(MemoryManager._EMBED_EXECUTOR)

    def test_late_schedule_does_not_initialize_rag(self) -> None:
        MemoryManager.shutdown_executor()
        manager = object.__new__(MemoryManager)

        with mock.patch.object(
            MemoryManager,
            "rag",
            new_callable=mock.PropertyMock,
            side_effect=AssertionError("RAG must not be touched during shutdown"),
        ):
            manager._schedule_embed(1, "late memory")


if __name__ == "__main__":
    unittest.main()
