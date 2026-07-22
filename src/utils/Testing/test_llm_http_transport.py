from __future__ import annotations

import concurrent.futures
import sys
import threading
from pathlib import Path

import httpx
import pytest

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.llm_providers.base import (
    LLMRequest,
    LLMResponse,
    RequestCancellation,
    RequestCancelledError,
    StreamChannel,
    get_request_cancellation,
)
from handlers.llm_providers.common_provider import CommonProvider
from handlers.llm_providers.errors import LLMProviderError, coerce_provider_error
from handlers.llm_providers.gemini_provider import GeminiProvider
from handlers.llm_providers.http_transport import (
    LLMHttpTransport,
    LLMTimeoutPolicy,
    TransportProfile,
)
from handlers.llm_providers.openai_provider import OpenAIProvider
from handlers.llm_providers.openai_compatible import OpenAICompatibleProvider
from handlers.llm_providers.streaming import (
    LLMStreamEventType,
    StreamAccumulator,
    StreamDeadlineExceeded,
    StreamDeadlinePolicy,
    StreamSupervisor,
    iter_sse_data,
)
from services.stream_presentation import TextDeltaCoalescer
from managers.api_preset_resolver import PresetSettings
from managers.llm_request_runner import LLMRequestRunner


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


def test_local_transport_does_not_inherit_environment_proxy(monkeypatch):
    created = []

    class DummyClient:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def close(self):
            return None

    monkeypatch.setattr("handlers.llm_providers.http_transport.httpx.Client", DummyClient)
    transport = LLMHttpTransport(enable_http2=False)

    transport.client_for_url("http://127.0.0.1:11434/v1")
    transport.client_for_url("https://example.test/v1")

    assert created[0]["trust_env"] is False
    assert created[1]["trust_env"] is True
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


def test_transport_get_reuses_profile_client_and_applies_timeout():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json={"data": []})

    transport = LLMHttpTransport(
        enable_http2=False,
        client_factory=lambda _profile, _http2: httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
    )

    response = transport.get("https://example.test/v1/models", timeout=3.0)

    assert response.json() == {"data": []}
    assert captured["timeout"] == {
        "connect": 3.0,
        "read": 3.0,
        "write": 3.0,
        "pool": 3.0,
    }
    assert len(transport._clients) == 1
    response.close()
    transport.close()


def test_stream_accumulator_preserves_exact_events_and_legacy_text_bridge():
    events = []
    legacy = []
    cancellation = RequestCancellation()
    req = _request()
    req.stream = True
    req.stream_cb = lambda text, channel: legacy.append((channel, text))
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
    # Мост stream_cb различает каналы явным аргументом, а не <think>-тегами
    # в тексте: подписчику незачем парсить строку, чтобы понять, что пришло.
    assert legacy == [
        (StreamChannel.REASONING, "think"),
        (StreamChannel.CONTENT, "answer"),
    ]
    assert response.text == "answer"
    assert response.reasoning == "think"
    assert cancellation.has_meaningful_stream_event


def test_stream_accumulator_rescues_answer_left_in_the_reasoning_channel():
    # Сломанные сборки Qwen3 кладут весь ответ в reasoning и оставляют content
    # пустым — тогда мысли и есть ответ, иначе игрок получит пустоту.
    req = _request()
    req.stream = True
    accumulator = StreamAccumulator(req, provider="common", model="model")

    accumulator.add_reasoning("весь ответ тут")
    response = accumulator.complete(finish_reason="stop")

    assert response.text == "весь ответ тут"
    assert response.reasoning is None


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
    coalescer.flush()
    assert emitted == ["abcde"]

    coalescer.push("tail")
    coalescer.close(flush=True)
    assert emitted == ["abcde", "tail"]


def test_presentation_flush_is_a_barrier_for_inflight_emission():
    entered = threading.Event()
    release = threading.Event()
    flushed = threading.Event()

    def emit(_text):
        entered.set()
        release.wait(1.0)

    coalescer = TextDeltaCoalescer(emit, interval_seconds=0.001)
    coalescer.push("chunk")
    assert entered.wait(1.0)

    waiter = threading.Thread(target=lambda: (coalescer.flush(), flushed.set()))
    waiter.start()
    assert not flushed.wait(0.05)
    release.set()
    assert flushed.wait(1.0)
    waiter.join(timeout=1.0)
    coalescer.close()


def test_presentation_coalescer_reuses_one_worker_for_many_batches():
    emitted = []
    coalescer = TextDeltaCoalescer(emitted.append, interval_seconds=60.0)
    worker = coalescer._worker

    for index in range(50):
        coalescer.push(str(index))
        coalescer.flush()

    assert coalescer._worker is worker
    assert worker.is_alive()
    assert len(emitted) == 50
    coalescer.close()


