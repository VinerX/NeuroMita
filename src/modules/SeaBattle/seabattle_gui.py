from core.error_utils import format_exception
# seabattle_gui.py

import sys
import multiprocessing
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from modules.SeaBattle.seabattle_logic import GameStateProvider, to_alg, from_alg
from styles.main_styles import get_stylesheet
from ui.app_icon import application_icon, set_app_user_model_id

SEABATTLE_QSS = """
QWidget#SeaBattleWindow {
    background-color: #0a0a18;
}
QFrame#SeaBattleHeader, QFrame#SeaBattlePanel, QFrame#SeaBattleBoardCard {
    background-color: rgba(14, 16, 31, 0.96);
    border: 1px solid rgba(40, 38, 54, 0.90);
    border-radius: 14px;
}
QLabel#SeaBattleTitle {
    color: #f3edf6;
    font-size: 22pt;
    font-weight: 700;
}
QLabel#SeaBattleSubtitle {
    color: #bca9bb;
    font-size: 10pt;
}
QLabel#SeaBattleStatus {
    color: #f3edf6;
    font-size: 13pt;
    font-weight: 700;
}
QLabel#SeaBattleInfo {
    color: #bca9bb;
    font-size: 10pt;
}
QLabel#SeaBattleBoardTitle, QLabel#SeaBattlePanelTitle {
    color: #f3edf6;
    font-size: 10pt;
    font-weight: 700;
}
QLabel#SeaBattleHint {
    color: #bca9bb;
    font-size: 9pt;
}
QPushButton#ShipButton {
    min-height: 28px;
}
QPushButton#ShipButton[selected="true"] {
    background-color: #c04c80;
    border-color: rgba(255, 190, 220, 0.55);
}
"""

class BoardWidget(QWidget):
    cell_clicked = pyqtSignal(int, int, Qt.MouseButton)
    cell_hovered = pyqtSignal(int, int)

    COLORS = {
        0: QColor("#191b30"), 1: QColor("#b74b7d"), 2: QColor("#d64545"),
        3: QColor("#69758e"), 4: QColor("#ff7f8e"), 5: QColor("#111222"),
        'opp_0': QColor("#191b30"), 'opp_1': QColor("#d64545"),
        'opp_2': QColor("#69758e"), 'opp_3': QColor("#ff7f8e"),
    }

    def __init__(self, is_opponent_board=False):
        super().__init__()
        self.is_opponent_board = is_opponent_board
        self.board_data = [[0] * 10 for _ in range(10)]
        self.preview_ship = None
        self.setMouseTracking(True)
        self.cell_size = 32
        self.margin = 25  # Отступ для букв и цифр
        self.setFixedSize(self.cell_size * 10 + self.margin, self.cell_size * 10 + self.margin)

    def update_data(self, new_data):
        self.board_data = new_data
        self.update()

    def update_preview(self, ship_coords, is_valid):
        self.preview_ship = {'coords': ship_coords, 'is_valid': is_valid}
        self.update()

    def clear_preview(self):
        self.preview_ship = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        
        # Настройка шрифта для обозначений
        font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        painter.setFont(font)
        
        # Рисуем буквы (A-J) сверху
        painter.setPen(QColor("#bca9bb"))
        for i in range(10):
            letter = chr(ord('A') + i)
            x = self.margin + i * self.cell_size + self.cell_size // 2 - 5
            y = 15
            painter.drawText(x, y, letter)
        
        # Рисуем цифры (1-10) слева
        for i in range(10):
            number = str(i + 1)
            x = 5 if i < 9 else 2  # Сдвиг для двузначного числа
            y = self.margin + i * self.cell_size + self.cell_size // 2 + 5
            painter.drawText(x, y, number)
        
        # Рисуем клетки доски со смещением
        for r, row in enumerate(self.board_data):
            for c, cell_state in enumerate(row):
                x = self.margin + c * self.cell_size
                y = self.margin + r * self.cell_size
                key = f'opp_{cell_state}' if self.is_opponent_board else cell_state
                color = self.COLORS.get(key, QColor("black"))
                painter.fillRect(x, y, self.cell_size, self.cell_size, color)
                if not self.is_opponent_board and cell_state == 4:
                    painter.setPen(QPen(QColor("#ffb4d0"), 3))
                    painter.drawRect(x + 2, y + 2, self.cell_size - 4, self.cell_size - 4)
                painter.setPen(QColor("#34344b"))
                painter.drawRect(x, y, self.cell_size, self.cell_size)
                
        if self.preview_ship:
            color = QColor(183, 75, 125, 180) if self.preview_ship['is_valid'] else QColor(214, 69, 69, 180)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            for c, r in self.preview_ship['coords']:
                painter.drawRect(self.margin + c * self.cell_size, self.margin + r * self.cell_size, self.cell_size, self.cell_size)

    def mouseMoveEvent(self, event):
        x = (event.pos().x() - self.margin) // self.cell_size
        y = (event.pos().y() - self.margin) // self.cell_size
        if 0 <= x < 10 and 0 <= y < 10: self.cell_hovered.emit(x, y)
    
    def mousePressEvent(self, event):
        x = (event.pos().x() - self.margin) // self.cell_size
        y = (event.pos().y() - self.margin) // self.cell_size
        if 0 <= x < 10 and 0 <= y < 10: self.cell_clicked.emit(x, y, event.button())

    def leaveEvent(self, event): self.clear_preview()

