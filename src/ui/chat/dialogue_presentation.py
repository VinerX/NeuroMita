from __future__ import annotations

from services.contracts import DialogueRuntimeSnapshot, DialogueRuntimeSource


def format_conversation_title(
    snapshot: DialogueRuntimeSnapshot | None,
    selected_character: str = "",
) -> str:
    """Format a session-aware title with a safe single-character fallback."""

    fallback = str(selected_character or "character").strip() or "character"
    if snapshot is None or not snapshot.is_active:
        return f"Conversation with {fallback}"
    names: list[str] = []
    seen: set[str] = set()
    for participant in snapshot.participants:
        character_id = str(participant.character_id or "").strip()
        if not character_id or character_id.casefold() == "gamemaster":
            continue
        name = str(participant.display_name or character_id).strip()
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    if len(names) <= 1:
        return f"Conversation with {names[0] if names else fallback}"
    if len(names) <= 3:
        return "Conversation: " + ", ".join(names)
    return f"Conversation with Mitas ({len(names)})"


def format_runtime_source(snapshot: DialogueRuntimeSnapshot | None) -> str:
    if snapshot is None:
        return ""
    if snapshot.source is DialogueRuntimeSource.UNITY:
        return "Game"
    if snapshot.source is DialogueRuntimeSource.SANDBOX:
        return "Sandbox"
    return ""
