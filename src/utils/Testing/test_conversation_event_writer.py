from __future__ import annotations

from types import SimpleNamespace

from managers.conversation_event_writer import ConversationEventWriter


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


def test_write_turn_uses_dialogue_speaker_when_transport_sender_is_player() -> None:
    kind = _Character("Kind")
    crazy = _Character("Crazy")
    characters = {"Kind": kind, "Crazy": crazy}
    writer = ConversationEventWriter(
        character_ref_resolver=lambda character_id: characters.get(character_id)
    )
    dialogue = SimpleNamespace(
        speaker_actor_id="crazy-actor",
        responder_actor_id="kind-actor",
        participants=[
            SimpleNamespace(actor_id="crazy-actor", character_id="Crazy"),
            SimpleNamespace(actor_id="kind-actor", character_id="Kind"),
        ],
    )

    writer.write_turn(
        responder_character_id="Kind",
        sender="Player",
        participants=["Player", "Kind", "Crazy"],
        user_input="A question from Crazy",
        image_data=[],
        req_id="request-dialogue-sender",
        origin_message_id=None,
        assistant_text="An answer from Kind",
        assistant_target="Crazy",
        event_type="chat",
        task_uid="task-dialogue-sender",
        dialogue=dialogue,
    )

    assert [message["speaker"] for message in crazy.batches[0]] == ["Crazy", "Kind"]
    assert [message["role"] for message in crazy.batches[0]] == ["assistant", "user"]
    assert [message["speaker"] for message in kind.batches[0]] == ["Crazy", "Kind"]
    assert [message["role"] for message in kind.batches[0]] == ["user", "assistant"]


def test_write_turn_uses_unity_roster_to_fan_out_group_history() -> None:
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
        responder_actor_id="kind-actor",
        participants=[
            SimpleNamespace(actor_id="kind-actor", character_id="Kind"),
            SimpleNamespace(actor_id="crazy-actor", character_id="Crazy"),
        ],
    )

    writer.write_turn(
        responder_character_id="Kind",
        sender="Player",
        participants=["kind_transport_alias", "crazy_transport_alias"],
        user_input="Could you have a dance battle?",
        image_data=[],
        req_id="request-dance-battle",
        origin_message_id=None,
        assistant_text="I will not dance for her.",
        assistant_target="Player",
        event_type="chat",
        task_uid="task-dance-battle",
        dialogue=dialogue,
    )

    assert len(kind.batches) == 1
    assert len(crazy.batches) == 1
    assert [message["role"] for message in kind.batches[0]] == ["user", "assistant"]
    assert [message["role"] for message in crazy.batches[0]] == ["user", "user"]
