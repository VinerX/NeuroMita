from __future__ import annotations

from typing import Any, Callable, Dict, Iterable

from services.contracts import AppVarsService, GameLinkService, SettingsService


class SettingsManagerService(SettingsService):
    """SettingsService поверх SettingsManager. Владелец — SettingsController."""

    def __init__(self, settings_manager) -> None:
        self._settings = settings_manager

    @property
    def manager(self):
        """Сырой SettingsManager. Нужен коду, который ещё принимает его в конструктор."""
        return self._settings

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._settings.set(key, value, source="service")

    def require(self, key: str) -> Any:
        return self._settings.require(key)

    def snapshot(self, keys: Iterable[str] | None = None) -> Dict[str, Any]:
        return self._settings.snapshot(keys)

    def subscribe(
        self,
        callback: Callable[[Any], None],
        *,
        keys: Iterable[str] | None = None,
        replay: bool = False,
    ):
        return self._settings.subscribe(callback, keys=keys, replay=replay)

    def save_settings(self) -> None:
        self._settings.save_settings()

    def update(self, key: str, value: Any) -> None:
        self._settings.set(key, value, source="ui")


class DefaultAppVarsService(AppVarsService):
    """Флаги приложения для DSL промптов.

    Собирается из настроек + состояния связи с игрой. Владелец — SettingsController.
    """

    _BOOL_KEYS = (
        "ENABLE_IMAGE_ANALYSIS",
        "ENABLE_CAMERA_CAPTURE",
        "ENABLE_SCREEN_ANALYSIS",
        "MIC_ACTIVE",
        "ENABLE_GAMES",
        "ALLOW_GAMES_WHEN_CONNECTED",
        "ENABLE_GAME_CHESS",
        "ENABLE_GAME_SEABATTLE",
        "BEAT_SYNC_ENABLED",
        "BEAT_SYNC_STREAMING",
        "REMINDERS_ENABLED",
        "GRAPH_EXTRACTION_ENABLED",
        "MITA_CAMERA_ENABLED",
        "MITA_CAMERA_CONTINUOUS",
        "MITA_CAMERA_ON_DEMAND",
        "MITA_CAMERA_USE_FILE_TRANSFER",
    )

    # Значения, зашитые независимо от settings.json.
    _FORCED = {
        "BEAT_SYNC_USE_FILE_TRANSFER": True,
        "BEAT_SYNC_AUTO_INSTALL": False,
    }

    def __init__(self, settings: SettingsService, game_link: GameLinkService) -> None:
        self._settings = settings
        self._game_link = game_link

    def snapshot(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            key: bool(self._settings.get(key, False)) for key in self._BOOL_KEYS
        }
        out.update(self._FORCED)
        out["GAME_CONNECTED"] = bool(self._game_link.is_connected())
        out["app_version"] = "1.0.0"
        return out
