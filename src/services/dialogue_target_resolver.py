"""Safe normalization for participant references produced by language models."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable


_TARGET_SEPARATORS_RE = re.compile(r"[\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class DialogueTargetCandidate:
    """A participant identity with the display value used in Mita replies."""

    actor_id: str = ""
    character_id: str = ""
    display_name: str = ""
    is_active: bool = True
    can_speak: bool = True

    @property
    def canonical_display_name(self) -> str:
        return self.display_name or self.character_id or self.actor_id


def _value(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _text(value: Any) -> str:
    return str(value or "").strip()


def target_keys(value: Any) -> tuple[str, ...]:
    """Return conservative aliases without fuzzy matching."""
    raw = unicodedata.normalize("NFKC", _text(value)).casefold()
    if not raw:
        return ()
    spaced = _TARGET_SEPARATORS_RE.sub(" ", raw).strip()
    compact = spaced.replace(" ", "")
    return tuple(dict.fromkeys(key for key in (raw, spaced, compact) if key))


def dialogue_target_candidates(participants: Iterable[Any] | None) -> tuple[DialogueTargetCandidate, ...]:
    """Project raw participant values into resolver candidates."""
    candidates: list[DialogueTargetCandidate] = []
    for item in participants or ():
        if isinstance(item, str):
            name = _text(item)
            if name:
                candidates.append(
                    DialogueTargetCandidate(character_id=name, display_name=name)
                )
            continue

        actor_id = _text(_value(item, "actor_id", ""))
        character_id = _text(_value(item, "character_id", ""))
        display_name = _text(
            _value(item, "display_name", _value(item, "name", ""))
        )
        if actor_id or character_id or display_name:
            candidates.append(
                DialogueTargetCandidate(
                    actor_id=actor_id,
                    character_id=character_id,
                    display_name=display_name,
                    is_active=bool(_value(item, "is_active", True)),
                    can_speak=bool(_value(item, "can_speak", True)),
                )
            )
    return tuple(candidates)


def resolve_dialogue_target(
    value: Any,
    candidates: Iterable[DialogueTargetCandidate],
) -> DialogueTargetCandidate | None:
    """Resolve a target only when its normalized aliases identify one participant."""
    aliases: dict[str, dict[tuple[str, str, str], DialogueTargetCandidate]] = {}
    for candidate in candidates:
        identity = (
            candidate.actor_id.casefold(),
            candidate.character_id.casefold(),
            candidate.canonical_display_name.casefold(),
        )
        for alias in (
            candidate.actor_id,
            candidate.character_id,
            candidate.canonical_display_name,
        ):
            for key in target_keys(alias):
                aliases.setdefault(key, {})[identity] = candidate

    for key in target_keys(value):
        resolved = aliases.get(key, {})
        if len(resolved) == 1:
            return next(iter(resolved.values()))
    return None
