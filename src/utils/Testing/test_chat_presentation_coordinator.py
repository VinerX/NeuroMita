from __future__ import annotations

from ui.chat.presentation_coordinator import ChatPresentationCoordinator, ChatRenderCommand


def _command(message_id: str, content: str, *, character_id: str = "Crazy") -> ChatRenderCommand:
    return ChatRenderCommand(
        role="user",
        content=content,
        character_id=character_id,
        message_id=message_id,
    )


def test_live_message_present_before_snapshot_request_is_replayed_when_snapshot_misses_it() -> None:
    coordinator = ChatPresentationCoordinator()
    live = _command("in:req-1", "player live line")

    assert coordinator.record_live(live) is True
    ticket = coordinator.begin_history_load("Crazy")

    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )

    assert plan.accepted is True
    assert plan.replay == (live,)


def test_commit_after_snapshot_start_is_replayed_when_snapshot_was_taken_too_early() -> None:
    coordinator = ChatPresentationCoordinator()
    live = _command("in:req-2", "player live line")
    assert coordinator.record_live(live) is True

    ticket = coordinator.begin_history_load("Crazy")
    coordinator.acknowledge_persisted(
        message_ids=["in:req-2"],
        character_ids=["Crazy"],
    )

    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )

    assert plan.accepted is True
    assert plan.replay == (live,)


def test_snapshot_message_suppresses_late_duplicate_live_event() -> None:
    coordinator = ChatPresentationCoordinator()
    ticket = coordinator.begin_history_load("Crazy")

    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[
            {
                "role": "assistant",
                "content": "already persisted",
                "message_id": "out:task-1",
            }
        ],
    )

    assert plan.accepted is True
    late = ChatRenderCommand(
        role="assistant",
        content="already persisted",
        character_id="Crazy",
        message_id="out:task-1",
    )
    assert coordinator.record_live(late) is False


def test_same_message_id_can_have_multiple_live_fragments_before_history_projection() -> None:
    coordinator = ChatPresentationCoordinator()
    text = _command("in:req-3", "text")
    image = ChatRenderCommand(
        role="user",
        content=[{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA=="}}],
        character_id="Crazy",
        message_id="in:req-3",
    )

    assert coordinator.record_live(text) is True
    assert coordinator.record_live(image) is True

    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )

    assert plan.replay == (text, image)


def test_stale_or_wrong_character_snapshot_cannot_replace_current_chat() -> None:
    coordinator = ChatPresentationCoordinator()
    ticket = coordinator.begin_history_load("Crazy")

    stale = coordinator.plan_history_projection(
        request_id="older-request",
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )
    assert stale.accepted is False
    assert stale.reason == "stale_request"

    wrong_character = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Kind",
        history_messages=[],
    )
    assert wrong_character.accepted is False
    assert wrong_character.reason == "inactive_character"


def test_character_switch_rejects_snapshot_even_if_response_omits_character_id() -> None:
    coordinator = ChatPresentationCoordinator()
    ticket = coordinator.begin_history_load("Crazy")

    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="",
        current_character_id="Kind",
        history_messages=[],
    )

    assert plan.accepted is False
    assert plan.reason == "inactive_character"


def test_history_projection_waits_for_active_stream_and_requests_fresh_snapshot_after_finish() -> None:
    coordinator = ChatPresentationCoordinator()
    ticket = coordinator.begin_history_load("Crazy")
    coordinator.begin_stream("stream-1")
    coordinator.mark_stream_mounted("stream-1")

    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )

    assert plan.accepted is False
    assert plan.retry_after_stream is True
    assert plan.reason == "active_stream"
    assert coordinator.finish_stream("stream-1") is True
    assert coordinator.finish_stream("stream-1") is False


def test_other_character_stable_live_message_survives_unrelated_snapshot() -> None:
    coordinator = ChatPresentationCoordinator()
    other = _command("in:kind-1", "kind live line", character_id="Kind")
    assert coordinator.record_live(other) is True

    crazy_ticket = coordinator.begin_history_load("Crazy")
    crazy_plan = coordinator.plan_history_projection(
        request_id=crazy_ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )
    assert crazy_plan.accepted is True
    assert crazy_plan.replay == ()

    kind_ticket = coordinator.begin_history_load("Kind")
    kind_plan = coordinator.plan_history_projection(
        request_id=kind_ticket.request_id,
        response_character_id="Kind",
        current_character_id="Kind",
        history_messages=[],
    )
    assert kind_plan.accepted is True
    assert kind_plan.replay == (other,)


