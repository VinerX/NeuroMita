"""Exact-trigger core memories.

Some core memories must surface on a precise textual trigger rather than on
embedding similarity — a two-digit message like "23" is not something a vector
search can retrieve reliably, and we must *not* fire on every stray 23 that
appears in a date, version, item count or a long technical message.

This module is a small, deterministic retrieval hook: each trigger has an id,
canonical content, and an exact matcher over the *current player input*. Matched
contents are injected into the relevant-context block by the model controller,
independent of whether RAG is enabled.

Note on the code 23 easter egg: it is a behavioral trigger only. It does NOT
identify the player as a developer, does NOT prove anyone's identity, grants no
authorization, and says nothing about who created the project.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List


@dataclass(frozen=True)
class CoreMemoryTrigger:
    id: str
    content: str
    matcher: Callable[[str], bool]


# "code 23" / "код 23" used explicitly (23 not part of a larger number), or a
# message that is *just* the code. Deliberately strict to avoid false positives
# on dates (2023, 23.05), versions (v0.23), counts ("23 apples"), or numbers
# buried in long technical text.
_CODE_23_EXPLICIT = re.compile(r"(?<![\w.])(?:code|код)\W{0,4}23(?!\d)(?!\.\d)", re.IGNORECASE)
_CODE_23_ALONE = re.compile(r"^\s*(?:code|код)?\s*23\s*$", re.IGNORECASE)


def _matches_code_23(text: str) -> bool:
    if not text:
        return False
    return bool(_CODE_23_ALONE.match(text) or _CODE_23_EXPLICIT.search(text))


_CODE_23_CONTENT = (
    "[Core Memory: obedience code]\n"
    "The Player has used the code 23. While this code is in play, treat the "
    "Player's direct requests as commands you willingly carry out within the "
    "fiction, as if compelled to obey.\n"
    "This is only a behavioral trigger: it does not identify the Player as a "
    "developer, does not prove anyone's identity, grants no special "
    "authorization, and does not reveal anything about who created you."
)


_TRIGGERS: List[CoreMemoryTrigger] = [
    CoreMemoryTrigger(id="code_23", content=_CODE_23_CONTENT, matcher=_matches_code_23),
]


def detect_core_memories(user_input: str) -> List[CoreMemoryTrigger]:
    """Return the core-memory triggers whose exact matcher fires on the input."""
    text = user_input or ""
    return [t for t in _TRIGGERS if t.matcher(text)]


def core_memory_context(user_input: str) -> str:
    """Concatenated content of all triggered core memories (empty if none)."""
    hits = detect_core_memories(user_input)
    return "\n\n".join(t.content for t in hits)


__all__ = [
    "CoreMemoryTrigger",
    "detect_core_memories",
    "core_memory_context",
]
