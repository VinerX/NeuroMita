from typing import Dict, Any, Optional, Type
from main_logger import logger
from modules.available_games import get_available_games
from modules.game_interface import GameInterface
from core.chat_api import ChatAPI
from core.services import use
from services.contracts import GameLinkService, SettingsService
from managers.mini_game_session_registry import mini_game_sessions


class GameManager:
    """Управляет жизненным циклом и взаимодействием с экземплярами игр."""
    def __init__(self, character):
        self.character = character
        self.active_game: Optional[GameInterface] = None
        self.available_games: Dict[str, Type[GameInterface]] = get_available_games()

    def _parse_id_string(self, id_str: str) -> tuple[str, Dict[str, Any]]:
        parts = id_str.split('/')
        game_name = parts[0].lower()
        params = {}
        if len(parts) > 1:
            remaining = parts[1:]
            if game_name == "chess":
                elo_map = {"easy": 1100, "medium": 1500, "hard": 1900}
                for part in remaining:
                    part = part.lower()
                    if part in elo_map:
                        params["difficulty"] = part
                    elif part == "auto":
                        params["is_auto"] = True
                    elif part == "cheat":
                        params["is_cheat"] = True
                    elif part == "resign":
                        params["resign"] = True
                    elif part == "white":
                        params["player_is_white"] = True
                    elif part == "black":
                        params["player_is_white"] = False
            elif game_name == "seabattle":
                for part in remaining:
                    part = part.lower()
                    if part == "resign":
                        params["resign"] = True
        return game_name, params

    def _setting_bool(self, key: str, default: bool = False) -> bool:
        av = getattr(self.character, "app_vars", None)
        if isinstance(av, dict) and key in av:
            return bool(av.get(key))

        if key == "GAME_CONNECTED":
            return bool(use(GameLinkService).is_connected())

        return bool(use(SettingsService).get(key, default))

    def _is_game_launch_allowed(self, game_name: str) -> bool:
        if not self._setting_bool("ENABLE_GAMES", False):
            return False

        game_connected = self._setting_bool("GAME_CONNECTED", False)
        allow_when_connected = self._setting_bool("ALLOW_GAMES_WHEN_CONNECTED", False)
        if game_connected and not allow_when_connected:
            return False

        per_game_key = f"ENABLE_GAME_{game_name.upper()}"
        if not self._setting_bool(per_game_key, False):
            return False

        return True

    def start_game(self, full_id_str: str) -> bool:
        if self.active_game:
            logger.warning(f"[{self.character.char_id}] Игра уже активна. Остановка перед запуском новой.")
            self.active_game.stop(params={})
            self.active_game = None

        game_name, params = self._parse_id_string(full_id_str)

        game_class = self.available_games.get(game_name)
        if not game_class:
            logger.error(f"[{self.character.char_id}] Запрошена неизвестная игра: '{game_name}'")
            return False

        if not self._is_game_launch_allowed(game_name):
            logger.info(f"[{self.character.char_id}] Запуск игры '{game_name}' заблокирован настройками.")
            return False

        logger.info(f"[{self.character.char_id}] Запуск игры '{game_name}' с параметрами: {params}")
        game = game_class(self.character, game_name, host=self)
        self.active_game = game
        game.start(params)
        if self.active_game is not game:
            mini_game_sessions().stop(self.character.char_id, game_name)
            return False
        get_variable = getattr(self.character, "get_variable", None)
        if callable(get_variable) and not get_variable("playingGame", False):
            mini_game_sessions().stop(self.character.char_id, game_name)
            if self.active_game is game:
                self.active_game = None
            return False
        mini_game_sessions().start(
            owner_character_id=self.character.char_id,
            owner_name=str(
                getattr(self.character, "display_name", "")
                or getattr(self.character, "name", "")
                or self.character.char_id
            ),
            game_id=game_name,
        )
        return True

    def start_game_from_player(self, full_id_str: str) -> bool:
        """Start a game from the desktop UI and optionally invite a Mita reaction.

        A manual click is a player action, rather than an instruction emitted by
        the model.  The game still goes through ``start_game`` so every normal
        availability rule remains in force.
        """
        game_name, _params = self._parse_id_string(full_id_str)
        started = self.start_game(full_id_str)
        if started:
            self._request_manual_start_reaction(game_name)
        return started

    def _request_manual_start_reaction(self, game_name: str) -> None:
        """Request a visible reaction to a desktop-started mini-game."""
        try:
            if bool(use(SettingsService).get("IGNORE_GAME_REQUESTS", False)):
                return
        except Exception as exc:
            logger.debug(
                f"[{self.character.char_id}] Не удалось проверить настройки запуска игры: {exc}"
            )
            return

        game_labels = {
            "chess": "chess",
            "seabattle": "Sea Battle",
        }
        game_label = game_labels.get(game_name, game_name or "a mini-game")
        ChatAPI.react(
            character_id=self.character.char_id,
            instruction=(
                "[Desktop mini-game] The player manually started "
                f"{game_label} with you. The game window is already open. "
                "React briefly and naturally in character to the invitation. "
                "Do not start or end a game in this reply."
            ),
            visible=True,
            sender="Player",
        )

    def request_character_reaction(
        self,
        game: GameInterface,
        instruction: str,
        *,
        visible: bool = True,
    ) -> bool:
        """Application boundary used by a concrete mini-game to request chat activity."""
        if self.active_game is not game:
            logger.debug(
                f"[{self.character.char_id}] Игнорируется реакция от неактивной игры "
                f"'{getattr(game, 'game_id', 'unknown')}'."
            )
            return False
        return ChatAPI.react(
            character_id=self.character.char_id,
            instruction=str(instruction or ""),
            visible=visible,
            sender="Player",
        )

    def stop_game(self, full_id_str: str):
        game_name, params = self._parse_id_string(full_id_str)

        if not self.active_game:
            logger.warning(f"[{self.character.char_id}] Получена команда остановки для '{game_name}', но нет активной игры.")
            return

        if self.active_game.game_id != game_name:
            logger.warning(
                f"[{self.character.char_id}] Получена команда остановки для '{game_name}', но активна игра '{self.active_game.game_id}'. Все равно останавливаем."
            )

        logger.info(f"[{self.character.char_id}] Остановка игры '{self.active_game.game_id}' с параметрами: {params}")
        self.active_game.stop(params)
        self.active_game = None

    def process_active_game_tags(self, response: str) -> str:
        if self.active_game:
            return self.active_game.process_llm_tags(response)
        return response

    def process_active_game_structured_commands(self, commands: list):
        if self.active_game:
            self.active_game.process_structured_commands(commands)

    def get_active_game_state_prompt(self) -> Optional[str]:
        if self.active_game:
            return self.active_game.get_state_prompt()
        return None
