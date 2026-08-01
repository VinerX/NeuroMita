from __future__ import annotations

WORLD_CHARACTER_RELATIONS: dict[tuple[str, str], dict[str, object]] = {
    ("Crazy", "crazy_house"): {
        "relation": "home",
        "facts": ["This is your home.", "You hide personal things here."],
    },
    ("Kind", "crazy_house"): {
        "relation": "former_home",
        "facts": ["This house now belongs to Crazy.", "It belonged to you in the past."],
    },
    ("Crazy", "kind_house"): {
        "relation": "foreign_home",
        "facts": ["This is Kind's home.", "You suspect she hides something here."],
    },
}


def get_world_character_context(character_id: str, world_id: str) -> dict[str, object]:
    return WORLD_CHARACTER_RELATIONS.get(
        (str(character_id or "").strip(), str(world_id or "").strip()),
        {"relation": "visitor", "facts": []},
    )
