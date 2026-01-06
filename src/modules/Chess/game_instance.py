
import re
import threading
import multiprocessing
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type
from main_logger import logger
from modules.game_interface import GameInterface

class ChessGame(GameInterface):
    """Реализация игры в шахматы."""

    def __init__(self, character, game_id: str):
        super().__init__(character, game_id)
        self.gui_thread: Optional[threading.Thread] = None
        self.command_queue: Optional[multiprocessing.Queue] = None
        self.state_queue: Optional[multiprocessing.Queue] = None
        self.current_elo: Optional[int] = None
        self.elo_mapping: Dict[str, int] = {"easy": 1100, "medium": 1500, "hard": 1900}

    def start(self, params: Dict[str, Any]):
        if self.gui_thread and self.gui_thread.is_alive():
            logger.warning(f"[{self.character.char_id}] Поток шахматной игры уже запущен. Сначала останавливаем его.")
            self.stop({})

        try:
            from modules.Chess.chess_board import run_chess_gui_process

            difficulty = params.get("difficulty", "medium")
            self.current_elo = self.elo_mapping.get(difficulty, self.elo_mapping["medium"])
            player_is_white = params.get("player_is_white", True)

            self.character.set_variable("playingGame", True)
            self.character.set_variable("game_id", self.game_id)

            self.command_queue = multiprocessing.Queue()
            self.state_queue = multiprocessing.Queue()

            logger.info(f"[{self.character.char_id}] Запуск шахматного GUI. ELO: {self.current_elo}")

            self.gui_thread = multiprocessing.Process(
                target=run_chess_gui_process,
                args=(self.command_queue, self.state_queue, self.current_elo, player_is_white),
                daemon=True
            )
            self.gui_thread.start()
        except ImportError as e:
            logger.error(f"[{self.character.char_id}] Не удалось импортировать шахматный модуль: {e}", exc_info=True)
            self.cleanup()
        except Exception as e:
            logger.error(f"[{self.character.char_id}] Ошибка при запуске шахматной игры: {e}", exc_info=True)
            self.cleanup()

    def _send_command(self, command_data: Dict[str, Any]):
        if self.character.get_variable("playingGame") and self.command_queue and self.gui_thread and self.gui_thread.is_alive():
            try:
                self.command_queue.put(command_data)
                logger.debug(f"[{self.character.char_id}] Отправлена команда в поток шахмат: {command_data}")
            except Exception as e:
                logger.error(f"[{self.character.char_id}] Ошибка при отправке команды в очередь шахмат: {e}")
        else:
            logger.warning(f"[{self.character.char_id}] Невозможно отправить команду в шахматы: игра неактивна или очередь/поток недоступны.")

    def stop(self, params: Dict[str, Any]):
        resign = params.get("resign", False)
        logger.info(f"[{self.character.char_id}] Остановка шахматной игры (сдача={resign}).")
        
        command = {"action": "resign"} if resign else {"action": "stop_gui_process"}
        self._send_command(command)

        if self.gui_thread and self.gui_thread.is_alive():
            self.gui_thread.join(timeout=10)
            if self.gui_thread.is_alive():
                logger.warning(f"[{self.character.char_id}] Поток шахматного GUI не завершился корректно.")
        
        self.cleanup()

    def cleanup(self):
        logger.debug(f"[{self.character.char_id}] Очистка ресурсов шахмат.")
        self.character.set_variable("playingGame", False)
        self.character.set_variable("game_id", None)

        try:
            gm = getattr(self.character, "game_manager", None)
            if gm and getattr(gm, "active_game", None) is self:
                gm.active_game = None
        except Exception:
            pass

        self.gui_thread = None
        self.command_queue = None
        self.state_queue = None
        self.current_elo = None


    def process_llm_tags(self, response: str) -> str:
        # Обработка старых тегов для обратной совместимости, пока игра активна
        change_diff_match = re.search(r"<ChangeChessDifficulty>(.*?)</ChangeChessDifficulty>", response, re.DOTALL)
        if change_diff_match:
            difficulty_str = change_diff_match.group(1).strip().lower()
            new_elo = self.elo_mapping.get(difficulty_str)
            if new_elo:
                self.current_elo = new_elo
                self._send_command({"action": "change_elo", "elo": new_elo})
                logger.info(f"[{self.character.char_id}] Запрошено изменение сложности шахмат на '{difficulty_str}' (ELO: {new_elo}).")
            response = response.replace(change_diff_match.group(0), "", 1).strip()

        if "<RequestBestChessMove!>" in response:
            self._send_command({"action": "engine_move"})
            logger.info(f"[{self.character.char_id}] Запрошен лучший ход от движка Maia.")
            response = response.replace("<RequestBestChessMove!>", "", 1).strip()

        llm_move_match = re.search(r"<MakeChessMoveAsLLM>(.*?)</MakeChessMoveAsLLM>", response, re.DOTALL)
        if llm_move_match:
            uci_move = llm_move_match.group(1).strip().lower()
            if uci_move:
                self._send_command({"action": "force_engine_move", "move": uci_move})
                logger.info(f"[{self.character.char_id}] LLM указал шахматный ход: {uci_move}.")
            response = response.replace(llm_move_match.group(0), "", 1).strip()
            
        return response
    
    def get_state_prompt(self) -> Optional[str]:
        if self.gui_thread and not self.gui_thread.is_alive():
            self.cleanup()
            return "Шахматная игра была закрыта (окно закрыто). Считай игру завершённой."

        if not self.state_queue:
            return None

        latest_state_data: Optional[Dict[str, Any]] = None
        while not self.state_queue.empty():
            try:
                latest_state_data = self.state_queue.get_nowait()
            except Exception:
                break

        if latest_state_data and isinstance(latest_state_data, dict):
            ev = str(latest_state_data.get("event") or "").strip().lower()
            if ev == "gui_closed" or latest_state_data.get("gui_closed") is True:
                self.cleanup()
                return "Шахматная игра была закрыта (окно закрыто). Считай игру завершённой."

            if latest_state_data.get("critical_process_failure") is True:
                self.cleanup()
                return "Шахматная игра завершилась из-за ошибки процесса. Считай игру завершённой."

            if latest_state_data.get("game_resigned_by_llm") or latest_state_data.get("game_stopped_by_llm"):
                self.cleanup()
                return "Шахматная игра завершена. Считай игру завершённой."

        if not latest_state_data:
            self._send_command({"action": "get_state"})
            return "Шахматная игра активна, но нет данных от модуля. Запрашиваю текущее состояние."

        player_gui_is_white = latest_state_data.get('player_is_white_in_gui', True)
        current_board_turn = latest_state_data.get('turn', 'N/A')
        llm_actual_color = 'white' if not player_gui_is_white else 'black'
        is_llm_turn_now = (current_board_turn == llm_actual_color)
        last_mover_color = 'black' if current_board_turn == 'white' else 'white'

        self.character.set_variable("GAME_STATE_ELO", latest_state_data.get('current_elo', 'N/A'))
        self.character.set_variable("GAME_STATE_LLM_COLOR_TEXT", "белыми" if not player_gui_is_white else "черными")
        self.character.set_variable("GAME_STATE_PLAYER_COLOR_TEXT", "белыми" if player_gui_is_white else "черными")
        self.character.set_variable("GAME_STATE_LAST_MOVE_SAN", latest_state_data.get('last_move_san', 'Нет (начало игры)'))
        self.character.set_variable("GAME_STATE_IS_LLM_LAST_MOVER", last_mover_color == llm_actual_color)
        self.character.set_variable("GAME_STATE_FEN", latest_state_data.get('fen', 'N/A'))
        self.character.set_variable("GAME_STATE_TURN_COLOR_TEXT", 'белые' if current_board_turn == 'white' else 'черные')
        self.character.set_variable("GAME_STATE_IS_OVER", latest_state_data.get('is_game_over', False))
        self.character.set_variable("GAME_STATE_OUTCOME", latest_state_data.get('outcome_message', 'Игра продолжается'))
        self.character.set_variable("GAME_STATE_IS_LLM_TURN", is_llm_turn_now)

        legal_moves = latest_state_data.get('legal_moves_uci', [])
        self.character.set_variable("GAME_STATE_HAS_LEGAL_MOVES", bool(legal_moves))
        self.character.set_variable("GAME_STATE_LEGAL_MOVES_STRING", ", ".join(legal_moves))
        self.character.set_variable("GAME_STATE_HAS_PROMOTION_MOVE", any(len(m) == 5 and m[4] in 'qrbn' for m in legal_moves))

        self.character.set_variable("GAME_STATE_ERROR_MSG", latest_state_data.get("error", None))
        self.character.set_variable("GAME_STATE_INVALID_MOVE_TEXT", latest_state_data.get("error_move", None))
        self.character.set_variable("GAME_STATE_INVALID_MOVE_REASON", latest_state_data.get("error_message_for_move", None))

        template_filename = f"{self.game_id}.system"
        try:
            content, _ = self.character.dsl_interpreter.process_file(template_filename)
            return content
        except FileNotFoundError:
            logger.error(f"[{self.character.char_id}] Скрипт для игры '{self.game_id}' не найден: {template_filename}")
            return f"ОШИБКА: Не найден системный скрипт для игры '{self.game_id}'."
        except Exception as e:
            logger.error(f"[{self.character.char_id}] Ошибка исполнения DSL-скрипта '{template_filename}': {e}", exc_info=True)
            return f"ОШИБКА: Ошибка при генерации промпта для игры '{self.game_id}'."