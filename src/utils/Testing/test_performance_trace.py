from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from core.performance_trace import PerformanceTraceStore, performance_traces


class PerformanceTraceTests(unittest.TestCase):
    def setUp(self):
        performance_traces().clear()

    def test_marks_spans_and_derived_metrics(self):
        trace = performance_traces().start(
            "test",
            attributes={"engine": "fake", "user_input": "must not be stored"},
        )
        trace.mark("generation.enqueued")
        trace.mark("generation.worker_started")
        token = trace.start_span("llm.total", provider="fake")
        trace.finish_span(token, result="success")
        trace.mark("response.first_visible_text")

        snapshot = performance_traces().finish(trace.trace_id)

        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["attributes"], {"engine": "fake"})
        self.assertGreaterEqual(snapshot["metrics"]["generation_pool_wait_ms"], 0.0)
        self.assertGreaterEqual(snapshot["metrics"]["first_visible_text_ms"], 0.0)
        self.assertEqual(snapshot["metrics"]["llm_total_ms"], snapshot["spans"][0]["duration_ms"])

    def test_llm_relative_and_http_queue_metrics(self):
        trace = performance_traces().start("test")
        llm_token = trace.start_span("llm.total")
        trace.mark("response.first_stream_event")
        trace.mark("response.first_visible_text")
        trace.finish_span(llm_token)
        trace.mark("llm.http_enqueued", attempt_id="1:1", provider="fake", model="model")
        time.sleep(0.001)
        trace.mark("llm.http_started", attempt_id="1:1", provider="fake", model="model")

        snapshot = performance_traces().finish(trace.trace_id)
        self.assertGreaterEqual(snapshot["metrics"]["llm_first_event_ms"], 0.0)
        self.assertGreaterEqual(snapshot["metrics"]["llm_first_visible_text_ms"], 0.0)
        self.assertGreaterEqual(snapshot["metrics"]["llm_http_pool_wait_ms"], 0.0)

    def test_span_context_closes_on_error_and_duration_is_positive(self):
        trace = performance_traces().start("test")
        with self.assertRaises(RuntimeError):
            with trace.span("failing.operation"):
                time.sleep(0.001)
                raise RuntimeError("expected")

        span = trace.snapshot()["spans"][0]
        self.assertIsNotNone(span["ended_ns"])
        self.assertGreater(span["duration_ms"], 0.0)
        self.assertEqual(span["attributes"]["result"], "error")
        self.assertEqual(span["attributes"]["error_type"], "RuntimeError")

    def test_concurrent_writes_are_kept_in_one_trace(self):
        trace = performance_traces().start("test")

        def write_measurement(index: int):
            trace.mark(f"worker.{index}")
            with trace.span("parallel.operation", worker=index):
                time.sleep(0.001)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(write_measurement, range(8)))

        snapshot = performance_traces().finish(trace.trace_id)
        self.assertEqual(len(snapshot["marks"]), 8)
        self.assertEqual(len(snapshot["spans"]), 8)
        self.assertTrue(all(span["ended_ns"] is not None for span in snapshot["spans"]))

    def test_mark_once_is_idempotent_and_store_is_bounded(self):
        trace = performance_traces().start("test")
        self.assertTrue(trace.mark_once("first"))
        self.assertFalse(trace.mark_once("first"))
        performance_traces().finish(trace.trace_id)
        self.assertEqual(len(performance_traces().recent()), 1)

        store = PerformanceTraceStore(maxlen=2)
        for _ in range(3):
            item = store.start("bounded")
            store.finish(item.trace_id)
        self.assertEqual(len(store.recent()), 2)

        reused = PerformanceTraceStore()
        first = reused.start("same-id", trace_id="same-id")
        reused.finish(first.trace_id)
        second = reused.start("same-id", trace_id="same-id")
        self.assertNotEqual(first.trace_id, second.trace_id)

    def test_stale_trace_is_abandoned_and_summary_is_agent_readable(self):
        store = PerformanceTraceStore(active_trace_ttl_sec=0.001)
        stale = store.start(
            "stale",
            started_ns=time.perf_counter_ns() - 2_000_000,
        )
        stale_snapshot = store.recent(1)[0]
        self.assertEqual(stale_snapshot["trace_id"], stale.trace_id)
        self.assertEqual(stale_snapshot["status"], "abandoned")
        self.assertEqual(stale_snapshot["error_stage"], "unknown")

        fresh = store.start("fresh")
        fresh.mark("response.first_visible_text")
        span_token = fresh.start_span("llm.total")
        fresh.finish_span(span_token)
        store.finish(fresh.trace_id)
        summary = store.summary()

        self.assertEqual(summary["trace_count"], 2)
        self.assertIn("first_visible_text_ms", summary["latency"])
        self.assertIn("median_ms", summary["latency"]["first_visible_text_ms"])
        self.assertIn("p95_ms", summary["latency"]["first_visible_text_ms"])
        self.assertIn("llm.total", summary["spans"])
        self.assertIsNotNone(store.snapshot(fresh.trace_id))


if __name__ == "__main__":
    unittest.main()