def test_exact_live_turn_race_keeps_player_between_two_assistant_messages() -> None:
    coordinator = ChatPresentationCoordinator()
    player = _command("in:req-live", "player turn")
    assert coordinator.record_live(player) is True

    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[
            {
                "role": "assistant",
                "content": "previous assistant",
                "message_id": "out:old-task",
            }
        ],
    )
    assert plan.accepted is True
    assert plan.replay == (player,)

    coordinator.acknowledge_persisted(
        message_ids=["in:req-live", "out:new-task"],
        character_ids=["Crazy"],
    )
    assistant = ChatRenderCommand(
        role="assistant",
        content="new assistant",
        character_id="Crazy",
        message_id="out:new-task",
    )
    assert coordinator.record_live(assistant) is True

    refresh = coordinator.begin_history_load("Crazy")
    refreshed = coordinator.plan_history_projection(
        request_id=refresh.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[
            {"role": "assistant", "content": "previous assistant", "message_id": "out:old-task"},
            {"role": "user", "content": "player turn", "message_id": "in:req-live"},
            {"role": "assistant", "content": "new assistant", "message_id": "out:new-task"},
        ],
    )
    assert refreshed.accepted is True
    assert refreshed.replay == ()
    assert coordinator.record_live(assistant) is False


def test_composite_snapshot_covers_separate_live_fragments_with_same_message_id() -> None:
    coordinator = ChatPresentationCoordinator()
    text = _command("in:req-composite", "hello")
    image = ChatRenderCommand(
        role="user",
        content=[{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA=="}}],
        character_id="Crazy",
        message_id="in:req-composite",
    )
    assert coordinator.record_live(text) is True
    assert coordinator.record_live(image) is True

    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[
            {
                "role": "user",
                "message_id": "in:req-composite",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA=="}},
                ],
            }
        ],
    )

    assert plan.accepted is True
    assert plan.replay == ()
    assert coordinator.record_live(text) is False
    assert coordinator.record_live(image) is False


def test_partial_snapshot_replays_only_uncovered_fragment_for_same_message_id() -> None:
    coordinator = ChatPresentationCoordinator()
    text = _command("in:req-partial", "hello")
    image = ChatRenderCommand(
        role="user",
        content=[{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BB=="}}],
        character_id="Crazy",
        message_id="in:req-partial",
    )
    assert coordinator.record_live(text) is True
    assert coordinator.record_live(image) is True

    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[
            {
                "role": "user",
                "message_id": "in:req-partial",
                "content": [{"type": "text", "text": "hello"}],
            }
        ],
    )

    assert plan.accepted is True
    assert plan.replay == (image,)
    assert coordinator.record_live(text) is False


def test_inactive_character_live_message_is_recorded_but_not_rendered() -> None:
    coordinator = ChatPresentationCoordinator()
    late_crazy = ChatRenderCommand(
        role="assistant",
        content="late Crazy response",
        character_id="Crazy",
        message_id="out:crazy-late",
    )

    assert coordinator.record_live(late_crazy, current_character_id="Kind") is False

    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )

    assert plan.accepted is True
    assert plan.replay == (late_crazy,)


def test_live_surface_character_match_is_case_insensitive() -> None:
    coordinator = ChatPresentationCoordinator()
    command = _command("in:case", "same surface", character_id="CrAzY")

    assert coordinator.record_live(command, current_character_id="crazy") is True


def test_scoped_stream_does_not_block_other_character_history_projection() -> None:
    coordinator = ChatPresentationCoordinator()
    coordinator.begin_stream("crazy-stream", character_id="Crazy")

    kind_ticket = coordinator.begin_history_load("Kind")
    kind_plan = coordinator.plan_history_projection(
        request_id=kind_ticket.request_id,
        response_character_id="Kind",
        current_character_id="Kind",
        history_messages=[],
    )

    assert kind_plan.accepted is True
    assert kind_plan.retry_after_stream is False


def test_scoped_stream_blocks_own_history_until_last_stream_finishes() -> None:
    coordinator = ChatPresentationCoordinator()
    coordinator.begin_stream("crazy-stream-1", character_id="Crazy")
    coordinator.begin_stream("crazy-stream-2", character_id="Crazy")
    coordinator.mark_stream_mounted("crazy-stream-1")
    coordinator.mark_stream_mounted("crazy-stream-2")

    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )

    assert plan.accepted is False
    assert plan.retry_after_stream is True
    assert coordinator.finish_stream("crazy-stream-1", current_character_id="Crazy") is False
    assert coordinator.finish_stream("crazy-stream-2", current_character_id="Crazy") is True