def test_presentation_close_has_bounded_wait_when_consumer_is_stuck():
    entered = threading.Event()
    release = threading.Event()

    def emit(_text):
        entered.set()
        release.wait(1.0)

    coalescer = TextDeltaCoalescer(
        emit,
        interval_seconds=0.001,
        close_timeout_seconds=0.01,
    )
    coalescer.push("chunk")
    assert entered.wait(1.0)

    assert coalescer.close(flush=True) is False
    release.set()
    assert coalescer.close(flush=True, timeout_seconds=1.0) is True


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
        stream_cb=lambda text, channel: legacy.append((channel, text)),
    )
    cancellation = RequestCancellation()
    req.extra["_request_cancellation"] = cancellation

    response = provider.generate(req)

    assert response.text == "hello world"
    assert response.reasoning == "r"
    assert response.finish_reason == "stop"
    assert legacy == [
        (StreamChannel.REASONING, "r"),
        (StreamChannel.CONTENT, "hello"),
        (StreamChannel.CONTENT, " world"),
    ]
    assert cancellation.response_body_started
    transport.close()


@pytest.mark.parametrize(
    ("bad_event", "expected_code"),
    [
        ('{"error":{"message":"upstream failed"}}', "stream.provider_error"),
        ("{not-json}", "stream.invalid_json"),
    ],
)
def test_openai_compatible_stream_failure_never_returns_partial_success(bad_event, expected_code):
    body = (
        'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        f"data: {bad_event}\n\n"
        "data: [DONE]\n\n"
    )
    transport = LLMHttpTransport(
        enable_http2=False,
        client_factory=lambda _profile, _http2: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
        ),
    )
    provider = CommonProvider(http_transport=transport)
    req = LLMRequest(
        model="local-model",
        messages=[],
        api_url="http://localhost:1234/v1",
        provider_name="common",
        stream=True,
        extra={"_request_cancellation": RequestCancellation()},
    )

    with pytest.raises(LLMProviderError) as caught:
        provider.generate(req)

    assert caught.value.code == expected_code
    assert not caught.value.retryable
    assert get_request_cancellation(req).has_meaningful_stream_event
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

    # Мысли уезжают отдельным полем, а не <think>-обёрткой внутри текста:
    # text — только то, что видит игрок.
    assert response.text == "answer"
    assert response.reasoning == "thought"
    assert response.finish_reason == "STOP"
    assert requested_urls and ":streamGenerateContent" in requested_urls[0]
    assert "alt=sse" in requested_urls[0]
    transport.close()


def test_gemini_stream_error_never_returns_partial_success():
    body = (
        'data: {"candidates":[{"content":{"parts":[{"text":"hello"}]}}]}\n\n'
        'data: {"error":{"code":503,"message":"upstream failed"}}\n\n'
    )
    transport = LLMHttpTransport(
        enable_http2=False,
        client_factory=lambda _profile, _http2: httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    text=body,
                )
            )
        ),
    )
    provider = GeminiProvider(http_transport=transport)
    req = LLMRequest(
        model="gemini-test",
        messages=[{"role": "user", "content": "hi"}],
        api_url="https://example.test/v1/models/gemini-test:generateContent?key=secret",
        provider_name="gemini",
        stream=True,
        extra={"_request_cancellation": RequestCancellation()},
    )

    with pytest.raises(LLMProviderError) as caught:
        provider.generate(req)

    assert caught.value.code == "stream.provider_error"
    assert caught.value.status_code == 503
    assert not caught.value.retryable
    transport.close()


def test_gemini_http_error_preserves_retry_after_header():
    transport = LLMHttpTransport(
        enable_http2=False,
        client_factory=lambda _profile, _http2: httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    429,
                    headers={"Retry-After": "9"},
                    json={"error": {"message": "rate limited"}},
                )
            )
        ),
    )
    provider = GeminiProvider(http_transport=transport)
    req = LLMRequest(
        model="gemini-test",
        messages=[{"role": "user", "content": "hi"}],
        api_url="https://example.test/v1/models/gemini-test:generateContent?key=secret",
        provider_name="gemini",
    )

    with pytest.raises(LLMProviderError) as caught:
        provider.generate(req)

    assert caught.value.retry_after_seconds == 9.0
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


class _CapturingSdkProvider(OpenAICompatibleProvider):
    name = "capturing-sdk"
    supports_stream_usage = True

    def __init__(self, captured):
        super().__init__()
        self._captured = captured

    def is_applicable(self, req):
        return True

    def _get_client(self, req):
        captured = self._captured

        class Completions:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return iter(())

        class Chat:
            completions = Completions()

        class Client:
            chat = Chat()

            @staticmethod
            def close():
                return None

        return Client()


