# src/managers/game_state.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


_ROOM_NAMES = {
    0: "Кухня",
    1: "Зал",
    2: "Комната",
    3: "Туалет",
    4: "Подвал",
}


def get_room_name(room_id: int) -> str:
    return _ROOM_NAMES.get(int(room_id), "?")


@dataclass
class GameState:
    distance: float = 0.0
    roomPlayer: int = -1
    roomMita: int = -1
    nearObjects: str = ""
    world_state: str = ""
    runtime_rules: str = ""
    runtime_static_catalog: str = ""
    runtime_capabilities: str = ""
    intent_rules: str = ""

    def update_from_event_data(self, data: Dict[str, Any]) -> None:
        self.distance = float(data.get("distance", self.distance) or 0.0)
        self.roomPlayer = int(data.get("roomPlayer", self.roomPlayer) if data.get("roomPlayer", None) is not None else self.roomPlayer)
        self.roomMita = int(data.get("roomMita", self.roomMita) if data.get("roomMita", None) is not None else self.roomMita)
        self.nearObjects = str(data.get("nearObjects", self.nearObjects) or "")
        self.world_state = str(data.get("world_state", self.world_state) or "")
        self.runtime_rules = str(data.get("runtime_rules", self.runtime_rules) or "")
        self.runtime_static_catalog = str(data.get("runtime_static_catalog", self.runtime_static_catalog) or "")
        self.runtime_capabilities = str(data.get("runtime_capabilities", self.runtime_capabilities) or "")
        self.intent_rules = str(data.get("intent_rules", self.intent_rules) or "")

    def to_prompt_dict(self) -> Dict[str, Any]:
        return {
            "distance": float(self.distance),
            "roomPlayer": int(self.roomPlayer),
            "roomMita": int(self.roomMita),
            "nearObjects": str(self.nearObjects),
            "world_state": str(self.world_state),
            "runtime_rules": str(self.runtime_rules),
            "runtime_static_catalog": str(self.runtime_static_catalog),
            "runtime_capabilities": str(self.runtime_capabilities),
            "intent_rules": str(self.intent_rules),
        }