from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .core import DialogueSimulation, MitaMode, SimulationError, TurnResult, create_default_simulation


class DialogueTurnSimulatorWindow(QMainWindow):
    def __init__(self, simulation: DialogueSimulation | None = None) -> None:
        super().__init__()
        self.simulation = simulation or create_default_simulation()
        self._running = False
        self._row_by_id: dict[str, int] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(650)
        self._timer.timeout.connect(self._run_one_automatic_turn)
        self.setWindowTitle("Unity Dialogue Turn Simulator")
        self.resize(1180, 760)
        self.setMinimumSize(920, 620)
        self._build_ui()
        self._apply_style()
        self._populate_table()
        self._refresh()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Симулятор очереди диалога Unity")
        title.setObjectName("Title")
        subtitle = QLabel(
            "Активность и дистанция формируют roster; очки определяют следующую Миту; "
            "режим меняет имитацию ответа."
        )
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        settings = QFrame()
        settings.setObjectName("Card")
        settings_layout = QGridLayout(settings)
        settings_layout.setContentsMargins(14, 12, 14, 12)
        settings_layout.setHorizontalSpacing(12)
        settings_layout.setVerticalSpacing(8)
        self.auto_check = QCheckBox("Автоматические ответы")
        self.auto_check.setChecked(self.simulation.auto_dialogue_enabled)
        self.auto_check.toggled.connect(self._sync_global_settings)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 500)
        self.limit_spin.setSuffix(" %")
        self.limit_spin.setValue(round(self.simulation.limit_modifier_percent))
        self.limit_spin.valueChanged.connect(self._sync_global_settings)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.setValue(self.simulation.seed)
        settings_layout.addWidget(self.auto_check, 0, 0, 1, 2)
        settings_layout.addWidget(QLabel("Модификатор лимита"), 0, 2)
        settings_layout.addWidget(self.limit_spin, 0, 3)
        settings_layout.addWidget(QLabel("Seed сброса очереди"), 0, 4)
        settings_layout.addWidget(self.seed_spin, 0, 5)
        settings_layout.setColumnStretch(1, 1)
        layout.addWidget(settings)

        body = QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, 1)

        left = QFrame()
        left.setObjectName("Card")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        left_title = QLabel("Состояние Мит")
        left_title.setObjectName("SectionTitle")
        left_layout.addWidget(left_title)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("Вкл.", "Персонаж", "Режим", "Дистанция", "Очки", "Приоритет")
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self.table, 1)
        body.addWidget(left, 7)

        right = QFrame()
        right.setObjectName("Card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)
        right_title = QLabel("Ход симуляции")
        right_title.setObjectName("SectionTitle")
        right_layout.addWidget(right_title)
        self.status_label = QLabel()
        self.status_label.setObjectName("Status")
        self.status_label.setWordWrap(True)
        self.order_label = QLabel()
        self.order_label.setObjectName("Muted")
        self.order_label.setWordWrap(True)
        right_layout.addWidget(self.status_label)
        right_layout.addWidget(self.order_label)

        self.player_input = QPlainTextEdit()
        self.player_input.setPlaceholderText("Введите реплику игрока…")
        self.player_input.setFixedHeight(92)
        self.player_input.setPlainText("Как вы думаете, чем нам заняться сегодня?")
        right_layout.addWidget(self.player_input)

        player_buttons = QHBoxLayout()
        self.send_button = QPushButton("Отправить игроком")
        self.send_button.setObjectName("Primary")
        self.send_button.clicked.connect(self._begin_player_turn)
        self.step_button = QPushButton("Следующий ход")
        self.step_button.clicked.connect(self._step)
        player_buttons.addWidget(self.send_button, 1)
        player_buttons.addWidget(self.step_button)
        right_layout.addLayout(player_buttons)

        chain_buttons = QHBoxLayout()
        self.run_button = QPushButton("Запустить цепочку")
        self.run_button.clicked.connect(self._toggle_run)
        self.reset_button = QPushButton("Сбросить")
        self.reset_button.clicked.connect(self._reset)
        chain_buttons.addWidget(self.run_button, 1)
        chain_buttons.addWidget(self.reset_button)
        right_layout.addLayout(chain_buttons)

        log_title = QLabel("Лента ответов")
        log_title.setObjectName("SectionTitle")
        right_layout.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Ответы симулятора появятся здесь")
        right_layout.addWidget(self.log, 1)
        body.addWidget(right, 5)

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.simulation.mitas))
        self._row_by_id.clear()
        for row, mita in enumerate(self.simulation.mitas):
            self._row_by_id[mita.character_id] = row
            enabled = QCheckBox()
            enabled.setChecked(mita.enabled)
            enabled.toggled.connect(lambda value, cid=mita.character_id: self._set_enabled(cid, value))
            enabled_host = QWidget()
            enabled_layout = QHBoxLayout(enabled_host)
            enabled_layout.setContentsMargins(0, 0, 0, 0)
            enabled_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            enabled_layout.addWidget(enabled)
            self.table.setCellWidget(row, 0, enabled_host)

            name_item = QTableWidgetItem(mita.display_name)
            name_item.setData(Qt.ItemDataRole.UserRole, mita.character_id)
            self.table.setItem(row, 1, name_item)

            mode = QComboBox()
            mode.addItem("Обычный", MitaMode.NORMAL.value)
            mode.addItem("Охота", MitaMode.HUNT.value)
            mode.addItem("Взаимодействие", MitaMode.INTERACTION.value)
            mode.setCurrentIndex(max(0, mode.findData(mita.mode.value)))
            mode.currentIndexChanged.connect(
                lambda _index, combo=mode, cid=mita.character_id: self._set_mode(cid, combo.currentData())
            )
            self.table.setCellWidget(row, 2, mode)

            distance = QDoubleSpinBox()
            distance.setRange(0.0, 100.0)
            distance.setDecimals(1)
            distance.setSuffix(" м")
            distance.setValue(mita.distance)
            distance.valueChanged.connect(lambda value, cid=mita.character_id: self._set_distance(cid, value))
            self.table.setCellWidget(row, 3, distance)

            points = QSpinBox()
            points.setRange(-999, 999)
            points.setValue(mita.order_points)
            points.valueChanged.connect(lambda value, cid=mita.character_id: self._set_points(cid, value))
            self.table.setCellWidget(row, 4, points)

            priority = QPushButton("Следующая")
            priority.clicked.connect(lambda _checked=False, cid=mita.character_id: self._prioritize(cid))
            self.table.setCellWidget(row, 5, priority)
            self.table.setRowHeight(row, 42)

    def _set_enabled(self, character_id: str, enabled: bool) -> None:
        self.simulation.get_mita(character_id).enabled = enabled
        self._refresh()

    def _set_mode(self, character_id: str, mode: str) -> None:
        self.simulation.get_mita(character_id).mode = MitaMode(str(mode))
        self._refresh()

    def _set_distance(self, character_id: str, distance: float) -> None:
        self.simulation.get_mita(character_id).distance = float(distance)
        self._refresh()

    def _set_points(self, character_id: str, points: int) -> None:
        self.simulation.get_mita(character_id).order_points = int(points)
        self._refresh()

    def _prioritize(self, character_id: str) -> None:
        try:
            self.simulation.set_next_speaker(character_id)
        except SimulationError as exc:
            self._show_error(str(exc))
        self._sync_point_widgets()
        self._refresh()

    def _sync_global_settings(self) -> None:
        self.simulation.auto_dialogue_enabled = self.auto_check.isChecked()
        self.simulation.limit_modifier_percent = float(self.limit_spin.value())
        self._refresh()

    def _begin_player_turn(self) -> None:
        self._stop_timer()
        try:
            result = self.simulation.begin_player_turn(self.player_input.toPlainText())
        except SimulationError as exc:
            self._show_error(str(exc))
            return
        self._append_turn(result)
        self._sync_point_widgets()
        self._refresh()

    def _step(self) -> None:
        self._stop_timer()
        self._perform_step()

    def _perform_step(self) -> bool:
        try:
            result = self.simulation.step()
        except SimulationError as exc:
            self._show_error(str(exc))
            self._refresh()
            return False
        self._append_turn(result)
        self._sync_point_widgets()
        self._refresh()
        return True

    def _toggle_run(self) -> None:
        if self._running:
            self._stop_timer()
            return
        if not self.simulation.pending_speaker_id:
            self._show_error("Сначала отправьте реплику игрока или создайте следующий ход")
            return
        self._running = True
        self.run_button.setText("Пауза")
        self._timer.start()
        self._refresh()

    def _run_one_automatic_turn(self) -> None:
        if not self.simulation.pending_speaker_id or not self._perform_step():
            self._stop_timer()

    def _stop_timer(self) -> None:
        self._timer.stop()
        self._running = False
        self.run_button.setText("Запустить цепочку")

    def _reset(self) -> None:
        self._stop_timer()
        self.simulation.seed = self.seed_spin.value()
        self.simulation.reset()
        self.log.clear()
        self._sync_point_widgets()
        self._refresh()

    def _append_turn(self, result: TurnResult) -> None:
        kind = "AUTO" if result.automatic else "PLAYER"
        self.log.appendPlainText(
            f"#{result.turn_index:02d} [{kind}] {result.speaker_name} "
            f"({result.mode.value}):\n{result.response}\n"
        )

    def _sync_point_widgets(self) -> None:
        for mita in self.simulation.mitas:
            row = self._row_by_id[mita.character_id]
            widget = self.table.cellWidget(row, 4)
            if isinstance(widget, QSpinBox):
                widget.blockSignals(True)
                widget.setValue(mita.order_points)
                widget.blockSignals(False)

    def _refresh(self) -> None:
        active = self.simulation.ordered_active_mitas()
        active_ids = {item.character_id for item in active}
        order_text = " → ".join(item.display_name for item in active) or "—"
        self.order_label.setText(f"Текущая очередь: {order_text}")
        self.status_label.setText(
            f"{self.simulation.stop_reason}\n"
            f"Счётчик Unity: {self.simulation.auto_turn_counter}; "
            f"активных персонажей: {len(active)}"
        )
        self.step_button.setEnabled(bool(self.simulation.pending_speaker_id) and not self._running)
        self.send_button.setEnabled(bool(active) and not self._running)
        self.reset_button.setEnabled(not self._running)
        for mita in self.simulation.mitas:
            row = self._row_by_id.get(mita.character_id)
            if row is None:
                continue
            name_item = self.table.item(row, 1)
            if name_item is not None:
                available = mita.character_id in active_ids
                name_item.setForeground(QColor("#f4f6ff" if available else "#72788d"))
                reason = "доступна" if available else ("выключена" if not mita.enabled else "дальше 25 м")
                name_item.setToolTip(reason)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Симулятор диалога", message)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#Root { background: #0b0d16; color: #eef0f8; }
            QLabel#Title { font-size: 24px; font-weight: 700; color: #ffffff; }
            QLabel#Subtitle, QLabel#Muted { color: #9ca3ba; }
            QLabel#SectionTitle { font-size: 15px; font-weight: 700; color: #ffffff; }
            QLabel#Status { background: #111827; border: 1px solid #26314b; border-radius: 8px; padding: 9px; color: #cbd5ff; }
            QFrame#Card { background: #11131f; border: 1px solid #25293a; border-radius: 10px; }
            QTableWidget, QPlainTextEdit { background: #0d101a; border: 1px solid #292e42; border-radius: 7px; color: #eef0f8; selection-background-color: #3c4778; }
            QHeaderView::section { background: #171a28; color: #b9bfd4; border: 0; border-bottom: 1px solid #30354b; padding: 7px; }
            QPushButton { background: #24283a; border: 1px solid #353b54; border-radius: 7px; padding: 7px 11px; color: #f4f5fb; }
            QPushButton:hover { background: #30364d; }
            QPushButton:disabled { color: #656b7e; background: #181b28; }
            QPushButton#Primary { background: #6757d9; border-color: #8072ef; font-weight: 700; }
            QPushButton#Primary:hover { background: #7565e7; }
            QComboBox, QSpinBox, QDoubleSpinBox { background: #171a28; border: 1px solid #30364b; border-radius: 6px; padding: 5px; color: #f2f3fa; }
            QCheckBox { color: #eef0f8; spacing: 7px; }
            """
        )


def run() -> int:
    app = QApplication.instance() or QApplication([])
    window = DialogueTurnSimulatorWindow()
    window.show()
    return app.exec()
