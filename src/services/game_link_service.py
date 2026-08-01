from __future__ import annotations

import threading
from typing import Callable, Optional

from services.contracts import GameLinkService


class ServerGameLinkService(GameLinkService):
    """Состояние TCP-связи с модом.

    Создаётся композиционным корнем (MainController) до ServerController,
    потому что от него зависит AppVarsService. ServerController затем
    подключает probe к живым соединениям и обновляет флаг.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connected = False
        self._probe: Optional[Callable[[], Optional[bool]]] = None
        self._owner_probe: Optional[Callable[[], str]] = None

    def attach_probe(self, probe: Callable[[], Optional[bool]]) -> None:
        """probe() -> True/False по живым соединениям, либо None если неизвестно."""
        with self._lock:
            self._probe = probe

    def attach_owner_probe(self, probe: Callable[[], str]) -> None:
        """probe() -> client_id активной игровой сессии ("" — таковой нет)."""
        with self._lock:
            self._owner_probe = probe

    def player_turn_owner(self) -> str:
        with self._lock:
            probe = self._owner_probe
        if probe is None:
            return ""
        try:
            return str(probe() or "")
        except Exception:
            return ""

    def set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = bool(connected)

    def is_connected(self) -> bool:
        with self._lock:
            probe = self._probe
            fallback = self._connected
        if probe is not None:
            probed = probe()
            if probed is not None:
                return bool(probed)
        return fallback


class DisconnectedGameLinkService(GameLinkService):
    """GUI-only режим: сервер игры не поднимается."""

    def is_connected(self) -> bool:
        return False
