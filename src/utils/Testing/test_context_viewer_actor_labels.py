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


def test_working_state_and_retained_actions_have_distinct_context_labels() -> None:
    viewer = _viewer()
    working_state = {"role": "assistant", "content": "[WORKING STATE]\nFocus: test\n[/WORKING STATE]"}
    actions = {"role": "assistant", "content": "[RECENT ACTIONS BEFORE SUMMARY BOUNDARY]\n- animation: Dance_07"}

    assert viewer._classify_message_label(working_state, "assistant", 1, 0) == "Working State"
    assert viewer._classify_message_label(actions, "assistant", 2, 1) == "Recent Actions Before Summary Boundary"
