from core.error_utils import format_exception
# seabattle_instance.py

import re
import multiprocessing
import queue
import threading
from typing import Dict, Any, Optional

from core.events import Events
from core.request_policy import resolve_policy
from core.services import use
from main_logger import logger
from modules.game_interface import GameInterface
from services.contracts import SettingsService

class SeaBattleGame(GameInterface):

    def __init__(self, character, game_id: str = "seabattle"):
        super().__init__(character, game_id)
        self.gui_process: Optional[multiprocessing.Process] = None
        self.command_queue: Optional[multiprocessing.Queue] = None
        self.state_queue: Optional[multiprocessing.Queue] = None
        self.reaction_queue: Optional[multiprocessing.Queue] = None
        self._reaction_listener: Optional[threading.Thread] = None
        self._reaction_stop_event = threading.Event()

    def start(self, params: Dict[str, Any]):
        if self.gui_process and self.gui_process.is_alive():
            logger.warning(f"[{self.character.char_id}] Процесс 'Морского боя' уже запущен. Останавливаем.")
            self.stop({})

        try:
            from modules.SeaBattle.seabattle_gui import run_seabattle_gui_process

            self.character.set_variable("playingGame", True)
            self.character.set_variable("game_id", self.game_id)

            self.command_queue = multiprocessing.Queue()
            self.state_queue = multiprocessing.Queue()
            self.reaction_queue = multiprocessing.Queue()
            self._reaction_stop_event.clear()

            logger.info(f"[{self.character.char_id}] Запуск GUI для 'Морского боя'.")

            self.gui_process = multiprocessing.Process(
                target=run_seabattle_gui_process,
                args=(self.command_queue, self.state_queue, self.reaction_queue),
                daemon=True
            )
            self.gui_process.start()
            self._reaction_listener = threading.Thread(
                target=self._listen_for_player_target_reactions,
                name=f"SeaBattleReaction-{self.character.char_id}",
                daemon=True,
            )
            self._reaction_listener.start()
        except ImportError as e:
            logger.error(f"[{self.character.char_id}] Не удалось импортировать модуль 'Морского боя': {format_exception(e)}", exc_info=True)
            self.cleanup()
        except Exception as e:
            logger.error(f"[{self.character.char_id}] Ошибка при запуске игры 'Морской бой': {format_exception(e)}", exc_info=True)
            self.cleanup()

    def _send_command(self, command_data: Dict[str, Any]):
        if self.character.get_variable("playingGame") and self.command_queue and self.gui_process and self.gui_process.is_alive():
            try:
                self.command_queue.put(command_data)
                logger.debug(f"[{self.character.char_id}] Отправлена команда в 'Морской бой': {command_data}")
            except Exception as e:
                logger.error(f"[{self.character.char_id}] Ошибка при отправке команды в очередь: {format_exception(e)}")
        else:
            logger.warning(f"[{self.character.char_id}] Невозможно отправить команду: игра неактивна.")

    def stop(self, params: Dict[str, Any]):
        logger.info(f"[{self.character.char_id}] Остановка игры 'Морской бой'.")
        self._send_command({"action": "stop_gui_process"})

        if self.gui_process and self.gui_process.is_alive():
            self.gui_process.join(timeout=5)
            if self.gui_process.is_alive():
                logger.warning(f"[{self.character.char_id}] Процесс GUI 'Морского боя' не завершился, принудительное завершение.")
                self.gui_process.terminate()
        
        self.cleanup()

    def cleanup(self):
        logger.debug(f"[{self.character.char_id}] Очистка ресурсов 'Морского боя'.")
        self._reaction_stop_event.set()
        listener = self._reaction_listener
        if listener and listener.is_alive() and listener is not threading.current_thread():
            listener.join(timeout=1)

        self.character.set_variable("playingGame", False)
        self.character.set_variable("game_id", None)

        try:
            gm = getattr(self.character, "game_manager", None)
            if gm and getattr(gm, "active_game", None) is self:
                gm.active_game = None
        except Exception:
            pass

        if self.command_queue:
            self.command_queue.close()
        if self.state_queue:
            self.state_queue.close()
        if self.reaction_queue:
            self.reaction_queue.close()

        self.gui_process = None
        self.command_queue = None
        self.state_queue = None
        self.reaction_queue = None
        self._reaction_listener = None

    def _listen_for_player_target_reactions(self):
        """Forward explicit player shots from the GUI to the normal L2 react path."""
        while not self._reaction_stop_event.is_set():
            reaction_queue = self.reaction_queue
            if reaction_queue is None:
                return
            try:
                event = reaction_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                return
            except Exception as exc:
                logger.debug(
                    f"[{self.character.char_id}] Ошибка очереди реакций Морского боя: "
                    f"{format_exception(exc)}"
                )
                continue

            if not isinstance(event, dict) or event.get("event") != "player_target_selected":
                continue
            self._dispatch_player_target_reaction(event)

    def _dispatch_player_target_reaction(self, event: Dict[str, Any]):
        """Request a visible Mita reaction after a valid player shot.

        This mirrors the existing L2 ``react`` policy, so the global reactions
        switches remain the source of truth.  The game-level checkbox only
        decides whether the GUI sends this event for the current match.
        """
        try:
            settings = use(SettingsService)
            if not bool(settings.get("REACT_ENABLED", True)):
                return
            if not bool(settings.get("REACT_L2_ENABLED", True)):
                return
        except Exception as exc:
            logger.debug(
                f"[{self.character.char_id}] Не удалось проверить настройки реакций: "
                f"{format_exception(exc)}"
            )
            return

        if not self.character.get_variable("playingGame", False):
            return

        coord = str(event.get("coord") or "неизвестную клетку")
        result = str(event.get("message") or event.get("result") or "сделал ход")
        system_input = (
            "[Sea Battle] The player fired at "
            f"{coord}. Result: {result}. "
            "React briefly and naturally in character to this move. "
            "Do not take a Sea Battle turn yourself in this reply."
        )
        policy = resolve_policy(model_event_type="react", react_level=2)
        self.character.event_bus.emit(
            Events.Chat.SEND_MESSAGE,
            {
                "user_input": "",
                "system_input": system_input,
                "event_type": "react",
                "character_id": self.character.char_id,
                "sender": "Player",
                "participants": [],
                "policy": policy.to_dict(),
            },
        )

    def process_llm_tags(self, response: str) -> str:
        
        place_ship_match = re.search(r"<PlaceShip>(.*?)</PlaceShip>", response, re.IGNORECASE)
        if place_ship_match:
            spec = place_ship_match.group(1).strip()
            self._send_command({"action": "mita_place_ship", "spec": spec})
            logger.info(f"[{self.character.char_id}] LLM размещает корабль: {spec}.")
            response = response.replace(place_ship_match.group(0), "", 1).strip()

        if "<PlaceShipsRandomly/>" in response:
            self._send_command({"action": "mita_place_randomly"})
            logger.info(f"[{self.character.char_id}] LLM запросил случайную расстановку своих кораблей.")
            response = response.replace("<PlaceShipsRandomly/>", "", 1).strip()

        make_move_match = re.search(r"<MakeMove>([A-J][1-9]|A10|B10|C10|D10|E10|F10|G10|H10|I10|J10)</MakeMove>", response, re.IGNORECASE)
        if make_move_match:
            coord = make_move_match.group(1).strip().upper()
            self._send_command({"action": "mita_move", "coord": coord})
            logger.info(f"[{self.character.char_id}] LLM делает ход: {coord}.")
            response = response.replace(make_move_match.group(0), "", 1).strip()
            
        return response

    def process_structured_commands(self, commands: list):
        """Translate the commands advertised by the Sea Battle prompt to GUI actions."""
        for command in commands:
            if not isinstance(command, str):
                continue
            command = command.strip()
            if not command:
                continue

            if command == "PlaceShipsRandomly":
                self._send_command({"action": "mita_place_randomly"})
                continue

            place_match = re.fullmatch(
                r"PlaceShip\s*,\s*([A-J](?:10|[1-9]))\s*,\s*([1-4])\s*,\s*([HV])",
                command,
                re.IGNORECASE,
            )
            if place_match:
                coord, length, orientation = place_match.groups()
                self._send_command(
                    {
                        "action": "mita_place_ship",
                        "spec": f"{coord.upper()},{length},{orientation.upper()}",
                    }
                )
                continue

            move_match = re.fullmatch(
                r"MakeMove\s*,\s*([A-J](?:10|[1-9]))", command, re.IGNORECASE
            )
            if move_match:
                self._send_command(
                    {"action": "mita_move", "coord": move_match.group(1).upper()}
                )
                continue

            logger.warning(
                f"[{self.character.char_id}] Structured: неизвестная команда Морского боя: {command!r}"
            )

    def get_state_prompt(self) -> Optional[str]:
        if self.gui_process and not self.gui_process.is_alive():
            self.cleanup()
            return "Игра 'Морской бой' была закрыта (окно закрыто). Считай игру завершённой."

        if not self.state_queue:
            return None

        latest_state: Optional[Dict[str, Any]] = None
        while not self.state_queue.empty():
            try:
                latest_state = self.state_queue.get_nowait()
            except Exception:
                break

        if latest_state and isinstance(latest_state, dict):
            ev = str(latest_state.get("event") or "").strip().lower()
            if ev == "gui_closed" or latest_state.get("gui_closed") is True:
                self.cleanup()
                return "Игра 'Морской бой' была закрыта (окно закрыто). Считай игру завершённой."

            if latest_state.get("critical_process_failure") is True:
                self.cleanup()
                return "Игра 'Морской бой' завершилась из-за ошибки процесса. Считай игру завершённой."

        if not latest_state:
            self._send_command({"action": "get_state"})
            return "Игра 'Морской бой' активна. Ожидание данных от игрового модуля..."

        mita_id = latest_state.get('mita_id')

        self.character.set_variable("GAME_STATE_PHASE", latest_state.get('phase'))
        self.character.set_variable("GAME_STATE_IS_LLM_TURN", not latest_state.get('is_player_turn'))
        self.character.set_variable("GAME_STATE_IS_GAME_OVER", latest_state.get('phase') == 'game_over')

        winner_id = latest_state.get('winner')
        outcome = "Игра продолжается"
        if winner_id is not None:
            outcome = "Ты победил!" if winner_id == mita_id else "Ты проиграл."
        self.character.set_variable("GAME_STATE_OUTCOME", outcome)

        self.character.set_variable("GAME_STATE_MY_BOARD", latest_state.get('mita_my_board_str', 'Ошибка загрузки доски'))
        self.character.set_variable("GAME_STATE_OPPONENT_BOARD", latest_state.get('mita_opponent_view_str', 'Ошибка загрузки доски'))

        ships_to_place = latest_state.get('mita_ships_to_place', [])
        self.character.set_variable("GAME_STATE_SHIPS_TO_PLACE_LIST", ", ".join(map(str, ships_to_place)))
        self.character.set_variable("GAME_STATE_HAS_SHIPS_TO_PLACE", bool(ships_to_place))

        last_move = latest_state.get('last_move')
        if last_move:
            self.character.set_variable("GAME_STATE_IS_LLM_LAST_MOVER", last_move['attacker'] == mita_id)
            self.character.set_variable("GAME_STATE_LAST_MOVE_COORD", last_move.get('coord_alg'))
            self.character.set_variable("GAME_STATE_LAST_MOVE_RESULT", last_move.get('result'))
        else:
            self.character.set_variable("GAME_STATE_IS_LLM_LAST_MOVER", False)
            self.character.set_variable("GAME_STATE_LAST_MOVE_COORD", None)
            self.character.set_variable("GAME_STATE_LAST_MOVE_RESULT", None)

        hunt_info = latest_state.get('hunt_info', {})
        self.character.set_variable("GAME_STATE_HAS_WOUNDED_SHIPS", bool(hunt_info))
        self.character.set_variable("GAME_STATE_WOUNDED_SHIPS_INFO", hunt_info.get('wounded_info_str', ''))
        self.character.set_variable("GAME_STATE_HUNT_TARGETS_LIST", ", ".join(hunt_info.get('hunt_targets', [])))
        self.character.set_variable("GAME_STATE_SHOT_HISTORY_STRING", latest_state.get('shot_history_str', ''))
        self.character.set_variable("GAME_STATE_ERROR_MSG", latest_state.get('error'))

        template_filename = f"{self.game_id}.system"
        try:
            content, _ = self.character.dsl_interpreter.process_file(template_filename)
            return content
        except FileNotFoundError:
            logger.error(f"[{self.character.char_id}] Скрипт для игры '{self.game_id}' не найден: {template_filename}")
            return f"ОШИБКА: Не найден системный скрипт для игры '{self.game_id}'."
        except Exception as e:
            logger.error(f"[{self.character.char_id}] Ошибка исполнения DSL-скрипта '{template_filename}': {format_exception(e)}", exc_info=True)
            return f"ОШИБКА: Ошибка при генерации промпта для игры '{self.game_id}'."
