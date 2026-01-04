# File: Modules/Chess/chess_board.py
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import chess # For chess.square, chess.Move
import multiprocessing
import queue # Для command_queue
import time # Для цикла обработки
import threading # Для блока __main__
import traceback # Added for error reporting
import sys

# Импортируем контроллер из соседнего файла
from .engine_handler import ChessGameController, MAIA_ELO as DEFAULT_MAIA_ELO # DEFAULT_MAIA_ELO если не передан ELO
from .board_logic import PureBoardLogic # Не используется напрямую здесь, но контроллер его использует

# --- Константы для GUI (остаются как были) ---
SQUARE_SIZE = 70
BOARD_BORDER_WIDTH = 2
DEFAULT_PIECE_FONT_SIZE = int(SQUARE_SIZE * 0.6)

class ChessGameModelTkStyles:
    COLOR_BOARD_LIGHT = "#EDE0C8"
    COLOR_BOARD_DARK = "#779556"
    COLOR_HIGHLIGHT_SELECTED = "#F5F57E"
    COLOR_HIGHLIGHT_POSSIBLE = "#A0D87E"
    COLOR_HIGHLIGHT_LAST_MOVE = "#FF8C8C"
    COLOR_BUTTON_BG = "#5C85D6"
    COLOR_BUTTON_HOVER_BG = "#4A6BAD"
    COLOR_BUTTON_PRESSED_BG = "#3A558C"
    COLOR_BUTTON_TEXT = "white"
    COLOR_WINDOW_BG = "#2E2E2E"
    COLOR_PANEL_BG = "#3C3C3C"
    COLOR_TEXT_LIGHT = "#E0E0E0"
    COLOR_BOARD_OUTER_BORDER = "#5F7745"
    PIECE_FONT_FAMILY = "DejaVu Sans"
    PIECE_FONT = (PIECE_FONT_FAMILY, DEFAULT_PIECE_FONT_SIZE, "bold")
    BUTTON_FONT = ("Arial", 11)
    STATUS_FONT = ("Arial", 9)
    COORDINATE_LABEL_FONT_TUPLE = ("Arial", 9, "bold") 
    COORDINATE_LABEL_FG = "#C0C0C0"
    COORDINATE_LABEL_BG = COLOR_WINDOW_BG
    LABEL_AREA_PADDING = 4

    @staticmethod
    def get_button_normal_style():
        return {
            "bg": ChessGameModelTkStyles.COLOR_BUTTON_BG, "fg": ChessGameModelTkStyles.COLOR_BUTTON_TEXT,
            "activebackground": ChessGameModelTkStyles.COLOR_BUTTON_PRESSED_BG,
            "activeforeground": ChessGameModelTkStyles.COLOR_BUTTON_TEXT,
            "relief": "flat", "font": ChessGameModelTkStyles.BUTTON_FONT, "padx": 10, "pady": 5
        }
    @staticmethod
    def get_button_hover_style(): return {"bg": ChessGameModelTkStyles.COLOR_BUTTON_HOVER_BG}

