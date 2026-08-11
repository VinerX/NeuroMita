from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
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
    QLineEdit,
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

from ui.widgets.number_stepper import NumberStepper

from .core import DialogueSimulation, MitaMode, SimulationError, create_default_simulation
from .protocol import UnityClientEndpoint, UnityProtocolClient
from .session import SessionEvent, UnityLikeDialogueSession


class _ProtocolBridge(QObject):
    message_received = pyqtSignal(object)
    state_changed = pyqtSignal(bool, str)


class DialogueTurnSimulatorWindow(QMainWindow):
    def __init__(self, simulation: DialogueSimulation | None = None) -> None:
        super().__init__()
        self.simulation = simulation or create_default_simulation()
        self._row_by_id: dict[str, int] = {}
        self._client: UnityProtocolClient | None = None
        self._session: UnityLikeDialogueSession | None = None
        self._connected = False
        self._connection_message = "Отключено"
        self._bridge = _ProtocolBridge(self)
        self._bridge.message_received.connect(self._handle_server_message)
        self._bridge.state_changed.connect(self._handle_connection_state)
        self.setWindowTitle("NeuroMita Headless Unity Dialogue Client")
        self.resize(1360, 820)
        self.setMinimumSize(1080, 680)
        self._build_ui()
        self._apply_style()
        self._populate_table()
        self._sync_policy_widgets()
        self._refresh()
        QTimer.singleShot(0, self._connect_client)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Headless Unity-клиент диалогов NeuroMita")
        title.setObjectName("Title")
        subtitle = QLabel(
            "Работает по настоящему TCP-протоколу Unity: handshake, settings, create_task и push task_update. "
            "Состав, доступность, очередь, лимиты, продолжения и GameMaster остаются на стороне этого клиента."
        )
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        connection = QFrame()
        connection.setObjectName("Card")
        connection_layout = QGridLayout(connection)
        connection_layout.setContentsMargins(14, 12, 14, 12)
        connection_layout.setHorizontalSpacing(10)
        self.host_edit = QLineEdit("127.0.0.1")
        self.host_edit.setMaximumWidth(180)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(12345)
        self.connect_button = QPushButton("Подключиться")
        self.connect_button.setObjectName("Primary")
        self.connect_button.clicked.connect(self._toggle_connection)
        self.connection_label = QLabel("Отключено")
        self.connection_label.setObjectName("ConnectionStatus")
        connection_layout.addWidget(QLabel("Host"), 0, 0)
        connection_layout.addWidget(self.host_edit, 0, 1)
        connection_layout.addWidget(QLabel("Port"), 0, 2)
        connection_layout.addWidget(self.port_spin, 0, 3)
        connection_layout.addWidget(self.connect_button, 0, 4)
        connection_layout.addWidget(self.connection_label, 0, 5)
        connection_layout.setColumnStretch(5, 1)
        layout.addWidget(connection)

        policy = QFrame()
        policy.setObjectName("Card")
        policy_layout = QGridLayout(policy)
        policy_layout.setContentsMargins(14, 10, 14, 10)
        policy_layout.setHorizontalSpacing(10)
        self.auto_check = QCheckBox("Автодиалог")
        self.auto_check.toggled.connect(self._read_policy_widgets)
        self.turn_limit_spin = NumberStepper()
        self.turn_limit_spin.setRange(1, 24)
        self.turn_limit_spin.valueChanged.connect(self._read_policy_widgets)
        self.continue_spin = NumberStepper()
        self.continue_spin.setRange(0, 12)
        self.continue_spin.valueChanged.connect(self._read_policy_widgets)
        self.gm_check = QCheckBox("GameMaster")
        self.gm_check.toggled.connect(self._read_policy_widgets)
        self.gm_repeat_spin = NumberStepper()
        self.gm_repeat_spin.setRange(1, 100)
        self.gm_repeat_spin.valueChanged.connect(self._read_policy_widgets)
        policy_layout.addWidget(self.auto_check, 0, 0)
        self.turn_limit_label = QLabel("Максимум ходов в цепочке")
        policy_layout.addWidget(self.turn_limit_label, 0, 1)
        policy_layout.addWidget(self.turn_limit_spin, 0, 2)
        policy_layout.addWidget(QLabel("Продолжений"), 0, 3)
        policy_layout.addWidget(self.continue_spin, 0, 4)
        policy_layout.addWidget(self.gm_check, 0, 5)
        policy_layout.addWidget(QLabel("Проверка через"), 0, 6)
        policy_layout.addWidget(self.gm_repeat_spin, 0, 7)
        policy_layout.setColumnStretch(8, 1)
        layout.addWidget(policy)

        body = QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, 1)

        left = QFrame()
        left.setObjectName("Card")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        left_title = QLabel("Unity-side состояние персонажей")
        left_title.setObjectName("SectionTitle")
        left_layout.addWidget(left_title)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(("Вкл.", "Персонаж", "Режим", "Дистанция", "Очки", "Приоритет"))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self.table, 1)
        body.addWidget(left, 7)

        right = QFrame()
        right.setObjectName("Card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)
        right_title = QLabel("Живой диалог")
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
        buttons = QHBoxLayout()
        self.send_button = QPushButton("Отправить как Unity")
        self.send_button.setObjectName("Primary")
        self.send_button.clicked.connect(self._submit_player_message)
        self.reset_button = QPushButton("Новый диалог")
        self.reset_button.clicked.connect(self._reset)
        buttons.addWidget(self.send_button, 1)
        buttons.addWidget(self.reset_button)
        right_layout.addLayout(buttons)
        log_title = QLabel("Wire/runtime журнал")
        log_title.setObjectName("SectionTitle")
        right_layout.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Здесь появятся реальные ответы NeuroMita")
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

    def _connect_client(self) -> None:
        self._disconnect_client()
        endpoint = UnityClientEndpoint(host=self.host_edit.text().strip() or "127.0.0.1", port=self.port_spin.value())
        self._client = UnityProtocolClient(
            endpoint,
            on_message=lambda message: self._bridge.message_received.emit(message),
            on_state=lambda connected, text: self._bridge.state_changed.emit(connected, text),
        )
        self._session = UnityLikeDialogueSession(self.simulation, self._client, on_event=self._handle_session_event)
        self._connection_message = f"Подключение к {endpoint.host}:{endpoint.port}…"
        self._client.start()
        self._refresh()

    def _disconnect_client(self) -> None:
        client = self._client
        self._client = None
        self._session = None
        if client is not None:
            client.stop()
        self._connected = False

    def _toggle_connection(self) -> None:
        if self._client is not None:
            self._disconnect_client()
            self._connection_message = "Отключено"
            self._refresh()
            return
        self._connect_client()

    def _handle_connection_state(self, connected: bool, message: str) -> None:
        was_connected = self._connected
        self._connected = connected
        self._connection_message = message
        if was_connected and not connected and self._session is not None:
            self._session.handle_connection_lost()
        self._refresh()

    def _handle_server_message(self, message: object) -> None:
        if not isinstance(message, dict) or self._session is None:
            return
        self._session.handle_server_message(message)
        self._sync_policy_widgets()
        self._sync_point_widgets()
        self._refresh()

    def _handle_session_event(self, event: SessionEvent) -> None:
        if event.kind == "turn" and event.turn is not None:
            turn = event.turn
            kind = "AUTO" if turn.automatic else "PLAYER"
            self.log.appendPlainText(
                f"#{turn.turn_index:02d} [{kind}] {turn.speaker_name} ({turn.mode.value}):\n"
                f"{turn.response or '[только structured intents]'}\n"
            )
        elif event.kind in {"error", "warning", "directive", "protocol"}:
            self.log.appendPlainText(f"[{event.kind.upper()}] {event.message}\n")
        elif event.kind == "asr" and event.message:
            self.player_input.setPlainText(event.message)
        self._sync_point_widgets()
        self._refresh()

    def _submit_player_message(self) -> None:
        session = self._session
        if session is None:
            self._show_error("Клиент не запущен")
            return
        try:
            session.submit_player_message(self.player_input.toPlainText())
        except (SimulationError, ConnectionError, OSError) as exc:
            self._show_error(str(exc))
        self._sync_point_widgets()
        self._refresh()

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

    def _read_policy_widgets(self) -> None:
        policy = self.simulation.policy
        policy.auto_dialogue_enabled = self.auto_check.isChecked()
        policy.max_chain_turns = self.turn_limit_spin.value()
        policy.max_continues = self.continue_spin.value()
        policy.game_master_enabled = self.gm_check.isChecked()
        policy.game_master_repeat = self.gm_repeat_spin.value()
        self._sync_policy_dependencies()
        self._refresh()

    def _sync_policy_widgets(self) -> None:
        policy = self.simulation.policy
        widgets = (self.auto_check, self.turn_limit_spin, self.continue_spin, self.gm_check, self.gm_repeat_spin)
        for widget in widgets:
            widget.blockSignals(True)
        self.auto_check.setChecked(policy.auto_dialogue_enabled)
        self.turn_limit_spin.setValue(policy.max_chain_turns)
        self.continue_spin.setValue(policy.max_continues)
        self.gm_check.setChecked(policy.game_master_enabled)
        self.gm_repeat_spin.setValue(policy.game_master_repeat)
        for widget in widgets:
            widget.blockSignals(False)
        self._sync_policy_dependencies()

    def _sync_policy_dependencies(self) -> None:
        enabled = self.auto_check.isChecked()
        self.turn_limit_label.setEnabled(enabled)
        self.turn_limit_spin.setEnabled(enabled)

    def _reset(self) -> None:
        if self._session is not None and self._session.busy:
            self._show_error("Дождитесь завершения текущей задачи")
            return
        if self._session is not None:
            self._session.reset()
        else:
            self.simulation.reset()
        self.log.clear()
        self._sync_point_widgets()
        self._refresh()

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
        busy = bool(self._session and self._session.busy)
        self.status_label.setText(
            f"{self.simulation.stop_reason}\n"
            f"Ходов в цепочке: {self.simulation.chain_turn_count}; активных Мит: {len(active)}; "
            f"settings revision: {self.simulation.policy.settings_revision}"
        )
        self.connection_label.setText(self._connection_message)
        self.connection_label.setProperty("connected", self._connected)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)
        self.connect_button.setText("Отключиться" if self._client is not None else "Подключиться")
        self.host_edit.setEnabled(self._client is None)
        self.port_spin.setEnabled(self._client is None)
        self.send_button.setEnabled(self._connected and bool(active) and not busy)
        self.reset_button.setEnabled(not busy)
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
        QMessageBox.warning(self, "Headless Unity-клиент", message)

    def closeEvent(self, event: Any) -> None:
        self._disconnect_client()
        super().closeEvent(event)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#Root { background: #0b0d16; color: #eef0f8; }
            QLabel#Title { font-size: 24px; font-weight: 700; color: #ffffff; }
            QLabel#Subtitle, QLabel#Muted { color: #9ca3ba; }
            QLabel#SectionTitle { font-size: 15px; font-weight: 700; color: #ffffff; }
            QLabel#Status { background: #111827; border: 1px solid #26314b; border-radius: 8px; padding: 9px; color: #cbd5ff; }
            QLabel#ConnectionStatus { color: #e39b64; font-weight: 600; }
            QLabel#ConnectionStatus[connected="true"] { color: #75d99b; }
            QFrame#Card { background: #11131f; border: 1px solid #25293a; border-radius: 10px; }
            QTableWidget, QPlainTextEdit, QLineEdit { background: #0d101a; border: 1px solid #292e42; border-radius: 7px; color: #eef0f8; selection-background-color: #3c4778; }
            QHeaderView::section { background: #171a28; color: #b9bfd4; border: 0; border-bottom: 1px solid #30354b; padding: 7px; }
            QPushButton { background: #24283a; border: 1px solid #353b54; border-radius: 7px; padding: 7px 11px; color: #f4f5fb; }
            QPushButton:hover { background: #30364d; }
            QPushButton:disabled { color: #656b7e; background: #181b28; }
            QPushButton#Primary { background: #6757d9; border-color: #8072ef; font-weight: 700; }
            QPushButton#Primary:hover { background: #7565e7; }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: #171a28; border: 1px solid #30364b; border-radius: 6px; padding: 5px; color: #f2f3fa; }
            QWidget#NumberStepper { background: #171a28; border: 1px solid #30364b; border-radius: 8px; }
            QSpinBox#NumberStepperValue { background: transparent; border: 0; border-radius: 0; padding: 0 6px; font-weight: 700; }
            QToolButton#NumberStepperDecrease, QToolButton#NumberStepperIncrease { min-width: 34px; max-width: 34px; min-height: 38px; max-height: 38px; background: #1c2030; border: 0; color: #aeb5cc; font-size: 16px; }
            QToolButton#NumberStepperDecrease { border-right: 1px solid #30364b; border-top-left-radius: 7px; border-bottom-left-radius: 7px; }
            QToolButton#NumberStepperIncrease { border-left: 1px solid #30364b; border-top-right-radius: 7px; border-bottom-right-radius: 7px; }
            QToolButton#NumberStepperDecrease:hover, QToolButton#NumberStepperIncrease:hover { background: #34305a; color: #ffffff; }
            QWidget#NumberStepper:disabled, QSpinBox#NumberStepperValue:disabled, QToolButton#NumberStepperDecrease:disabled, QToolButton#NumberStepperIncrease:disabled { color: #656b7e; background: #181b28; }
            QCheckBox { color: #eef0f8; spacing: 7px; }
            """
        )


def run() -> int:
    app = QApplication.instance() or QApplication([])
    window = DialogueTurnSimulatorWindow()
    window.show()
    return app.exec()
