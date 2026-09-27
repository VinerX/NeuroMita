from __future__ import annotations

from types import SimpleNamespace

from managers.llm_request_runner import LLMRequestRunner


class _Events:
    def __init__(self) -> None:
        self.emitted = []

    def emit(self, name, data) -> None:
        self.emitted.append((name, data))


class _Resolver:
    @staticmethod
    def resolve_chain(_preset_id):
        return [SimpleNamespace(preset_name="test")]


class _Failure:
    @staticmethod
    def to_console_summary():
        return "canonical details"

    @staticmethod
    def to_user_message():
        return "canonical error"

    @staticmethod
    def to_payload():
        return {"code": "network.dns"}


def test_failure_context_cannot_override_terminal_error_payload() -> None:
    runner = LLMRequestRunner.__new__(LLMRequestRunner)
    events = _Events()
    runner.preset_resolver = _Resolver()
    runner.provider_manager = object()
    runner.event_bus = events
    runner._run_state = SimpleNamespace(abort_chain=False)

    def fail_request(**_kwargs):
        runner.last_error = _Failure()
        return None

    runner._run_on_preset = fail_request

    runner.run(
        messages=[],
        preset_id=None,
        stream_callback=None,
        build_request=lambda *_args: None,
        max_attempts=1,
        retry_delay=0.0,
        request_timeout=1.0,
        failure_context={
            "message_id": "in:req-1",
            "character_id": "Crazy",
            "error": "overwritten error",
            "details": "overwritten details",
        },
    )

    _, payload = events.emitted[-1]
    assert payload == {
        "error": "canonical error",
        "details": "canonical details",
        "provider_error": {"code": "network.dns"},
        "message_id": "in:req-1",
        "character_id": "Crazy",
    }
