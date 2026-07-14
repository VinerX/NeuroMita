"""Регрессии на критический путь одного пользовательского сообщения.

Проверяем то, чего раньше не было:
- SEND_MESSAGE не блокирует поток вызывающего (раньше — fut.result(timeout=600));
- генерация не занимает поток шины и не требует asyncio-loop;
- у очереди генераций есть backpressure, а не бесконечный рост.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.chat_controller import ChatController
from core.events import Events, get_event_bus
from core.executors import Pools, executors
from core.services import services
from services.contracts import (
    CharacterRegistry,
    ChatGenerationRequest,
    ChatGenerationResult,
    GenerationService,
)


class _StubSettings:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


class _StubRegistry(CharacterRegistry):
    def get(self, character_id):
        return None

    def all_ids(self):
        return ["Crazy"]

    def current(self):
        return None

    def current_id(self):
        return "Crazy"

    def current_profile(self):
        return {"character_id": "Crazy", "name": "Crazy"}

    def current_name(self):
        return "Crazy"

    def name_of(self, character_id):
        return str(character_id or "")


class _BlockingGeneration(GenerationService):
    """Генерация, которую тест держит открытой, чтобы поймать блокировку вызывающего."""

    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Semaphore(0)
        self.threads: list[str] = []

    def generate_chat(self, request: ChatGenerationRequest):
        self.threads.append(threading.current_thread().name)
        self.entered.release()
        self.release.wait(10)
        return ChatGenerationResult(text="ok", character_id="Crazy")

    def generate_utility(self, request):
        raise AssertionError("не используется")


class ChatRequestPipelineTests(unittest.TestCase):
    def setUp(self):
        services().register(CharacterRegistry, _StubRegistry(), replace=True)
        self.generation = _BlockingGeneration()
        services().register(GenerationService, self.generation, replace=True)
        self.bus = get_event_bus()
        self.controller = ChatController(_StubSettings())

    def tearDown(self):
        # ChatController подписывается с weak=False: без явной отписки прошлый
        # инстанс продолжит обрабатывать SEND_MESSAGE и сломает следующий тест.
        self.bus.unsubscribe(Events.Chat.SEND_MESSAGE, self.controller._on_send_message)
        self.bus.unsubscribe(
            Events.Model.GET_LLM_PROCESSING_STATUS, self.controller._on_get_llm_processing_status
        )
        self.generation.release.set()

        pool = executors().pool(Pools.GENERATION)
        deadline = time.time() + 5
        while pool.inflight and time.time() < deadline:
            time.sleep(0.02)

    def _send(self):
        self.bus.emit(Events.Chat.SEND_MESSAGE, {"user_input": "hi"}, sync=True)

    def test_send_message_does_not_block_caller(self):
        """Раньше обработчик стоял на fut.result(600) и держал поток шины."""
        started = time.perf_counter()
        self._send()
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.5, "SEND_MESSAGE заблокировал вызывающий поток")
        self.assertTrue(
            self.generation.entered.acquire(timeout=3),
            "генерация не стартовала в фоне",
        )
        self.assertTrue(self.controller.llm_processing, "inflight-счётчик не поднялся")

    def test_generation_runs_on_generation_pool(self):
        self._send()
        self.assertTrue(self.generation.entered.acquire(timeout=3))
        self.assertTrue(
            self.generation.threads[0].startswith(Pools.GENERATION),
            f"генерация ушла не в свой пул: {self.generation.threads[0]}",
        )

    def test_inflight_counter_tracks_concurrent_requests(self):
        for _ in range(3):
            self._send()
        for _ in range(3):
            self.assertTrue(self.generation.entered.acquire(timeout=3))

        self.assertTrue(self.controller.llm_processing)
        self.generation.release.set()
        deadline = time.time() + 5
        while self.controller.llm_processing and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.controller.llm_processing, "inflight не обнулился")

    def test_queue_backpressure_rejects_overflow(self):
        failures: list[dict] = []
        self.bus.subscribe(
            Events.Model.ON_FAILED_RESPONSE,
            lambda ev: failures.append(ev.data or {}),
            weak=False,
        )

        capacity = executors().pool(Pools.GENERATION).spec.capacity
        for _ in range(capacity + 3):
            self._send()

        deadline = time.time() + 3
        while len(failures) < 3 and time.time() < deadline:
            time.sleep(0.05)

        self.assertGreaterEqual(
            len(failures), 3, "переполнение очереди генераций прошло молча"
        )
        self.assertIn("Слишком много запросов", failures[0].get("error", ""))


if __name__ == "__main__":
    unittest.main()
