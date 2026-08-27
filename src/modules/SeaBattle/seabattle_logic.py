# seabattle_logic.py

import random
from typing import List, Tuple, Dict, Any

def to_alg(x: int, y: int) -> str:
    if not (0 <= x < 10 and 0 <= y < 10): return "INVALID"
    return f"{chr(ord('A') + x)}{y + 1}"

def from_alg(notation: str) -> Tuple[int, int]:
    notation = notation.upper().strip()
    if not (2 <= len(notation) <= 3 and 'A' <= notation[0] <= 'J' and notation[1:].isdigit()):
        raise ValueError("Invalid notation format")
    x = ord(notation[0]) - ord('A')
    y = int(notation[1:]) - 1
    if not (0 <= x < 10 and 0 <= y < 10):
        raise ValueError("Coordinates out of bounds")
    return x, y

class SeaBattleEngine:
    BOARD_SIZE = 10
    SHIP_CONFIG = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]
    CELL_EMPTY = 0; CELL_SHIP = 1; CELL_HIT = 2; CELL_MISS = 3; CELL_SUNK = 4; CELL_FORBIDDEN = 5
    VIEW_UNKNOWN = 0; VIEW_HIT = 1; VIEW_MISS = 2; VIEW_SUNK = 3
    
    def __init__(self, player_id: int = 0, mita_id: int = 1):
        self.player_id = player_id
        self.mita_id = mita_id
        self.reset()

    def reset(self):
        self.player_boards: Dict[int, List[List[int]]] = { self.player_id: self._create_empty_board(), self.mita_id: self._create_empty_board() }
        self.player_ships: Dict[int, List[Dict[str, Any]]] = { self.player_id: [], self.mita_id: [] }
        self.ships_to_place: Dict[int, List[int]] = { self.player_id: self.SHIP_CONFIG[:], self.mita_id: self.SHIP_CONFIG[:] }
        self.game_phase = "placement"
        self.current_player = self.player_id
        self.winner = None
        self.last_move_result = None

    def _create_empty_board(self):
        return [[self.CELL_EMPTY for _ in range(self.BOARD_SIZE)] for _ in range(self.BOARD_SIZE)]

    def place_ship(self, player_id, x, y, length, orientation):
        if self.game_phase != "placement": return False, "Неверная фаза игры"
        if length not in self.ships_to_place[player_id]: return False, f"Корабль длины {length} уже размещен"
        coords = []
        for i in range(length):
            px, py = (x + i, y) if orientation == 'h' else (x, y + i)
            if not self._is_valid_coord(px, py): return False, "Выход за границы поля"
            coords.append((px, py))
        if not self._can_place(player_id, coords): return False, "Нельзя ставить корабли рядом"
        ship = {'coords': coords, 'hits': [False] * length, 'sunk': False}
        self.player_ships[player_id].append(ship)
        for cx, cy in coords: self.player_boards[player_id][cy][cx] = self.CELL_SHIP
        self._mark_forbidden_zone(player_id, coords)
        self.ships_to_place[player_id].remove(length)
        if not self.ships_to_place[self.player_id] and not self.ships_to_place[self.mita_id]: self.game_phase = "battle"
        return True, "Корабль размещен"

    def make_move(self, attacker_id: int, x: int, y: int):
        if self.game_phase != "battle": return "invalid_phase", "Неверная фаза игры"
        if self.current_player != attacker_id: return "not_your_turn", "Сейчас не ваш ход"
        defender_id = self.mita_id if attacker_id == self.player_id else self.player_id
        defender_board = self.player_boards[defender_id]
        if not self._is_valid_coord(x, y): return "invalid_coord", "Неверные координаты"
        cell = defender_board[y][x]
        if cell in [self.CELL_HIT, self.CELL_MISS, self.CELL_SUNK]: return "already_shot", "Вы уже стреляли в эту клетку"
        result_code, result_msg = "", ""
        if cell == self.CELL_SHIP:
            defender_board[y][x] = self.CELL_HIT
            for ship in self.player_ships[defender_id]:
                if (x, y) in ship['coords']:
                    hit_index = ship['coords'].index((x,y))
                    ship['hits'][hit_index] = True
                    if all(ship['hits']):
                        ship['sunk'] = True
                        for sx, sy in ship['coords']: defender_board[sy][sx] = self.CELL_SUNK
                        if all(s['sunk'] for s in self.player_ships[defender_id]):
                            self.game_phase = "game_over"; self.winner = self.current_player
                            result_code, result_msg = "win", f"Игрок {self.current_player} победил!"
                        else: result_code, result_msg = "sunk", "Потопил! Стреляйте еще раз."
                    else: result_code, result_msg = "hit", "Попал! Стреляйте еще раз."
                    break
        else:
            defender_board[y][x] = self.CELL_MISS
            self.current_player = defender_id
            result_code, result_msg = "miss", "Мимо!"
        self.last_move_result = {"attacker": attacker_id, "coords": (x,y), "result": result_code, "message": result_msg}
        return result_code, result_msg

    def _is_valid_coord(self, x, y): return 0 <= x < self.BOARD_SIZE and 0 <= y < self.BOARD_SIZE
    def _can_place(self, player_id, coords): return all(self.player_boards[player_id][y][x] == self.CELL_EMPTY for x, y in coords)
    def _mark_forbidden_zone(self, player_id, coords):
        board = self.player_boards[player_id]
        for x, y in coords:
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    nx, ny = x + dx, y + dy
                    if self._is_valid_coord(nx, ny) and board[ny][nx] == self.CELL_EMPTY: board[ny][nx] = self.CELL_FORBIDDEN
    
    def place_all_mita_ships_randomly(self):
        mita_id = self.mita_id
        for ship_len in self.ships_to_place[mita_id][:]:
            placed = False
            for _ in range(100):
                orient = random.choice(['h', 'v'])
                x, y = random.randint(0, 9), random.randint(0, 9)
                if self.place_ship(mita_id, x, y, ship_len, orient)[0]:
                    placed = True
                    break
            if not placed: return False, f"Не удалось разместить {ship_len}-палубный"
        return True, "Все корабли Миты размещены."


