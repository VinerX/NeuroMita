from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from controllers.sandbox_dialogue_controller import get_sandbox_dialogue_controller
from core.services import services
from services.contracts import (
    CharacterRegistry,
    DialogueRuntimeSource,
    SettingsService,
    SandboxDialogueConfig,
)
from services.dialogue_runtime_state import get_dialogue_runtime_state_service
from utils import _


class DialogueRuntimeInspector(QWidget):
    """Readable operational panel for local Multi-Mita sessions."""

    _MODE_LABELS = {
        "off": ("Off", "Off"),
        "automatic": ("Automatic", "Automatic"),
        "step": ("Step-by-step", "Step-by-step"),
    }

    _STATUS_LABELS = {
        "inactive": "Inactive",
        "ready": "Ready",
        "waiting_model": "Waiting for the model",
        "automatic_running": "Automatic dialogue is running",
        "manual_route_ready": "Next turn is ready",
        "budget_exhausted": "Automatic dialogue finished",
        "auto_disabled": "Automatic dialogue is disabled",
        "route_rejected": "Automatic routing was rejected",
        "task_failed": "The model response failed",
        "no_next_route": "No additional turn requested",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DialogueRuntimeInspector")
        self.setMinimumWidth(0)
        self._character_ids: tuple[str, ...] = ()
        self._character_checks: dict[str, QCheckBox] = {}
        self._character_names: dict[str, str] = {}
        self._status_label = QLabel()
        self._status_detail_label = QLabel()
        self._participants_label = QLabel()
        self._error_label = QLabel()
        self._conversation_label = QLabel()
        self._turn_label = QLabel()
        self._budget_label = QLabel()
        self._route_label = QLabel()
        self._technical_label = QLabel()
        self._technical_toggle = QToolButton()
        self._mode_group = QButtonGroup(self)
        self._mode_buttons: dict[str, QPushButton] = {}
        self._initial_combo = QComboBox()
        self._gm_check = QCheckBox(_("GameMaster", "GameMaster"))
        self._max_auto_spin = QSpinBox()
        self._auto_turn_mode_combo = QComboBox()
        self._auto_turn_budget_hint = QLabel()
        self._auto_turns_per_participant_spin = QSpinBox()
        self._max_continue_spin = QSpinBox()
        self._gm_repeat_spin = QSpinBox()
        self._gm_instruction_edit = QPlainTextEdit()
        self._start_button = QPushButton(_("Start session", "Start session"))
        self._stop_button = QPushButton(_("Stop", "Stop"))
        self._step_button = QPushButton(_("Run next turn", "Run next turn"))
        self._character_host = QWidget()
        self._build_ui()
        self._populate_characters()
        self._set_dialogue_mode("automatic")
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
                "Configure a local Multi-Mita session. These controls apply only until the session stops.",
                "Configure a local Multi-Mita session. These controls apply only until the session stops.",
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
        self._add_status_row(status_layout, "Current source", self._status_label)
        self._add_status_row(status_layout, "Status", self._status_detail_label)
        self._add_status_row(status_layout, "Conversation", self._conversation_label)
        self._add_status_row(status_layout, "Turn", self._turn_label)
        self._add_status_row(status_layout, "Budget", self._budget_label)
        self._add_status_row(status_layout, "Next route", self._route_label)
        layout.addWidget(status_frame)

        participants_title = QLabel(_("Participants", "Participants"))
        participants_title.setObjectName("SandboxInspectorSectionTitle")
        layout.addWidget(participants_title)

        character_scroll = QScrollArea()
        character_scroll.setObjectName("DialogueParticipantsList")
        character_scroll.setWidgetResizable(True)
        character_scroll.setFrameShape(QFrame.Shape.NoFrame)
        character_scroll.setMinimumHeight(230)
        character_scroll.setMaximumHeight(280)
        self._character_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._character_layout = QVBoxLayout(self._character_host)
        self._character_layout.setContentsMargins(4, 2, 4, 2)
        self._character_layout.setSpacing(3)
        character_scroll.setWidget(self._character_host)
        layout.addWidget(character_scroll)

        session_frame = QFrame()
        session_frame.setObjectName("SandboxInspectorCard")
        session_layout = QFormLayout(session_frame)
        session_layout.setContentsMargins(10, 8, 10, 8)
        session_layout.setHorizontalSpacing(12)
        session_layout.setVerticalSpacing(6)
        session_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        session_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        mode_label = QLabel(_("Dialogue mode", "Dialogue mode"))
        mode_label.setObjectName("SandboxInspectorSectionTitle")
        session_layout.addRow(mode_label)

        mode_host = QWidget()
        mode_host.setObjectName("DialogueModeControl")
        mode_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        mode_layout = QHBoxLayout(mode_host)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(4)
        for mode in ("off", "automatic", "step"):
            button = QPushButton(_(*self._MODE_LABELS[mode]))
            button.setObjectName("DialogueModeSegment")
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.setProperty("mode", mode)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            self._mode_group.addButton(button)
            self._mode_buttons[mode] = button
            mode_layout.addWidget(button, 1)
        self._mode_group.buttonClicked.connect(
            lambda button: self._set_dialogue_mode(str(button.property("mode")))
        )
        session_layout.addRow(mode_host)

        self._initial_combo.setObjectName("DialogueInitialCharacter")
        session_layout.addRow(_("Starts with", "Starts with"), self._initial_combo)
        self._auto_turn_mode_combo.addItem(
            _("Fixed limit", "Fixed limit"),
            userData="fixed",
        )
        self._auto_turn_mode_combo.addItem(
            _("One per selected Mita", "One per selected Mita"),
            userData="per_participant",
        )
        saved_auto_turn_mode = self._global_dialogue_setting(
            "DIALOGUE_AUTO_TURN_COUNT_MODE",
            "per_participant",
        )
        saved_auto_turn_mode_index = self._auto_turn_mode_combo.findData(
            saved_auto_turn_mode
        )
        if saved_auto_turn_mode_index >= 0:
            self._auto_turn_mode_combo.setCurrentIndex(saved_auto_turn_mode_index)
        self._auto_turn_mode_combo.currentIndexChanged.connect(
            self._refresh_auto_turn_budget_hint
        )
        session_layout.addRow(
            _("Auto-turn budget", "Auto-turn budget"),
            self._auto_turn_mode_combo,
        )
        self._auto_turn_budget_hint.setObjectName("SandboxInspectorHint")
        self._auto_turn_budget_hint.setWordWrap(True)
        session_layout.addRow("", self._auto_turn_budget_hint)
        self._configure_spin(self._max_auto_spin, 0, 24, 6)
        self._configure_spin(self._auto_turns_per_participant_spin, 1, 24, 1)
        try:
            self._auto_turns_per_participant_spin.setValue(
                max(
                    1,
                    min(
                        24,
                        int(
                            self._global_dialogue_setting(
                                "DIALOGUE_AUTO_TURNS_PER_PARTICIPANT",
                                "1",
                            )
                        ),
                    ),
                )
            )
        except (TypeError, ValueError):
            pass
        self._configure_spin(self._max_continue_spin, 0, 12, 3)
        self._configure_spin(self._gm_repeat_spin, 1, 100, 2)
        session_layout.addRow(
            _("Turns per selected Mita", "Turns per selected Mita"),
            self._auto_turns_per_participant_spin,
        )
        session_layout.addRow(
            _("Fixed automatic turns", "Fixed automatic turns"),
            self._max_auto_spin,
        )
        session_layout.addRow(
            _("Same-Mita continuations", "Same-Mita continuations"),
            self._max_continue_spin,
        )
        session_layout.addRow(self._gm_check)
        session_layout.addRow(
            _("Mita replies between GM checks", "Mita replies between GM checks"),
            self._gm_repeat_spin,
        )
        self._gm_instruction_edit.setObjectName("DialogueGameMasterInstruction")
        self._gm_instruction_edit.setFixedHeight(74)
        self._gm_instruction_edit.setPlaceholderText(
            _("Optional task for this session's GameMaster", "Optional task for this session's GameMaster")
        )
        self._gm_instruction_edit.setPlainText(self._global_gm_instruction())
        session_layout.addRow(
            _("GameMaster task (updates the next GM turn)", "GameMaster task (updates the next GM turn)"),
            self._gm_instruction_edit,
        )
        self._gm_instruction_edit.textChanged.connect(
            self._update_live_gm_instruction
        )
        layout.addWidget(session_frame)

        self._participants_label.setWordWrap(True)
        self._participants_label.setObjectName("SandboxInspectorHint")
        layout.addWidget(self._participants_label)

        self._technical_toggle.setText(
            _("Show technical details", "Show technical details")
        )
        self._technical_toggle.setCheckable(True)
        self._technical_toggle.setObjectName("DialogueTechnicalDetailsToggle")
        self._technical_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._technical_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._technical_toggle.setToolTip(
            _("Show protocol and routing diagnostics", "Show protocol and routing diagnostics")
        )
        self._technical_toggle.toggled.connect(self._toggle_technical_details)
        layout.addWidget(self._technical_toggle)

        self._technical_label.setObjectName("DialogueTechnicalDetails")
        self._technical_label.setWordWrap(True)
        self._technical_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._technical_label.setVisible(False)
        layout.addWidget(self._technical_label)

        self._error_label.setWordWrap(True)
        self._error_label.setObjectName("SandboxInspectorError")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self._start_button.setObjectName("DialoguePrimaryAction")
        self._start_button.clicked.connect(self._start_session)
        self._stop_button.clicked.connect(self._stop_session)
        self._step_button.clicked.connect(self._step_once)
        buttons.addWidget(self._start_button, 1)
        buttons.addWidget(self._step_button)
        buttons.addWidget(self._stop_button)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def _toggle_technical_details(self, visible: bool) -> None:
        self._technical_label.setVisible(bool(visible))
        self._technical_toggle.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
        )
        self._technical_toggle.setText(
            _(
                "Hide technical details" if visible else "Show technical details",
                "Hide technical details" if visible else "Show technical details",
            )
        )
        self._technical_toggle.setProperty("expanded", bool(visible))
        style = self._technical_toggle.style()
        if style is not None:
            style.unpolish(self._technical_toggle)
            style.polish(self._technical_toggle)
        self._technical_toggle.update()

    @staticmethod
    def _configure_spin(spin: QSpinBox, minimum: int, maximum: int, value: int) -> None:
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setMaximumWidth(100)

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
        self._character_names = {}
        for character_id in ids:
            display_name = (
                str(registry.name_of(character_id) or character_id)
                if registry is not None
                else character_id
            )
            self._character_names[character_id] = display_name
            row = QFrame()
            row.setObjectName("DialogueParticipantRow")
            row.setProperty("character_id", character_id)
            row.setMinimumHeight(46)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 5, 8, 5)
            row_layout.setSpacing(9)
            check = QCheckBox()
            check.setAccessibleName(display_name)
            check.setProperty("character_id", character_id)
            check.setToolTip(character_id)
            check.stateChanged.connect(self._sync_initial_options)
            check.stateChanged.connect(self._refresh_selection_controls)
            row_layout.addWidget(check, 0, Qt.AlignmentFlag.AlignTop)
            participant_text = QWidget()
            participant_text_layout = QVBoxLayout(participant_text)
            participant_text_layout.setContentsMargins(0, 0, 0, 0)
            participant_text_layout.setSpacing(1)
            name_label = QLabel(display_name)
            name_label.setObjectName("DialogueParticipantName")
            name_label.setWordWrap(True)
            participant_text_layout.addWidget(name_label)
            id_label = QLabel(character_id)
            id_label.setObjectName("DialogueParticipantId")
            id_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            id_label.setWordWrap(True)
            participant_text_layout.addWidget(id_label)
            row_layout.addWidget(participant_text, 1)
            self._character_layout.addWidget(row)
            self._character_checks[character_id] = check
        if not ids:
            empty = QLabel(_("No characters loaded", "No characters loaded"))
            empty.setObjectName("SandboxInspectorHint")
            self._character_layout.addWidget(empty)
        self._character_layout.addStretch(1)
        self._sync_initial_options()

    def _selected_character_ids(self) -> tuple[str, ...]:
        return tuple(
            character_id
            for character_id, check in self._character_checks.items()
            if check.isChecked()
        )

    def _sync_initial_options(self, *_args) -> None:
        selected = self._selected_character_ids()
        current = self._initial_combo.currentData()
        self._initial_combo.blockSignals(True)
        try:
            self._initial_combo.clear()
            for character_id in selected:
                self._initial_combo.addItem(
                    self._character_names.get(character_id, character_id),
                    userData=character_id,
                )
            target = current if current in selected else (selected[0] if selected else "")
            if target:
                self._initial_combo.setCurrentIndex(
                    max(0, self._initial_combo.findData(target))
                )
        finally:
            self._initial_combo.blockSignals(False)
        self._refresh_selection_controls()

    @staticmethod
    def _global_dialogue_setting(key: str, default: str = "") -> str:
        settings = services().get_optional(SettingsService)
        if settings is None:
            return default
        return str(settings.get(key, default) or default)

    @classmethod
    def _global_gm_instruction(cls) -> str:
        return cls._global_dialogue_setting("GM_SMALL_PROMPT")

    def _refresh_auto_turn_budget_hint(self, *_args) -> None:
        participant_count = sum(
            1
            for character_id in self._selected_character_ids()
            if character_id.casefold() != "gamemaster"
        )
        mode = str(self._auto_turn_mode_combo.currentData() or "fixed")
        if mode == "per_participant":
            self._auto_turn_budget_hint.setText(
                _("Automatic turns: ", "Automatic turns: ")
                + str(
                    participant_count
                    * self._auto_turns_per_participant_spin.value()
                )
                + _(
                    " (active Mitas × turns per Mita)",
                    " (active Mitas × turns per Mita)",
                )
            )
        else:
            self._auto_turn_budget_hint.setText(
                _("Fixed automatic-turn limit: ", "Fixed automatic-turn limit: ")
                + str(self._max_auto_spin.value())
            )

    def _refresh_selection_controls(self, *_args) -> None:
        self._refresh_auto_turn_budget_hint()
        snapshot = get_dialogue_runtime_state_service().snapshot()
        ui_state = get_sandbox_dialogue_controller().ui_state()
        self._start_button.setEnabled(
            snapshot.source is not DialogueRuntimeSource.UNITY
            and not ui_state.active
            and len(self._selected_character_ids()) >= 2
        )
    def _dialogue_mode(self) -> str:
        for mode, button in self._mode_buttons.items():
            if button.isChecked():
                return mode
        return "automatic"

    def _set_dialogue_mode(self, mode: str) -> None:
        mode = mode if mode in self._mode_buttons else "automatic"
        for key, button in self._mode_buttons.items():
            checked = key == mode
            button.setChecked(checked)
            button.setProperty("checked", checked)
            button.style().unpolish(button)
            button.style().polish(button)
        self._mode_group.setExclusive(True)

    @staticmethod
    def _mode_to_config(mode: str) -> tuple[bool, bool]:
        return {
            "off": (False, False),
            "automatic": (True, False),
            "step": (True, True),
        }.get(mode, (True, False))

    def _start_session(self) -> None:
        selected = self._selected_character_ids()
        if len(selected) < 2:
            self._show_error(
                _("Select at least two characters.", "Select at least two characters.")
            )
            return
        initial = self._initial_combo.currentData() or selected[0]
        auto_enabled, manual_step = self._mode_to_config(self._dialogue_mode())
        config = SandboxDialogueConfig(
            participant_character_ids=selected,
            initial_character_id=str(initial),
            auto_dialogue_enabled=auto_enabled,
            manual_step_mode=manual_step,
            max_auto_turns=self._max_auto_spin.value(),
            auto_turn_count_mode=str(self._auto_turn_mode_combo.currentData() or "fixed"),
            auto_turns_per_participant=self._auto_turns_per_participant_spin.value(),
            max_consecutive_continues=self._max_continue_spin.value(),
            game_master_enabled=self._gm_check.isChecked(),
            gm_repeat=self._gm_repeat_spin.value(),
            gm_instruction=self._gm_instruction_edit.toPlainText().strip(),
        )
        if not get_sandbox_dialogue_controller().start_session(config):
            self._show_error(
                _(
                    "Cannot start a sandbox session while Unity dialogue is active.",
                    "Cannot start a sandbox session while Unity dialogue is active.",
                )
            )
        else:
            self._clear_error()
            self.refresh()

    def _update_live_gm_instruction(self) -> None:
        controller = get_sandbox_dialogue_controller()
        if controller.active:
            controller.update_gm_instruction(
                self._gm_instruction_edit.toPlainText()
            )

    def _stop_session(self) -> None:
        get_sandbox_dialogue_controller().stop_session()
        self._clear_error()
        self.refresh()

    def _step_once(self) -> None:
        if not get_sandbox_dialogue_controller().step_once():
            self._show_error(
                _("The session is busy or no manual route is ready.", "The session is busy or no manual route is ready.")
            )

    def _show_error(self, text: str) -> None:
        self._error_label.setText(text)
        self._error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.setVisible(False)

    def _refresh_status(self, snapshot, ui_state) -> None:
        source = snapshot.source.value if snapshot.source else "none"
        self._status_label.setText(source)
        status_text = self._STATUS_LABELS.get(
            ui_state.status_code,
            ui_state.status_code or "Inactive",
        )
        self._status_detail_label.setText(ui_state.status_detail or status_text)
        self._conversation_label.setText(snapshot.conversation_id or "-")
        self._turn_label.setText(str(snapshot.turn_index) if snapshot.is_active else "-")
        if snapshot.is_active:
            self._budget_label.setText(
                f"{snapshot.auto_turns_used}/{snapshot.auto_turns_max} ({snapshot.auto_turns_remaining} left)"
            )
        else:
            self._budget_label.setText("-")
        route_kind = ui_state.pending_route_kind or snapshot.pending_route_kind
        target = ui_state.pending_target_actor_id or snapshot.pending_route_target_actor_id
        self._route_label.setText(f"{route_kind} -> {target}" if route_kind else "-")

    def _refresh_participants(self, snapshot, ui_state) -> None:
        participant_names = [
            item.display_name or item.character_id
            for item in snapshot.participants
            if item.character_id and item.character_id != "GameMaster"
        ]
        self._participants_label.setText(
            _("Active: ", "Active: ") + (", ".join(participant_names) or "-")
        )
        if ui_state.active:
            selected = {
                item.character_id
                for item in snapshot.participants
                if item.character_id and item.character_id != "GameMaster"
            }
            for character_id, check in self._character_checks.items():
                check.blockSignals(True)
                check.setChecked(character_id in selected)
                check.blockSignals(False)
            self._sync_initial_options()

    def _refresh_controls(self, snapshot, ui_state) -> None:
        unity_active = snapshot.source is DialogueRuntimeSource.UNITY
        sandbox_active = ui_state.active and snapshot.source is DialogueRuntimeSource.SANDBOX
        configuration_enabled = not unity_active and not sandbox_active
        for widget in (
            *self._mode_buttons.values(),
            self._initial_combo,
            self._gm_check,
            self._auto_turn_mode_combo,
            self._max_auto_spin,
            self._auto_turns_per_participant_spin,
            self._max_continue_spin,
            self._gm_repeat_spin,
        ):
            widget.setEnabled(configuration_enabled)
        is_per_participant = (
            str(self._auto_turn_mode_combo.currentData() or "fixed")
            == "per_participant"
        )
        self._max_auto_spin.setEnabled(configuration_enabled and not is_per_participant)
        self._auto_turns_per_participant_spin.setEnabled(
            configuration_enabled and is_per_participant
        )
        self._gm_instruction_edit.setEnabled(not unity_active)
        self._refresh_auto_turn_budget_hint()
        for check in self._character_checks.values():
            check.setEnabled(configuration_enabled)
        self._start_button.setEnabled(configuration_enabled and len(self._selected_character_ids()) >= 2)
        manual_ready = (
            sandbox_active
            and ui_state.manual_step_mode
            and ui_state.has_pending_route
            and not ui_state.busy
        )
        self._step_button.setVisible(bool(ui_state.manual_step_mode and sandbox_active))
        self._step_button.setEnabled(manual_ready)
        if manual_ready:
            target = ui_state.pending_target_actor_id
            target_name = self._character_name_for_actor(snapshot, target)
            self._step_button.setText(
                _("Run next: ", "Run next: ") + (target_name or _("turn", "turn"))
            )
        else:
            self._step_button.setText(_("Run next turn", "Run next turn"))
        self._stop_button.setEnabled(sandbox_active)

    def _refresh_actions(self, snapshot, ui_state) -> None:
        if snapshot.source is DialogueRuntimeSource.UNITY:
            self._clear_error()

    def _refresh_details(self, snapshot, ui_state) -> None:
        self._technical_label.setText(
            "\n".join(
                (
                    f"source={snapshot.source.value}",
                    f"conversation_id={snapshot.conversation_id or '-'}",
                    f"epoch={snapshot.epoch}",
                    f"turn_index={snapshot.turn_index}",
                    f"speaker_actor_id={snapshot.speaker_actor_id or '-'}",
                    f"responder_actor_id={snapshot.responder_actor_id or '-'}",
                    f"control_plane_trusted={snapshot.control_plane_trusted}",
                    f"sandbox_status={ui_state.status_code}",
                )
            )
        )

    @staticmethod
    def _character_name_for_actor(snapshot, actor_id: str) -> str:
        for item in snapshot.participants:
            if item.actor_id == actor_id:
                return item.display_name or item.character_id
        return ""

    def refresh(self) -> None:
        self._populate_characters()
        snapshot = get_dialogue_runtime_state_service().snapshot()
        ui_state = get_sandbox_dialogue_controller().ui_state()
        self._refresh_status(snapshot, ui_state)
        self._refresh_participants(snapshot, ui_state)
        self._refresh_controls(snapshot, ui_state)
        self._refresh_actions(snapshot, ui_state)
        self._refresh_details(snapshot, ui_state)
