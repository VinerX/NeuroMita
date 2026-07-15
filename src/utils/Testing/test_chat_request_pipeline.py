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
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.chat_controller import ChatController
from core.events import Events, get_event_bus
from core.executors import Pools, executors
from core.services import services
from services.llm_stream import LLMStreamEvent, LLMStreamEventType
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


class _StreamingGeneration(GenerationService):
    def __init__(self):
        self.request = None

    def generate_chat(self, request: ChatGenerationRequest):
        self.request = request
        request.stream_event_callback(LLMStreamEvent(
            type=LLMStreamEventType.TEXT_DELTA,
            request_id="request",
            provider="common",
            model="model",
            sequence=1,
            text="hello",
        ))
        return ChatGenerationResult(text="hello", character_id="Crazy")

    def generate_utility(self, request):
        raise AssertionError("не используется")


class _ImmediateGeneration(GenerationService):
    def generate_chat(self, request: ChatGenerationRequest):
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

    def test_chat_consumes_typed_stream_events_without_legacy_tag_bridge(self):
        generation = _StreamingGeneration()
        services().register(GenerationService, generation, replace=True)
        self.controller.settings = _StubSettings({"ENABLE_STREAMING": True})

        result = self.controller._run_request("hi", character_id="Crazy")

        self.assertEqual(result, "hello")
        self.assertIsNotNone(generation.request)
        self.assertIsNone(generation.request.stream_callback)
        self.assertTrue(callable(generation.request.stream_event_callback))

    def test_request_keeps_its_own_unity_context_snapshot(self):
        generation = _StreamingGeneration()
        services().register(GenerationService, generation, replace=True)
        self.controller.settings = _StubSettings({"ENABLE_STREAMING": False})

        snapshot = {
            "world_state": "Player is standing.",
            "runtime_events": ["Player stood up."],
        }
        self.controller._run_request(
            "hi",
            character_id="Crazy",
            game_state=snapshot,
        )

        self.assertEqual(generation.request.game_state, snapshot)
        self.assertIsNot(generation.request.game_state, snapshot)

    def test_task_result_keeps_response_protocol_version(self):
        result = ChatController._build_task_result(
            "hello",
            "Player",
            {"response_protocol_version": 2, "segments": [{"text": "hello"}]},
        )
        self.assertEqual(result["response_protocol_version"], 2)

        plain_result = ChatController._build_task_result("hello", "Player", None)
        self.assertEqual(plain_result["response_protocol_version"], 2)

    def test_non_stream_request_does_not_create_presentation_coalescer(self):
        services().register(GenerationService, _ImmediateGeneration(), replace=True)
        self.controller.settings = _StubSettings({"ENABLE_STREAMING": False})

        with patch(
            "controllers.chat_controller.TextDeltaCoalescer",
            side_effect=AssertionError("coalescer must stay lazy"),
        ):
            result = self.controller._run_request("hi", character_id="Crazy")

        self.assertEqual(result, "ok")


if __name__ == "__main__":
    unittest.main()
