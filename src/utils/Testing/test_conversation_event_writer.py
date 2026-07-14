from __future__ import annotations

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
