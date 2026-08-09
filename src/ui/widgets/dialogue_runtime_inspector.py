from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.services import services
from services.contracts import (
    CharacterRegistry,
    DialogueRuntimeSource,
    SandboxDialogueConfig,
)
from services.dialogue_runtime_state import get_dialogue_runtime_state_service
from controllers.sandbox_dialogue_controller import get_sandbox_dialogue_controller
from utils import _


class DialogueRuntimeInspector(QWidget):
    """Operational inspector for local Multi-Mita sessions and Unity mirrors."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DialogueRuntimeInspector")
        self._character_ids: tuple[str, ...] = ()
        self._character_checks: dict[str, QCheckBox] = {}
        self._status_label = QLabel()
        self._participants_label = QLabel()
        self._error_label = QLabel()
        self._conversation_label = QLabel()
        self._turn_label = QLabel()
        self._budget_label = QLabel()
        self._route_label = QLabel()
        self._auto_check = QCheckBox(_("Auto dialogue", "Auto dialogue"))
        self._gm_check = QCheckBox(_("Game Master", "Game Master"))
        self._max_auto_spin = QSpinBox()
        self._max_continue_spin = QSpinBox()
        self._gm_repeat_spin = QSpinBox()
        self._start_button = QPushButton(_("Start sandbox", "Start sandbox"))
        self._stop_button = QPushButton(_("Stop", "Stop"))
        self._step_button = QPushButton(_("Step once", "Step once"))
        self._character_host = QWidget()
        self._build_ui()
        self._populate_characters()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        intro = QLabel(
            _(
                "Local Multi-Mita runtime. Settings apply only to the current sandbox session.",
                "Local Multi-Mita runtime. Settings apply only to the current sandbox session.",
            )
        )
        intro.setWordWrap(True)
        intro.setObjectName("SandboxInspectorHint")
        layout.addWidget(intro)

        status_frame = QFrame()
        status_frame.setObjectName("SandboxInspectorCard")
        status_layout = QFormLayout(status_frame)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setHorizontalSpacing(12)
        status_layout.setVerticalSpacing(5)
        self._add_status_row(status_layout, "Source", self._status_label)
        self._add_status_row(status_layout, "Conversation", self._conversation_label)
        self._add_status_row(status_layout, "Turn", self._turn_label)
        self._add_status_row(status_layout, "Budget", self._budget_label)
        self._add_status_row(status_layout, "Route", self._route_label)
        layout.addWidget(status_frame)

        participants_title = QLabel(_("Participants", "Participants"))
        participants_title.setObjectName("SandboxInspectorSectionTitle")
        layout.addWidget(participants_title)

        character_scroll = QScrollArea()
        character_scroll.setWidgetResizable(True)
        character_scroll.setFrameShape(QFrame.Shape.NoFrame)
        character_scroll.setMaximumHeight(150)
        self._character_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._character_layout = QVBoxLayout(self._character_host)
        self._character_layout.setContentsMargins(4, 2, 4, 2)
        self._character_layout.setSpacing(3)
        character_scroll.setWidget(self._character_host)
        layout.addWidget(character_scroll)

        controls_frame = QFrame()
        controls_frame.setObjectName("SandboxInspectorCard")
        controls_layout = QFormLayout(controls_frame)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setHorizontalSpacing(12)
        controls_layout.setVerticalSpacing(5)
        controls_layout.addRow(self._auto_check)
        controls_layout.addRow(self._gm_check)
        self._configure_spin(self._max_auto_spin, 0, 100, 6)
        self._configure_spin(self._max_continue_spin, 0, 100, 3)
        self._configure_spin(self._gm_repeat_spin, 0, 20, 2)
        controls_layout.addRow(_("Max auto turns", "Max auto turns"), self._max_auto_spin)
        controls_layout.addRow(_("Max continues", "Max continues"), self._max_continue_spin)
        controls_layout.addRow(_("GM repeat", "GM repeat"), self._gm_repeat_spin)
        layout.addWidget(controls_frame)

        self._participants_label.setWordWrap(True)
        self._participants_label.setObjectName("SandboxInspectorHint")
        layout.addWidget(self._participants_label)

        self._error_label.setWordWrap(True)
        self._error_label.setObjectName("SandboxInspectorError")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self._start_button.clicked.connect(self._start_session)
        self._stop_button.clicked.connect(self._stop_session)
        self._step_button.clicked.connect(self._step_once)
        buttons.addWidget(self._start_button, 1)
        buttons.addWidget(self._step_button)
        buttons.addWidget(self._stop_button)
        layout.addLayout(buttons)
        layout.addStretch(1)

    @staticmethod
    def _configure_spin(spin: QSpinBox, minimum: int, maximum: int, value: int) -> None:
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setMaximumWidth(90)

    @staticmethod
    def _add_status_row(form: QFormLayout, title: str, value: QLabel) -> None:
        value.setText("-")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        form.addRow(title, value)

    def _populate_characters(self) -> None:
        registry = services().get_optional(CharacterRegistry)
        ids = tuple(
            str(item).strip()
            for item in (registry.all_ids() if registry is not None else ())
            if str(item).strip()
        )
        if ids == self._character_ids:
            return
        self._character_ids = ids
        while self._character_layout.count():
            item = self._character_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._character_checks = {}
        for character_id in ids:
            display_name = registry.name_of(character_id) if registry is not None else character_id
            check = QCheckBox(f"{display_name} ({character_id})")
            check.setProperty("character_id", character_id)
            self._character_layout.addWidget(check)
            self._character_checks[character_id] = check
        if not ids:
            empty = QLabel(_("No characters loaded", "No characters loaded"))
            empty.setObjectName("SandboxInspectorHint")
            self._character_layout.addWidget(empty)
        self._character_layout.addStretch(1)

    def _selected_character_ids(self) -> tuple[str, ...]:
        return tuple(
            character_id
            for character_id, check in self._character_checks.items()
            if check.isChecked()
        )

    def _start_session(self) -> None:
        selected = self._selected_character_ids()
        if len(selected) < 2:
            self._show_error(_("Select at least two characters.", "Select at least two characters."))
            return
        config = SandboxDialogueConfig(
            participant_character_ids=selected,
            initial_character_id=selected[0],
            auto_dialogue_enabled=self._auto_check.isChecked(),
            max_auto_turns=self._max_auto_spin.value(),
            max_consecutive_continues=self._max_continue_spin.value(),
            game_master_enabled=self._gm_check.isChecked(),
            gm_repeat=self._gm_repeat_spin.value(),
        )
        if not get_sandbox_dialogue_controller().start_session(config):
            self._show_error(
                _(
                    "Cannot start sandbox while a Unity dialogue is active.",
                    "Cannot start sandbox while a Unity dialogue is active.",
                )
            )
        else:
            self._clear_error()
            self.refresh()

    def _stop_session(self) -> None:
        get_sandbox_dialogue_controller().stop_session()
        self._clear_error()
        self.refresh()

    def _step_once(self) -> None:
        if not get_sandbox_dialogue_controller().step_once():
            self._show_error(
                _("Sandbox is busy or not running.", "Sandbox is busy or not running.")
            )

    def _show_error(self, text: str) -> None:
        self._error_label.setText(text)
        self._error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.setVisible(False)

    def refresh(self) -> None:
        self._populate_characters()
        snapshot = get_dialogue_runtime_state_service().snapshot()
        controller = get_sandbox_dialogue_controller()
        source = snapshot.source
        unity_active = source is DialogueRuntimeSource.UNITY
        sandbox_active = controller.active and source is DialogueRuntimeSource.SANDBOX

        self._status_label.setText(source.value)
        self._conversation_label.setText(snapshot.conversation_id or "-")
        self._turn_label.setText(str(snapshot.turn_index) if snapshot.is_active else "-")
        if snapshot.is_active:
            self._budget_label.setText(
                f"{snapshot.auto_turns_used}/{snapshot.auto_turns_max} ({snapshot.auto_turns_remaining} left)"
            )
        else:
            self._budget_label.setText("-")
        route = snapshot.pending_route_kind
        if route:
            route = f"{route} -> {snapshot.pending_route_target_actor_id}"
        self._route_label.setText(route or "-")
        participant_names = [
            item.display_name or item.character_id
            for item in snapshot.participants
            if item.character_id and item.character_id != "GameMaster"
        ]
        self._participants_label.setText(
            _("Active: ", "Active: ") + (", ".join(participant_names) or "-")
        )

        for widget in (
            self._auto_check,
            self._gm_check,
            self._max_auto_spin,
            self._max_continue_spin,
            self._gm_repeat_spin,
        ):
            widget.setEnabled(not unity_active and not sandbox_active)
        for check in self._character_checks.values():
            check.setEnabled(not unity_active and not sandbox_active)
        self._start_button.setEnabled(not unity_active and not sandbox_active)
        self._step_button.setEnabled(sandbox_active)
        self._stop_button.setEnabled(sandbox_active)

        if sandbox_active:
            selected = {item.character_id for item in snapshot.participants}
            for character_id, check in self._character_checks.items():
                check.blockSignals(True)
                check.setChecked(character_id in selected)
                check.blockSignals(False)
        elif unity_active:
            self._clear_error()
