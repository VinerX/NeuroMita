from __future__ import annotations

import sys
from pathlib import Path

import httpx

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.llm_providers.base import LLMRequest, RequestCancellation
from handlers.llm_providers.common_provider import CommonProvider
from handlers.llm_providers.errors import coerce_provider_error
from handlers.llm_providers.gemini_provider import GeminiProvider
from handlers.llm_providers.http_transport import (
    LLMHttpTransport,
    LLMTimeoutPolicy,
    TransportProfile,
)
from handlers.llm_providers.openai_provider import OpenAIProvider
from handlers.llm_providers.streaming import (
    LLMStreamEventType,
    StreamAccumulator,
    StreamDeadlineExceeded,
    StreamDeadlinePolicy,
    StreamSupervisor,
    iter_sse_data,
)
from services.stream_presentation import TextDeltaCoalescer


def _request(url: str = "https://example.test/v1") -> LLMRequest:
    return LLMRequest(model="model", messages=[], api_url=url, provider_name="common")


def test_timeout_policy_separates_network_phases_and_scales_large_uploads():
    req = _request()

    regular = LLMTimeoutPolicy.for_request(req, payload_size_bytes=16_000)
    large = LLMTimeoutPolicy.for_request(req, payload_size_bytes=2_000_000)

    assert regular.connect == 30.0
    assert regular.write == 60.0
    assert regular.read == 240.0
    assert regular.pool == 10.0
    assert large.write > regular.write
    assert large.write <= 180.0


def test_localhost_uses_fast_connect_profile_without_reducing_stream_read_budget():
    req = _request("http://127.0.0.1:11434/v1/chat/completions")
    req.extra["http_read_timeout_seconds"] = 300

    policy = LLMTimeoutPolicy.for_request(req)

    assert policy.connect == 5.0
    assert policy.read == 300.0


def test_transport_reuses_profile_clients_and_negotiates_http2_only_for_remote():
    created: list[tuple[TransportProfile, bool]] = []

    def factory(profile: TransportProfile, http2: bool) -> httpx.Client:
        created.append((profile, http2))
        return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})))

    transport = LLMHttpTransport(enable_http2=True, client_factory=factory)
    transport._http2_available = True

    assert transport.client_for_url("https://example.test") is transport.client_for_url("https://other.test")
    transport.client_for_url("http://localhost:11434")

    assert created == [
        (TransportProfile.REMOTE, True),
        (TransportProfile.LOCAL, False),
    ]
    transport.close()


def test_transport_posts_json_with_phase_timeouts_and_returns_streamable_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, text='data: {"choices":[]}\n\ndata: [DONE]\n\n')

    transport = LLMHttpTransport(
        enable_http2=False,
        client_factory=lambda _profile, _http2: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    req = _request()
    response = transport.post_json(req, req.api_url, headers={}, payload={"messages": []}, stream=True)

    assert list(iter_sse_data(response.iter_lines()))[-1] == "[DONE]"
    assert captured["timeout"] == {
        "connect": 30.0,
        "read": 240.0,
        "write": 60.0,
        "pool": 10.0,
    }
    response.close()
    transport.close()


def test_stream_accumulator_preserves_exact_events_and_legacy_text_bridge():
    events = []
    legacy = []
    cancellation = RequestCancellation()
    req = _request()
    req.stream = True
    req.stream_cb = legacy.append
    req.stream_event_cb = events.append
    req.extra["_request_cancellation"] = cancellation
    accumulator = StreamAccumulator(req, provider="common", model="model")

    accumulator.add_reasoning("think")
    accumulator.add_text("answer")
    response = accumulator.complete(finish_reason="stop")
    accumulator.channel.complete(response)

    assert [event.type for event in events] == [
        LLMStreamEventType.STARTED,
        LLMStreamEventType.REASONING_DELTA,
        LLMStreamEventType.TEXT_DELTA,
        LLMStreamEventType.COMPLETED,
    ]
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert legacy == ["<think>think</think>", "answer"]
    assert response.text == "<think>think</think>\nanswer"
    assert cancellation.has_meaningful_stream_event


def test_sse_decoder_supports_comments_and_multiline_data():
    lines = [": heartbeat", "data: one", "data: two", "", "data:[DONE]", ""]

    assert list(iter_sse_data(lines)) == ["one\ntwo", "[DONE]"]


def test_gemini_stream_endpoint_preserves_key_and_enables_sse():
    req = _request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent?key=secret"
    )

    stream_url = GeminiProvider._request_url(req, stream=True)

    assert ":streamGenerateContent" in stream_url
    assert "key=secret" in stream_url
    assert "alt=sse" in stream_url


def test_httpx_write_timeout_is_exposed_as_upload_phase():
    request = httpx.Request("POST", "https://example.test")
    error = coerce_provider_error(
        "gemini",
        httpx.WriteTimeout("upload stalled", request=request),
        url=str(request.url),
    )

    assert error.phase == "write"
    assert error.code == "timeout.write"
    assert not error.retryable
    assert error.to_payload()["phase"] == "write"


