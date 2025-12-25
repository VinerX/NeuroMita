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
    actualInfo: str = ""

    def update_from_event_data(self, data: Dict[str, Any]) -> None:
        self.distance = float(data.get("distance", self.distance) or 0.0)
        self.roomPlayer = int(data.get("roomPlayer", self.roomPlayer) if data.get("roomPlayer", None) is not None else self.roomPlayer)
        self.roomMita = int(data.get("roomMita", self.roomMita) if data.get("roomMita", None) is not None else self.roomMita)
        self.nearObjects = str(data.get("nearObjects", self.nearObjects) or "")
        self.actualInfo = str(data.get("actualInfo", self.actualInfo) or "")

    def to_prompt_dict(self) -> Dict[str, Any]:
        return {
            "distance": float(self.distance),
            "roomPlayer": int(self.roomPlayer),
            "roomMita": int(self.roomMita),
            "nearObjects": str(self.nearObjects),
            "actualInfo": str(self.actualInfo),
        }