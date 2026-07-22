import os

import qtawesome as qta

from PyQt6.QtCore import QSize, QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from main_logger import logger
from ui.chat.message_widget import AVATAR_MAP, _get_avatar_dir
from ui.pages.sandbox_presentation import (
    SandboxActivated,
    SandboxCharacterSelected,
    SandboxClearHistoryRequested,
    SandboxHistoryCleared,
    SandboxModelSelected,
    SandboxOpenHistory,
    SandboxOpenHistoryRequested,
    SandboxPromptSelected,
    SandboxRefreshRequested,
    SandboxRefreshVoicePanelsRequested,
    SandboxSettingChanged,
    SandboxShowError,
    SandboxState,
)
from ui.widgets.chat_panel import ChatPanel
from ui.widgets.character_state_panel import CharacterStatePanel
from ui.widgets.tr_combobox import TRQComboBox
from utils import _
from localization.live import register_if_tr, tr_set

_MODEL_CONFIGURE_SENTINEL = "__configure_models__"
_TTS_CONFIGURE_SENTINEL = "__configure_tts__"
_ASR_CONFIGURE_SENTINEL = "__configure_asr__"
_PROMPT_CONFIGURE_SENTINEL = "__configure_prompts__"


class _NoWheelComboBox(TRQComboBox):
    """TRQComboBox (живой перевод пунктов) + блокировка wheel-скролла по
    разделителям/сентинелам."""

    _SENTINELS = frozenset({
        _MODEL_CONFIGURE_SENTINEL,
        _TTS_CONFIGURE_SENTINEL,
        _ASR_CONFIGURE_SENTINEL,
        _PROMPT_CONFIGURE_SENTINEL,
    })

    def wheelEvent(self, event):
        step = -1 if event.angleDelta().y() > 0 else 1
        target = self.currentIndex() + step
        if not (0 <= target < self.count()):
            event.accept()
            return
        if not self.itemText(target) or self.itemData(target) in self._SENTINELS:
            event.accept()
            return
        super().wheelEvent(event)


def _round_pixmap(src: QPixmap, size: int) -> QPixmap:
    from PyQt6.QtGui import QPainter, QPainterPath
    scaled = src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    p.setClipPath(path)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    p.drawPixmap(x, y, scaled)
    p.end()
    return out