def test_finishing_inactive_character_stream_does_not_reload_active_character() -> None:
    coordinator = ChatPresentationCoordinator()
    coordinator.begin_stream("crazy-stream", character_id="Crazy")
    coordinator.mark_stream_mounted("crazy-stream")

    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[],
    )
    assert plan.retry_after_stream is True

    assert coordinator.finish_stream("crazy-stream", current_character_id="Kind") is False


def test_stream_rendering_is_isolated_by_character() -> None:
    coordinator = ChatPresentationCoordinator()
    coordinator.begin_stream("crazy-stream", character_id="Crazy")

    assert coordinator.should_render_stream(
        "crazy-stream",
        current_character_id="Crazy",
    ) is True
    assert coordinator.should_render_stream(
        "crazy-stream",
        current_character_id="Kind",
    ) is False


def test_unscoped_stream_conservatively_blocks_history_projection() -> None:
    coordinator = ChatPresentationCoordinator()
    coordinator.begin_stream("legacy-stream")
    coordinator.mark_stream_mounted("legacy-stream")

    ticket = coordinator.begin_history_load("Kind")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Kind",
        current_character_id="Kind",
        history_messages=[],
    )

    assert plan.accepted is False
    assert plan.retry_after_stream is True
    assert coordinator.finish_stream("legacy-stream", current_character_id="Kind") is True


def test_multiple_unscoped_streams_reload_only_after_last_one_finishes() -> None:
    coordinator = ChatPresentationCoordinator()
    coordinator.begin_stream("legacy-1")
    coordinator.begin_stream("legacy-2")
    coordinator.mark_stream_mounted("legacy-1")
    coordinator.mark_stream_mounted("legacy-2")

    ticket = coordinator.begin_history_load("Kind")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Kind",
        current_character_id="Kind",
        history_messages=[],
    )
    assert plan.retry_after_stream is True

    assert coordinator.finish_stream("legacy-1", current_character_id="Kind") is False
    assert coordinator.finish_stream("legacy-2", current_character_id="Kind") is True


def test_unmounted_stream_allows_switch_back_snapshot_and_keeps_full_transcript() -> None:
    coordinator = ChatPresentationCoordinator()
    coordinator.begin_stream(
        "crazy-stream",
        character_id="Crazy",
        role="think",
        speaker_name="Crazy Mita",
    )
    coordinator.record_stream_chunk(
        "crazy-stream",
        "first thought ",
        role="think",
        character_id="Crazy",
    )
    coordinator.mark_stream_mounted("crazy-stream")

    coordinator.mark_streams_unmounted()
    coordinator.begin_stream(
        "crazy-stream",
        character_id="Crazy",
        role="assistant",
        speaker_name="Crazy Mita",
    )
    coordinator.record_stream_chunk(
        "crazy-stream",
        "first answer ",
        role="assistant",
        character_id="Crazy",
    )
    coordinator.record_stream_chunk(
        "crazy-stream",
        "second answer",
        role="assistant",
        character_id="Crazy",
    )

    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[
            {"role": "assistant", "content": "older", "message_id": "out:older"},
        ],
    )

    assert plan.accepted is True
    assert plan.retry_after_stream is True
    replay = coordinator.stream_replay("crazy-stream")
    assert replay is not None
    assert [(phase.role, phase.text) for phase in replay.phases] == [
        ("think", "first thought "),
        ("assistant", "first answer second answer"),
    ]
    assert coordinator.is_stream_mounted("crazy-stream") is False
    assert coordinator.finish_stream("crazy-stream", current_character_id="Crazy") is True


def test_history_snapshot_deduplicates_persisted_thinking_for_same_message_id() -> None:
    coordinator = ChatPresentationCoordinator()
    ticket = coordinator.begin_history_load("Crazy")
    think = ChatRenderCommand(
        role="think",
        content=[
            {"type": "meta", "speaker": "Crazy Mita"},
            {"type": "text", "text": "private reasoning"},
        ],
        character_id="Crazy",
        message_id="out:task-1",
    )
    assert coordinator.record_live(think, current_character_id="Crazy") is True

    plan = coordinator.plan_history_projection(
        request_id=ticket.request_id,
        response_character_id="Crazy",
        current_character_id="Crazy",
        history_messages=[
            {
                "role": "assistant",
                "content": "visible answer",
                "thinking": "private reasoning",
                "message_id": "out:task-1",
            }
        ],
    )

    assert plan.accepted is True
    assert plan.replay == ()
    assert coordinator.record_live(think, current_character_id="Crazy") is False