class ChessBoardCanvas(QWidget):
    def __init__(self, parent, square_clicked_callback):
        super().__init__(parent)
        self.square_clicked_callback = square_clicked_callback
        self.setFixedSize(8 * SQUARE_SIZE, 8 * SQUARE_SIZE)
        self.square_colors = [[None for _ in range(8)] for _ in range(8)]
        self.piece_symbols = [[None for _ in range(8)] for _ in range(8)]
        self.piece_colors = [[None for _ in range(8)] for _ in range(8)]
        
        # Инициализация цветов квадратов
        for r in range(8):
            for c in range(8):
                color_idx = (c + r) % 2
                color = ChessGameModelTkStyles.COLOR_BOARD_LIGHT if color_idx == 0 else ChessGameModelTkStyles.COLOR_BOARD_DARK
                self.square_colors[r][c] = color
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            col_gui = int(pos.x()) // SQUARE_SIZE
            row_gui = int(pos.y()) // SQUARE_SIZE
            if 0 <= col_gui < 8 and 0 <= row_gui < 8:
                self.square_clicked_callback(row_gui, col_gui)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Рисуем квадраты
        for r in range(8):
            for c in range(8):
                x, y = c * SQUARE_SIZE, r * SQUARE_SIZE
                color = self.square_colors[r][c] if self.square_colors[r][c] else "#FFFFFF"
                painter.fillRect(x, y, SQUARE_SIZE, SQUARE_SIZE, QColor(color))
        
        # Рисуем рамку
        painter.setPen(QPen(QColor(ChessGameModelTkStyles.COLOR_BOARD_OUTER_BORDER), BOARD_BORDER_WIDTH))
        painter.drawRect(0, 0, 8 * SQUARE_SIZE, 8 * SQUARE_SIZE)
        
        # Рисуем фигуры
        font = QFont(ChessGameModelTkStyles.PIECE_FONT_FAMILY, DEFAULT_PIECE_FONT_SIZE)
        font.setBold(True)
        painter.setFont(font)
        
        for r in range(8):
            for c in range(8):
                if self.piece_symbols[r][c]:
                    x_center = (c + 0.5) * SQUARE_SIZE
                    y_center = (r + 0.5) * SQUARE_SIZE
                    text_color = "#FFFFFF" if self.piece_colors[r][c] else "#1E1E1E"
                    painter.setPen(QColor(text_color))
                    rect = QRectF(c * SQUARE_SIZE, r * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.piece_symbols[r][c])
    
    def set_square_color(self, r, c, color):
        self.square_colors[r][c] = color
        self.update()
    
    def set_piece(self, r, c, symbol, is_white):
        self.piece_symbols[r][c] = symbol
        self.piece_colors[r][c] = is_white
        self.update()

