from __future__ import annotations

from ui.dialogs.context_viewer_dialog import ContextViewerDialog


def _viewer() -> ContextViewerDialog:
    viewer = ContextViewerDialog.__new__(ContextViewerDialog)
    viewer._message_meta = {}
    viewer._data = {
        "character_name": "Crazy Mita",
    }
    return viewer


def test_legacy_speaker_prefix_uses_characters_instead_of_provider_role() -> None:
    viewer = _viewer()
    message = {
        "role": "user",
        "content": "[SPEAKER Mila -> Crazy]\nBe quiet, Crazy.",
    }

    assert viewer._resolve_actor(message, 0) == ("Mila", "Crazy Mita")
    label = viewer._classify_message_label(message, "user", 1, 0)
    assert label == "👤 Mila → Crazy Mita"
    assert "SPEAKER" not in label
    assert "Player" not in label


def test_legacy_speaker_player_prefix_is_displayed_as_player() -> None:
    viewer = _viewer()
    message = {
        "role": "user",
        "content": "[SPEAKER Player]\nWho likes apples?",
    }

    assert viewer._resolve_actor(message, 0) == ("Player", None)
    assert viewer._classify_message_label(message, "user", 1, 0) == "👤 Player"


def test_legacy_owner_prefix_uses_owner_display_name() -> None:
    viewer = _viewer()
    message = {
        "role": "assistant",
        "content": "[SPEAKER Crazy]\nApples? Seriously?",
    }

    assert viewer._resolve_actor(message, 0) == ("Crazy Mita", None)
    assert viewer._classify_message_label(message, "assistant", 1, 0) == "🤖 Crazy Mita"