def test_stream_usage_is_capability_driven_for_http_and_sdk_adapters():
    common = CommonProvider()
    req = _request()
    req.stream = True
    req.capabilities["supports_stream_usage"] = True

    payload = common._build_payload(req, req.model, req.messages)
    assert payload["stream_options"] == {"include_usage": True}

    req.capabilities["supports_stream_usage"] = False
    assert "stream_options" not in common._build_payload(req, req.model, req.messages)
    common.close()

    captured = {}
    sdk = _CapturingSdkProvider(captured)
    sdk_req = _request()
    sdk_req.stream = True
    sdk.generate(sdk_req)
    assert captured["stream_options"] == {"include_usage": True}
    sdk.close()


def test_sdk_stream_error_never_returns_partial_success():
    class Delta:
        content = "hello"
        reasoning_content = ""
        model_extra = {}
        tool_calls = []

    class Choice:
        finish_reason = None
        delta = Delta()

    class TextChunk:
        model = "model"
        usage = None
        choices = [Choice()]

        @staticmethod
        def model_dump():
            return {"choices": [{"delta": {"content": "hello"}}]}

    class ErrorChunk:
        model = "model"
        usage = None
        choices = []

        @staticmethod
        def model_dump():
            return {"error": {"message": "upstream failed"}}

    provider = _CapturingSdkProvider({})
    req = _request()
    req.stream = True
    req.extra["_request_cancellation"] = RequestCancellation()

    with pytest.raises(LLMProviderError) as caught:
        provider._handle_stream(iter((TextChunk(), ErrorChunk())), req)

    assert caught.value.code == "stream.provider_error"
    assert not caught.value.retryable
    provider.close()


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


class _RunnerSettings:
    def get(self, key, default=None):
        return default


class _RunnerEvents:
    def emit(self, *_args, **_kwargs):
        return None


class _RunnerResolver:
    def __init__(self, presets):
        self._presets = presets

    def resolve_chain(self, _preset_id):
        return list(self._presets)

    def apply_key_rotation(self, preset, _attempt):
        return preset


def _runner_preset(name: str) -> PresetSettings:
    return PresetSettings(
        protocol_id="openai_compatible_default",
        dialect_id="openai_chat_completions",
        provider_name="common",
        headers={},
        transforms=[],
        capabilities={"streaming": True},
        api_key="",
        api_url="http://localhost:1234/v1",
        api_model=name,
        preset_name=name,
        reserve_keys=[],
    )


def _runner_with_provider(presets, provider_manager):
    runner = LLMRequestRunner(_RunnerSettings(), _RunnerResolver(presets), _RunnerEvents())
    runner.provider_manager.close()
    runner.provider_manager = provider_manager
    return runner


def test_stream_timeout_before_body_allows_fallback_preset():
    calls = []

    class ProviderManager:
        def generate(self, req):
            calls.append(req.model)
            if req.model == "main":
                cancellation = get_request_cancellation(req)
                assert cancellation is not None
                cancellation.wait(1.0)
                cancellation.raise_if_cancelled()
            return LLMResponse(text="fallback ok", model=req.model, provider_name="common")

        def close(self):
            return None

    presets = [_runner_preset("main"), _runner_preset("fallback")]
    runner = _runner_with_provider(presets, ProviderManager())

    def build_request(_preset, model):
        return LLMRequest(
            model=model,
            messages=[],
            api_url="http://localhost:1234/v1",
            provider_name="common",
            stream=True,
            stream_event_cb=lambda _event: None,
            extra={
                "stream_first_meaningful_timeout_seconds": 0.05,
                "stream_watchdog_poll_seconds": 0.01,
            },
        )

    response = runner.run(
        messages=[],
        preset_id=None,
        stream_callback=None,
        build_request=build_request,
        max_attempts=2,
        retry_delay=0.0,
        request_timeout=1.0,
    )

    assert response is not None and response.text == "fallback ok"
    assert calls == ["main", "main", "fallback"]
    runner.close()