def test_stream_consumer_failure_does_not_abort_provider_accumulation():
    calls = []

    def broken_consumer(event):
        calls.append(event.type)
        raise RuntimeError("presentation failed")

    req = _request()
    req.stream = True
    req.stream_event_cb = broken_consumer
    accumulator = StreamAccumulator(req, provider="common", model="model")

    accumulator.add_text("still generated")

    assert calls == [LLMStreamEventType.STARTED]
    assert accumulator.complete().text == "still generated"


def test_presentation_coalescer_batches_small_deltas_and_bounds_buffer():
    emitted = []
    coalescer = TextDeltaCoalescer(
        emitted.append,
        interval_seconds=60.0,
        max_buffer_chars=5,
    )

    coalescer.push("ab")
    coalescer.push("cd")
    assert emitted == []
    coalescer.push("e")
    assert emitted == ["abcde"]

    coalescer.push("tail")
    coalescer.close(flush=True)
    assert emitted == ["abcde", "tail"]


def test_openai_compatible_provider_streams_sse_through_normalized_accumulator():
    body = (
        'data: {"model":"local-model","choices":[{"delta":{"reasoning_content":"r"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )
    transport = LLMHttpTransport(
        enable_http2=False,
        client_factory=lambda _profile, _http2: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
        ),
    )
    provider = CommonProvider(http_transport=transport)
    legacy = []
    req = LLMRequest(
        model="local-model",
        messages=[{"role": "user", "content": "hi"}],
        api_url="http://localhost:1234/v1",
        provider_name="common",
        dialect_id="openai_chat_completions",
        stream=True,
        stream_cb=legacy.append,
    )
    cancellation = RequestCancellation()
    req.extra["_request_cancellation"] = cancellation

    response = provider.generate(req)

    assert response.text == "<think>r</think>\nhello world"
    assert response.finish_reason == "stop"
    assert legacy == ["<think>r</think>", "hello", " world"]
    assert cancellation.response_body_started
    transport.close()


def test_gemini_provider_uses_real_sse_endpoint_and_streams_deltas():
    requested_urls = []
    body = (
        'data: {"modelVersion":"gemini-test","candidates":[{"content":{"parts":[{"text":"thought","thought":true}]}}]}\n\n'
        'data: {"candidates":[{"content":{"parts":[{"text":"answer"}]},"finishReason":"STOP"}]}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    transport = LLMHttpTransport(
        enable_http2=False,
        client_factory=lambda _profile, _http2: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider = GeminiProvider(http_transport=transport)
    req = LLMRequest(
        model="gemini-test",
        messages=[{"role": "user", "content": "hi"}],
        api_url="https://example.test/v1/models/gemini-test:generateContent?key=secret",
        provider_name="gemini",
        stream=True,
    )

    response = provider.generate(req)

    assert response.text == "<think>thought</think>\nanswer"
    assert response.finish_reason == "STOP"
    assert requested_urls and ":streamGenerateContent" in requested_urls[0]
    assert "alt=sse" in requested_urls[0]
    transport.close()


def test_openai_sdk_adapter_reuses_httpx_pool_and_disables_hidden_retries():
    transport = LLMHttpTransport(
        enable_http2=False,
        client_factory=lambda _profile, _http2: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ),
    )
    provider = OpenAIProvider(http_transport=transport)
    req = LLMRequest(
        model="gpt-test",
        messages=[],
        api_key="key",
        api_url="https://api.openai.test/v1",
        provider_name="openai",
    )

    first = provider._get_client(req)
    second = provider._get_client(req)

    assert first.max_retries == 0
    assert second.max_retries == 0
    assert first._client is second._client
    provider.close()
    transport.close()


def test_stream_supervisor_distinguishes_first_event_and_idle_deadlines():
    cancellation = RequestCancellation()
    policy = StreamDeadlinePolicy(
        first_meaningful_event=10.0,
        idle_after_started=3.0,
        maximum_duration=30.0,
        poll_interval=0.1,
    )
    supervisor = StreamSupervisor(cancellation, policy)

    supervisor.raise_if_expired(now=cancellation.started_at + 9.0)
    try:
        supervisor.raise_if_expired(now=cancellation.started_at + 10.0)
    except StreamDeadlineExceeded as exc:
        assert "no meaningful event" in str(exc)
    else:
        raise AssertionError("first meaningful event deadline was not enforced")

    cancellation.record_meaningful_stream_event()
    _, _, last_event_at = cancellation.stream_activity()
    assert last_event_at is not None
    supervisor.raise_if_expired(now=last_event_at + 2.0)
    try:
        supervisor.raise_if_expired(now=last_event_at + 3.0)
    except StreamDeadlineExceeded as exc:
        assert "became idle" in str(exc)
    else:
        raise AssertionError("stream idle deadline was not enforced")
