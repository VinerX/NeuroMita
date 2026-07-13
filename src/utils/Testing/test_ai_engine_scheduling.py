"""Регрессии на границу AI-worker'а.

Раньше `_worker_loop` делал `await service.handle(...)` прямо в цикле чтения
очереди: синтез TTS предыдущего ответа блокировал эмбеддинг запроса следующего.
Теперь команды диспетчеризуются конкурентно, а доступ к устройству сериализует
приоритетный планировщик.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.ai_engine import worker_process as wp
from handlers.ai_engine.gpu_scheduler import Priority, PriorityScheduler


class _CollectingQueue:
    def __init__(self):
        self.items: list = []

    def put(self, message):
        self.items.append(message)


class PrioritySchedulerTests(unittest.TestCase):
    def test_higher_priority_overtakes_queued_work(self):
        async def scenario():
            scheduler = PriorityScheduler(slots=1)
            order: list[str] = []

            async def job(name: str, priority: int, hold: float = 0.01):
                async with scheduler.slot(priority):
                    order.append(name)
                    await asyncio.sleep(hold)

            holder = asyncio.create_task(job("tts", Priority.TTS, hold=0.08))
            await asyncio.sleep(0.01)
            queued = [
                asyncio.create_task(job("bulk", Priority.BULK)),
                asyncio.create_task(job("hot", Priority.HOT)),
                asyncio.create_task(job("rerank", Priority.RERANK)),
            ]
            await asyncio.gather(holder, *queued)
            return order, scheduler

        order, scheduler = asyncio.run(scenario())
        self.assertEqual(order, ["tts", "hot", "rerank", "bulk"])
        self.assertEqual(scheduler.free_slots, 1)
        self.assertEqual(scheduler.queue_depth, 0)

    def test_slot_released_on_exception(self):
        async def scenario():
            scheduler = PriorityScheduler(slots=1)

            async def boom():
                async with scheduler.slot(Priority.HOT):
                    raise ValueError("gpu blew up")

            with self.assertRaises(ValueError):
                await boom()
            return scheduler

        scheduler = asyncio.run(scenario())
        self.assertEqual(scheduler.free_slots, 1)

    def test_cancelled_waiter_does_not_leak_slot(self):
        async def scenario():
            scheduler = PriorityScheduler(slots=1)
            await scheduler.acquire(Priority.HOT)

            waiter = asyncio.create_task(scheduler.acquire(Priority.BULK))
            await asyncio.sleep(0.01)
            waiter.cancel()
            try:
                await waiter
            except asyncio.CancelledError:
                pass

            scheduler.release()
            return scheduler

        scheduler = asyncio.run(scenario())
        self.assertEqual(scheduler.free_slots, 1)

    def test_run_serializes_blocking_sections(self):
        async def scenario():
            scheduler = PriorityScheduler(slots=1)
            lock = threading.Lock()
            state = {"now": 0, "peak": 0}

            def blocking():
                with lock:
                    state["now"] += 1
                    state["peak"] = max(state["peak"], state["now"])
                time.sleep(0.03)
                with lock:
                    state["now"] -= 1

            await asyncio.gather(*[scheduler.run(Priority.HOT, blocking) for _ in range(4)])
            return state["peak"]

        self.assertEqual(asyncio.run(scenario()), 1, "GPU-секции выполнялись параллельно")


class _SlotService:
    def __init__(self, scheduler, name: str, hold: float, log: list[str]):
        self._scheduler = scheduler
        self._name = name
        self._hold = hold
        self._log = log

    async def handle(self, method: str, payload: dict):
        priority = Priority.parse(payload.get("priority"), default=Priority.HOT)
        async with self._scheduler.slot(priority):
            tag = payload.get("tag") or self._name
            self._log.append(f"{tag}:start")
            await asyncio.sleep(self._hold)
            self._log.append(f"{tag}:end")
        return tag


class WorkerDispatchTests(unittest.TestCase):
    def test_tts_does_not_block_intake_and_hot_overtakes_bulk(self):
        async def scenario():
            scheduler = PriorityScheduler(slots=1)
            log: list[str] = []
            responses = _CollectingQueue()
            logs = _CollectingQueue()

            services = {
                "tts": _SlotService(scheduler, "tts", 0.08, log),
                "rag": _SlotService(scheduler, "rag", 0.01, log),
            }
            inflight: set[asyncio.Task] = set()

            def dispatch(service_name: str, payload: dict, req_id: str):
                task = asyncio.create_task(
                    wp._dispatch(
                        services[service_name], service_name, "call", payload, req_id, responses, logs
                    )
                )
                inflight.add(task)
                task.add_done_callback(inflight.discard)

            dispatch("tts", {"tag": "tts", "priority": "tts"}, "r1")
            await asyncio.sleep(0.01)
            dispatch("rag", {"tag": "bulk", "priority": "bulk"}, "r2")
            await asyncio.sleep(0.005)
            dispatch("rag", {"tag": "hot", "priority": "hot"}, "r3")

            await asyncio.gather(*list(inflight))
            return log, responses.items

        log, responses = asyncio.run(scenario())

        # Команды приняты в работу, пока TTS ещё считает: очередь чтения не стоит.
        self.assertEqual(log[0], "tts:start")
        # hot приехал позже bulk, но обогнал его в очереди к устройству.
        self.assertLess(log.index("hot:start"), log.index("bulk:start"))
        # GPU-секции не пересекались.
        self.assertEqual(
            log,
            ["tts:start", "tts:end", "hot:start", "hot:end", "bulk:start", "bulk:end"],
        )
        self.assertEqual(len(responses), 3)
        self.assertTrue(all(item["ok"] for item in responses))

    def test_failure_is_reported_per_request(self):
        async def scenario():
            responses = _CollectingQueue()
            logs = _CollectingQueue()

            class _Boom:
                async def handle(self, method, payload):
                    raise RuntimeError("model exploded")

            await wp._dispatch(_Boom(), "rag", "get_embeddings", {}, "r9", responses, logs)
            return responses.items

        responses = asyncio.run(scenario())
        self.assertEqual(len(responses), 1)
        self.assertFalse(responses[0]["ok"])
        self.assertIn("model exploded", responses[0]["error"])


class WorkerBootstrapTests(unittest.TestCase):
    def test_onnx_runtime_enables_kmp_inside_windows_worker(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        with TemporaryDirectory() as temp_dir:
            roots = []
            for name, capabilities in (("onnx", ["onnx.cpu", "onnx.dml"]),):
                root = Path(temp_dir) / name
                site_packages = root / "site-packages"
                site_packages.mkdir(parents=True)
                (root / "manifest.json").write_text(
                    json.dumps({"capabilities": capabilities}),
                    encoding="utf-8",
                )
                roots.append(str(site_packages))

            with patch.object(wp.os, "name", "nt"), patch.dict(
                os.environ,
                {"KMP_DUPLICATE_LIB_OK": "FALSE"},
                clear=False,
            ):
                enabled = wp._configure_openmp_compatibility(roots)
                self.assertTrue(enabled)
                self.assertEqual(os.environ["KMP_DUPLICATE_LIB_OK"], "TRUE")

    def test_single_backend_runtime_does_not_enable_kmp(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "torch"
            site_packages = root / "site-packages"
            site_packages.mkdir(parents=True)
            (root / "manifest.json").write_text(
                json.dumps({"capabilities": ["torch.cpu"]}),
                encoding="utf-8",
            )

            with patch.object(wp.os, "name", "nt"), patch.dict(
                os.environ,
                {},
                clear=True,
            ):
                enabled = wp._configure_openmp_compatibility([str(site_packages)])
                self.assertFalse(enabled)
                self.assertNotIn("KMP_DUPLICATE_LIB_OK", os.environ)


if __name__ == "__main__":
    unittest.main()
