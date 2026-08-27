from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any, Mapping


_WORLD_ID_KEY_RE = re.compile(r"[^a-z0-9]+")

_WORLD_ID_ALIASES = {
    "crazyhouse": "CrazyHouse",
    "kindhouse": "KindHouse",
    "cappiehouse": "CappieHouse",
    "milahouse": "MilaHouse",
    "sleepyhouse": "SleepyHouse",
    "creepyhouse": "CreepyHouse",
    "ghosthouse": "GhostHouse",
}

_CHARACTER_ID_ALIASES = {
    "crazy": "Crazy",
    "crazymita": "Crazy",
    "crazy_mita": "Crazy",
    "kind": "Kind",
    "kindmita": "Kind",
    "kind_mita": "Kind",
    "cappie": "Cappie",
    "cappy": "Cappie",
    "shorthair": "ShortHair",
    "short_hair": "ShortHair",
    "short_hair_mita": "ShortHair",
    "mila": "Mila",
    "sleepy": "Sleepy",
    "sleepy_mita": "Sleepy",
    "creepy": "Creepy",
    "creepy_mita": "Creepy",
    "ghost": "Ghost",
    "ghost_mita": "Ghost",
}

# Stable runtime character IDs. Unknown IDs are still accepted and receive a
# world's visitor context, which keeps custom characters safe by default.
KNOWN_CHARACTER_IDS = (
    "Crazy", "Kind", "Cappie", "ShortHair", "Mila", "Sleepy", "Creepy", "Ghost",
)


def _compact_key(value: Any) -> str:
    return _WORLD_ID_KEY_RE.sub("", str(value or "").strip().lower())


def normalize_world_id(world_id: Any) -> str:
    """Normalize Unity's ``CrazyHouse`` and legacy ``crazy_house`` forms."""
    raw = str(world_id or "").strip()
    if not raw:
        return ""
    return _WORLD_ID_ALIASES.get(_compact_key(raw), raw)


def normalize_character_id(character_id: Any) -> str:
    """Normalize known IDs while preserving the stable runtime spelling."""
    raw = str(character_id or "").strip()
    if not raw:
        return ""
    alias = _CHARACTER_ID_ALIASES.get(_compact_key(raw))
    if alias:
        return alias
    for known_id in KNOWN_CHARACTER_IDS:
        if known_id.casefold() == raw.casefold():
            return known_id
    return raw



@dataclass(frozen=True)
class WorldContext:
    world_id: str
    display_name: str
    owner: str
    former_owners: tuple[str, ...]
    default_context: str
    character_contexts: Mapping[str, str]
    character_relations: Mapping[str, str]


class WorldContextResolver:
    """Resolve lore for one character without mutating global game state."""

    def __init__(self, worlds: Mapping[str, Mapping[str, Any]] | None = None):
        raw_worlds = worlds if worlds is not None else load_world_contexts()
        self._worlds = {
            normalize_world_id(world_id): self._parse_world(
                normalize_world_id(world_id), payload
            )
            for world_id, payload in raw_worlds.items()
            if normalize_world_id(world_id)
        }

    @staticmethod
    def _parse_world(world_id: str, payload: Mapping[str, Any]) -> WorldContext:
        raw_contexts = payload.get("character_contexts", {})
        if not isinstance(raw_contexts, Mapping):
            raw_contexts = {}
        character_contexts = {
            normalize_character_id(character_id): str(text or "").strip()
            for character_id, text in raw_contexts.items()
            if str(text or "").strip()
        }
        raw_relations = payload.get("character_relations", {})
        if not isinstance(raw_relations, Mapping):
            raw_relations = {}
        character_relations = {
            normalize_character_id(character_id): str(relation or "").strip()
            for character_id, relation in raw_relations.items()
            if str(relation or "").strip()
        }
        raw_former_owners = payload.get("former_owners", ()) or ()
        former_owners = tuple(
            normalize_character_id(character_id)
            for character_id in raw_former_owners
            if normalize_character_id(character_id)
        )
        owner = normalize_character_id(
            payload.get("owner", payload.get("current_owner", ""))
        )
        display_name = str(payload.get("display_name", "") or "").strip()
        default_context = str(payload.get("default_context", "") or "").strip()
        if not display_name:
            raise ValueError(f"World context {world_id!r} has no display_name")
        if not default_context:
            raise ValueError(f"World context {world_id!r} has no default_context")
        return WorldContext(
            world_id=world_id,
            display_name=display_name,
            owner=owner,
            former_owners=former_owners,
            default_context=default_context,
            character_contexts=character_contexts,
            character_relations=character_relations,
        )

    def get(self, world_id: Any) -> WorldContext | None:
        normalized = normalize_world_id(world_id)
        direct = self._worlds.get(normalized)
        if direct is not None:
            return direct

        # Custom worlds may use a CamelCase ID in configuration while a client
        # sends the same ID as snake_case. Known Unity worlds use the explicit
        # aliases above; this compact fallback keeps custom worlds compatible.
        compact = _compact_key(normalized)
        for configured_id, world in self._worlds.items():
            if _compact_key(configured_id) == compact:
                return world
        return None

    def resolve_details(self, world_id: Any, character_id: Any) -> dict[str, object]:
        world = self.get(world_id)
        character = normalize_character_id(character_id)
        if world is None:
            return {"relation": "visitor", "facts": []}

        exact = world.character_contexts.get(character, "")
        if exact:
            relation = (
                world.character_relations.get(character)
                or (
                    "home" if character == world.owner else
                    "former_home" if character in world.former_owners else "custom"
                )
            )
            return {"relation": relation, "facts": [exact]}
        if character == world.owner:
            return {"relation": "home", "facts": [f"This is your home — {world.display_name}."]}
        if character in world.former_owners:
            return {
                "relation": "former_home",
                "facts": [
                    f"This house now belongs to its current owner: {world.display_name}.",
                    "It belonged to you in the past.",
                ],
            }
        return {"relation": "visitor", "facts": [world.default_context]}

    def resolve(self, world_id: Any, character_id: Any) -> str:
        """Return prompt text, or empty for an unknown/absent world."""
        world = self.get(world_id)
        if world is None:
            return ""
        character = normalize_character_id(character_id)
        exact = world.character_contexts.get(character, "")
        if exact:
            return exact
        if character == world.owner:
            return f"You are in your own home: {world.display_name}."
        if character in world.former_owners:
            return (
                f"This is {world.display_name}. It used to belong to you, "
                "although it belongs to someone else now."
            )
        return world.default_context


def load_world_contexts() -> dict[str, dict[str, Any]]:
    """Load UTF-8 JSON resources in source and ``NeuroMita.pyz`` builds."""
    root = resources.files("domain").joinpath("world_contexts")
    result: dict[str, dict[str, Any]] = {}
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".json"):
            continue
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"World context {resource.name!r} must contain an object")
        world_id = str(payload.get("world_id", "") or "").strip()
        if not world_id:
            raise ValueError(f"World context {resource.name!r} has no world_id")
        result[world_id] = payload
    return result


_DEFAULT_RESOLVER = WorldContextResolver()


def get_world_character_context(character_id: str, world_id: str) -> dict[str, object]:
    """Compatibility API used by the multi-Mita conversation prompt."""
    return _DEFAULT_RESOLVER.resolve_details(
        character_id=character_id,
        world_id=world_id,
    )


def get_world_context_text(character_id: str, world_id: str) -> str:
    """Resolve character-specific context for one generation request."""
    return _DEFAULT_RESOLVER.resolve(
        world_id=world_id,
        character_id=character_id,
    )