class _SandboxStatusRow(QWidget):
    """A live status line: [name] [state-chip] … [value] [switch] [gear→settings].

    * Раньше слева был крошечный цветной кружок — Артём читал его как «пункт
      списка», а не индикатор работы (#15). Заменён на текстовую плашку-статус:
      «Активно» (зелёная), «Не инициализировано» (жёлтая), «Ошибка» (красная),
      «Выключено» (серая). Состояние берётся так же: green/off — из
      update_status_colors() (`setChecked`), loading/red — из
      SET_SETTINGS_ICON_INDICATOR через `set_indicator()`.
    * The switch turns the feature on/off (its enable setting); the gear jumps
      to settings to actually pick the engine/model.
    * The "what exactly" value is filled by the sandbox via `set_value()`.
      Когда подсистема выключена — скрываем сам текст, но сохраняем отдельный
      растягивающийся слот в layout, чтобы строка не прыгала по горизонтали.
    """

    _DOT_COLORS = {
        "off": ("rgba(255,255,255,0.10)", "rgba(255,255,255,0.18)"),
        "active": ("#79e78c", "rgba(121,231,140,0.88)"),
        "init": ("#ffd60a", "rgba(255,214,10,0.85)"),
        "error": ("#ff453a", "rgba(255,69,58,0.85)"),
    }

    # Плашка-статус: (фон, рамка/текст) для каждого состояния.
    _CHIP_STYLE = {
        "off": ("rgba(255,255,255,0.06)", "rgba(255,255,255,0.45)"),
        "active": ("rgba(121,231,140,0.16)", "#79e78c"),
        "init": ("rgba(255,214,10,0.16)", "#ffd60a"),
        "error": ("rgba(255,69,58,0.18)", "#ff6b61"),
    }

    def __init__(self, name_text: str, on_settings, settings_tooltip: str,
                 on_toggle=None, initial_on: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("SandboxInfoRow")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self._enabled = bool(initial_on)
        self._active = False
        self._indicator = None  # None | "loading" | "red" | "green"

        name = QLabel(name_text)
        register_if_tr(name, name_text)
        name.setObjectName("SandboxInfoLabel")
        name.setMinimumWidth(88)
        h.addWidget(name, 0, Qt.AlignmentFlag.AlignVCenter)

        self._chip = QLabel("")
        self._chip.setObjectName("SandboxStatusChip")
        self._chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self._chip, 0, Qt.AlignmentFlag.AlignVCenter)

        self._value_slot = QWidget()
        self._value_slot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # Небольшой резерв спасает от схлопывания до одной буквы, но не
        # раздувает строку так агрессивно, как старый минимум 112px.
        self._value_slot.setMinimumWidth(64)
        value_layout = QHBoxLayout(self._value_slot)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(0)

        self._value = QLabel("—")
        self._value.setObjectName("SandboxInfoValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._value.setMinimumWidth(0)
        value_layout.addWidget(self._value, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        h.addWidget(self._value_slot, 1, Qt.AlignmentFlag.AlignVCenter)
        self._full_value_text = "—"

        from ui.widgets.toggle_switch import ToggleSwitch
        self._switch = ToggleSwitch()
        self._switch.setChecked(bool(initial_on))
        tr_set(self._switch, "Включить / выключить", "Enable / disable", "setToolTip")
        if on_toggle is not None:
            self._switch.toggled.connect(on_toggle)
        h.addWidget(self._switch, 0, Qt.AlignmentFlag.AlignVCenter)

        gear = QPushButton()
        gear.setObjectName("SandboxInfoEditBtn")
        gear.setIcon(qta.icon("fa6s.gear", color="#ffd2ec"))
        gear.setFixedSize(26, 26)
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setToolTip(settings_tooltip)
        gear.clicked.connect(on_settings)
        h.addWidget(gear, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_chip()

    # ----- state inputs -----
    def setChecked(self, checked: bool):
        # update_status_colors() → True means the subsystem is actually live.
        self._active = bool(checked)
        self._apply_chip()

    def setText(self, _text: str):
        # update_status_colors() pushes a terse label for the voice chip; the
        # sandbox computes a richer "what exactly" value itself, so ignore it.
        pass

    def set_enabled_state(self, enabled: bool):
        """Reflect the enable setting on the switch without re-firing toggled."""
        self._enabled = bool(enabled)
        self._switch.blockSignals(True)
        try:
            self._switch.setChecked(bool(enabled))
        finally:
            self._switch.blockSignals(False)
        self._apply_chip()

    def set_indicator(self, state):
        # state: None | "loading" | "red" | "green" | "warn" (from
        # SET_SETTINGS_ICON_INDICATOR). "warn" = настроено, но не
        # инициализировано/не готово — это НЕ ошибка.
        st = str(state).strip().lower() if state else None
        self._indicator = st if st in ("loading", "red", "green", "warn") else None
        self._apply_chip()

    def set_value(self, text: str):
        self._full_value_text = text or "—"
        self._value.setToolTip(self._full_value_text)
        self._apply_value_text()
        # Ширина слота может быть ещё не разложена в момент set_value —
        # пересчитаем элизию после текущего цикла layout, иначе текст
        # схлопывается до одной буквы.
        QTimer.singleShot(0, self._apply_value_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_value_text()

    # ----- chip rendering -----
    def _resolve_state(self) -> str:
        if not self._enabled:
            return "off"
        # "warn" — настроено, но не инициализировано → жёлтая плашка «Не
        # инициализировано», а не красная «Ошибка» (различаем, фидбэк Винера).
        if self._indicator == "warn":
            return "init"
        if self._indicator == "red":
            return "error"
        if self._indicator == "loading":
            return "init"
        if self._indicator == "green" or self._active:
            return "active"
        # Enabled but not confirmed active yet and no explicit signal.
        return "init"

    @staticmethod
    def _chip_label(state: str) -> str:
        # Коротко, чтобы плашка не распирала узкую строку статуса и не выдавливала
        # шестерёнку за край (фидбэк Винера). Полный текст — в tooltip плашки.
        return {
            "off": _("Выкл.", "Off"),
            "active": _("Активно", "Active"),
            "init": _("Не готово", "Not ready"),
            "error": _("Ошибка", "Error"),
        }.get(state, "")

    @staticmethod
    def _chip_tooltip(state: str) -> str:
        return {
            "off": _("Выключено", "Disabled"),
            "active": _("Активно и готово", "Active and ready"),
            "init": _("Включено, но не инициализировано", "Enabled but not initialized"),
            "error": _("Ошибка", "Error"),
        }.get(state, "")

    def _apply_chip(self):
        state = self._resolve_state()
        bg, fg = self._CHIP_STYLE[state]
        self._chip.setText(self._chip_label(state))
        self._chip.setToolTip(self._chip_tooltip(state))
        self._chip.setStyleSheet(
            f"QLabel#SandboxStatusChip {{"
            f" background-color: {bg}; color: {fg};"
            f" border: 1px solid {bg}; border-radius: 8px;"
            f" padding: 1px 9px; font-size: 8pt; font-weight: 700;"
            f" letter-spacing: 0.3px; }}"
        )
        # Когда выключено — прячем «что именно» (плашка уже сказала «Выкл»);
        # так у микрофона/голоса не мозолят глаза лишние поля в отключённом виде.
        self._value.setVisible(state != "off")

    def _apply_value_text(self):
        value = self._full_value_text or "—"
        # Ширину берём у слота, а не у самого QLabel: у него size policy
        # Ignored, поэтому width() бывает устаревшим/нулевым до раскладки.
        slot_w = self._value_slot.width() or self._value.width()
        available = max(24, slot_w - 2)
        elided = self._value.fontMetrics().elidedText(
            value,
            Qt.TextElideMode.ElideRight,
            available,
        )
        self._value.setText(elided)


class _GameLinkStatusRow(QWidget):
    """Строка статуса связи с игрой (мод MiSide) в панели «Статус».

    В отличие от _SandboxStatusRow (там переключатель включает подсистему), тут
    плашка отражает ЖИВОЕ состояние TCP-связи с модом — её двигает
    update_status_colors() через общий индикатор ``game_status_checkbox``
    (setChecked). Переключатель же управляет глушением входящих запросов игры
    (IGNORE_GAME_REQUESTS): ON = принимаем запросы, OFF = заглушено. Уровень
    глушения (только idle / все события, GAME_BLOCK_LEVEL) живёт в настройках
    мода — к нему ведёт шестерёнка.
    """

    _CHIP_STYLE = {
        "connected":    ("rgba(121,231,140,0.16)", "#79e78c"),
        "disconnected": ("rgba(255,255,255,0.06)", "rgba(255,255,255,0.45)"),
    }

    def __init__(self, name_text: str, on_toggle_active, on_settings,
                 settings_tooltip: str, parent=None):
        super().__init__(parent)
        self.setObjectName("SandboxInfoRow")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self._connected = False
        self._ignore = False
        self._level = "Idle events"

        name = QLabel(name_text)
        register_if_tr(name, name_text)
        name.setObjectName("SandboxInfoLabel")
        name.setMinimumWidth(88)
        h.addWidget(name, 0, Qt.AlignmentFlag.AlignVCenter)

        self._chip = QLabel("")
        self._chip.setObjectName("SandboxStatusChip")
        self._chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self._chip, 0, Qt.AlignmentFlag.AlignVCenter)

        self._value_slot = QWidget()
        self._value_slot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._value_slot.setMinimumWidth(64)
        value_layout = QHBoxLayout(self._value_slot)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(4)
        # Иконка состояния значения — qtawesome, а не эмодзи (единый стиль с
        # остальным UI, чёткая отрисовка и управляемый цвет).
        self._value_icon = QLabel()
        self._value_icon.setFixedSize(14, 14)
        self._value_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_icon.setStyleSheet("background: transparent; border: none;")
        value_layout.addWidget(self._value_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self._value = QLabel("—")
        self._value.setObjectName("SandboxInfoValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._value.setMinimumWidth(0)
        value_layout.addWidget(self._value, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        h.addWidget(self._value_slot, 1, Qt.AlignmentFlag.AlignVCenter)
        self._full_value_text = "—"

        from ui.widgets.toggle_switch import ToggleSwitch
        self._switch = ToggleSwitch()
        self._switch.setChecked(True)  # по умолчанию принимаем запросы игры
        tr_set(self._switch, "Принимать запросы игры / заглушить",
               "Accept game requests / mute", "setToolTip")
        self._switch.toggled.connect(lambda checked: on_toggle_active(bool(checked)))
        h.addWidget(self._switch, 0, Qt.AlignmentFlag.AlignVCenter)

        gear = QPushButton()
        gear.setObjectName("SandboxInfoEditBtn")
        gear.setIcon(qta.icon("fa6s.gear", color="#ffd2ec"))
        gear.setFixedSize(26, 26)
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setToolTip(settings_tooltip)
        gear.clicked.connect(on_settings)
        h.addWidget(gear, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply()

    # ----- state inputs -----
    def setChecked(self, checked: bool):
        # update_status_colors() → game_connected: живое состояние TCP-связи.
        self._connected = bool(checked)
        self._apply()

    def setText(self, _text: str):
        # Общий индикатор шлёт для игры только setChecked; текст игнорируем.
        pass

    def set_mute_state(self, ignore: bool, level: str):
        """Отразить IGNORE_GAME_REQUESTS/GAME_BLOCK_LEVEL на переключателе и
        значении, не перевызывая toggled."""
        self._ignore = bool(ignore)
        self._level = str(level or "Idle events")
        self._switch.blockSignals(True)
        try:
            self._switch.setChecked(not self._ignore)
        finally:
            self._switch.blockSignals(False)
        self._apply()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_value_text()

    # ----- rendering -----
    def _apply(self):
        state = "connected" if self._connected else "disconnected"
        bg, fg = self._CHIP_STYLE[state]
        self._chip.setText(_("Активно", "Active") if self._connected else _("Нет связи", "Offline"))
        self._chip.setToolTip(
            _("Мод игры подключён", "Game mod connected") if self._connected
            else _("Мод игры не подключён", "Game mod not connected")
        )
        self._chip.setStyleSheet(
            f"QLabel#SandboxStatusChip {{"
            f" background-color: {bg}; color: {fg};"
            f" border: 1px solid {bg}; border-radius: 8px;"
            f" padding: 1px 9px; font-size: 8pt; font-weight: 700;"
            f" letter-spacing: 0.3px; }}"
        )
        # Значение держим коротким — строка узкая (плашка + переключатель +
        # шестерёнка уже съедают ширину). Полный смысл — в tooltip. Само по себе
        # состояние «принимаем/заглушено» дублирует переключатель, поэтому:
        # принимаем → короткое «Активна»; заглушено → «idle/всё». Иконку слева
        # рисуем через qtawesome (см. _value_icon), не эмодзи.
        if self._ignore:
            lvl = _("всё", "all") if str(self._level).lower().startswith("all") else "idle"
            self._set_value(
                lvl,
                tooltip=_("Запросы игры заглушены ({lvl})", "Game requests muted ({lvl})").format(lvl=lvl),
                icon="fa6s.volume-xmark",
                icon_color="#ffd60a",
            )
            self._value.setStyleSheet("color: #ffd60a;")
        else:
            self._set_value(
                _("Активна", "Live"),
                tooltip=_("Принимает запросы игры", "Accepting game requests"),
                icon="fa6s.tower-broadcast",
                icon_color="#79e78c",
            )
            self._value.setStyleSheet("")

    def _set_value(self, text: str, tooltip: str | None = None,
                   icon: str | None = None, icon_color: str = "#cfcfe0"):
        self._full_value_text = text or "—"
        self._value.setToolTip(tooltip or self._full_value_text)
        if icon:
            try:
                self._value_icon.setPixmap(qta.icon(icon, color=icon_color).pixmap(14, 14))
                self._value_icon.setToolTip(tooltip or "")
                self._value_icon.setVisible(True)
            except Exception:
                self._value_icon.clear()
                self._value_icon.setVisible(False)
        else:
            self._value_icon.clear()
            self._value_icon.setVisible(False)
        self._apply_value_text()
        QTimer.singleShot(0, self._apply_value_text)

    def _apply_value_text(self):
        value = self._full_value_text or "—"
        slot_w = self._value_slot.width() or self._value.width()
        available = max(24, slot_w - 2)
        elided = self._value.fontMetrics().elidedText(
            value, Qt.TextElideMode.ElideRight, available,
        )
        self._value.setText(elided)


class SandboxPage(QWidget):
    def __init__(
        self,
        gui,
        view_model,
        *,
        character_state_view_model,
        chat_panel_view_model,
        chat_panel_actions,
        page_actions,
    ):
        super().__init__(gui)
        self._view_model = view_model
        self._character_state_view_model = character_state_view_model
        self._chat_panel_view_model = chat_panel_view_model
        self._chat_panel_actions = chat_panel_actions
        self._page_actions = page_actions
        self._state: SandboxState = view_model.state
        self._settings_snapshot = dict(self._state.settings)
        self.setObjectName("SandboxPage")

        self._memory_limit_values = {}
        self._debug_summary_values = {}
        self._chat_panel = None
        self._chat_character_combobox = None
        self._chat_prompt_pack_combobox = None
        self._chat_model_combobox = None
        self._inspector_collapsed = False
        self._inspector_widget = None
        self._inspector_stack = None
        self._inspector_tab_host = None
        self._inspector_header = None
        self._inspector_layout = None
        self._inspector_collapse_btn = None
        self._inspector_tab_buttons = {}
        # Collapsed-state rail (activity-bar): expand btn + tab icons.
        self._inspector_rail = None
        self._rail_tab_buttons = {}
        self._character_avatar_label = None
        self._game_status_row = None
        self._voice_status_row = None
        self._mic_status_row = None
        self._rag_status_row = None
        # Capture rows carry a two-state dot (off/active) mirroring its switch —
        # keyed by the switch widget so _sync_toggles_from_settings can recolour.
        self._toggle_dots = {}
        # Toggleable inspector panels (key -> strip widget) and the two new
        # diagnostics panels' live widgets.
        self._panels = {}
        self._budget_bar = None
        self._budget_value = None
        self._lr_values = {}
        self._lr_t0 = None
        self._inspector_expanded_width = 420
        self._inspector_collapsed_width = 60
        self._inspector_tab_indexes = {}
        self._activation_ticket = 0

        self._build_ui()
        self._view_model.state_changed.connect(self.render)
        self._view_model.effect_emitted.connect(self._handle_effect)
        self.destroyed.connect(lambda *_: self._view_model.close())
        self.render(self._state)
        self._view_model.dispatch(SandboxActivated())

    @property
    def chat_character_combobox(self):
        return self._chat_character_combobox

    @property
    def chat_prompt_pack_combobox(self):
        return self._chat_prompt_pack_combobox

    @property
    def chat_model_combobox(self):
        return self._chat_model_combobox

    @property
    def inspector_stack(self):
        return self._inspector_stack

    def render(self, state: SandboxState) -> None:
        self._state = state
        self._settings_snapshot = dict(state.settings)
        self._render_character_selector(state)
        self._render_model_selector(state)
        self._render_prompt_selector(state)
        self._refresh_status_values()
        self._render_status_indicators(state)
        self._render_memory(state)
        self._render_budget(state)
        self._render_last_request(state)
        self._sync_toggles_from_settings()
        self._refresh_debug_summary()

    def _handle_effect(self, effect) -> None:
        if isinstance(effect, SandboxHistoryCleared):
            try:
                self._chat_panel_actions.clear_chat()
            except Exception:
                logger.debug("Failed to clear Sandbox chat display", exc_info=True)
            return
        if isinstance(effect, SandboxOpenHistory):
            return
        if isinstance(effect, SandboxShowError):
            QMessageBox.warning(self, str(effect.title), str(effect.message))

    def _render_model_selector(self, state: SandboxState) -> None:
        combo = self._chat_model_combobox
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            combo.clear()
            if state.selectors_loading and not state.model_items:
                combo.add_tr_item("Загрузка моделей...", "Loading models...", value=None)
            elif state.model_items:
                for item in state.model_items:
                    combo.add_data_item(item.label, value=item.preset_id)
            else:
                combo.add_tr_item(
                    "Нет настроенных моделей",
                    "No configured models",
                    value=None,
                )
            combo.insertSeparator(combo.count())
            combo.add_tr_item(
                "Настроить...",
                "Configure...",
                value=_MODEL_CONFIGURE_SENTINEL,
            )
            if state.current_model_id is not None:
                for index in range(combo.count()):
                    if combo.itemData(index) == state.current_model_id:
                        combo.setCurrentIndex(index)
                        break
        finally:
            combo.blockSignals(False)

    def _render_prompt_selector(self, state: SandboxState) -> None:
        combo = self._chat_prompt_pack_combobox
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            combo.clear()
            if state.selectors_loading and not state.prompt_items:
                combo.add_tr_item("Загрузка наборов...", "Loading sets...", value=None)
            elif state.prompt_items:
                for item in state.prompt_items:
                    combo.add_data_item(item, value=item)
            else:
                combo.add_tr_item("Нет наборов", "No sets", value=None)
            combo.insertSeparator(combo.count())
            combo.add_tr_item(
                "Настроить...",
                "Configure...",
                value=_PROMPT_CONFIGURE_SENTINEL,
            )
            if state.current_prompt:
                index = combo.findText(
                    state.current_prompt,
                    Qt.MatchFlag.MatchFixedString,
                )
                if index >= 0:
                    combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _render_character_selector(self, state: SandboxState) -> None:
        combo = self._chat_character_combobox
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            combo.clear()
            if state.character_items:
                combo.addItems(list(state.character_items))
            else:
                combo.addItem("...")
            if state.current_character_id:
                index = combo.findText(
                    state.current_character_id,
                    Qt.MatchFlag.MatchFixedString,
                )
                if index >= 0:
                    combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)
        self._refresh_character_avatar()

    def _render_status_indicators(self, state: SandboxState) -> None:
        rows = {
            "voice": self._voice_status_row,
            "microphone": self._mic_status_row,
            "models": self._rag_status_row,
        }
        for category, indicator in state.status.indicators:
            row = rows.get(str(category))
            if row is not None:
                row.set_indicator(indicator)

    def _render_memory(self, state: SandboxState) -> None:
        memory = state.memory
        values = {
            "messages": memory.messages,
            "memories": memory.memories,
            "forgotten": memory.forgotten,
            "missing": memory.missing,
            "trash": memory.trash,
            "last": memory.last,
            "dbsize": memory.db_size,
        }
        for key, label in self._memory_limit_values.items():
            label.setText("..." if memory.loading else str(values.get(key, "—")))

    def _render_budget(self, state: SandboxState) -> None:
        if self._budget_bar is None:
            return
        budget = state.budget
        maximum = max(1, int(budget.maximum or 1))
        used = max(0, int(budget.used or 0))
        percent = min(100, int(used * 100 / maximum))
        self._budget_bar.setValue(percent)
        if self._budget_value is not None:
            if budget.loading:
                self._budget_value.setText("...")
            else:
                self._budget_value.setText(
                    _(
                        "{used} / {max} токенов · {pct}% · ~{cost:.4f} ₽",
                        "{used} / {max} tokens · {pct}% · ~{cost:.4f} ₽",
                    ).format(
                        used=used,
                        max=maximum,
                        pct=percent,
                        cost=budget.estimated_cost,
                    )
                )
        token_label = self._lr_values.get("tokens")
        if token_label is not None:
            token_label.setText(self._fmt_tokens(used))

    def _render_last_request(self, state: SandboxState) -> None:
        if not self._lr_values:
            return
        request = state.last_request
        status_text = {
            "idle": "—",
            "running": _("Генерация…", "Generating…"),
            "success": _("✓ Успех", "✓ Success"),
            "error": _("✗ Ошибка", "✗ Error"),
        }.get(request.status, str(request.status or "—"))
        if request.status == "error" and request.error:
            status_text = f"{status_text}: {request.error}"
        self._lr_values["status"].setText(status_text)
        self._lr_values["model"].setText(request.model_name or "—")
        self._lr_values["time"].setText(request.finished_at or "—")
        if request.latency_seconds is None:
            self._lr_values["latency"].setText("—")
        else:
            self._lr_values["latency"].setText(
                _("{:.2f} с", "{:.2f} s").format(request.latency_seconds)
            )

    def _get_current_character_id(self) -> str:
        return str(self._state.current_character_id or "")

    def _get_current_character_ref(self):
        return None

    def _get_effective_prompt_history_count(self, character_ref, dialog_limit: int):
        if character_ref is None:
            return None

        char_id = str(getattr(character_ref, "char_id", "") or "").strip()
        if not char_id:
            return None

        return None

    def _setting(self, key: str, default=None):
        return self._settings_snapshot.get(str(key), default)

    def get(self, key: str, default=None):
        """Read-only settings facade used by passive child controls."""
        return self._setting(key, default)

    def set(self, key: str, value) -> None:
        """Forward a child-control edit as a typed Sandbox intent."""
        self._view_model.dispatch(SandboxSettingChanged(str(key), value))

    def _jump_to_settings(self, category: str, subsection=None):
        # Шестерёнка у строки статуса ведёт ИМЕННО в её раздел, даже если подсистема
        # сейчас выключена/скрыта в «Видимых разделах» (фидбэк #14). subsection —
        # вложенная секция (например RAG внутри «Модели»), чтобы попасть сразу к
        # нужным полям, а не в начало длинной страницы (фидбэк Артёма).
        self._page_actions.switch_page("settings")
        self._page_actions.show_settings_category(
            category,
            force=True,
            subsection=subsection,
        )

    # --------- Status rows (voice / mic / RAG) -----------
    def _make_status_row(self, name_text: str, registry_attr: str, settings_key: str,
                         enable_key: str, tooltip: str, subsection=None) -> "_SandboxStatusRow":
        initial_on = bool(self._setting(enable_key, False))
        row = _SandboxStatusRow(
            name_text,
            lambda: self._jump_to_settings(settings_key, subsection),
            tooltip,
            on_toggle=lambda checked, _k=enable_key: self._on_status_toggle(_k, checked),
            initial_on=initial_on,
        )
        # Register under the shared indicator attr so update_status_colors()
        # keeps the dot live alongside the home/header indicators.
        try:
            self._page_actions.register_status_indicator(registry_attr, row)
        except Exception:
            pass
        return row

    def _on_status_toggle(self, enable_key: str, checked: bool):
        """Flip a feature through SettingsViewModel/SettingsRegistry.

        RuntimeFeatureManager observes the same registry and starts or stops the
        corresponding subsystem outside the Qt thread.
        """
        self._view_model.dispatch(SandboxSettingChanged(enable_key, bool(checked)))
        # Optimistic dot feedback; the authoritative refresh arrives through the
        # SettingsViewModel change signal and runtime status notifications.
        row = {
            "USE_VOICEOVER": self._voice_status_row,
            "MIC_ACTIVE": self._mic_status_row,
            "RAG_ENABLED": self._rag_status_row,
        }.get(enable_key)
        if row is not None:
            row.set_enabled_state(bool(checked))

    def _on_game_mute_toggle(self, active: bool):
        """Переключатель строки «Связь с игрой»: ON = принимаем запросы игры,
        OFF = заглушить полностью (IGNORE_GAME_REQUESTS + уровень All events, то
        есть глушим ВСЕ внутриигровые события, а не только idle-таймер). Точную
        настройку уровня всё ещё можно поменять шестерёнкой в настройках мода."""
        ignore = not bool(active)
        if ignore:
            self._view_model.dispatch(SandboxSettingChanged("GAME_BLOCK_LEVEL", "All events"))
        self._view_model.dispatch(SandboxSettingChanged("IGNORE_GAME_REQUESTS", ignore))
        if self._game_status_row is not None:
            level = "All events" if ignore else self._setting("GAME_BLOCK_LEVEL", "Idle events")
            self._game_status_row.set_mute_state(ignore, level)

    def _game_link_connected(self) -> bool:
        """Живое состояние TCP-связи с модом (для начального заполнения строки;
        далее её двигает update_status_colors через game_status_checkbox).
        Сервисы спрашивает view model — view пассивна."""
        try:
            return bool(self._view_model.game_link_connected())
        except Exception:
            return False

    def _make_toggle_row(self, label_text: str, on_toggle, initial_on: bool,
                         tooltip: str | None = None, with_dot: bool = False,
                         on_settings=None, settings_tooltip: str = ""):
        """A [label … switch (gear)] row using the same pill toggle as the status
        rows. When *with_dot* is set, a leading status dot (like the Status
        rows above) reflects the switch — two states only: grey off / green on.
        When *on_settings* is set, a trailing gear jumps to settings (как у RAG).
        Returns (row_widget, switch)."""
        row = QWidget()
        row.setObjectName("SandboxInfoRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        dot = None
        if with_dot:
            dot = QLabel()
            dot.setFixedSize(12, 12)
            self._style_toggle_dot(dot, bool(initial_on))
            h.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(label_text)
        register_if_tr(label, label_text)
        label.setObjectName("SandboxInfoLabel")
        if tooltip:
            label.setToolTip(tooltip)
        h.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addStretch(1)

        from ui.widgets.toggle_switch import ToggleSwitch
        switch = ToggleSwitch()
        switch.setChecked(bool(initial_on))
        if tooltip:
            switch.setToolTip(tooltip)
        switch.toggled.connect(on_toggle)
        if dot is not None:
            switch.toggled.connect(lambda checked, d=dot: self._style_toggle_dot(d, bool(checked)))
            self._toggle_dots[switch] = dot
        h.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)

        if on_settings is not None:
            gear = QPushButton()
            gear.setObjectName("SandboxInfoEditBtn")
            gear.setIcon(qta.icon("fa6s.gear", color="#ffd2ec"))
            gear.setFixedSize(26, 26)
            gear.setCursor(Qt.CursorShape.PointingHandCursor)
            if settings_tooltip:
                gear.setToolTip(settings_tooltip)
            gear.clicked.connect(on_settings)
            h.addWidget(gear, 0, Qt.AlignmentFlag.AlignVCenter)

        return row, switch

    @staticmethod
    def _style_toggle_dot(dot: QLabel, on: bool) -> None:
        """Colour a two-state dot using the same palette as _SandboxStatusRow."""
        bg, border = _SandboxStatusRow._DOT_COLORS["active" if on else "off"]
        dot.setStyleSheet(
            f"background-color: {bg}; border: 1px solid {border}; border-radius: 6px;"
        )

    def _refresh_status_values(self):
        """Fill the 'what exactly' value on each status row. The dots (active
        state) are driven separately by update_status_colors()."""
        get = self._setting

        if self._game_status_row is not None:
            self._game_status_row.setChecked(self._game_link_connected())
            self._game_status_row.set_mute_state(
                bool(get("IGNORE_GAME_REQUESTS", False)),
                str(get("GAME_BLOCK_LEVEL", "Idle events") or "Idle events"),
            )

        if self._voice_status_row is not None:
            use_voice = bool(get("USE_VOICEOVER", False))
            method = str(get("VOICEOVER_METHOD", "Local") or "Local")
            self._voice_status_row.set_enabled_state(use_voice)
            if not use_voice:
                voice_val = _("Выключено", "Off")
            elif method.lower() == "local":
                model_id = str(get("NM_CURRENT_VOICEOVER", "") or get("LOCAL_VOICE_MODEL_ID", "") or "").strip()
                voice_val = self._format_local_voice_value(model_id)
            else:
                voice_val = "Telegram"
            self._voice_status_row.set_value(voice_val)

        if self._mic_status_row is not None:
            self._mic_status_row.set_enabled_state(bool(get("MIC_ACTIVE", False)))
            engine = str(get("RECOGNIZER_TYPE", "") or "").strip()
            self._mic_status_row.set_value(engine or _("Не выбран", "None"))

        if self._rag_status_row is not None:
            self._rag_status_row.set_enabled_state(bool(get("RAG_ENABLED", False)))
            if bool(get("RAG_ENABLED", False)):
                rag_val = self._rag_preset_name()
            else:
                rag_val = _("Выключен", "Disabled")
            self._rag_status_row.set_value(rag_val)

    def _refresh_status_panel(self):
        """Полное обновление блока «Статус» без перезапуска приложения.

        Дёргается кнопкой в шапке блока и автоматически по завершении установки
        (см. подписки на Install.TASK_FINISHED / VoiceModel.MODEL_INSTALL_FINISHED).
        Помимо пере-чтения значений из настроек, просит контроллеры голоса
        пере-сканировать диск на предмет вновь установленных моделей.
        """
        self._view_model.dispatch(SandboxRefreshVoicePanelsRequested())

    def _local_voice_name(self, model_id: str) -> str:
        try:
            from presets.local_voice_models import LOCAL_VOICE_MODELS
            for model in LOCAL_VOICE_MODELS:
                if str(model.get("id") or "") == model_id:
                    return str(model.get("name") or model_id)
        except Exception:
            pass
        return model_id

    def _format_local_voice_value(self, model_id: str) -> str:
        # Без префикса «Локально: » — он съедал всю ширину узкой строки статуса,
        # и от имени модели («Edge-TTS + RVC») ничего не оставалось. Слева уже
        # есть метка «Голос», а TG-режим отдаёт значение «Telegram», так что
        # локальную озвучку от телеграмной всё равно видно. Полное имя — в tooltip.
        if not model_id:
            return _("Локально", "Local")
        return self._local_voice_name(model_id)

    # --------- Avatar -----------
    def _resolve_avatar_pixmap(self, character_id: str, size: int = 32) -> QPixmap:
        # Единый резолвер аватара (по id или display-имени) — общий с настройками.
        from ui.chat.message_widget import resolve_character_avatar
        return resolve_character_avatar(character_id, size)

    def _refresh_character_avatar(self):
        if self._character_avatar_label is None:
            return
        combo = self._chat_character_combobox
        char_id = combo.currentText().strip() if combo is not None else ""
        if not char_id or char_id == "...":
            return
        self._character_avatar_label.setPixmap(self._resolve_avatar_pixmap(char_id, 32))

    # --------- Model -----------
    def _populate_model_combobox(self):
        self._view_model.dispatch(SandboxRefreshRequested("selectors"))
        self._render_model_selector(self._state)

    def _populate_model_combobox_sync_legacy(self):
        self._render_model_selector(self._state)

    def _on_chat_model_changed(self, index: int):
        combo = self._chat_model_combobox
        if combo is None or index < 0:
            return
        data = combo.itemData(index)
        if data == _MODEL_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_model_combobox)
            self._jump_to_settings("api")
            return
        if data is None:
            return
        self._view_model.dispatch(SandboxModelSelected(int(data)))
        self._clear_stale_error_status()
        self._refresh_debug_summary()

    def _clear_stale_error_status(self):
        try:
            status = self._chat_panel.mita_status if self._chat_panel is not None else None
            if status is not None and getattr(status, "current_state", None) == "error":
                status.hide_animated()
        except Exception:
            pass
        if self._lr_values and "status" in self._lr_values:
            self._lr_values["status"].setText("—")

    def _current_preset_name(self) -> str:
        current_id = self._state.current_model_id
        for item in self._state.model_items:
            if item.preset_id == current_id:
                return item.label
        return ""

    # --------- Prompt set -----------
    def _populate_prompt_pack_combobox(self):
        self._view_model.dispatch(SandboxRefreshRequested("selectors"))
        self._render_prompt_selector(self._state)

    def _populate_prompt_pack_combobox_sync_legacy(self):
        self._render_prompt_selector(self._state)

    def _on_chat_prompt_pack_changed(self, index: int):
        combo = self._chat_prompt_pack_combobox
        if combo is None or index < 0:
            return
        data = combo.itemData(index)
        if data == _PROMPT_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_prompt_pack_combobox)
            self._jump_to_settings("characters")
            return
        if not data:
            return
        self._view_model.dispatch(SandboxPromptSelected(str(data)))
        self._refresh_debug_summary()

    # --------- Character -----------
    def _populate_chat_character_combobox(self):
        self._view_model.dispatch(SandboxRefreshRequested("selectors"))
        self._render_character_selector(self._state)

    def _on_chat_character_changed(self, character_id):
        character_id = str(character_id or "").strip()
        if not character_id:
            return

        self._view_model.dispatch(SandboxCharacterSelected(character_id))
        if self._chat_panel is not None:
            self._chat_panel.on_activated()
        self._refresh_character_avatar()
        self._populate_prompt_pack_combobox()
        self._refresh_debug_summary()

    def _open_selected_character_history(self):
        combo = self._chat_character_combobox
        character_id = combo.currentText().strip() if combo is not None else ""
        self._view_model.dispatch(SandboxOpenHistoryRequested(character_id))

    # --------- RAG / memory profile -----------
    def _memory_profile_labels(self):
        from ui.settings.memory_profile import KEY_TO_LABEL_EN, KEY_TO_LABEL_RU
        lang = str(self._setting("LANGUAGE", "RU") or "RU").upper()
        return KEY_TO_LABEL_EN if lang == "EN" else KEY_TO_LABEL_RU

    def _rag_preset_name(self) -> str:
        status = self._state.status
        name = str(status.rag_preset_name or _("Custom", "Custom"))
        model_name = self._short_rag_model_name(status.rag_model_name)
        if model_name:
            name = f"{name} · {model_name}"
        return name.replace(" only", "") or _("Включён", "Enabled")

    @staticmethod
    def _short_rag_model_name(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        if text.startswith(("local:", "openai_compat:", "gemini:")):
            text = text.split(":", 1)[1].strip()

        normalized = text.replace("\\", "/").rstrip("/")
        if not normalized:
            return ""

        if "/" in normalized:
            return normalized.rsplit("/", 1)[-1].strip()

        return normalized

    def _memory_summary_mapping(self) -> dict[str, str]:
        memory = self._state.memory
        return {
            "messages": memory.messages,
            "memories": memory.memories,
            "forgotten": memory.forgotten,
            "missing": memory.missing,
            "trash": memory.trash,
            "last": memory.last,
            "dbsize": memory.db_size,
        }

    def _refresh_memory_summary(self):
        self._view_model.dispatch(SandboxRefreshRequested("memory"))
        self._render_memory(self._state)

    def _refresh_memory_summary_sync_legacy(self):
        self._render_memory(self._state)

    @staticmethod
    def _fmt_timestamp(value) -> str:
        s = str(value or "").strip()
        if not s:
            return "—"
        s = s.replace("T", " ")
        parts = s.split(" ", 1)
        date = parts[0]
        tm = parts[1][:5] if len(parts) > 1 else ""  # HH:MM
        # Compact the date: "DD.MM.YYYY" → "DD.MM"; ISO "YYYY-MM-DD" → "MM-DD".
        if "." in date:
            d = date.split(".")
            short_date = ".".join(d[:2]) if len(d) >= 2 else date
        elif "-" in date:
            d = date.split("-")
            short_date = "-".join(d[1:3]) if len(d) >= 3 else date
        else:
            short_date = date
        return f"{short_date} {tm}".strip()

    @staticmethod
    def _fmt_tokens(n) -> str:
        """Compact token counts: show in thousands (e.g. 12.3k) once above 10000."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            return str(n)
        return f"{n / 1000:.1f}k" if n > 10000 else str(n)

    @staticmethod
    def _fmt_bytes(value) -> str:
        try:
            n = float(value or 0)
        except Exception:
            return "—"
        if n <= 0:
            return "—"
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if n < 1024 or unit == "ГБ":
                return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} ГБ"

    # --------- Debug summary -----------
    def _refresh_debug_summary(self):
        get = self._setting
        on_off = lambda v: (_("Вкл", "On") if v else _("Выкл", "Off"))

        def set_value(key: str, value) -> None:
            widget = self._debug_summary_values.get(key)
            if widget is None:
                return
            try:
                widget.setText(str(value or "—"))
            except Exception:
                pass

        char_combo = self._chat_character_combobox
        prompt_combo = self._chat_prompt_pack_combobox
        model_combo = self._chat_model_combobox

        if "character" in self._debug_summary_values:
            value = char_combo.currentText().strip() if char_combo is not None else ""
            set_value("character", value if value and value != "..." else "—")
        if "prompts" in self._debug_summary_values:
            value = prompt_combo.currentText().strip() if prompt_combo is not None else ""
            set_value("prompts", value if value else "—")
        if "model" in self._debug_summary_values:
            value = model_combo.currentText().strip() if model_combo is not None else ""
            set_value("model", value if value else "—")
        if "voice" in self._debug_summary_values:
            set_value("voice", str(get("VOICEOVER_METHOD", "Local")))
        if "asr" in self._debug_summary_values:
            set_value("asr", str(get("RECOGNIZER_TYPE", "") or "—"))
        if "rag" in self._debug_summary_values:
            set_value("rag", self._rag_preset_name() if get("RAG_ENABLED", False) else _("Выключен", "Disabled"))
        if "messages" in self._debug_summary_values:
            set_value("messages", str(get("MODEL_MESSAGE_LIMIT", 35)))
        if "memory" in self._debug_summary_values:
            set_value("memory", str(get("MEMORY_CAPACITY", 50)))
        if "screen" in self._debug_summary_values:
            set_value("screen", on_off(get("ENABLE_SCREEN_ANALYSIS", False)))
        if "camera" in self._debug_summary_values:
            set_value("camera", on_off(get("ENABLE_CAMERA_CAPTURE", False)))

    def _refresh_debug_summary_sync_legacy(self):
        get = self._setting
        on_off = lambda v: (_("Вкл", "On") if v else _("Выкл", "Off"))

        def safe(key, fn):
            try:
                self._debug_summary_values[key].setText(str(fn()))
            except Exception:
                try:
                    self._debug_summary_values[key].setText("—")
                except Exception:
                    pass

        if "character" in self._debug_summary_values:
            safe("character", lambda: self._get_current_character_id() or "—")
        if "prompts" in self._debug_summary_values:
            def _prompts():
                cid = self._get_current_character_id()
                return get(f"PROMPT_SET_{cid}", "") or "—" if cid else "—"
            safe("prompts", _prompts)
        if "model" in self._debug_summary_values:
            safe("model", lambda: self._current_preset_name() or "—")
        if "voice" in self._debug_summary_values:
            safe("voice", lambda: str(get("VOICEOVER_METHOD", "Local")))
        if "asr" in self._debug_summary_values:
            safe("asr", lambda: str(get("RECOGNIZER_TYPE", "") or "—"))
        if "rag" in self._debug_summary_values:
            safe("rag", lambda: (self._rag_preset_name() if get("RAG_ENABLED", False)
                                 else _("Выключен", "Disabled")))
        if "messages" in self._debug_summary_values:
            safe("messages", lambda: str(get("MODEL_MESSAGE_LIMIT", 35)))
        if "memory" in self._debug_summary_values:
            safe("memory", lambda: str(get("MEMORY_CAPACITY", 50)))
        if "screen" in self._debug_summary_values:
            safe("screen", lambda: on_off(get("ENABLE_SCREEN_ANALYSIS", False)))
        if "camera" in self._debug_summary_values:
            safe("camera", lambda: on_off(get("ENABLE_CAMERA_CAPTURE", False)))

    # --------- Activation -----------
    def _schedule_activation_step(self, ticket: int, delay_ms: int, callback) -> None:
        def _run():
            if ticket != self._activation_ticket:
                return
            if not self._page_actions.is_current("sandbox"):
                return
            try:
                callback()
            except Exception:
                logger.error("Sandbox activation refresh failed", exc_info=True)

        QTimer.singleShot(delay_ms, _run)

    def on_activated(self):
        self._sync_toggles_from_settings()
        self.apply_panel_visibility()
        self._activation_ticket += 1
        ticket = self._activation_ticket

        self._schedule_activation_step(ticket, 0, self._populate_chat_character_combobox)
        self._schedule_activation_step(ticket, 0, self._refresh_character_avatar)
        self._schedule_activation_step(ticket, 15, self._populate_model_combobox)
        self._schedule_activation_step(ticket, 30, self._populate_prompt_pack_combobox)
        self._schedule_activation_step(ticket, 45, self._refresh_status_values)
        self._schedule_activation_step(ticket, 60, self._refresh_memory_summary)
        self._schedule_activation_step(ticket, 75, self._refresh_context_budget)
        self._schedule_activation_step(ticket, 90, self._refresh_debug_summary)
        self._schedule_activation_step(ticket, 105, self._page_actions.refresh_status)
        self._schedule_activation_step(
            ticket,
            120,
            lambda: self._chat_panel.on_activated() if self._chat_panel is not None else None,
        )
        self._schedule_activation_step(
            ticket,
            135,
            lambda: self._character_state_panel.refresh(rebuild=True)
            if getattr(self, "_character_state_panel", None) is not None else None,
        )

    def show_debug_tab(self):
        if self._inspector_collapsed:
            self._toggle_inspector_collapsed()
        self._set_inspector_tab("debug")
        self._refresh_debug_summary()

    def _repolish(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _set_inspector_tab(self, tab_key: str) -> None:
        if self._inspector_stack is None:
            return
        index = self._inspector_tab_indexes.get(tab_key)
        if index is None:
            return
        self._inspector_stack.setCurrentIndex(index)
        for key, button in self._inspector_tab_buttons.items():
            active = key == tab_key
            button.setProperty("active", active)
            button.setChecked(active)
            self._repolish(button)
        # Keep the collapsed-rail icons highlighting the same tab.
        for key, button in self._rail_tab_buttons.items():
            active = key == tab_key
            button.setProperty("active", active)
            button.setChecked(active)
            self._repolish(button)

    def _make_inspector_tab_button(self, tab_key: str, label: str) -> QPushButton:
        button = QPushButton(label)
        register_if_tr(button, label)
        button.setObjectName("SandboxInspectorTabButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda checked=False, key=tab_key: self._set_inspector_tab(key))
        self._inspector_tab_buttons[tab_key] = button
        return button

    def _update_inspector_collapse_icon(self) -> None:
        if self._inspector_collapse_btn is None:
            return
        icon_name = "fa6s.angles-left" if self._inspector_collapsed else "fa6s.angles-right"
        self._inspector_collapse_btn.setIcon(qta.icon(icon_name, color="#ffd6ee"))
        self._inspector_collapse_btn.setIconSize(QSize(14, 14))

    # --------- Building blocks -----------
    def _make_selector_card(self, title: str, icon_name: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SandboxSelectorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.setContentsMargins(0, 0, 0, 0)

        if icon_name:
            icon_label = QLabel()
            icon_label.setObjectName("SandboxSelectorIcon")
            icon_label.setPixmap(qta.icon(icon_name, color="#ffd2ec").pixmap(14, 14))
            title_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(title)
        register_if_tr(label, title)
        label.setObjectName("SandboxSelectorLabel")
        title_row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        layout.addLayout(title_row)
        return card, layout

    def _make_tab_page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("SandboxInspectorTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 12, 2, 4)
        layout.setSpacing(12)
        return page, layout

    def _make_inspector_card(self, title_text: str | None = None, icon_name: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SandboxInspectorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        if title_text:
            title_row = QHBoxLayout()
            title_row.setSpacing(6)
            title_row.setContentsMargins(0, 0, 0, 0)
            if icon_name:
                icon_label = QLabel()
                icon_label.setObjectName("SandboxSelectorIcon")
                icon_label.setPixmap(qta.icon(icon_name, color="#ffd2ec").pixmap(14, 14))
                title_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
            title = QLabel(title_text)
            register_if_tr(title, title_text)
            title.setObjectName("SandboxInspectorTitle")
            title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
            title_row.addStretch(1)
            layout.addLayout(title_row)
        return card, layout

    def _make_strip(self, title_text: str, icon_name: str | None = None,
                    header_action: "QWidget | None" = None) -> tuple[QWidget, QVBoxLayout]:
        """Stack-panel section: flat, no card border, just a title row
        with an optional icon and an underline. Used everywhere except the
        State tab (which keeps cards on the character_state_panel).

        `header_action` — необязательный виджет (обычно маленькая кнопка),
        прижимается к правому краю строки заголовка (напр. «обновить статус»).
        """
        strip = QWidget()
        strip.setObjectName("SandboxInspectorStrip")
        layout = QVBoxLayout(strip)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        if icon_name:
            icon_label = QLabel()
            icon_label.setObjectName("SandboxSelectorIcon")
            icon_label.setPixmap(qta.icon(icon_name, color="#ffd2ec").pixmap(14, 14))
            title_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title = QLabel(title_text)
        register_if_tr(title, title_text)
        title.setObjectName("SandboxStripTitle")
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        if header_action is not None:
            title_row.addWidget(header_action, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(title_row)

        underline = QFrame()
        underline.setObjectName("SandboxStripUnderline")
        underline.setFixedHeight(1)
        layout.addWidget(underline)

        return strip, layout

    def _make_info_row(
        self,
        label_text: str,
        value_provider,
        edit_target: str,
        *,
        edit_tooltip: str | None = None,
    ) -> tuple[QWidget, QLabel]:
        """One read-only row: [label] [bold value] [pencil button].

        `value_provider` is a callable that returns the current text, OR a
        QComboBox (then we mirror currentText() and listen for changes).
        `edit_target` is the settings category key to jump to on pencil click.
        Returns (widget, value_label) so the caller can store the label and
        update it later if needed.
        """
        row = QWidget()
        row.setObjectName("SandboxInfoRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        label = QLabel(label_text)
        register_if_tr(label, label_text)
        label.setObjectName("SandboxInfoLabel")
        h.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

        value_label = QLabel("—")
        value_label.setObjectName("SandboxInfoValue")
        value_label.setMinimumWidth(0)
        value_label.setWordWrap(True)
        value_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(value_label, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        edit_btn = QPushButton()
        edit_btn.setObjectName("SandboxInfoEditBtn")
        edit_btn.setIcon(qta.icon("fa6s.pen", color="#ffd2ec"))
        edit_btn.setFixedSize(26, 26)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setToolTip(edit_tooltip or _("Изменить в настройках", "Edit in settings"))
        edit_btn.clicked.connect(lambda: self._jump_to_settings(edit_target))
        h.addWidget(edit_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Wire up the value source
        if isinstance(value_provider, QComboBox):
            combo = value_provider

            def _sync():
                value_label.setText(combo.currentText() or "—")
            _sync()
            combo.currentTextChanged.connect(lambda _t: _sync())
        elif callable(value_provider):
            try:
                value_label.setText(str(value_provider() or "—"))
            except Exception:
                value_label.setText("—")
        else:
            value_label.setText(str(value_provider or "—"))

        return row, value_label

    def _build_title_bar(self) -> QFrame:
        title_card = QFrame()
        title_card.setObjectName("SandboxWorkspaceHeader")
        title_layout = QHBoxLayout(title_card)
        title_layout.setContentsMargins(4, 2, 4, 10)
        title_layout.setSpacing(18)

        title_col = QVBoxLayout()
        title_col.setSpacing(5)

        headline_row = QHBoxLayout()
        headline_row.setSpacing(10)
        headline_row.setContentsMargins(0, 0, 0, 0)

        icon_label = QLabel()
        icon_label.setObjectName("SandboxHeroIcon")
        icon_label.setPixmap(qta.icon("fa6s.flask", color="#ff6db7").pixmap(22, 22))
        headline_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        title_label = tr_set(QLabel(), "Песочница / Sandbox", "Sandbox")
        title_label.setObjectName("ChatHeroTitle")
        headline_row.addWidget(title_label, 0, Qt.AlignmentFlag.AlignVCenter)

        badge = QLabel("BETA")
        badge.setObjectName("SandboxHeroBadge")
        headline_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        headline_row.addStretch(1)
        title_col.addLayout(headline_row)

        title_layout.addLayout(title_col, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        guide_button = tr_set(QPushButton(), "Руководство", "Guide")
        guide_button.setObjectName("SandboxHeaderButton")
        guide_button.clicked.connect(self._page_actions.show_guide)
        actions.addWidget(guide_button)

        wiki_button = tr_set(QPushButton(), "Вики", "Wiki")
        wiki_button.setObjectName("SandboxHeaderButton")
        wiki_button.clicked.connect(lambda: self._page_actions.switch_page("wiki"))
        actions.addWidget(wiki_button)

        settings_button = tr_set(QPushButton(), "Настройки", "Settings")
        settings_button.setObjectName("SandboxHeaderButton")
        settings_button.clicked.connect(
            lambda: self._page_actions.switch_page("settings")
        )
        actions.addWidget(settings_button)

        home_button = tr_set(QPushButton(), "На главную", "Home")
        home_button.setObjectName("SandboxHeaderPrimaryButton")
        home_button.clicked.connect(lambda: self._page_actions.switch_page("home"))
        actions.addWidget(home_button)

        title_layout.addLayout(actions, 0)
        return title_card

    # --------- Inspector tabs -----------
    def _wrap_in_scroll(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("SandboxInspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _build_inspector_session_tab(self) -> QWidget:
        page, layout = self._make_tab_page()

        # ── Visible comboboxes (label + combo per row) ─────────────────────
        # Other modules (chat_panel, character_settings/logic, etc.) reference
        # gui.chat_*_combobox to read the active character / sync model lists.
        # These are _NoWheelComboBox, so the mouse wheel can't change the
        # selection — scrolling used to trigger a spurious re-initialization.
        # To switch a value the user clicks the combo and picks an item; the
        # final "Настроить…" entry jumps to the matching settings section.
        def _session_combo(attr: str, *, tooltip: str, change_slot, by_text: bool = False) -> QComboBox:
            combo = _NoWheelComboBox()
            combo.setObjectName("ChatCharacterCombo")
            combo.setToolTip(tooltip)
            if by_text:
                combo.currentTextChanged.connect(change_slot)
            else:
                combo.currentIndexChanged.connect(change_slot)
            setattr(self, f"_{attr}", combo)
            return combo

        def _combo_row(strip_layout, label_text: str, combo: QComboBox, leading=None, trailing=None) -> None:
            row = QWidget()
            row.setObjectName("SandboxInfoRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            lbl = QLabel(label_text)
            register_if_tr(lbl, label_text)
            lbl.setObjectName("SandboxInfoLabel")
            lbl.setMinimumWidth(104)
            h.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            if leading is not None:
                h.addWidget(leading, 0, Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(combo, 1, Qt.AlignmentFlag.AlignVCenter)
            if trailing is not None:
                h.addWidget(trailing, 0, Qt.AlignmentFlag.AlignVCenter)
            strip_layout.addWidget(row)

        # ── Активная сессия ────────────────────────────────────────────────
        active_strip, active_layout = self._make_strip(_("Активная сессия", "Active session"), "fa6s.id-badge")

        self._character_avatar_label = QLabel()
        self._character_avatar_label.setObjectName("SandboxCharacterAvatar")
        self._character_avatar_label.setFixedSize(22, 22)

        char_combo = _session_combo(
            "chat_character_combobox",
            tooltip=_("Выбрать персонажа", "Select character"),
            change_slot=self._on_chat_character_changed,
            by_text=True,
        )
        # Кнопка-шестерёнка рядом с выбором персонажа → в настройки персонажа
        # (промпты/пресеты/история). Выбор — тут, конфиг — там (#4).
        char_settings_btn = QPushButton()
        char_settings_btn.setObjectName("SandboxInlineIconBtn")
        char_settings_btn.setIcon(qta.icon("fa6s.gear", color="#ffd2ec"))
        char_settings_btn.setFixedSize(28, 28)
        char_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        char_settings_btn.setToolTip(_("Настройки персонажа", "Character settings"))
        char_settings_btn.clicked.connect(lambda: self._jump_to_settings("characters"))
        _combo_row(active_layout, _("Персонаж", "Character"), char_combo,
                   leading=self._character_avatar_label, trailing=char_settings_btn)

        prompt_combo = _session_combo(
            "chat_prompt_pack_combobox",
            tooltip=_("Активный набор промптов", "Active prompt set"),
            change_slot=self._on_chat_prompt_pack_changed,
        )
        _combo_row(active_layout, _("Набор промптов", "Prompt set"), prompt_combo)

        model_combo = _session_combo(
            "chat_model_combobox",
            tooltip=_("Активный API-пресет (модель)", "Active API preset (model)"),
            change_slot=self._on_chat_model_changed,
        )
        _combo_row(active_layout, _("Модель", "Model"), model_combo)
        layout.addWidget(active_strip)
        self._panels["active"] = active_strip

        # ── Статус: голос, микрофон, RAG ───────────────────────────────────
        # Read-only live status. The dots are driven by update_status_colors()
        # via the shared indicator registry (green = active); each row shows
        # what's actually configured and a gear that jumps to its settings
        # section to change it.
        status_refresh_btn = QPushButton()
        status_refresh_btn.setObjectName("SandboxInfoEditBtn")
        status_refresh_btn.setIcon(qta.icon("fa6s.rotate", color="#ffd2ec"))
        status_refresh_btn.setFixedSize(26, 26)
        status_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(status_refresh_btn,
               "Перечитать состояние с диска (голоса, модели, RAG)",
               "Re-read state from disk (voices, models, RAG)",
               "setToolTip")
        status_refresh_btn.clicked.connect(self._refresh_status_panel)
        status_strip, status_layout = self._make_strip(
            _("Статус", "Status"), "fa6s.wave-square", header_action=status_refresh_btn)

        # Связь с игрой — сверху: плашка = живое состояние TCP-связи с модом
        # (двигает update_status_colors через game_status_checkbox),
        # переключатель = глушение запросов игры (IGNORE_GAME_REQUESTS),
        # шестерёнка ведёт в настройки мода (уровень idle / все события).
        self._game_status_row = _GameLinkStatusRow(
            _("Связь с игрой", "Game link"),
            self._on_game_mute_toggle,
            lambda: self._jump_to_settings("game"),
            _("Открыть настройки мода (глушение idle / все события)",
              "Open mod settings (mute idle / all events)"),
        )
        try:
            self._page_actions.register_status_indicator(
                "game_status_checkbox", self._game_status_row)
        except Exception:
            pass
        status_layout.addWidget(self._game_status_row)

        self._voice_status_row = self._make_status_row(
            _("Голос", "Voice"),
            "silero_status_checkbox",
            "voice",
            "USE_VOICEOVER",
            _("Открыть настройки озвучки", "Open voice settings"),
        )
        status_layout.addWidget(self._voice_status_row)

        self._mic_status_row = self._make_status_row(
            _("Микрофон", "Microphone"),
            "mic_status_checkbox",
            "microphone",
            "MIC_ACTIVE",
            _("Открыть настройки микрофона", "Open microphone settings"),
        )
        status_layout.addWidget(self._mic_status_row)

        # Мгновенная отправка распознанного текста (MIC_INSTANT_SENT) — тот же
        # тумблер, что и в настройках микрофона; здесь под строкой микрофона,
        # чтобы включать «речь сразу уходит в чат» не уходя со страницы.
        mic_instant_row, self._mic_instant_cb = self._make_toggle_row(
            _("Мгновенная отправка", "Instant send"),
            lambda v: self._on_capture_toggle("MIC_INSTANT_SENT", v),
            bool(self._setting("MIC_INSTANT_SENT", False)),
            tooltip=_("Мгновенная отправка распознанного текста",
                      "Send recognized text immediately"),
            with_dot=True,
            on_settings=lambda: self._jump_to_settings("microphone"),
            settings_tooltip=_("Открыть настройки микрофона", "Open microphone settings"),
        )
        status_layout.addWidget(mic_instant_row)

        self._rag_status_row = self._make_status_row(
            "RAG",
            "rag_status_checkbox",
            "models",
            "RAG_ENABLED",
            _("Открыть настройки RAG / памяти", "Open RAG / memory settings"),
            subsection=("RAG",),
        )
        status_layout.addWidget(self._rag_status_row)
        layout.addWidget(status_strip)
        self._panels["status"] = status_strip

        # ── Бюджет контекста ───────────────────────────────────────────────
        # Hidden for now: shows a placeholder limit/cost, not real usage. The
        # builder (_build_context_budget_strip) and refresh stay in place — to
        # restore, re-add the three lines below and the "context_budget" entry
        # in ui/widgets/sandbox_panels.py once real usage is surfaced.
        #   budget_strip = self._build_context_budget_strip()
        #   layout.addWidget(budget_strip)
        #   self._panels["context_budget"] = budget_strip

        # ── Последний запрос ───────────────────────────────────────────────
        last_request_strip = self._build_last_request_strip()
        layout.addWidget(last_request_strip)
        self._panels["last_request"] = last_request_strip

        # ── Захват ─────────────────────────────────────────────────────────
        capture_strip, capture_layout = self._make_strip(_("Захват", "Capture"), "fa6s.camera-retro")
        _img_settings_tip = _("Открыть настройки изображений и камеры",
                              "Open image & camera settings")
        attach_row, self._capture_auto_attach_cb = self._make_toggle_row(
            _("Авто-прикрепление", "Auto-attach"),
            lambda v: self._on_capture_toggle("AUTO_ATTACH_IMAGES", v),
            bool(self._setting("AUTO_ATTACH_IMAGES", False)),
            with_dot=True,
            on_settings=lambda: self._jump_to_settings("screen"),
            settings_tooltip=_img_settings_tip,
        )
        capture_layout.addWidget(attach_row)

        screen_row, self._capture_screen_cb = self._make_toggle_row(
            _("Захват экрана", "Screen capture"),
            lambda v: self._on_capture_toggle("ENABLE_SCREEN_ANALYSIS", v),
            bool(self._setting("ENABLE_SCREEN_ANALYSIS", False)),
            with_dot=True,
            on_settings=lambda: self._jump_to_settings("screen"),
            settings_tooltip=_img_settings_tip,
        )
        capture_layout.addWidget(screen_row)

        camera_row, self._capture_camera_cb = self._make_toggle_row(
            _("Захват с камеры", "Camera capture"),
            lambda v: self._on_capture_toggle("ENABLE_CAMERA_CAPTURE", v),
            bool(self._setting("ENABLE_CAMERA_CAPTURE", False)),
            with_dot=True,
            on_settings=lambda: self._jump_to_settings("screen"),
            settings_tooltip=_img_settings_tip,
        )
        capture_layout.addWidget(camera_row)
        layout.addWidget(capture_strip)
        self._panels["capture"] = capture_strip

        # ── Быстрые действия ───────────────────────────────────────────────
        # "Очистить чат" / "Загрузить историю" живут в полосе над чатом
        # (ui/widgets/chat_panel._build_conversation_strip), поэтому здесь не
        # дублируются. Остаётся сброс персонажа + переходы к настройкам и
        # просмотр последнего запроса (удобно для отладки, см. задачу 5).
        actions_strip, actions_layout = self._make_strip(_("Быстрые действия", "Quick actions"), "fa6s.bolt")

        view_last_btn = tr_set(QPushButton(), "Посмотреть последний запрос", "View last request")
        view_last_btn.setObjectName("SandboxQuickAction")
        tr_set(view_last_btn,
               "Открыть просмотр контекста последнего запроса к нейросети.",
               "Open the context viewer for the last request sent to the model.",
               "setToolTip")
        view_last_btn.clicked.connect(self._on_view_last_request)
        actions_layout.addWidget(view_last_btn)

        char_settings_btn = tr_set(QPushButton(), "Настройки персонажа", "Character settings")
        char_settings_btn.setObjectName("SandboxQuickAction")
        char_settings_btn.clicked.connect(lambda: self._jump_to_settings("characters"))
        actions_layout.addWidget(char_settings_btn)

        full_settings_btn = tr_set(QPushButton(), "Полные настройки", "Full settings")
        full_settings_btn.setObjectName("SandboxQuickAction")
        full_settings_btn.clicked.connect(
            lambda: self._page_actions.switch_page("settings")
        )
        actions_layout.addWidget(full_settings_btn)

        reset_btn = tr_set(QPushButton(), "Сбросить персонажа", "Reset character")
        reset_btn.setObjectName("SandboxQuickAction")
        reset_btn.setProperty("danger", True)
        reset_btn.clicked.connect(self._on_reset_character)
        actions_layout.addWidget(reset_btn)
        layout.addWidget(actions_strip)
        self._panels["actions"] = actions_strip

        self.apply_panel_visibility()

        layout.addStretch(1)
        return self._wrap_in_scroll(page)

    # --------- Panel visibility -----------
    def apply_panel_visibility(self):
        """Show/hide each inspector panel per the sandbox_panels toggles."""
        try:
            from ui.widgets.sandbox_panels import SANDBOX_PANEL_DEFAULTS, _panel_key
        except Exception:
            return
        for key, widget in self._panels.items():
            if widget is not None:
                default = SANDBOX_PANEL_DEFAULTS.get(key, True)
                widget.setVisible(bool(self._setting(_panel_key(key), default)))

    # --------- Context budget panel -----------
    def _build_context_budget_strip(self) -> QWidget:
        strip, slayout = self._make_strip(_("Бюджет контекста", "Context budget"), "fa6s.gauge-high")

        bar_row = QWidget()
        bar_row.setObjectName("SandboxMemoryRow")
        rl = QHBoxLayout(bar_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        self._budget_bar = QProgressBar()
        self._budget_bar.setObjectName("SandboxMemoryBar")
        self._budget_bar.setRange(0, 100)
        self._budget_bar.setValue(0)
        self._budget_bar.setTextVisible(False)
        self._budget_bar.setFixedHeight(8)
        rl.addWidget(self._budget_bar, 1, Qt.AlignmentFlag.AlignVCenter)
        slayout.addWidget(bar_row)

        self._budget_value = QLabel("—")
        self._budget_value.setObjectName("SandboxInfoValue")
        self._budget_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        slayout.addWidget(self._budget_value)
        return strip

    def _refresh_context_budget(self):
        self._view_model.dispatch(SandboxRefreshRequested("budget"))
        self._render_budget(self._state)

    # --------- Last-request diagnostics panel -----------
    def _build_last_request_strip(self) -> QWidget:
        strip, slayout = self._make_strip(_("Последний запрос", "Last request"), "fa6s.gauge")
        self._lr_values = {}
        for key, label_text in (
            ("status", _("Статус", "Status")),
            ("latency", _("Задержка", "Latency")),
            ("model", _("Модель", "Model")),
            ("tokens", _("Контекст (токены)", "Context (tokens)")),
            ("time", _("Время", "Time")),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            register_if_tr(label, label_text)
            label.setObjectName("SandboxInfoLabel")
            row.addWidget(label)
            value = QLabel("—")
            value.setObjectName("SandboxInfoValue")
            value.setMinimumWidth(0)
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(value, 1)
            slayout.addLayout(row)
            self._lr_values[key] = value
        return strip

    def _sync_toggles_from_settings(self):
        """Re-sync the capture/display checkboxes from the current settings so a
        change made on the settings page is reflected when the Sandbox is shown.
        (The Voice/Mic/RAG pills are synced separately by _refresh_status_values,
        and live via the SettingsViewModel subscription.)"""
        get = self._setting
        pairs = (
            ("_capture_screen_cb", "ENABLE_SCREEN_ANALYSIS", False),
            ("_capture_auto_attach_cb", "AUTO_ATTACH_IMAGES", False),
            ("_capture_camera_cb", "ENABLE_CAMERA_CAPTURE", False),
            ("_mic_instant_cb", "MIC_INSTANT_SENT", False),
            ("_show_thinking_cb", "SHOW_THINK_IN_GUI", False),
            ("_hide_tags_cb", "HIDE_CHAT_TAGS", True),
            ("_show_ts_cb", "SHOW_CHAT_TIMESTAMPS", True),
            ("_show_sys_cb", "SHOW_SYSTEM_MESSAGES", False),
            ("_show_tokens_cb", "SHOW_TOKEN_INFO", False),
        )
        for attr, key, default in pairs:
            w = getattr(self, attr, None)
            if w is None:
                continue
            want = bool(get(key, default))
            if w.isChecked() == want:
                continue
            w.blockSignals(True)
            try:
                w.setChecked(want)
            finally:
                w.blockSignals(False)
            # toggled was suppressed above — refresh the dot manually.
            dot = self._toggle_dots.get(w)
            if dot is not None:
                self._style_toggle_dot(dot, want)

    def _on_capture_toggle(self, key: str, value: bool):
        self._view_model.dispatch(SandboxSettingChanged(key, bool(value)))
        self._refresh_debug_summary()

    def _on_view_last_request(self) -> None:
        """Open the last-request context viewer. Reuses the host view's handler
        so the SavedMessages fallback lookup stays in one place."""
        self._page_actions.view_last_context()

    def _on_reset_character(self) -> None:
        char_id = self._get_current_character_id()
        if not char_id:
            return
        reply = QMessageBox.question(
            self,
            _("Сбросить персонажа", "Reset character"),
            _(
                "Очистить историю и состояние '{name}'? Это действие необратимо.",
                "Clear history and state of '{name}'? This cannot be undone.",
            ).format(name=char_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._view_model.dispatch(SandboxClearHistoryRequested())

    def _build_inspector_state_tab(self) -> QWidget:
        page, layout = self._make_tab_page()
        character_state_vm = self._character_state_view_model
        self._character_state_panel = CharacterStatePanel(
            character_state_vm,
            parent=page,
        )
        character_state_vm.setParent(self._character_state_panel)
        layout.addWidget(self._character_state_panel)

        # Live DB mini-stats for the current character.
        memory_card, memory_layout = self._make_inspector_card(_("Контекст и память", "Context & memory"), "fa6s.brain")
        for label_text, stat_key, hint in (
            (_("Сообщений в окне", "Messages in window"), "messages", None),
            (_("Воспоминаний", "Memories"), "memories", None),
            (_("Забыто (RAG)", "Forgotten (RAG)"), "forgotten", None),
            (_("Без эмбеддинга", "Missing embeddings"), "missing",
             _("Сообщения / воспоминания без эмбеддинга для текущей модели (устаревший индекс)",
               "Messages / memories without an embedding for the current model (stale index)")),
            (_("Корзина", "Trash"), "trash",
             _("Удалённые сообщения / воспоминания", "Deleted messages / memories")),
            (_("Посл. сообщение", "Last message"), "last", None),
            (_("Размер БД", "DB size"), "dbsize", None),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            register_if_tr(label, label_text)
            label.setObjectName("SandboxInspectorLabel")
            if hint:
                register_if_tr(label, hint, "setToolTip")
            row.addWidget(label)
            value = QLabel("—")
            value.setObjectName("SandboxInspectorValue")
            if hint:
                register_if_tr(value, hint, "setToolTip")
            row.addWidget(value, 1)
            memory_layout.addLayout(row)
            self._memory_limit_values[stat_key] = value

        memory_btn = tr_set(QPushButton(), "Открыть RAG / память", "Open RAG / memory")
        memory_btn.setObjectName("SandboxQuickAction")
        memory_btn.clicked.connect(lambda: self._jump_to_settings("models"))
        memory_layout.addWidget(memory_btn)
        layout.addWidget(memory_card)

        layout.addStretch(1)
        return self._wrap_in_scroll(page)

    def _build_inspector_debug_tab(self) -> QWidget:
        page, layout = self._make_tab_page()
        layout.setContentsMargins(2, 12, 10, 4)

        # ── Отображение сообщений ───────────────────────────────────────────
        # Show-thinking moved here from General settings: the toggle controls
        # the inline "thinking" message bubble. Default OFF so the sandbox
        # stays uncluttered out of the box.
        display_strip, display_layout = self._make_strip(_("Отображение сообщений", "Message display"), "fa6s.eye")

        think_cb = tr_set(QCheckBox(), "Показывать мышление", "Show thinking")
        think_cb.setObjectName("SandboxCaptureToggle")
        think_cb.setChecked(bool(self._setting("SHOW_THINK_IN_GUI", False)))
        tr_set(think_cb,
               "Показывать содержимое блока мышления модели как отдельное сообщение в чате.",
               "Show the model's thinking block as a separate chat message.",
               "setToolTip")
        think_cb.toggled.connect(lambda v: self._on_capture_toggle("SHOW_THINK_IN_GUI", v))
        display_layout.addWidget(think_cb)
        self._show_thinking_cb = think_cb

        tags_cb = tr_set(QCheckBox(), "Скрывать теги в чате", "Hide tags in chat")
        tags_cb.setObjectName("SandboxCaptureToggle")
        tags_cb.setChecked(bool(self._setting("HIDE_CHAT_TAGS", True)))
        tags_cb.toggled.connect(lambda v: self._on_capture_toggle("HIDE_CHAT_TAGS", v))
        display_layout.addWidget(tags_cb)
        self._hide_tags_cb = tags_cb

        ts_cb = tr_set(QCheckBox(), "Показывать время сообщений", "Show timestamps")
        ts_cb.setObjectName("SandboxCaptureToggle")
        ts_cb.setChecked(bool(self._setting("SHOW_CHAT_TIMESTAMPS", True)))
        ts_cb.toggled.connect(lambda v: self._on_capture_toggle("SHOW_CHAT_TIMESTAMPS", v))
        display_layout.addWidget(ts_cb)
        self._show_ts_cb = ts_cb

        sys_cb = tr_set(QCheckBox(), "Показывать системные сообщения", "Show system messages")
        sys_cb.setObjectName("SandboxCaptureToggle")
        sys_cb.setChecked(bool(self._setting("SHOW_SYSTEM_MESSAGES", False)))
        tr_set(sys_cb, "Показывать системные/контекстные заметки (например «[Easel drawing]…») в чате. По умолчанию скрыты.",
                "Show system/context notes (e.g. \"[Easel drawing]…\") in chat. Hidden by default.", "setToolTip")
        sys_cb.toggled.connect(lambda v: self._on_capture_toggle("SHOW_SYSTEM_MESSAGES", v))
        display_layout.addWidget(sys_cb)
        self._show_sys_cb = sys_cb

        tokens_cb = tr_set(QCheckBox(), "Показывать статистику токенов/стоимости", "Show token/cost stats")
        tokens_cb.setObjectName("SandboxCaptureToggle")
        tokens_cb.setChecked(bool(self._setting("SHOW_TOKEN_INFO", False)))
        tr_set(tokens_cb,
               "Строка снизу чата с токенами, заполнением контекста, кешем и стоимостью. По умолчанию выключена.",
               "Bottom-of-chat line with tokens, context fill, cache and cost. Off by default.", "setToolTip")
        tokens_cb.toggled.connect(lambda v: self._on_capture_toggle("SHOW_TOKEN_INFO", v))
        display_layout.addWidget(tokens_cb)
        self._show_tokens_cb = tokens_cb
        layout.addWidget(display_strip)

        # ── Контекст сессии ─────────────────────────────────────────────────
        summary_strip, summary_layout = self._make_strip(_("Контекст сессии", "Session context"), "fa6s.list-check")
        rows = [
            ("character", _("Персонаж", "Character")),
            ("prompts", _("Промпты", "Prompts")),
            ("model", _("Модель", "Model")),
            ("voice", _("Голос", "Voice")),
            ("asr", _("ASR", "ASR")),
            ("rag", _("RAG-режим", "RAG mode")),
            ("messages", _("Сообщений в окне", "Messages")),
            ("memory", _("Память", "Memory")),
            ("screen", _("Захват экрана", "Screen capture")),
            ("camera", _("Камера", "Camera")),
        ]
        for key, label_text in rows:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            register_if_tr(label, label_text)
            label.setObjectName("SandboxInfoLabel")
            row.addWidget(label)
            value = QLabel("—")
            value.setObjectName("SandboxInfoValue")
            value.setMinimumWidth(0)
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(value, 1)
            summary_layout.addLayout(row)
            self._debug_summary_values[key] = value

        refresh_btn = tr_set(QPushButton(), "Обновить сводку", "Refresh summary")
        refresh_btn.setObjectName("SandboxQuickAction")
        refresh_btn.clicked.connect(self._refresh_debug_summary)
        summary_layout.addWidget(refresh_btn)
        layout.addWidget(summary_strip)

        # ── Диагностика ─────────────────────────────────────────────────────
        diagnostics_strip, diagnostics_layout = self._make_strip(_("Диагностика", "Diagnostics"), "fa6s.screwdriver-wrench")
        db_btn = tr_set(QPushButton(), "Открыть DB персонажа", "Open character DB")
        db_btn.setObjectName("SandboxQuickAction")
        db_btn.clicked.connect(self._open_selected_character_history)
        diagnostics_layout.addWidget(db_btn)

        logs_btn = tr_set(QPushButton(), "Открыть страницу логов", "Open logs page")
        logs_btn.setObjectName("SandboxQuickAction")
        logs_btn.clicked.connect(lambda: self._page_actions.switch_page("logs"))
        diagnostics_layout.addWidget(logs_btn)

        api_btn = tr_set(QPushButton(), "Открыть API-настройки", "Open API settings")
        api_btn.setObjectName("SandboxQuickAction")
        api_btn.clicked.connect(lambda: self._jump_to_settings("api"))
        diagnostics_layout.addWidget(api_btn)
        layout.addWidget(diagnostics_strip)

        # ── Параметры отладки (migrated debug panel) ────────────────────────
        debug_panel_strip, debug_panel_layout = self._make_strip(_("Параметры отладки", "Debug parameters"), "fa6s.bug")
        try:
            from ui.settings.debug_settings import setup_debug_panel_controls
            setup_debug_panel_controls(
                debug_panel_layout,
                settings=self,
                insert_system_message=self._page_actions.insert_debug_message,
                save_snapshot=self._page_actions.save_debug_snapshot,
                load_snapshot=self._page_actions.load_debug_snapshot,
                view_context=self._page_actions.view_debug_context,
            )
        except Exception as exc:
            err = QLabel(f"[debug_settings error] {exc}")
            err.setWordWrap(True)
            debug_panel_layout.addWidget(err)
        layout.addWidget(debug_panel_strip)

        layout.addStretch(1)
        return self._wrap_in_scroll(page)

    def _build_inspector(self) -> QWidget:
        inspector = QFrame()
        inspector.setObjectName("SandboxInspector")
        inspector.setMinimumWidth(self._inspector_expanded_width)
        inspector.setMaximumWidth(self._inspector_expanded_width)
        self._inspector_widget = inspector

        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self._inspector_layout = layout

        header = QFrame()
        header.setObjectName("SandboxInspectorTabHeader")
        self._inspector_header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        tab_host = QWidget()
        tab_host.setObjectName("SandboxInspectorTabHost")
        tab_host_layout = QHBoxLayout(tab_host)
        tab_host_layout.setContentsMargins(0, 0, 0, 0)
        tab_host_layout.setSpacing(8)
        self._inspector_tab_host = tab_host

        session_page = self._build_inspector_session_tab()
        state_page = self._build_inspector_state_tab()
        debug_page = self._build_inspector_debug_tab()

        self._inspector_tab_buttons = {}
        for key, label in (
            ("session", _("Сессия", "Session")),
            ("state", _("Состояние", "State")),
            ("debug", _("Отладка", "Debug")),
        ):
            tab_host_layout.addWidget(self._make_inspector_tab_button(key, label))
        tab_host_layout.addStretch(1)
        header_layout.addWidget(tab_host, 1)

        collapse_btn = QPushButton()
        collapse_btn.setObjectName("SandboxInspectorCollapseBtn")
        collapse_btn.setFixedSize(34, 34)
        collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(collapse_btn, "Свернуть панель", "Collapse panel", "setToolTip")
        collapse_btn.clicked.connect(self._toggle_inspector_collapsed)
        header_layout.addWidget(collapse_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._inspector_collapse_btn = collapse_btn
        self._update_inspector_collapse_icon()
        layout.addWidget(header)

        stack = QStackedWidget()
        stack.setObjectName("SandboxInspectorStack")
        self._inspector_tab_indexes = {
            "session": stack.addWidget(session_page),
            "state": stack.addWidget(state_page),
            "debug": stack.addWidget(debug_page),
        }
        layout.addWidget(stack, 1)
        self._inspector_stack = stack

        # Collapsed-state rail lives in the same layout, hidden until folded.
        rail = self._build_inspector_rail()
        rail.setVisible(False)
        layout.addWidget(rail, 1)
        self._inspector_rail = rail

        self._set_inspector_tab("session")
        return inspector

    def _build_inspector_rail(self) -> QWidget:
        """Collapsed inspector as a slim activity-bar rail (VS Code style):
        an expand button, one icon per tab (click → expand straight to it),
        and a live status-dot cluster — so the folded panel stays glanceable
        and one click from anywhere instead of being a dead empty strip."""
        rail = QWidget()
        rail.setObjectName("SandboxInspectorRail")
        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 0, 0, 4)
        v.setSpacing(10)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        expand = QPushButton()
        expand.setObjectName("SandboxInspectorCollapseBtn")
        expand.setFixedSize(34, 34)
        expand.setCursor(Qt.CursorShape.PointingHandCursor)
        expand.setIcon(qta.icon("fa6s.angles-left", color="#ffd6ee"))
        expand.setIconSize(QSize(14, 14))
        tr_set(expand, "Развернуть панель", "Expand panel", "setToolTip")
        expand.clicked.connect(self._toggle_inspector_collapsed)
        v.addWidget(expand, 0, Qt.AlignmentFlag.AlignHCenter)

        top_div = QFrame()
        top_div.setObjectName("SandboxRailDivider")
        top_div.setFixedSize(24, 1)
        v.addWidget(top_div, 0, Qt.AlignmentFlag.AlignHCenter)

        self._rail_tab_buttons = {}
        for key, icon_name, tip in (
            ("session", "fa6s.id-badge", _("Сессия", "Session")),
            ("state", "fa6s.heart-pulse", _("Состояние", "State")),
            ("debug", "fa6s.bug", _("Отладка", "Debug")),
        ):
            btn = QPushButton()
            btn.setObjectName("SandboxRailTabButton")
            btn.setCheckable(True)
            btn.setFixedSize(38, 38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(qta.icon(icon_name, color="#ffd2ec"))
            btn.setIconSize(QSize(16, 16))
            btn.setToolTip(tip)
            register_if_tr(btn, tip, "setToolTip")
            btn.clicked.connect(lambda _c=False, k=key: self._expand_to_tab(k))
            self._rail_tab_buttons[key] = btn
            v.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)

        v.addStretch(1)

        return rail

    def _expand_to_tab(self, tab_key: str):
        """Rail icon click: unfold the inspector and jump straight to that tab."""
        if self._inspector_collapsed:
            self._toggle_inspector_collapsed()
        self._set_inspector_tab(tab_key)

    def _toggle_inspector_collapsed(self):
        self._inspector_collapsed = not self._inspector_collapsed
        if self._inspector_widget is None or self._inspector_stack is None:
            return
        collapsed = self._inspector_collapsed

        if self._inspector_header is not None:
            self._inspector_header.setVisible(not collapsed)
        self._inspector_stack.setVisible(not collapsed)
        if self._inspector_rail is not None:
            self._inspector_rail.setVisible(collapsed)

        width = self._inspector_collapsed_width if collapsed else self._inspector_expanded_width
        self._inspector_widget.setMinimumWidth(width)
        self._inspector_widget.setMaximumWidth(width)
        if self._inspector_layout is not None:
            # Tighten the shell margins when folded so the 38px icons breathe
            # inside the narrow rail; restore the roomy padding when expanded.
            if collapsed:
                self._inspector_layout.setContentsMargins(8, 14, 8, 12)
            else:
                self._inspector_layout.setContentsMargins(14, 14, 14, 14)

        if self._inspector_collapse_btn is not None:
            self._inspector_collapse_btn.setToolTip(
                _("Развернуть панель", "Expand panel") if collapsed else _("Свернуть панель", "Collapse panel")
            )
        self._update_inspector_collapse_icon()

    def _build_ui(self):
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(14, 12, 14, 12)
        page_layout.setSpacing(0)

        workspace_shell = QFrame()
        workspace_shell.setObjectName("SandboxWorkspaceShell")
        shell_layout = QGridLayout(workspace_shell)
        shell_layout.setContentsMargins(14, 12, 14, 12)
        shell_layout.setHorizontalSpacing(12)
        shell_layout.setVerticalSpacing(8)
        shell_layout.setColumnStretch(0, 1)
        shell_layout.setColumnStretch(1, 0)
        shell_layout.setRowStretch(1, 1)

        shell_layout.addWidget(self._build_title_bar(), 0, 0, 1, 2)

        chat_view_model = self._chat_panel_view_model
        self._chat_panel = ChatPanel(
            self,
            chat_view_model,
            self._chat_panel_actions,
        )
        chat_view_model.setParent(self._chat_panel)
        chat_host = QFrame()
        chat_host.setObjectName("SandboxChatHost")
        chat_host_layout = QVBoxLayout(chat_host)
        chat_host_layout.setContentsMargins(14, 14, 14, 14)
        chat_host_layout.setSpacing(0)
        chat_host_layout.addWidget(self._chat_panel)

        shell_layout.addWidget(chat_host, 1, 0)
        shell_layout.addWidget(self._build_inspector(), 1, 1)
        page_layout.addWidget(workspace_shell, 1)


def build_sandbox_page(
    window,
    view_model,
    *,
    character_state_view_model,
    chat_panel_view_model,
    chat_panel_actions,
    page_actions,
) -> QWidget:
    page = SandboxPage(
        window,
        view_model,
        character_state_view_model=character_state_view_model,
        chat_panel_view_model=chat_panel_view_model,
        chat_panel_actions=chat_panel_actions,
        page_actions=page_actions,
    )
    view_model.setParent(page)
    return page
