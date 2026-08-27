# board_logic.py
import chess

PIECE_SYMBOLS = {
    'r': '♜', 'n': '♞', 'b': '♝', 'q': '♛', 'k': '♚', 'p': '♟',
    'R': '♖', 'N': '♘', 'B': '♗', 'Q': '♕', 'K': '♔', 'P': '♙',
}


class PureBoardLogic:
    def __init__(self):
        self.board = chess.Board()

    def reset_board(self, fen=None):
        if fen:
            try:
                self.board.set_fen(fen)
            except ValueError:
                print(f"Ошибка: Некорректный FEN: {fen}. Сброс на начальную позицию.")
                self.board.reset()
        else:
            self.board.reset()

    def get_fen(self):
        return self.board.fen()

    def get_turn(self):
        return self.board.turn

    def get_legal_moves_uci(self):
        return [move.uci() for move in self.board.legal_moves]

    def get_legal_moves_uci_short(self, limit: int = 10):
        return [move.uci() for move in list(self.board.legal_moves)[:limit]]

    def make_move(self, uci_move_str):
        try:
            move = chess.Move.from_uci(uci_move_str)
            if move in self.board.legal_moves:
                san_move_str = self.board.san(move)
                self.board.push(move)
                return True, f"Ход {san_move_str} (UCI: {uci_move_str}) сделан.", san_move_str
            else:
                promotion_move_options = [
                    uci_move_str + 'q', uci_move_str + 'r', uci_move_str + 'b', uci_move_str + 'n'
                ]
                for promo_uci in promotion_move_options:
                    try:
                        promo_move = chess.Move.from_uci(promo_uci)
                        if promo_move in self.board.legal_moves:
                             return False, f"Нелегальный ход: {uci_move_str}. Возможно, вы имели в виду ход с превращением, например {promo_uci}?", None
                    except ValueError:
                        continue
                return False, f"Нелегальный ход: {uci_move_str}", None
        except ValueError:
            return False, f"Некорректный формат хода UCI: {uci_move_str}", None

    def force_move(self, uci_move_str):
        """Cheat: делает ход без проверки легальности."""
        try:
            move = chess.Move.from_uci(uci_move_str)
            self.board.push(move)
            san = self.board.san(move)
            return True, f"Чит-ход {san} (UCI: {uci_move_str}).", san
        except (ValueError, AssertionError):
            return False, f"Невозможный чит-ход: {uci_move_str}", None

    def spawn_piece(self, square_str, piece_char):
        """Cheat: ставит фигуру на клетку (piece_char: K, Q, R, B, N, P / k, q, r, b, n, p)."""
        try:
            sq = chess.parse_square(square_str)
        except ValueError:
            return False, f"Некорректная клетка: {square_str}"
        piece = chess.Piece.from_symbol(piece_char)
        self.board.set_piece_at(sq, piece)
        color = "белых" if piece.color == chess.WHITE else "чёрных"
        name = {chess.KING: "король", chess.QUEEN: "ферзь", chess.ROOK: "ладья",
                chess.BISHOP: "слон", chess.KNIGHT: "конь", chess.PAWN: "пешка"}.get(piece.piece_type, "?")
        return True, f"Спавн: {name} {color} на {square_str}.", None

    def remove_piece(self, square_str):
        """Cheat: убирает фигуру с клетки."""
        try:
            sq = chess.parse_square(square_str)
        except ValueError:
            return False, f"Некорректная клетка: {square_str}"
        removed = self.board.piece_at(sq)
        if removed:
            self.board.remove_piece_at(sq)
            sym = PIECE_SYMBOLS.get(removed.symbol(), removed.symbol())
            return True, f"Удалена фигура {sym} с {square_str}.", None
        return False, f"На клетке {square_str} нет фигуры.", None

    def is_game_over(self):
        if self.board.is_checkmate():
            winner = "Черные" if self.board.turn == chess.WHITE else "Белые"
            return True, f"Мат! Победили {winner}."
        if self.board.is_stalemate():
            return True, "Ничья (пат)."
        if self.board.is_insufficient_material():
            return True, "Ничья (недостаточно материала)."
        if self.board.is_seventyfive_moves():
            return True, "Ничья (правило 75 ходов)."
        if self.board.is_fivefold_repetition():
            return True, "Ничья (пятикратное повторение позиции)."
        if self.board.can_claim_draw():
             return True, "Ничья (можно заявить по правилу 50 ходов или трехкратного повторения)."
        return False, "Игра продолжается."

    def get_piece_at(self, square_name):
        try:
            square_index = chess.parse_square(square_name)
            return self.board.piece_at(square_index)
        except ValueError:
            return None

    def get_board_for_display(self):
        return self.board

    def ascii_board(self):
        """ASCII-доска с Unicode-фигурами для промпта LLM."""
        lines = ["  a b c d e f g h"]
        for rank in range(7, -1, -1):
            row = f"{rank + 1} "
            for file in range(8):
                piece = self.board.piece_at(chess.square(file, rank))
                row += (PIECE_SYMBOLS.get(piece.symbol(), '.') if piece else '.') + ' '
            row += f"{rank + 1}"
            lines.append(row)
        lines.append("  a b c d e f g h")
        return "\n".join(lines)