class GameStateProvider:
    """
    Предоставляет удобный доступ к состоянию игры для GUI и основного процесса.
    Работает как враппер над SeaBattleEngine.
    """
    def __init__(self, player_id: int = 0, mita_id: int = 1):
        self.engine = SeaBattleEngine(player_id, mita_id)
        self.player_id = player_id
        self.mita_id = mita_id

    def _board_to_str(self, board_data: list, perspective: str) -> str:
        """
        Преобразует 2D-список доски в форматированную строку.
        perspective: 'my_full' (своя доска, все видно), 'opponent_view' (видно только результаты выстрелов)
        """
        if perspective == 'my_full':
            mapping = {
                self.engine.CELL_EMPTY: '.', self.engine.CELL_FORBIDDEN: '.',
                self.engine.CELL_SHIP: 'S', self.engine.CELL_HIT: 'H',
                self.engine.CELL_MISS: 'M', self.engine.CELL_SUNK: 'X',
            }
        else: # opponent_view
            mapping = {
                self.engine.VIEW_UNKNOWN: '.', self.engine.VIEW_HIT: 'H',
                self.engine.VIEW_MISS: 'M', self.engine.VIEW_SUNK: 'X',
            }
        
        lines = []
        for r_idx, row in enumerate(board_data):
            line = f"{r_idx + 1:<2}" + " ".join([mapping.get(cell, '?') for cell in row])
            lines.append(line)
        return "\n".join(lines)

    def get_full_state(self) -> Dict[str, Any]:
        """Возвращает полное состояние игры, включая тактическую аналитику и строки досок для Миты."""
        player_board_raw, player_opponent_view_raw = self._get_player_views()
        
        last_move_info = self.engine.last_move_result
        if last_move_info:
            last_move_info['coord_alg'] = to_alg(last_move_info['coords'][0], last_move_info['coords'][1])

        # Генерация представлений досок для Миты
        # "Моя доска" для Миты - это её собственная доска со всеми её кораблями
        mita_my_board_str = self._board_to_str(self.engine.player_boards[self.mita_id], 'my_full')
        # "Доска противника" для Миты - это то, как Мита видит доску игрока
        _, mita_opponent_view_raw = self._get_mita_views()
        mita_opponent_view_str = self._board_to_str(mita_opponent_view_raw, 'opponent_view')

        return {
            # Основные данные
            "phase": self.engine.game_phase,
            "is_player_turn": self.engine.current_player == self.player_id,
            "winner": self.engine.winner,
            "player_id": self.player_id,
            "mita_id": self.mita_id,
            "last_move": last_move_info,
            
            # Данные для GUI
            "player_board_raw": player_board_raw,
            "opponent_view_raw": player_opponent_view_raw,
            
            # Данные для расстановки
            "mita_ships_to_place": self.engine.ships_to_place[self.mita_id][:],
            "player_ships_to_place": self.engine.ships_to_place[self.player_id][:],
            
            # Строки досок специально для промпта Миты
            "mita_my_board_str": mita_my_board_str,
            "mita_opponent_view_str": mita_opponent_view_str,
            
            # Тактическая аналитика для Миты
            "hunt_info": self._get_hunt_info_for_mita(),
            "shot_history_str": ", ".join(self._get_shot_history_for_mita()),
        }

    def _get_shot_history_for_mita(self) -> List[str]:
        """Возвращает список клеток, по которым Мита уже стреляла (по доске игрока)."""
        history = []
        player_board = self.engine.player_boards[self.player_id]
        for r in range(self.engine.BOARD_SIZE):
            for c in range(self.engine.BOARD_SIZE):
                if player_board[r][c] in [self.engine.CELL_HIT, self.engine.CELL_MISS, self.engine.CELL_SUNK]:
                    history.append(to_alg(c, r))
        return sorted(history)

    def _get_hunt_info_for_mita(self) -> Dict[str, Any]:
        """Анализирует доску игрока и находит цели для Миты."""
        wounded_ships_coords = []
        # Ищем подбитые, но не потопленные корабли игрока
        for ship in self.engine.player_ships[self.player_id]:
            if not ship['sunk'] and any(ship['hits']):
                hit_coords = [coord for i, coord in enumerate(ship['coords']) if ship['hits'][i]]
                wounded_ships_coords.append(hit_coords)

        if not wounded_ships_coords:
            return {}

        all_hit_coords = [item for sublist in wounded_ships_coords for item in sublist]
        
        # Генерируем рекомендуемые цели
        potential_targets = set()
        for hit_list in wounded_ships_coords:
            if len(hit_list) == 1: # Одна палуба подбита, проверяем 4 направления
                x, y = hit_list[0]
                potential_targets.update([(x+1, y), (x-1, y), (x, y+1), (x, y-1)])
            else: # Две и более палубы, корабль ориентирован
                is_horizontal = hit_list[0][1] == hit_list[1][1]
                min_coord = min(c[0] if is_horizontal else c[1] for c in hit_list)
                max_coord = max(c[0] if is_horizontal else c[1] for c in hit_list)
                if is_horizontal:
                    y = hit_list[0][1]
                    potential_targets.update([(min_coord - 1, y), (max_coord + 1, y)])
                else:
                    x = hit_list[0][0]
                    potential_targets.update([(x, min_coord - 1), (x, max_coord + 1)])

        # Фильтруем цели: должны быть на доске и по ним еще не стреляли
        shot_coords = {from_alg(c) for c in self._get_shot_history_for_mita()}
        valid_targets = []
        for x, y in potential_targets:
            if self.engine._is_valid_coord(x, y) and (x, y) not in shot_coords:
                valid_targets.append(to_alg(x, y))
        
        return {
            "wounded_info_str": f"Обнаружен подбитый корабль в клетках: {', '.join(map(lambda c: to_alg(c[0], c[1]), all_hit_coords))}.",
            "hunt_targets": sorted(list(set(valid_targets)))
        }

    def _get_player_views(self):
        """Возвращает доски с точки зрения Игрока (GUI)."""
        my_board = self.engine.player_boards[self.player_id]
        opponent_board = self.engine.player_boards[self.mita_id]
        opponent_view = [[0] * self.engine.BOARD_SIZE for _ in range(self.engine.BOARD_SIZE)]
        for r in range(self.engine.BOARD_SIZE):
            for c in range(self.engine.BOARD_SIZE):
                cell = opponent_board[r][c]
                if cell == self.engine.CELL_HIT: opponent_view[r][c] = self.engine.VIEW_HIT
                elif cell == self.engine.CELL_MISS: opponent_view[r][c] = self.engine.VIEW_MISS
                elif cell == self.engine.CELL_SUNK: opponent_view[r][c] = self.engine.VIEW_SUNK
                else: opponent_view[r][c] = self.engine.VIEW_UNKNOWN
        return my_board, opponent_view

    def _get_mita_views(self):
        """Возвращает доски с точки зрения Миты."""
        my_board = self.engine.player_boards[self.mita_id]
        opponent_board = self.engine.player_boards[self.player_id]
        opponent_view = [[0] * self.engine.BOARD_SIZE for _ in range(self.engine.BOARD_SIZE)]
        for r in range(self.engine.BOARD_SIZE):
            for c in range(self.engine.BOARD_SIZE):
                cell = opponent_board[r][c]
                if cell == self.engine.CELL_HIT: opponent_view[r][c] = self.engine.VIEW_HIT
                elif cell == self.engine.CELL_MISS: opponent_view[r][c] = self.engine.VIEW_MISS
                elif cell == self.engine.CELL_SUNK: opponent_view[r][c] = self.engine.VIEW_SUNK
                else: opponent_view[r][c] = self.engine.VIEW_UNKNOWN
        return my_board, opponent_view