class PromotionDialog(QDialog):
    def __init__(self, parent, title, items_dict):
        super().__init__(parent)
        self.items_dict = items_dict
        self.item_keys = list(items_dict.keys())
        self.result_value = None
        self.setWindowTitle(title)
        self.setStyleSheet(f"background-color: {ChessGameModelTkStyles.COLOR_PANEL_BG}")
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout()
        
        label = QLabel("Выберите фигуру:")
        label.setStyleSheet(f"color: {ChessGameModelTkStyles.COLOR_TEXT_LIGHT}")
        layout.addWidget(label)
        
        self.radio_group = QButtonGroup()
        self.radio_buttons = {}
        
        for i, key_text in enumerate(self.item_keys):
            rb = QRadioButton(key_text)
            rb.setStyleSheet(f"""
                QRadioButton {{
                    color: {ChessGameModelTkStyles.COLOR_TEXT_LIGHT};
                    background-color: {ChessGameModelTkStyles.COLOR_PANEL_BG};
                }}
                QRadioButton::indicator {{
                    background-color: {ChessGameModelTkStyles.COLOR_WINDOW_BG};
                }}
            """)
            self.radio_buttons[key_text] = rb
            self.radio_group.addButton(rb, i)
            layout.addWidget(rb)
            if i == 0:
                rb.setChecked(True)
        
        button_layout = QHBoxLayout()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        self._apply_button_style(ok_btn)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        self._apply_button_style(cancel_btn)
        
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _apply_button_style(self, button):
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {ChessGameModelTkStyles.COLOR_BUTTON_BG};
                color: {ChessGameModelTkStyles.COLOR_BUTTON_TEXT};
                border: none;
                padding: 5px 10px;
                font-family: Arial;
                font-size: 10pt;
            }}
            QPushButton:hover {{
                background-color: {ChessGameModelTkStyles.COLOR_BUTTON_HOVER_BG};
            }}
            QPushButton:pressed {{
                background-color: {ChessGameModelTkStyles.COLOR_BUTTON_PRESSED_BG};
            }}
        """)
    
    def get_result(self):
        for key_text, rb in self.radio_buttons.items():
            if rb.isChecked():
                return self.items_dict[key_text]
        return None


class ChessGuiTkinter(QMainWindow):
    # Сигналы для потокобезопасного обновления GUI
    status_update_signal = pyqtSignal(str)
    board_update_signal = pyqtSignal()
    game_over_signal = pyqtSignal(str)
    
    def __init__(self, game_controller: ChessGameController): 
        super().__init__()
        self.game_controller = game_controller
        self.setWindowTitle(f"Шахматы против Maia ELO {self.game_controller.current_maia_elo if self.game_controller else DEFAULT_MAIA_ELO}")
        self.setStyleSheet(f"background-color: {ChessGameModelTkStyles.COLOR_WINDOW_BG}")

        coord_font_tuple = ChessGameModelTkStyles.COORDINATE_LABEL_FONT_TUPLE
        self.app_coord_font = QFont(coord_font_tuple[0], coord_font_tuple[1])
        if coord_font_tuple[2] == "bold":
            self.app_coord_font.setBold(True)

        fm = QFontMetrics(self.app_coord_font)
        coord_label_strip_width_approx = fm.horizontalAdvance("W") + ChessGameModelTkStyles.LABEL_AREA_PADDING * 2 + 5
        coord_label_strip_height_approx = fm.height() + ChessGameModelTkStyles.LABEL_AREA_PADDING * 2 + 5
        
        min_width = int(8 * SQUARE_SIZE + 2 * BOARD_BORDER_WIDTH + 250 + 40 + coord_label_strip_width_approx)
        min_height = int(8 * SQUARE_SIZE + 2 * BOARD_BORDER_WIDTH + 60 + 40 + coord_label_strip_height_approx)
        self.setMinimumSize(min_width, min_height)

        self.piece_symbols = {
            'P': '♙', 'N': '♘', 'B': '♗', 'R': '♖', 'Q': '♕', 'K': '♔',
            'p': '♟', 'n': '♞', 'b': '♝', 'r': '♜', 'q': '♛', 'k': '♚'
        }
        self.selected_square_gui_coords = None
        self.possible_moves_for_selected_gui_coords = []
        self.last_move_squares_gui_coords = []
        self.square_original_colors = [[None for _ in range(8)] for _ in range(8)]
        self.rank_labels_gui = [None] * 8
        self.file_labels_gui = [None] * 8
        
        self.is_closing = False 

        # Подключаем сигналы к слотам
        self.status_update_signal.connect(self.update_status_bar_slot)
        self.board_update_signal.connect(self.update_board_display_slot)
        self.game_over_signal.connect(self.show_game_over_message_slot)

        self._init_ui()
        self._setup_board_squares()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Board area
        board_area_widget = QWidget()
        board_area_widget.setStyleSheet(f"background-color: {ChessGameModelTkStyles.COLOR_WINDOW_BG}")
        board_area_layout = QGridLayout()
        board_area_layout.setSpacing(0)
        
        _label_font_obj_for_ui = self.app_coord_font 
        _label_fg = ChessGameModelTkStyles.COORDINATE_LABEL_FG
        _label_bg = ChessGameModelTkStyles.COORDINATE_LABEL_BG
        
        # Rank labels
        for r_gui in range(8):
            lbl = QLabel("")
            lbl.setFont(_label_font_obj_for_ui)
            lbl.setStyleSheet(f"color: {_label_fg}; background-color: {_label_bg}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            board_area_layout.addWidget(lbl, r_gui, 0)
            self.rank_labels_gui[r_gui] = lbl
        
        # File labels
        for c_gui in range(8):
            lbl = QLabel("")
            lbl.setFont(_label_font_obj_for_ui)
            lbl.setStyleSheet(f"color: {_label_fg}; background-color: {_label_bg}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            board_area_layout.addWidget(lbl, 8, c_gui + 1)
            self.file_labels_gui[c_gui] = lbl
        
        # Corner label
        corner_lbl = QLabel("")
        corner_lbl.setStyleSheet(f"background-color: {_label_bg}")
        board_area_layout.addWidget(corner_lbl, 8, 0)
        
        # Chess board canvas
        self.board_canvas = ChessBoardCanvas(board_area_widget, self.on_square_clicked_slot)
        board_area_layout.addWidget(self.board_canvas, 0, 1, 8, 8)
        
        board_area_widget.setLayout(board_area_layout)
        main_layout.addWidget(board_area_widget)
        
        # Control panel
        control_panel_widget = QWidget()
        control_panel_widget.setStyleSheet(f"background-color: {ChessGameModelTkStyles.COLOR_PANEL_BG}")
        control_panel_layout = QVBoxLayout()
        control_panel_layout.setContentsMargins(15, 15, 15, 15)
        
        self.btn_new_game_white = self._create_button(control_panel_widget, "Новая игра (Белыми)",
                                                      lambda: self.game_controller.new_game(player_is_white_gui_override=True) if self.game_controller else None)
        control_panel_layout.addWidget(self.btn_new_game_white)
        
        self.btn_new_game_black = self._create_button(control_panel_widget, "Новая игра (Черными)",
                                                      lambda: self.game_controller.new_game(player_is_white_gui_override=False) if self.game_controller else None)
        control_panel_layout.addWidget(self.btn_new_game_black)
        
        control_panel_layout.addStretch()
        
        control_panel_widget.setLayout(control_panel_layout)
        main_layout.addWidget(control_panel_widget)
        
        central_widget.setLayout(main_layout)
        
        # Status bar
        self.status_bar_label = QLabel("Инициализация GUI...")
        self.status_bar_label.setStyleSheet(f"""
            color: {ChessGameModelTkStyles.COLOR_TEXT_LIGHT};
            background-color: {ChessGameModelTkStyles.COLOR_PANEL_BG};
            padding: 3px 5px;
        """)
        self.status_bar_label.setFont(QFont("Arial", 9))
        self.statusBar().addPermanentWidget(self.status_bar_label, 1)
        self.statusBar().setStyleSheet(f"background-color: {ChessGameModelTkStyles.COLOR_PANEL_BG}")
        
        self._update_board_coordinates_labels()

    def _create_button(self, parent, text, command): 
        button = QPushButton(text)
        button.clicked.connect(command)
        button.setFixedWidth(200)
        
        normal_style = ChessGameModelTkStyles.get_button_normal_style()
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {normal_style['bg']};
                color: {normal_style['fg']};
                border: none;
                padding: {normal_style['pady']}px {normal_style['padx']}px;
                font-family: {normal_style['font'][0]};
                font-size: {normal_style['font'][1]}pt;
            }}
            QPushButton:hover {{
                background-color: {ChessGameModelTkStyles.COLOR_BUTTON_HOVER_BG};
            }}
            QPushButton:pressed {{
                background-color: {ChessGameModelTkStyles.COLOR_BUTTON_PRESSED_BG};
            }}
        """)
        
        return button

    def _setup_board_squares(self):
        for r_gui in range(8):
            for c_gui in range(8):
                color_idx = (c_gui + r_gui) % 2
                fill_color = ChessGameModelTkStyles.COLOR_BOARD_LIGHT if color_idx == 0 else ChessGameModelTkStyles.COLOR_BOARD_DARK
                self.square_original_colors[r_gui][c_gui] = fill_color

    def _set_square_fill_color(self, r_gui, c_gui, color): 
        self.board_canvas.set_square_color(r_gui, c_gui, color)
        
    def _reset_square_fill_color(self, r_gui, c_gui): 
        original_color = self.square_original_colors[r_gui][c_gui]
        if original_color: self._set_square_fill_color(r_gui, c_gui, original_color)
        
    def _set_piece_on_square(self, r_gui, c_gui, symbol, piece_color_is_white): 
        self.board_canvas.set_piece(r_gui, c_gui, symbol, piece_color_is_white)

    def _update_board_coordinates_labels(self):
        if not self.game_controller: return
        player_pov_white = self.game_controller.get_player_color_is_white_for_gui()
        files_display = [chr(ord('A') + i) for i in range(8)]
        if not player_pov_white: files_display.reverse()
        for c_gui in range(8):
            if self.file_labels_gui[c_gui]: self.file_labels_gui[c_gui].setText(files_display[c_gui])
        ranks_display = [str(8 - i) for i in range(8)]
        if not player_pov_white: ranks_display = [str(1 + i) for i in range(8)]
        for r_gui in range(8):
            if self.rank_labels_gui[r_gui]: self.rank_labels_gui[r_gui].setText(ranks_display[r_gui])

    def update_board_display_slot(self):
        if not self.game_controller or self.is_closing : return
        current_elo_in_title = self.game_controller.current_maia_elo if self.game_controller else DEFAULT_MAIA_ELO
        expected_title = f"Шахматы против Maia ELO {current_elo_in_title}"
        if self.windowTitle() != expected_title:
            self.setWindowTitle(expected_title)

        self._update_board_coordinates_labels()
        current_board_obj = self.game_controller.get_current_board_object_for_gui()
        for r_gui in range(8):
            for c_gui in range(8): self._reset_square_fill_color(r_gui, c_gui)

        self.last_move_squares_gui_coords = []
        if self.game_controller.get_board_logic_for_gui().board.move_stack: 
            last_move = self.game_controller.get_board_logic_for_gui().board.peek()
            from_sq_board, to_sq_board = last_move.from_square, last_move.to_square
            self.last_move_squares_gui_coords = [
                self._board_to_gui_coords(chess.square_rank(from_sq_board), chess.square_file(from_sq_board)),
                self._board_to_gui_coords(chess.square_rank(to_sq_board), chess.square_file(to_sq_board))
            ]
        for r_gui in range(8):
            for c_gui in range(8):
                file_idx, rank_idx = self._gui_to_board_coords(r_gui, c_gui)
                square_chess_index = chess.square(file_idx, rank_idx)
                piece = current_board_obj.piece_at(square_chess_index)
                piece_symbol_char, is_white_piece_on_square = ("", False)
                if piece:
                    piece_symbol_char = self.piece_symbols[piece.symbol()]
                    is_white_piece_on_square = piece.color == chess.WHITE
                self._set_piece_on_square(r_gui, c_gui, piece_symbol_char, is_white_piece_on_square)
        for r_lm, c_lm in self.last_move_squares_gui_coords:
            if 0 <= r_lm < 8 and 0 <= c_lm < 8: self._set_square_fill_color(r_lm, c_lm, ChessGameModelTkStyles.COLOR_HIGHLIGHT_LAST_MOVE)
        if self.selected_square_gui_coords:
            r_sel, c_sel = self.selected_square_gui_coords
            self._set_square_fill_color(r_sel, c_sel, ChessGameModelTkStyles.COLOR_HIGHLIGHT_SELECTED)
        for r_pm, c_pm in self.possible_moves_for_selected_gui_coords:
            self._set_square_fill_color(r_pm, c_pm, ChessGameModelTkStyles.COLOR_HIGHLIGHT_POSSIBLE)

    def show_game_over_message_slot(self, message):
        if self.is_closing: return
        self.update_status_bar_slot(message) 
        QMessageBox.information(self, "Игра окончена", message)

    def update_status_bar_slot(self, message):
        if self.is_closing: return
        if hasattr(self, 'status_bar_label'): 
             self.status_bar_label.setText(message)
        else:
            print(f"DEBUG (chess_board GUI): status_bar_label not found, message: {message}")

    def _gui_to_board_coords(self, r_gui, c_gui): 
        player_pov_white = self.game_controller.get_player_color_is_white_for_gui()
        file_idx = c_gui if player_pov_white else 7 - c_gui
        rank_idx = 7 - r_gui if player_pov_white else r_gui
        return file_idx, rank_idx
    def _board_to_gui_coords(self, rank_idx, file_idx): 
        player_pov_white = self.game_controller.get_player_color_is_white_for_gui()
        c_gui = file_idx if player_pov_white else 7 - file_idx
        r_gui = 7 - rank_idx if player_pov_white else rank_idx
        return r_gui, c_gui

    def on_square_clicked_slot(self, r_gui, c_gui):
        if not self.game_controller or self.is_closing: return
        current_board_obj = self.game_controller.get_current_board_object_for_gui()
        if current_board_obj.is_game_over() or self.game_controller.engine_is_thinking: return

        file_idx, rank_idx = self._gui_to_board_coords(r_gui, c_gui)
        clicked_square_chess_index = chess.square(file_idx, rank_idx)

        if self.selected_square_gui_coords is None:
            piece = current_board_obj.piece_at(clicked_square_chess_index)
            board_turn_color = self.game_controller.get_board_logic_for_gui().get_turn()
            
            is_player_gui_turn = (self.game_controller.player_is_white_in_gui and board_turn_color == chess.WHITE) or \
                                 (not self.game_controller.player_is_white_in_gui and board_turn_color == chess.BLACK)

            if piece and piece.color == board_turn_color and is_player_gui_turn:
                self.selected_square_gui_coords = (r_gui, c_gui)
                self.possible_moves_for_selected_gui_coords = []
                for move in current_board_obj.legal_moves:
                    if move.from_square == clicked_square_chess_index:
                        to_r_gui, to_c_gui = self._board_to_gui_coords(
                            chess.square_rank(move.to_square), chess.square_file(move.to_square))
                        self.possible_moves_for_selected_gui_coords.append((to_r_gui, to_c_gui))
            elif not is_player_gui_turn:
                 self.update_status_bar_slot("Сейчас не ваш ход (ожидается ход Maia/LLM).")
            else:
                current_turn_color_str = "белых" if board_turn_color == chess.WHITE else "черных"
                self.update_status_bar_slot(f"Выберите фигуру {current_turn_color_str} / Пустой квадрат.")
        else:
            from_r_gui, from_c_gui = self.selected_square_gui_coords
            from_file_idx, from_rank_idx = self._gui_to_board_coords(from_r_gui, from_c_gui)
            from_square_chess_index = chess.square(from_file_idx, from_rank_idx)
            uci_move_str = chess.Move(from_square_chess_index, clicked_square_chess_index).uci()
            piece_at_from = current_board_obj.piece_at(from_square_chess_index)
            if piece_at_from and piece_at_from.piece_type == chess.PAWN:
                target_rank_for_promo_board = 7 if current_board_obj.turn == chess.WHITE else 0
                if rank_idx == target_rank_for_promo_board:
                    is_legal_promo_move = any(m for m in current_board_obj.legal_moves
                                             if m.from_square == from_square_chess_index and
                                                m.to_square == clicked_square_chess_index and m.promotion)
                    if is_legal_promo_move:
                        items = {"Ферзь": "q", "Ладья": "r", "Слон": "b", "Конь": "n"}
                        dialog = PromotionDialog(self, "Превращение пешки", items)
                        if dialog.exec() == QDialog.DialogCode.Accepted:
                            promo_piece_char = dialog.get_result()
                            if promo_piece_char: 
                                uci_move_str += promo_piece_char
                            else:
                                self.update_status_bar_slot("Превращение отменено. Ход не сделан.")
                                self.selected_square_gui_coords = None
                                self.possible_moves_for_selected_gui_coords = []
                                self.update_board_display_slot() 
                                return
                        else:
                            self.update_status_bar_slot("Превращение отменено. Ход не сделан.")
                            self.selected_square_gui_coords = None
                            self.possible_moves_for_selected_gui_coords = []
                            self.update_board_display_slot() 
                            return
            self.game_controller.handle_player_move_from_gui(uci_move_str)
            self.selected_square_gui_coords = None
            self.possible_moves_for_selected_gui_coords = []
        self.update_board_display_slot()

    def closeEvent(self, event):
        reply = QMessageBox.question(self, "Выход", "Вы уверены, что хотите выйти из шахмат?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.is_closing = True
            print("CONSOLE (chess_board GUI): Окно GUI закрывается пользователем.")
            event.accept()
        else:
            event.ignore()

def run_chess_gui_process(command_q: multiprocessing.Queue, state_q: multiprocessing.Queue,
                          initial_elo: int, player_is_white_gui: bool):
    print(f"CONSOLE (chess_board_process): >>> ЗАПУСК ПРОЦЕССА GUI. ELO: {initial_elo}, Игрок GUI белый: {player_is_white_gui}")
    
    app_instance_ref = {"instance": None} 
    logged_command_q_none_warning_for_this_run = False

    gui_event_queue = queue.Queue()
    close_event_sent = {"sent": False}

    def _send_gui_closed(reason: str):
        if close_event_sent["sent"]:
            return
        if not state_q:
            close_event_sent["sent"] = True
            return
        try:
            state_q.put({"event": "gui_closed", "reason": str(reason or "")})
        except Exception:
            pass
        close_event_sent["sent"] = True

    def _proxy_update_status(message):
        if app_instance_ref["instance"] and not app_instance_ref["instance"].is_closing and message is not None:
            gui_event_queue.put(("status_update", message))
        return None 
        
    def _proxy_update_board():
        if app_instance_ref["instance"] and not app_instance_ref["instance"].is_closing:
            gui_event_queue.put(("board_update", None))
                
    def _proxy_game_over(message):
        if app_instance_ref["instance"] and not app_instance_ref["instance"].is_closing:
            gui_event_queue.put(("game_over", message))

    game_controller = None
    app = None 
    qt_app = None
    try:
        print(f"CONSOLE (chess_board_process): [STAGE 0] Создание QApplication...")
        qt_app = QApplication.instance()
        if qt_app is None:
            qt_app = QApplication(sys.argv)
        print(f"CONSOLE (chess_board_process): [STAGE 0] QApplication создан.")

        print(f"CONSOLE (chess_board_process): [STAGE 1] Создание ChessGameController...")
        game_controller = ChessGameController(
            initial_elo=initial_elo,
            player_is_white_gui=player_is_white_gui,
            state_q=state_q,
            status_update_cb_gui=_proxy_update_status,
            board_update_cb_gui=_proxy_update_board,
            game_over_cb_gui=_proxy_game_over
        )
        print(f"CONSOLE (chess_board_process): [STAGE 1] ChessGameController создан.")

        print(f"CONSOLE (chess_board_process): [STAGE 2] Вызов game_controller.initialize_dependencies_and_engine()...")
        if not game_controller.initialize_dependencies_and_engine():
            print(f"CONSOLE (chess_board_process): [STAGE 2] ОШИБКА: initialize_dependencies_and_engine() ВЕРНУЛ FALSE. Процесс GUI завершается.")
            _send_gui_closed("init_failed")
            return 

        print(f"CONSOLE (chess_board_process): [STAGE 2] initialize_dependencies_and_engine() УСПЕШНО ВЫПОЛНЕН.")
        
        print(f"CONSOLE (chess_board_process): [STAGE 3] Создание ChessGuiTkinter (окна)...")
        app = ChessGuiTkinter(game_controller)
        app_instance_ref["instance"] = app
        app.show()
        print(f"CONSOLE (chess_board_process): [STAGE 3] ChessGuiTkinter (окно) СОЗДАНО.")

        print(f"CONSOLE (chess_board_process): [STAGE 4] Вызов game_controller.new_game()...")
        game_controller.new_game() 
        print(f"CONSOLE (chess_board_process): [STAGE 4] game_controller.new_game() ВЫПОЛНЕН.")

        timer = QTimer()
        
        def process_queues():
            if app_instance_ref["instance"] and app_instance_ref["instance"].is_closing:
                _send_gui_closed("user_closed")
                timer.stop()
                qt_app.quit()
                return
                
            try:
                if command_q: 
                    command = command_q.get_nowait()
                    if command:
                        print(f"CONSOLE (chess_board_process): [LOOP] Получена команда: {command}")
                        if command.get("action") == "stop_gui_process": 
                            print(f"CONSOLE (chess_board_process): [LOOP] Команда stop_gui_process, выход из цикла.")
                            _send_gui_closed("stop_gui_process")
                            app_instance_ref["instance"].is_closing = True
                            timer.stop()
                            qt_app.quit()
                            return
                        if command.get("action") == "resign" or command.get("action") == "stop": 
                             print(f"CONSOLE (chess_board_process): [LOOP] Команда resign/stop, обработка и выход.")
                             if game_controller:
                                 game_controller.process_command(command) 
                             _send_gui_closed(command.get("action"))
                             app_instance_ref["instance"].is_closing = True 
                             timer.stop()
                             qt_app.quit()
                             return
                        if game_controller:
                            game_controller.process_command(command)
                else: 
                    if not logged_command_q_none_warning_for_this_run:
                        print("CONSOLE (chess_board_process): [LOOP] WARNING: command_q is None. External command processing via queue will be skipped.")
                        logged_command_q_none_warning_for_this_run = True
                    pass 
            except queue.Empty:
                pass 
            except Exception as e_loop_command:
                print(f"CONSOLE (chess_board_process): [LOOP] Ошибка в цикле обработки команд: {e_loop_command}")
                traceback.print_exc() 

            try:
                while not gui_event_queue.empty():
                    event_type, data = gui_event_queue.get_nowait()
                    if app_instance_ref["instance"] and not app_instance_ref["instance"].is_closing:
                        current_app_gui = app_instance_ref["instance"]
                        if event_type == "status_update":
                            current_app_gui.status_update_signal.emit(data)
                        elif event_type == "board_update":
                            current_app_gui.board_update_signal.emit()
                        elif event_type == "game_over":
                            current_app_gui.game_over_signal.emit(data)
            except queue.Empty:
                pass
            except Exception as e_gui_event_loop:
                print(f"CONSOLE (chess_board_process): [LOOP] Ошибка в цикле обработки GUI событий: {e_gui_event_loop}")
                traceback.print_exc()

        timer.timeout.connect(process_queues)
        timer.start(50)
        
        print(f"CONSOLE (chess_board_process): [STAGE 5] >>> ВХОД В ГЛАВНЫЙ ЦИКЛ ОБНОВЛЕНИЯ GUI...")
        qt_app.exec()
        print(f"CONSOLE (chess_board_process): [STAGE 5] <<< ВЫХОД ИЗ ГЛАВНОГО ЦИКЛА GUI.")

    except Exception as e_main_run_try:
        print(f"CONSOLE (chess_board_process): КРИТИЧЕСКАЯ ОШИБКА В ОСНОВНОМ TRY-EXCEPT ПРОЦЕССА GUI: {e_main_run_try}")
        traceback.print_exc() 
        if state_q: 
            try:
                state_q.put({"error": f"Critical unhandled error in GUI process: {str(e_main_run_try)}", "critical_process_failure": True})
            except Exception as e_queue_put:
                print(f"CONSOLE (chess_board_process): Не удалось отправить критическую ошибку (основной try) в state_q: {e_queue_put}")
        _send_gui_closed("crash")
    finally:
        print(f"CONSOLE (chess_board_process): [FINALLY] Блок finally процесса GUI.")
        _send_gui_closed("process_exit")

        if game_controller:
            print(f"CONSOLE (chess_board_process): [FINALLY] Вызов game_controller.shutdown_engine_process().")
            game_controller.shutdown_engine_process()
        
        if app and app_instance_ref.get("instance"): 
            print(f"CONSOLE (chess_board_process): [FINALLY] Попытка app.close(). is_closing={app.is_closing if hasattr(app, 'is_closing') else 'N/A'}")
            try:
                 app.close()
                 print(f"CONSOLE (chess_board_process): [FINALLY] app.close() вызван.")
            except Exception as e_destroy_generic_app:
                print(f"CONSOLE (chess_board_process): [FINALLY] Непредвиденная ошибка при app.close(): {e_destroy_generic_app}")
                traceback.print_exc()
        elif app_instance_ref.get("instance"): 
            print(f"CONSOLE (chess_board_process): [FINALLY] app не был присвоен в try, но app_instance_ref['instance'] существует. Попытка close() для instance.")
            try:
                 app_instance_ref["instance"].close()
            except Exception as e_destroy_instance_alt:
                 print(f"CONSOLE (chess_board_process): [FINALLY] Ошибка при app_instance_ref['instance'].close(): {e_destroy_instance_alt}")
                 traceback.print_exc()

        print(f"CONSOLE (chess_board_process): >>> ПРОЦЕСС GUI ЗАВЕРШЕН.")

if __name__ == '__main__':
    print("Локальный тест chess_board.py (запуск GUI процесса)")
    cmd_q = multiprocessing.Queue()
    st_q = multiprocessing.Queue()
    gui_process = multiprocessing.Process(target=run_chess_gui_process, args=(cmd_q, st_q, 1500, True), daemon=True)
    gui_process.start()
    def monitor_queues():
        while True:
            try:
                state = st_q.get(timeout=1)
                print(f"[MAIN TEST] Получено состояние из GUI процесса: {state.get('fen', 'N/A FEN')}, Turn: {state.get('turn')}, Outcome: {state.get('outcome_message')}, Error: {state.get('error')}")
                if state.get("is_game_over") or state.get("error") or state.get("game_resigned_by_llm") or state.get("game_stopped_by_llm") or state.get("critical_process_failure"):
                    print("[MAIN TEST] Игра окончена, ошибка или критический сбой процесса GUI, завершение мониторинга.")
                    if gui_process.is_alive():
                         cmd_q.put({"action":"stop_gui_process"}) 
                    break
            except queue.Empty: pass
            except Exception as e_monitor: 
                print(f"[MAIN TEST] Ошибка чтения из state_queue: {e_monitor}")
                traceback.print_exc()
                break
            time.sleep(0.1)
        print("[MAIN TEST] Мониторинг завершен.")
    monitor_thread = threading.Thread(target=monitor_queues, daemon=True) 
    monitor_thread.start()
    time.sleep(15) 
    if gui_process.is_alive(): print("[MAIN TEST] Отправка команды на ход движка..."); cmd_q.put({"action": "engine_move"})
    time.sleep(10)
    if gui_process.is_alive(): print("[MAIN TEST] Отправка команды на смену ELO..."); cmd_q.put({"action": "change_elo", "elo": 1100})
    gui_process.join(timeout=60) 
    if gui_process.is_alive(): print("[MAIN TEST] GUI процесс не завершился, терминируем."); gui_process.terminate()
    print("[MAIN TEST] Тест завершен.")