from __future__ import annotations

from types import SimpleNamespace

from managers.conversation_event_writer import ConversationEventWriter
from services.dialogue_transcript_service import DialogueTranscriptService


class _Character:
    def __init__(self, char_id: str) -> None:
        self.char_id = char_id
        self.batches: list[list[dict]] = []

    def add_messages_to_history(self, messages: list[dict]):
        self.batches.append([dict(message) for message in messages])
        return list(range(1, len(messages) + 1))


def test_write_turn_fans_out_user_and_assistant_as_one_batch() -> None:
    character = _Character("Mita")
    writer = ConversationEventWriter(
        character_ref_resolver=lambda character_id: character if character_id == "Mita" else None
    )

    assistant_message_id = writer.write_turn(
        responder_character_id="Mita",
        sender="Player",
        participants=["Player", "Mita"],
        user_input="Hello",
        image_data=[],
        req_id="request-1",
        origin_message_id=None,
        assistant_text="Hi",
        assistant_target="Player",
        event_type="chat",
        task_uid="task-1",
    )

    assert assistant_message_id == "out:task-1"
    assert len(character.batches) == 1
    assert [message["role"] for message in character.batches[0]] == ["user", "assistant"]
    assert [message["content"] for message in character.batches[0]] == [
        [{"type": "text", "text": "Hello"}],
        "Hi",
    ]
    assert {message["turn_id"] for message in character.batches[0]} == {"turn:task-1"}


def test_write_turn_separates_source_and_responder_actor_metadata() -> None:
    character = _Character("Mita")
    writer = ConversationEventWriter(
        character_ref_resolver=lambda character_id: character if character_id == "Mita" else None
    )

    writer.write_turn(
        responder_character_id="Mita",
        sender="Crazy",
        participants=["Crazy", "Mita"],
        user_input="A question",
        image_data=[],
        req_id="request-2",
        origin_message_id=None,
        assistant_text="An answer",
        assistant_target="Crazy",
        event_type="chat",
        task_uid="task-2",
        dialogue=SimpleNamespace(
            conversation_id="conv-1",
            epoch=2,
            turn_index=4,
            speaker_actor_id="actor-crazy",
            responder_actor_id="actor-kind",
            participants=[
                SimpleNamespace(actor_id="actor-crazy"),
                SimpleNamespace(actor_id="actor-kind"),
            ],
        ),
    )

    user_event, assistant_event = character.batches[0]
    assert user_event["speaker_actor_id"] == "actor-crazy"
    assert assistant_event["speaker_actor_id"] == "actor-kind"
    assert assistant_event["source_actor_id"] == "actor-crazy"


def test_write_turn_fans_out_group_history_when_participants_are_actor_ids() -> None:
    kind = _Character("Kind")
    crazy = _Character("Crazy")
    characters = {"Kind": kind, "Crazy": crazy}
    writer = ConversationEventWriter(
        character_ref_resolver=lambda character_id: characters.get(character_id)
    )
    dialogue = SimpleNamespace(
        conversation_id="conv-dance-battle",
        epoch=2,
        turn_index=4,
        speaker_actor_id="Player",
        responder_actor_id="kind_mita_60b98a9a4fa7417c8f1021ba87cce926",
        participants=[
            SimpleNamespace(
                actor_id="kind_mita_60b98a9a4fa7417c8f1021ba87cce926",
                character_id="Kind",
                display_name="Kind Mita",
            ),
            SimpleNamespace(
                actor_id="crazy_mita_61fde7b594c34231935ee9a4e526fd21",
                character_id="Crazy",
                display_name="Crazy Mita",
            ),
        ],
    )

    writer.write_turn(
        responder_character_id="Kind",
        sender="Player",
        participants=["kind_mita", "crazy_mita"],
        user_input="Could you have a dance battle?",
        image_data=[],
        req_id="request-dance-battle",
        origin_message_id=None,
        assistant_text="I will not dance for her.",
        assistant_target="Crazy",
        event_type="chat",
        task_uid="task-dance-battle",
        dialogue=dialogue,
    )

    assert len(kind.batches) == 1
    assert len(crazy.batches) == 1
    assert [message["role"] for message in kind.batches[0]] == ["user", "assistant"]
    assert [message["role"] for message in crazy.batches[0]] == ["user", "user"]
    assert [message["content"] for message in crazy.batches[0]] == [
        [{"type": "text", "text": "Could you have a dance battle?"}],
        "I will not dance for her.",
    ]


def test_write_turn_records_player_and_segment_addressee_in_group_transcript() -> None:
    crazy = _Character("Crazy")
    mila = _Character("Mila")
    characters = {"Crazy": crazy, "Mila": mila}
    transcript = DialogueTranscriptService()
    writer = ConversationEventWriter(
        character_ref_resolver=lambda character_id: characters.get(character_id),
        transcript_service=transcript,
    )
    dialogue = SimpleNamespace(
        conversation_id="conv-target-context",
        epoch=1,
        turn_index=1,
        speaker_actor_id="Player",
        responder_actor_id="crazy_mita_actor",
        participants=[
            SimpleNamespace(actor_id="crazy_mita_actor", character_id="Crazy"),
            SimpleNamespace(actor_id="mila_actor", character_id="Mila"),
        ],
    )

    writer.write_turn(
        responder_character_id="Crazy",
        sender="Player",
        participants=["crazy_mita", "mila"],
        user_input="Can you talk to each other?",
        image_data=[],
        req_id="request-target-context",
        origin_message_id=None,
        assistant_text="Mila, answer me. Player, watch us.",
        assistant_target="Mila",
        event_type="chat",
        task_uid="task-target-context",
        structured_data={
            "segments": [
                {"text": "Mila, answer me.", "target": "Mila"},
                {"text": "Player, watch us."},
            ],
        },
        dialogue=dialogue,
    )

    entries = transcript.recent("conv-target-context")
    assert [entry.speaker_character_id for entry in entries] == [
        "Player",
        "Crazy",
        "Crazy",
    ]
    assert [entry.target_character_id for entry in entries] == ["", "Mila", ""]
    assert [entry.text for entry in entries] == [
        "Can you talk to each other?",
        "Mila, answer me.",
        "Player, watch us.",
    ]
