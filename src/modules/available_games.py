
from modules.Chess.game_instance import ChessGame

from modules.SeaBattle.seabattle_instance import SeaBattleGame
def get_available_games():
    available = {
        "chess": ChessGame,
        "seabattle": SeaBattleGame
    }
    return available