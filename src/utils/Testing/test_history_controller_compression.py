from __future__ import annotations

import sys
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.history_controller import HistoryController
from controllers import history_controller as history_controller_module
from core.services import services
from services.contracts import GenerationService, UtilityGenerationRequest, UtilityGenerationResult


class _StubGenerationService(GenerationService):
    """Подставной GenerationService: считает вызовы и отдаёт заготовленные ответы."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[UtilityGenerationRequest] = []

    def generate_chat(self, request):  # не используется в этих тестах
        raise AssertionError("generate_chat не должен вызываться при сжатии истории")

    def generate_utility(self, request: UtilityGenerationRequest) -> UtilityGenerationResult:
        self.calls.append(request)
        if self._responses:
            return self._responses.pop(0)
        return UtilityGenerationResult(ok=False, error="no more stub responses")


def _install_generation(responses) -> _StubGenerationService:
    stub = _StubGenerationService(responses)
    services().register(GenerationService, stub, replace=True)
    return stub


class _StubHistoryManager:
    def __init__(self, messages):
        self._messages = list(messages)
        self.saved_missed = []

    def load_history(self):
        return {"messages": list(self._messages)}

    def save_missed_history(self, messages):
        self.saved_missed.extend(messages)


class _StubCharacter:
    def __init__(self, messages, *, char_id="TestChar", memory_system=None):
        self.char_id = char_id
        self.name = char_id
        self.history_manager = _StubHistoryManager(messages)
        self.memory_system = memory_system
        self.vars = {}

    def get_variable(self, key, default=None):
        return self.vars.get(key, default)

    def set_variable(self, key, value):
        self.vars[key] = value

    def flush_variables(self):
        return None


class HistoryControllerCompressionTests(unittest.TestCase):
    def _make_controller(self, settings: dict | None = None) -> HistoryController:
        controller = HistoryController.__new__(HistoryController)
        controller.event_bus = SimpleNamespace()
        controller._messages_since_last_periodic_compression = {}
        controller._compression_guard = threading.Lock()
        controller._compression_inflight = set()
        controller._background_compression_inflight = set()
        controller._background_compression_timers = {}
        controller._compression_cooldowns = {}
        controller._messages_since_last_maintenance = {}
        controller._maintenance_inflight = set()
        cfg = dict(settings or {})
        controller._get_setting = lambda key, default=None: cfg.get(key, default)
        controller._sanitize_history_for_llm = lambda _character, messages: messages
        controller._apply_history_image_quality_reduction = lambda messages, _cfg: messages
        return controller

    def test_prepare_for_prompt_never_runs_compression(self):
        """prepare_for_prompt — чистая функция чтения.

        Регрессия на баг: раньше отсюда мог уйти синхронный LLM-вызов на 60с,
        вызывающий ждал 5с по таймауту шины и получал промпт БЕЗ истории.
        """
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        character = _StubCharacter([{"role": "user", "content": f"msg-{i}"} for i in range(50)])
        controller._process_history_compression = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("prepare_for_prompt не имеет права запускать сжатие")
        )
        _install_generation([])  # любой LLM-вызов -> AssertionError в стабе

        result = controller.prepare_for_prompt(
            character=character,
            memory_limit=3,
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )
        self.assertEqual(len(result.messages), 3)

    def test_prepare_for_prompt_window_is_bounded_even_without_summary(self):
        """Окно контекста ограничено всегда, даже пока фоновое сжатие не догнало."""
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        character = _StubCharacter([{"role": "user", "content": f"msg-{i}"} for i in range(20)])

        result = controller.prepare_for_prompt(
            character=character,
            memory_limit=3,
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )
        self.assertEqual(len(result.messages), 3)
        self.assertEqual(
            [m["content"] for m in result.messages], ["msg-17", "msg-18", "msg-19"]
        )

    def test_prepare_for_prompt_returns_existing_summary(self):
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        character = _StubCharacter([
            {"role": "user", "content": f"msg-{i}", "_history_row_id": 100 + i} for i in range(6)
        ])
        character.vars[HistoryController._SUMMARY_TEXT_VAR] = "summary"
        character.vars[HistoryController._SUMMARY_ANCHOR_VAR] = 102

        result = controller.prepare_for_prompt(
            character=character,
            memory_limit=10,
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )
        self.assertEqual(result.summary, "summary")
        self.assertEqual(len(result.messages), 3)  # свёрнуто всё по строку 102 включительно

    def test_summary_boundary_survives_shrinking_history(self):
        """Регрессия: свёрнутые сообщения выпадают из активной истории.

        Раньше граница хранилась количеством, и после архивации/очистки старых
        строк она отрезала всю оставшуюся историю — модель получала промпт
        вообще без диалога, только со сводкой.
        """
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        # свёрнуто по строку 102, но строки 100-102 уже не активны
        character = _StubCharacter([
            {"role": "user", "content": f"msg-{i}", "_history_row_id": i} for i in (103, 104, 105)
        ])
        character.vars[HistoryController._SUMMARY_TEXT_VAR] = "summary"
        character.vars[HistoryController._SUMMARY_ANCHOR_VAR] = 102

        result = controller.prepare_for_prompt(
            character=character,
            memory_limit=10,
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )
        self.assertEqual([m["content"] for m in result.messages], ["msg-103", "msg-104", "msg-105"])

    def test_stale_summary_count_no_longer_eats_history(self):
        """Легаси-счётчик без границы не должен резать историю вообще."""
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        character = _StubCharacter([
            {"role": "user", "content": f"msg-{i}", "_history_row_id": 300 + i} for i in range(5)
        ])
        character.vars[HistoryController._SUMMARY_TEXT_VAR] = "summary"
        character.vars[HistoryController._SUMMARY_COUNT_VAR] = 215

        result = controller.prepare_for_prompt(
            character=character,
            memory_limit=10,
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )
        self.assertEqual(len(result.messages), 5)

    def _prepare(self, controller, character, *, memory_limit=4):
        return controller.prepare_for_prompt(
            character=character,
            memory_limit=memory_limit,
            is_game_master=False,
            save_missed_history=True,
            image_quality={},
        )

    def test_archiving_takes_summarized_messages(self):
        """В архив уходит свёрнутое — оно уже пересказано в сводке.

        Архив (is_active=0) — единственный вход в RAG-поиск, поэтому свёрнутое
        не должно висеть активным вечно.
        """
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        messages = [
            {"role": "user", "content": f"m{i}", "_history_row_id": 700 + i} for i in range(8)
        ]
        character = _StubCharacter(messages)
        character.vars[HistoryController._SUMMARY_ANCHOR_VAR] = 702

        self._prepare(controller, character)

        archived = [m["content"] for m in character.history_manager.saved_missed]
        self.assertEqual(archived, ["m0", "m1", "m2"])

    def test_unsummarized_tail_is_never_archived(self):
        """Регрессия: раньше архивировался хвост за окном — ровно то, что сжатие
        ещё не успело свернуть. При лежащем компрессоре история уезжала в архив,
        ни разу не попав в сводку: тихая потеря памяти.
        """
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        messages = [
            {"role": "user", "content": f"m{i}", "_history_row_id": 800 + i} for i in range(10)
        ]
        character = _StubCharacter(messages)

        result = self._prepare(controller, character)

        self.assertEqual(character.history_manager.saved_missed, [])
        # окно промпта при этом всё равно ограничено
        self.assertEqual([m["content"] for m in result.messages], ["m6", "m7", "m8", "m9"])

    def test_disabled_compression_still_archives_by_window(self):
        """Сжатие выключено — сворачивать некому, держать историю активной незачем."""
        controller = self._make_controller({
            "HISTORY_COMPRESSION_OUTPUT_TARGET": "history",
            "ENABLE_HISTORY_COMPRESSION_ON_LIMIT": False,
            "ENABLE_HISTORY_COMPRESSION_PERIODIC": False,
        })
        messages = [
            {"role": "user", "content": f"m{i}", "_history_row_id": 900 + i} for i in range(6)
        ]
        character = _StubCharacter(messages)

        self._prepare(controller, character)

        archived = [m["content"] for m in character.history_manager.saved_missed]
        self.assertEqual(archived, ["m0", "m1"])

    def test_compression_advances_boundary_to_last_compressed_row(self):
        controller = self._make_controller({
            "HISTORY_COMPRESSION_OUTPUT_TARGET": "history",
            "HISTORY_COMPRESSION_KEEP_LAST": 2,
            "ENABLE_HISTORY_COMPRESSION_ON_LIMIT": True,
        })
        controller._compress_history_singleflight = lambda *_a, **_k: "chunk-summary"
        messages = [
            {"role": "user", "content": f"m{i}", "_history_row_id": 500 + i} for i in range(6)
        ]
        character = _StubCharacter(messages)

        controller._process_history_compression(
            character, messages, effective_limit=4, history_summary="", summary_cut=0,
        )

        # сжаты первые четыре (500..503), последние две остаются в окне
        self.assertEqual(character.vars[HistoryController._SUMMARY_ANCHOR_VAR], 503)
        self.assertEqual(controller._summary_cut_index(character, messages), 4)

    def test_prepare_for_prompt_counts_only_dialog_messages_for_tail_limit(self):
        controller = self._make_controller({"HISTORY_COMPRESSION_OUTPUT_TARGET": "history"})
        character = _StubCharacter(
            [
                {"role": "user", "content": "already summarized", "_history_row_id": 1},
                {"role": "system", "content": "older system", "_history_row_id": 2},
                {"role": "user", "content": "u1", "_history_row_id": 3},
                {"role": "event", "content": "e1", "_history_row_id": 4},
                {"role": "assistant", "content": "a1", "_history_row_id": 5},
                {"role": "system", "content": "keep system", "_history_row_id": 6},
                {"role": "user", "content": "u2", "_history_row_id": 7},
                {"role": "event", "content": "keep event", "_history_row_id": 8},
                {"role": "assistant", "content": "a2", "_history_row_id": 9},
            ]
        )
        character.vars[HistoryController._SUMMARY_TEXT_VAR] = "summary"
        character.vars[HistoryController._SUMMARY_ANCHOR_VAR] = 1

        result = controller.prepare_for_prompt(
            character=character,
            memory_limit=2,
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )

        self.assertEqual(
            [(m["role"], m["content"]) for m in result.messages],
            [
                ("system", "keep system"),
                ("user", "u2"),
                ("event", "keep event"),
                ("assistant", "a2"),
            ],
        )

    def test_build_compression_plan_triggers_at_threshold_and_keeps_keep_last(self):
        controller = self._make_controller()
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(40)]
        plan = controller._build_compression_plan(
            source_messages=msgs,
            keep_last=10,
            trigger_at=40,
            enable_on_limit=True,
            enable_periodic=False,
            periodic_interval=0,
            char_id="c",
        )
        self.assertIsNotNone(plan)
        to_compress, reason = plan
        self.assertEqual(reason, "On-limit compression")
        # дошло до 40 → сжимаем 30, оставляем последние 10
        self.assertEqual(len(to_compress), 30)

    def test_build_compression_plan_does_not_trigger_below_threshold(self):
        controller = self._make_controller()
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(39)]
        plan = controller._build_compression_plan(
            source_messages=msgs,
            keep_last=10,
            trigger_at=40,
            enable_on_limit=True,
            enable_periodic=False,
            periodic_interval=0,
            char_id="c",
        )
        self.assertIsNone(plan)

    def test_apply_compression_result_does_not_advance_memory_mode_without_memory_system(self):
        controller = self._make_controller()
        character = _StubCharacter([], memory_system=None)

        summary, count = controller._apply_compression_result(
            character,
            output_target="memory",
            compressed_summary="compressed",
            previous_summary="",
            summary_count=4,
            compressed_count=3,
        )

        self.assertEqual(summary, "")
        self.assertEqual(count, 4)

    def test_message_completed_starts_background_compression(self):
        controller = self._make_controller()
        character = _StubCharacter([])
        called = []
        controller._start_background_compression = lambda ch: called.append(ch.char_id)

        controller._on_message_completed(
            SimpleNamespace(data={"character_id": "TestChar", "character_ref": character})
        )

        self.assertEqual(called, ["TestChar"])

    def test_background_compression_is_delayed_and_rescheduled(self):
        controller = self._make_controller({"HISTORY_COMPRESSION_BACKGROUND_DELAY_SEC": 6})
        character = _StubCharacter([])
        created = []
        original_timer = history_controller_module.threading.Timer

        class _FakeTimer:
            def __init__(self, delay, callback, args=None, kwargs=None):
                self.delay = delay
                self.callback = callback
                self.args = args or ()
                self.kwargs = kwargs or {}
                self.daemon = False
                self.name = ""
                self.cancelled = False
                created.append(self)

            def start(self):
                return None

            def cancel(self):
                self.cancelled = True

        history_controller_module.threading.Timer = _FakeTimer
        try:
            controller._start_background_compression(character)
            controller._start_background_compression(character)
        finally:
            history_controller_module.threading.Timer = original_timer

        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].delay, 6)
        self.assertEqual(created[1].delay, 6)
        self.assertTrue(created[0].cancelled)
        self.assertIs(controller._background_compression_timers["TestChar"], created[1])

    def test_background_compression_uses_model_message_limit_setting(self):
        controller = self._make_controller({"MODEL_MESSAGE_LIMIT": 3})
        character = _StubCharacter(
            [{"role": "user", "content": f"msg-{i}"} for i in range(4)]
        )
        captured_limits = []

        controller._process_history_compression = (
            lambda _character, _history, effective_limit, **_kwargs: captured_limits.append(effective_limit)
        )

        controller._run_post_response_compression(character)

        self.assertEqual(captured_limits, [3])

    def test_compress_history_retries_retryable_failure_with_retry_after(self):
        controller = self._make_controller(
            {
                "HISTORY_COMPRESSION_MAX_ATTEMPTS": 2,
                "HISTORY_COMPRESSION_RETRY_BASE_DELAY_SEC": 1.5,
                "HISTORY_COMPRESSION_RETRY_MAX_DELAY_SEC": 10,
            }
        )
        character = _StubCharacter([])
        sleeps = []
        stub = _install_generation([
            UtilityGenerationResult(
                ok=False,
                error="rate limited",
                details="retry later",
                status_code=429,
                retryable=True,
                retry_after_sec=3,
            ),
            UtilityGenerationResult(ok=True, text="summary"),
        ])
        original_sleep = history_controller_module.time.sleep
        original_status = history_controller_module.response_status_kind
        history_controller_module.time.sleep = lambda seconds: sleeps.append(seconds)
        history_controller_module.response_status_kind = lambda *_a, **_k: nullcontext()

        try:
            result = controller._compress_history(character, [{"role": "user", "content": "hello"}])
        finally:
            history_controller_module.time.sleep = original_sleep
            history_controller_module.response_status_kind = original_status

        self.assertEqual(result, "summary")
        self.assertEqual(sleeps, [3])  # уважили retry_after от провайдера
        self.assertEqual(len(stub.calls), 2)
        first = stub.calls[0]
        self.assertEqual(first.kind, "compress")
        self.assertEqual(first.max_attempts, 1)  # ретраями рулит HistoryController, не runner
        self.assertEqual(first.character_id, "TestChar")

    def test_compression_prompt_carries_text_not_base64_images(self):
        """Картинка в окне раздувала запрос сжатия со ~1k до ~180k токенов."""
        controller = self._make_controller()
        character = _StubCharacter([])
        blob = "A" * 20000
        stub = _install_generation([UtilityGenerationResult(ok=True, text="summary")])

        controller._compress_history(
            character,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "глянь на это"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{blob}"}},
                    ],
                },
                {"role": "assistant", "content": "вижу"},
            ],
        )

        prompt = stub.calls[0].prompt
        self.assertNotIn(blob, prompt)
        self.assertIn("глянь на это", prompt)
        self.assertIn("[image]", prompt)
        self.assertIn("вижу", prompt)

    def test_memory_candidates_prompt_carries_text_not_base64_images(self):
        controller = self._make_controller({"MEMORY_SUMMARY_CANDIDATES_ENABLED": True})
        character = _StubCharacter([], memory_system=SimpleNamespace(add_memory=lambda *_a, **_k: None))
        blob = "B" * 20000
        stub = _install_generation([UtilityGenerationResult(ok=True, text="[]")])

        controller._extract_memory_candidates(
            character,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "запомни это"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{blob}"}},
                    ],
                },
            ],
        )

        self.assertTrue(stub.calls, "кандидаты в память не ушли в LLM")
        prompt = stub.calls[0].prompt
        self.assertNotIn(blob, prompt)
        self.assertIn("запомни это", prompt)

    def test_compression_falls_back_to_local_summary_after_non_retryable_failure(self):
        controller = self._make_controller(
            {
                "HISTORY_COMPRESSION_OUTPUT_TARGET": "history",
                "HISTORY_COMPRESSION_LOCAL_FALLBACK_ENABLED": True,
                "HISTORY_COMPRESSION_PROMPT_TEMPLATE": "Prompts/System/compression_prompt.txt",
            }
        )
        character = _StubCharacter(
            [
                {"role": "user", "content": "hello there"},
                {"role": "assistant", "content": "general kenobi"},
                {"role": "user", "content": "compress me"},
                {"role": "assistant", "content": "done"},
            ]
        )
        stub = _install_generation([
            UtilityGenerationResult(
                ok=False,
                error="Provider returned error. Reason: User location is not supported for the API use.",
                details="HTTP 400 | provider=common",
                status_code=400,
                retryable=False,
            )
        ])
        original_status = history_controller_module.response_status_kind
        history_controller_module.response_status_kind = lambda *_a, **_k: nullcontext()
        try:
            result = controller._compress_history(
                character,
                character.history_manager.load_history()["messages"],
                previous_summary="Older summary",
            )
        finally:
            history_controller_module.response_status_kind = original_status

        self.assertEqual(len(stub.calls), 1)  # non-retryable -> без повторов
        self.assertIsInstance(result, str)
        self.assertIn("Older summary", result)
        self.assertIn("Player: hello there", result)
        self.assertIn("TestChar: general kenobi", result)


    def test_layered_appends_new_layer_below_rollup_threshold(self):
        import json

        controller = self._make_controller(
            {"HISTORY_COMPRESSION_LAYERED_MAX_SEGMENTS": 6, "HISTORY_COMPRESSION_LAYERED_ROLLUP_BATCH": 3}
        )
        # ниже порога роллапа compressor не должен вызываться вовсе
        controller._compress_history_singleflight = (
            lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("unexpected rollup"))
        )
        character = _StubCharacter([])

        rendered, count = controller._apply_layered_compression_result(
            character, compressed_summary="seg-A", summary_count=0, compressed_count=10,
        )
        self.assertEqual(rendered, "seg-A")
        self.assertEqual(count, 10)

        rendered, count = controller._apply_layered_compression_result(
            character, compressed_summary="seg-B", summary_count=10, compressed_count=8,
        )
        segments = json.loads(character.vars[HistoryController._SUMMARY_SEGMENTS_VAR])
        self.assertEqual([s["text"] for s in segments], ["seg-A", "seg-B"])
        self.assertEqual(rendered, "seg-A\n\nseg-B")
        self.assertEqual(count, 18)

    def test_layered_process_does_not_refeed_previous_summary_to_chunk(self):
        # В layered-режиме кусок суммаризуется с previous_summary="" (нет телефона).
        controller = self._make_controller(
            {
                "HISTORY_COMPRESSION_OUTPUT_TARGET": "layered",
                "HISTORY_COMPRESSION_KEEP_LAST": 2,
                "HISTORY_COMPRESSION_MIN_PERCENT_TO_COMPRESS": 1.0,
                "ENABLE_HISTORY_COMPRESSION_ON_LIMIT": True,
                "HISTORY_COMPRESSION_LAYERED_MAX_SEGMENTS": 6,
            }
        )
        fed_previous = []
        controller._compress_history_singleflight = (
            lambda _c, _m, *, previous_summary="": (
                fed_previous.append(previous_summary) or "chunk-summary"
            )
        )
        character = _StubCharacter(
            [{"role": "user", "content": f"m{i}"} for i in range(6)]
        )
        character.vars[HistoryController._SUMMARY_TEXT_VAR] = "EXISTING SUMMARY"

        controller._process_history_compression(
            character,
            character.history_manager.load_history()["messages"],
            effective_limit=4,
            history_summary="EXISTING SUMMARY",
            summary_cut=0,
        )
        self.assertEqual(fed_previous, [""])

    def test_layered_migrates_legacy_blob_into_first_layer(self):
        import json

        controller = self._make_controller()
        controller._compress_history_singleflight = (
            lambda _c, _m, *, previous_summary="": "seg-new"
        )
        character = _StubCharacter([])
        character.vars[HistoryController._SUMMARY_TEXT_VAR] = "OLD BLOB"
        character.vars[HistoryController._SUMMARY_COUNT_VAR] = 5

        rendered, count = controller._apply_layered_compression_result(
            character, compressed_summary="seg-new", summary_count=5, compressed_count=4,
        )
        segments = json.loads(character.vars[HistoryController._SUMMARY_SEGMENTS_VAR])
        self.assertEqual([s["text"] for s in segments], ["OLD BLOB", "seg-new"])
        self.assertEqual(count, 9)

    def test_layered_rolls_up_oldest_layers_when_over_limit(self):
        import json

        controller = self._make_controller(
            {"HISTORY_COMPRESSION_LAYERED_MAX_SEGMENTS": 3, "HISTORY_COMPRESSION_LAYERED_ROLLUP_BATCH": 2}
        )
        controller._compress_history_singleflight = (
            lambda _c, _m, *, previous_summary="": "MERGED"
        )
        character = _StubCharacter([])
        character.vars[HistoryController._SUMMARY_SEGMENTS_VAR] = json.dumps([
            {"text": "L1", "msg_count": 3, "level": 0},
            {"text": "L2", "msg_count": 3, "level": 0},
            {"text": "L3", "msg_count": 3, "level": 0},
        ])

        controller._apply_layered_compression_result(
            character, compressed_summary="L4", summary_count=9, compressed_count=3,
        )
        segments = json.loads(character.vars[HistoryController._SUMMARY_SEGMENTS_VAR])
        self.assertEqual([s["text"] for s in segments], ["MERGED", "L3", "L4"])
        self.assertEqual(segments[0]["level"], 1)
        self.assertEqual(segments[0]["msg_count"], 6)


if __name__ == "__main__":
    unittest.main()