class SeaBattleWindow(QWidget):
    def __init__(self, command_queue, state_queue, reaction_queue=None):
        super().__init__()
        self.command_queue = command_queue
        self.state_queue = state_queue
        self.reaction_queue = reaction_queue
        self.game = GameStateProvider()
        
        self.ship_to_place = None
        self.init_ui()
        self.update_view()

        self.command_timer = QTimer(self)
        self.command_timer.timeout.connect(self.process_commands)
        self.command_timer.start(100)

    def closeEvent(self, event):
        try:
            if self.state_queue:
                self.state_queue.put({"event": "gui_closed", "reason": "user_closed"})
        except Exception:
            pass
        try:
            if hasattr(self, "command_timer") and self.command_timer:
                self.command_timer.stop()
        except Exception:
            pass
        event.accept()

    def init_ui(self):
        self.setWindowTitle("Морской Бой")
        self.setWindowIcon(application_icon())
        self.setMinimumSize(820, 680)
        self.resize(880, 720)
        self.setObjectName("SeaBattleWindow")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(22, 22, 22, 22)
        main_layout.setSpacing(14)

        header = QFrame(objectName="SeaBattleHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(4)
        header_layout.addWidget(QLabel("Морской бой", objectName="SeaBattleTitle"))
        header_layout.addWidget(QLabel(
            "Сыграйте партию с Митой — сначала расставьте корабли.",
            objectName="SeaBattleSubtitle",
        ))
        self.status_label = QLabel("Расстановка кораблей", objectName="SeaBattleStatus")
        self.info_label = QLabel("Выберите корабль", objectName="SeaBattleInfo")
        header_layout.addSpacing(6)
        header_layout.addWidget(self.status_label)
        header_layout.addWidget(self.info_label)
        main_layout.addWidget(header)

        boards_layout = QHBoxLayout()
        boards_layout.setSpacing(14)
        boards_layout.addStretch(1)
        self.my_board_widget = BoardWidget()
        self.opponent_board_widget = BoardWidget(is_opponent_board=True)

        self.my_board_card = self._make_board_card("Ваше поле", self.my_board_widget)
        self.opponent_board_card = self._make_board_card("Поле Миты", self.opponent_board_widget)
        boards_layout.addWidget(self.my_board_card)
        boards_layout.addWidget(self.opponent_board_card)
        boards_layout.addStretch(1)
        main_layout.addLayout(boards_layout)

        self.controls_panel = QFrame(objectName="SeaBattlePanel")
        controls_panel_layout = QVBoxLayout(self.controls_panel)
        controls_panel_layout.setContentsMargins(16, 14, 16, 14)
        controls_panel_layout.setSpacing(10)
        self.controls_title = QLabel("Ваши корабли", objectName="SeaBattlePanelTitle")
        controls_panel_layout.addWidget(self.controls_title)
        self.controls_layout = QGridLayout()
        self.controls_layout.setHorizontalSpacing(10)
        self.controls_layout.setVerticalSpacing(8)
        controls_panel_layout.addLayout(self.controls_layout)

        self.mita_reaction_checkbox = QCheckBox("Мита реагирует на мой выстрел")
        self.mita_reaction_checkbox.setChecked(True)
        self.mita_reaction_checkbox.setToolTip(
            "После вашего действительного хода Мита сразу получает повод для реакции в чате."
        )
        controls_panel_layout.addWidget(self.mita_reaction_checkbox)
        controls_panel_layout.addWidget(QLabel(
            "Можно отключить для этой партии. Общая настройка реакций приложения сохраняет приоритет.",
            objectName="SeaBattleHint",
        ))
        main_layout.addWidget(self.controls_panel)

        self.ship_buttons = {}
        ship_counts = {s: self.game.engine.SHIP_CONFIG.count(s) for s in sorted(list(set(self.game.engine.SHIP_CONFIG)), reverse=True)}
        for i, (length, count) in enumerate(ship_counts.items()):
            btn = QPushButton(f"{length}-палубный (x{count})")
            btn.setObjectName("ShipButton")
            btn.clicked.connect(lambda _, l=length: self.select_ship_to_place(l))
            self.ship_buttons[length] = {'btn': btn, 'count': count}
            self.controls_layout.addWidget(btn, i // 2, i % 2)

        self.my_board_widget.cell_hovered.connect(self.on_my_board_hover)
        self.my_board_widget.cell_clicked.connect(self.on_my_board_click)
        self.opponent_board_widget.cell_clicked.connect(self.on_opponent_board_click)

    @staticmethod
    def _make_board_card(title, board):
        card = QFrame(objectName="SeaBattleBoardCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(QLabel(title, objectName="SeaBattleBoardTitle"))
        layout.addWidget(board, alignment=Qt.AlignmentFlag.AlignCenter)
        return card

    def send_state_update(self):
        state = self.game.get_full_state()
        try:
            self.state_queue.put(state)
        except Exception as e:
            print(f"GUI Error: Could not put state in queue: {format_exception(e)}")

    def process_commands(self):
        while not self.command_queue.empty():
            try:
                cmd = self.command_queue.get_nowait()
                action = cmd.get("action")

                if action == "stop_gui_process":
                    self.close()
                    return

                if action == "get_state":
                    self.send_state_update()
                    continue

                if action == "mita_place_ship":
                    spec = cmd.get("spec", "").split(',')
                    if len(spec) == 3:
                        try:
                            coord, length, orient_char = spec
                            x, y = from_alg(coord)
                            length = int(length)
                            orient = 'v' if orient_char.lower() == 'v' else 'h'
                            success, message = self.game.engine.place_ship(self.game.mita_id, x, y, length, orient)
                            self.game.last_error = None if success else f"Мита не смогла поставить корабль: {message}"
                        except Exception as e:
                            self.game.last_error = f"Ошибка расстановки Миты: {format_exception(e)}"
                    else:
                        self.game.last_error = "Ошибка расстановки Миты: неверный формат команды"
                
                if action == "mita_place_randomly":
                    success, message = self.game.engine.place_all_mita_ships_randomly()
                    self.game.last_error = None if success else f"Мита не смогла расставить корабли: {message}"

                if action == "mita_move":
                    try:
                        x, y = from_alg(cmd.get("coord"))
                        result, message = self.game.engine.make_move(self.game.mita_id, x, y)
                        self.game.last_error = None if result not in {"invalid_phase", "not_your_turn", "invalid_coord", "already_shot"} else f"Ход Миты не принят: {message}"
                    except Exception as e:
                        self.game.last_error = f"Ошибка хода Миты: {format_exception(e)}"

                self.update_view()
                self.send_state_update()

            except multiprocessing.queues.Empty:
                break
            except Exception as e:
                print(f"GUI Error processing command: {format_exception(e)}")

    def select_ship_to_place(self, length):
        self.ship_to_place = {'len': length, 'orient': 'h'} if not (self.ship_to_place and self.ship_to_place['len'] == length) else None
        self.update_view()

    def on_my_board_hover(self, x, y):
        if self.game.engine.game_phase != "placement" or not self.ship_to_place: return
        l, o = self.ship_to_place['len'], self.ship_to_place['orient']
        coords = [(x + i, y) if o == 'h' else (x, y + i) for i in range(l)]
        is_valid = all(self.game.engine._is_valid_coord(px, py) for px, py in coords) and self.game.engine._can_place(self.game.player_id, coords)
        self.my_board_widget.update_preview(coords, is_valid)

    def on_my_board_click(self, x, y, button):
        state = self.game.get_full_state()
        if state['phase'] != "placement": return

        if button == Qt.MouseButton.RightButton and self.ship_to_place:
            self.ship_to_place['orient'] = 'v' if self.ship_to_place['orient'] == 'h' else 'h'
            self.on_my_board_hover(x, y)
            return
        
        if button == Qt.MouseButton.LeftButton and self.ship_to_place:
            l, o = self.ship_to_place['len'], self.ship_to_place['orient']
            success, msg = self.game.engine.place_ship(self.game.player_id, x, y, l, o)
            if success:
                self.ship_to_place = None
                self.update_view()
                self.send_state_update()
            else:
                self.info_label.setText(f"<font color='#BF616A'>{msg}</font>")

    def on_opponent_board_click(self, x, y, button):
        state = self.game.get_full_state()
        if state['phase'] != 'battle' or not state['is_player_turn']: return
        if button != Qt.MouseButton.LeftButton: return

        result, message = self.game.engine.make_move(self.game.player_id, x, y)
        if result not in {"invalid_phase", "not_your_turn", "invalid_coord", "already_shot"}:
            self._request_mita_reaction(x, y, result, message)
        self.update_view()
        self.send_state_update()

    def _request_mita_reaction(self, x, y, result, message):
        if not self.mita_reaction_checkbox.isChecked() or not self.reaction_queue:
            return
        try:
            self.reaction_queue.put({
                "event": "player_target_selected",
                "coord": to_alg(x, y),
                "result": str(result or ""),
                "message": str(message or ""),
            })
        except Exception as exc:
            print(f"GUI Error: Could not queue Mita reaction: {format_exception(exc)}")

    def update_view(self):
        state = self.game.get_full_state()
        self.my_board_widget.update_data(state['player_board_raw'])
        self.opponent_board_widget.update_data(state['opponent_view_raw'])

        if state['phase'] == 'placement':
            self.controls_panel.setVisible(True)
            self.controls_title.setVisible(True)
            self.opponent_board_card.setVisible(False)
            ships_left = state['player_ships_to_place']
            for length, data in self.ship_buttons.items():
                count = ships_left.count(length)
                data['btn'].setText(f"{length}-палубный (x{count})")
                data['btn'].setEnabled(count > 0)
                data['btn'].setVisible(True)
                is_selected = self.ship_to_place and self.ship_to_place['len'] == length
                data['btn'].setProperty("selected", bool(is_selected))
                data['btn'].style().unpolish(data['btn'])
                data['btn'].style().polish(data['btn'])

            if not ships_left:
                self.status_label.setText("Ожидание Миты")
                self.info_label.setText("Все ваши корабли расставлены.")
            else:
                self.status_label.setText("Расстановка кораблей")
                info = "Выберите корабль. ПКМ для вращения."
                if self.ship_to_place:
                    orient = "Вертикально" if self.ship_to_place['orient'] == 'v' else "Горизонтально"
                    info = f"Разместите {self.ship_to_place['len']}-палубный. ({orient})"
                self.info_label.setText(info)

        elif state['phase'] == 'battle':
            self.controls_panel.setVisible(True)
            self.controls_title.setVisible(False)
            for data in self.ship_buttons.values():
                data['btn'].setVisible(False)
            self.my_board_widget.clear_preview()
            self.opponent_board_card.setVisible(True)
            self.status_label.setText("Ваш ход!" if state['is_player_turn'] else "Ход Миты")
            self.info_label.setText("Стреляйте по полю противника.")
            if state.get('last_move'):
                last_move = state['last_move']
                actor = "Вы" if last_move['attacker'] == self.game.player_id else "Мита"
                self.info_label.setText(f"Последний ход: {actor} на {last_move['coord_alg']} - {last_move['message']}")

        elif state['phase'] == 'game_over':
            self.controls_panel.setVisible(False)
            self.my_board_widget.clear_preview()
            winner_text = "Вы победили!" if state['winner'] == self.game.player_id else "Мита победила."
            self.status_label.setText("Игра окончена")
            self.info_label.setText(winner_text)

def run_seabattle_gui_process(command_queue, state_queue, reaction_queue=None):
    set_app_user_model_id()
    app = QApplication(sys.argv)
    app.setWindowIcon(application_icon())
    app.setStyleSheet(get_stylesheet() + SEABATTLE_QSS)
    window = SeaBattleWindow(command_queue, state_queue, reaction_queue)
    window.show()
    window.send_state_update()
    sys.exit(app.exec())