def test_stream_timeout_after_body_aborts_fallback_chain():
    calls = []

    class ProviderManager:
        def generate(self, req):
            calls.append(req.model)
            cancellation = get_request_cancellation(req)
            assert cancellation is not None
            cancellation.record_response_body_started()
            accumulator = StreamAccumulator(req, provider="common", model=req.model)
            accumulator.add_text("partial")
            cancellation.wait(1.0)
            cancellation.raise_if_cancelled()
            return accumulator.complete()

        def close(self):
            return None

    presets = [_runner_preset("main"), _runner_preset("fallback")]
    runner = _runner_with_provider(presets, ProviderManager())

    response = runner.run(
        messages=[],
        preset_id=None,
        stream_callback=None,
        build_request=lambda _preset, model: LLMRequest(
            model=model,
            messages=[],
            api_url="http://localhost:1234/v1",
            provider_name="common",
            stream=True,
            stream_event_cb=lambda _event: None,
            extra={
                "stream_idle_timeout_seconds": 0.05,
                "stream_watchdog_poll_seconds": 0.01,
            },
        ),
        max_attempts=1,
        retry_delay=0.0,
        request_timeout=1.0,
    )

    assert response is not None and response.text is None
    assert calls == ["main"]
    runner.close()


def test_non_stream_timeout_before_response_allows_fallback_preset():
    calls = []

    class ProviderManager:
        def generate(self, req):
            calls.append(req.model)
            if req.model == "main":
                cancellation = get_request_cancellation(req)
                assert cancellation is not None
                cancellation.wait(1.0)
                cancellation.raise_if_cancelled()
            return LLMResponse(text="fallback ok", model=req.model, provider_name="common")

        def close(self):
            return None

    presets = [_runner_preset("main"), _runner_preset("fallback")]
    runner = _runner_with_provider(presets, ProviderManager())
    response = runner.run(
        messages=[],
        preset_id=None,
        stream_callback=None,
        build_request=lambda _preset, model: LLMRequest(
            model=model,
            messages=[],
            api_url="http://localhost:1234/v1",
            provider_name="common",
            stream=False,
        ),
        max_attempts=1,
        retry_delay=0.0,
        request_timeout=0.05,
    )

    assert response is not None and response.text == "fallback ok"
    assert calls == ["main", "fallback"]
    runner.close()


def test_non_stream_timeout_after_response_headers_aborts_fallback_chain():
    calls = []

    class ProviderManager:
        def generate(self, req):
            calls.append(req.model)
            cancellation = get_request_cancellation(req)
            assert cancellation is not None
            cancellation.record_response_headers_received()
            cancellation.wait(1.0)
            cancellation.raise_if_cancelled()

        def close(self):
            return None

    presets = [_runner_preset("main"), _runner_preset("fallback")]
    runner = _runner_with_provider(presets, ProviderManager())
    response = runner.run(
        messages=[],
        preset_id=None,
        stream_callback=None,
        build_request=lambda _preset, model: LLMRequest(
            model=model,
            messages=[],
            api_url="http://localhost:1234/v1",
            provider_name="common",
            stream=False,
        ),
        max_attempts=1,
        retry_delay=0.0,
        request_timeout=0.05,
    )

    assert response is not None and response.text is None
    assert calls == ["main"]
    runner.close()


def test_abort_future_does_not_retire_cooperatively_cancelled_worker():
    class CompletedFuture:
        @staticmethod
        def cancel():
            return False

        @staticmethod
        def result(timeout=None):
            raise RequestCancelledError("cancelled")

        @staticmethod
        def done():
            return True

    class Pool:
        retired_workers = 0
        max_retired_workers = 8
        abandon_calls = 0

        def abandon(self, _future):
            self.abandon_calls += 1
            return True

    pool = Pool()
    with pytest.raises(concurrent.futures.TimeoutError):
        LLMRequestRunner._abort_future(
            CompletedFuture(),
            pool,
            RequestCancellation(),
            reason="deadline",
            grace_timeout=1.0,
        )

    assert pool.abandon_calls == 0


def test_runner_uses_retry_after_with_a_reasonable_cap():
    calls = []
    waits = []

    class ProviderManager:
        def generate(self, req):
            calls.append(req.model)
            if len(calls) == 1:
                raise LLMProviderError(
                    provider="common",
                    friendly_message="rate limited",
                    provider_message="rate limited",
                    retryable=True,
                    retry_after_seconds=10.0,
                )
            return LLMResponse(text="ok", model=req.model, provider_name="common")

        def close(self):
            return None

    preset = _runner_preset("model")
    runner = _runner_with_provider([preset], ProviderManager())

    class WaitCapture:
        @staticmethod
        def wait(timeout):
            waits.append(timeout)
            return False

        @staticmethod
        def set():
            return None

    runner._shutdown_event = WaitCapture()

    response = runner.run(
        messages=[],
        preset_id=None,
        stream_callback=None,
        build_request=lambda _preset, model: LLMRequest(
            model=model,
            messages=[],
            api_url="http://localhost:1234/v1",
            provider_name="common",
        ),
        max_attempts=2,
        retry_delay=0.2,
        request_timeout=1.0,
    )

    assert response is not None and response.text == "ok"
    assert waits == [10.0]
    runner.close()
