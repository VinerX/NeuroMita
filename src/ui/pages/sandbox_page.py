import os
import time

import qtawesome as qta

from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
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

from core.events import Events
from main_logger import logger
from ui.chat.message_widget import AVATAR_MAP, _get_avatar_dir
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
    """A live status line: [dot] [name] … [value] [switch] [gear→settings].

    * The multi-state dot reflects real state: grey = off, green = active,
      yellow = initialising, red = error. Green/off come from
      update_status_colors() (registry `setChecked`); yellow/red come from the
      SET_SETTINGS_ICON_INDICATOR feed routed in via `set_indicator()`.
    * The switch turns the feature on/off (its enable setting); the gear jumps
      to settings to actually pick the engine/model.
    * The "what exactly" value is filled by the sandbox via `set_value()`.
    """

    _DOT_COLORS = {
        "off": ("rgba(255,255,255,0.10)", "rgba(255,255,255,0.18)"),
        "active": ("#79e78c", "rgba(121,231,140,0.88)"),
        "init": ("#ffd60a", "rgba(255,214,10,0.85)"),
        "error": ("#ff453a", "rgba(255,69,58,0.85)"),
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

        self._dot = QLabel()
        self._dot.setFixedSize(12, 12)
        h.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        name = QLabel(name_text)
        register_if_tr(name, name_text)
        name.setObjectName("SandboxInfoLabel")
        h.addWidget(name, 0, Qt.AlignmentFlag.AlignVCenter)

        self._value = QLabel("—")
        self._value.setObjectName("SandboxInfoValue")
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._value.setMinimumWidth(112)
        h.addWidget(self._value, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
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

        self._apply_dot()

    # ----- state inputs -----
    def setChecked(self, checked: bool):
        # update_status_colors() → True means the subsystem is actually live.
        self._active = bool(checked)
        self._apply_dot()

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
        self._apply_dot()

    def set_indicator(self, state):
        # state: None | "loading" | "red" | "green" (from SET_SETTINGS_ICON_INDICATOR)
        st = str(state).strip().lower() if state else None
        self._indicator = st if st in ("loading", "red", "green") else None
        self._apply_dot()

    def set_value(self, text: str):
        self._full_value_text = text or "—"
        self._value.setToolTip(self._full_value_text)
        self._apply_value_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_value_text()

    # ----- dot rendering -----
    def _resolve_state(self) -> str:
        if not self._enabled:
            return "off"
        if self._indicator == "red":
            return "error"
        if self._indicator == "loading":
            return "init"
        if self._indicator == "green" or self._active:
            return "active"
        # Enabled but not confirmed active yet and no explicit signal.
        return "init"

    def _apply_dot(self):
        bg, border = self._DOT_COLORS[self._resolve_state()]
        self._dot.setStyleSheet(
            f"background-color: {bg}; border: 1px solid {border}; border-radius: 6px;"
        )

    def _apply_value_text(self):
        value = self._full_value_text or "—"
        available = max(24, self._value.width() - 2)
        elided = self._value.fontMetrics().elidedText(
            value,
            Qt.TextElideMode.ElideRight,
            available,
        )
        self._value.setText(elided)


class SandboxPage(QWidget):
    # Marshal background-thread event callbacks onto the GUI thread.
    _lr_started_signal = pyqtSignal(dict)
    _lr_finished_signal = pyqtSignal(dict)
    _budget_refresh_signal = pyqtSignal()
    _indicator_signal = pyqtSignal(dict)
    _setting_changed_signal = pyqtSignal(str)

    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("SandboxPage")

        self._memory_limit_values = {}
        self._debug_summary_values = {}
        self._chat_panel = None
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
        self._wire_diagnostics()
        self._sync_host_exports()

    def _sync_host_exports(self):
        self.gui.sandbox_page = self

    def _get_current_character_id(self) -> str:
        try:
            result = self.gui.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=0.5)
            profile = result[0] if result else {}
        except Exception:
            profile = {}
        return str((profile or {}).get("character_id") or "")

    def _jump_to_settings(self, category: str, subsection=None):
        # Шестерёнка у строки статуса ведёт ИМЕННО в её раздел, даже если подсистема
        # сейчас выключена/скрыта в «Видимых разделах» (фидбэк #14). subsection —
        # вложенная секция (например RAG внутри «Модели»), чтобы попасть сразу к
        # нужным полям, а не в начало длинной страницы (фидбэк Артёма).
        self.gui.switch_main_page("settings")
        self.gui.show_settings_category(category, force=True, subsection=subsection)

    # --------- Status rows (voice / mic / RAG) -----------
    def _make_status_row(self, name_text: str, registry_attr: str, settings_key: str,
                         enable_key: str, tooltip: str, subsection=None) -> "_SandboxStatusRow":
        initial_on = bool(self.gui._get_setting(enable_key, False))
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
            from ui.widgets.status_indicators_widget import _register_indicator
            _register_indicator(self.gui, registry_attr, row)
        except Exception:
            pass
        return row

    def _on_status_toggle(self, enable_key: str, checked: bool):
        """Flip a feature on/off. Routed through SAVE_SETTING so the voiceover /
        ASR / RAG controllers actually start or stop the subsystem."""
        try:
            self.gui.event_bus.emit(Events.Settings.SAVE_SETTING, {"key": enable_key, "value": bool(checked)})
        except Exception as exc:
            logger.error(f"Failed to toggle {enable_key}: {exc}")
        # Optimistic dot feedback; the authoritative refresh happens reactively
        # when the resulting SETTING_CHANGED comes back (see _on_setting_changed_ui).
        row = {
            "USE_VOICEOVER": self._voice_status_row,
            "MIC_ACTIVE": self._mic_status_row,
            "RAG_ENABLED": self._rag_status_row,
        }.get(enable_key)
        if row is not None:
            row.set_enabled_state(bool(checked))

    def _make_toggle_row(self, label_text: str, on_toggle, initial_on: bool,
                         tooltip: str | None = None, with_dot: bool = False):
        """A [label … switch] row using the same pill toggle as the status
        rows. When *with_dot* is set, a leading status dot (like the Status
        rows above) reflects the switch — two states only: grey off / green on.
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
        get = self.gui._get_setting

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

    def _local_voice_name(self, model_id: str) -> str:
        try:
            from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
            for model in LOCAL_VOICE_MODELS:
                if str(model.get("id") or "") == model_id:
                    return str(model.get("name") or model_id)
        except Exception:
            pass
        return model_id

    def _format_local_voice_value(self, model_id: str) -> str:
        base = _("Локально", "Local")
        if not model_id:
            return base
        return f"{base}: {self._local_voice_name(model_id)}"

    # --------- Avatar -----------
    def _resolve_avatar_pixmap(self, character_id: str, size: int = 32) -> QPixmap:
        char_id = (character_id or "").strip()
        candidates = []
        if char_id:
            # Direct match in AVATAR_MAP keys (e.g. "Crazy Mita")
            for key, fn in AVATAR_MAP.items():
                if key.lower().startswith(char_id.lower()) or char_id.lower().startswith(key.lower().split()[0]):
                    candidates.append(fn)
            candidates.append(f"{char_id.lower()}.png")
        avatar_dir = _get_avatar_dir()
        for fn in candidates:
            path = os.path.join(avatar_dir, fn)
            if os.path.isfile(path):
                pm = QPixmap(path)
                if not pm.isNull():
                    return _round_pixmap(pm, size)
        # Fallback icon
        icon_pm = qta.icon("fa6s.user", color="#ffd2ec").pixmap(size - 4, size - 4)
        return _round_pixmap(icon_pm, size)

    def _refresh_character_avatar(self):
        if self._character_avatar_label is None:
            return
        char_id = self._get_current_character_id()
        if not char_id:
            combo = getattr(self.gui, "chat_character_combobox", None)
            if combo is not None:
                char_id = combo.currentText().strip()
        self._character_avatar_label.setPixmap(self._resolve_avatar_pixmap(char_id, 32))

    # --------- Model -----------
    def _populate_model_combobox(self):
        combo = getattr(self.gui, "chat_model_combobox", None)
        if combo is None:
            return

        try:
            result = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
            meta = result[0] if result else {}
        except Exception:
            meta = {}

        customs = list((meta or {}).get("custom", []))

        combo.blockSignals(True)
        try:
            combo.clear()

            if customs:
                for preset in customs:
                    preset_id = getattr(preset, "id", None)
                    name = getattr(preset, "name", "")
                    if preset_id is None:
                        continue
                    combo.add_data_item(str(name), value=int(preset_id))
                combo.insertSeparator(combo.count())
            else:
                combo.add_tr_item("Нет настроенных моделей", "No configured models", value=None)
                combo.insertSeparator(combo.count())

            combo.add_tr_item("Настроить…", "Configure…", value=_MODEL_CONFIGURE_SENTINEL)

            try:
                current_res = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_CURRENT_PRESET_ID, timeout=0.5)
                current_id = current_res[0] if current_res else None
            except Exception:
                current_id = None

            if current_id is not None:
                for index in range(combo.count()):
                    if combo.itemData(index) == int(current_id):
                        combo.setCurrentIndex(index)
                        break
        finally:
            combo.blockSignals(False)

    def _on_chat_model_changed(self, index: int):
        combo = getattr(self.gui, "chat_model_combobox", None)
        if combo is None or index < 0:
            return
        data = combo.itemData(index)
        if data == _MODEL_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_model_combobox)
            self._jump_to_settings("api")
            return
        if data is None:
            return
        try:
            self.gui.event_bus.emit(Events.ApiPresets.SET_CURRENT_PRESET_ID, {"id": int(data)})
        except Exception as exc:
            logger.error(f"Failed to switch preset: {exc}")
        self._refresh_debug_summary()

    def _current_preset_name(self) -> str:
        try:
            cur = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_CURRENT_PRESET_ID, timeout=0.5)
            cur_id = cur[0] if cur else None
            lst = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=0.5)
            meta = lst[0] if lst else {}
            for preset in (meta or {}).get("custom", []) or []:
                pid = getattr(preset, "id", None)
                if pid is not None and cur_id is not None and int(pid) == int(cur_id):
                    return str(getattr(preset, "name", "") or "")
        except Exception:
            pass
        return ""

    # --------- Prompt set -----------
    def _populate_prompt_pack_combobox(self):
        combo = getattr(self.gui, "chat_prompt_pack_combobox", None)
        if combo is None:
            return
        char_id = self._get_current_character_id()
        if not char_id:
            char_combo = getattr(self.gui, "chat_character_combobox", None)
            if char_combo is not None:
                char_id = char_combo.currentText().strip()

        try:
            from managers.prompt_catalogue_manager import list_prompt_sets
            options = list_prompt_sets("Prompts", char_id) or []
        except Exception:
            options = []

        current = ""
        if char_id:
            try:
                current = str(self.gui._get_setting(f"PROMPT_SET_{char_id}", "") or "")
            except Exception:
                current = ""

        combo.blockSignals(True)
        try:
            combo.clear()
            if options:
                for name in options:
                    combo.add_data_item(str(name), value=str(name))
            else:
                combo.add_tr_item("Нет наборов", "No sets", value=None)
            combo.insertSeparator(combo.count())
            combo.add_tr_item("Настроить…", "Configure…", value=_PROMPT_CONFIGURE_SENTINEL)

            if current:
                idx = combo.findText(current, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    def _on_chat_prompt_pack_changed(self, index: int):
        combo = getattr(self.gui, "chat_prompt_pack_combobox", None)
        if combo is None or index < 0:
            return
        data = combo.itemData(index)
        if data == _PROMPT_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_prompt_pack_combobox)
            self._jump_to_settings("characters")
            return
        if not data:
            return
        char_id = self._get_current_character_id()
        if not char_id:
            char_combo = getattr(self.gui, "chat_character_combobox", None)
            if char_combo is not None:
                char_id = char_combo.currentText().strip()
        if not char_id:
            return
        try:
            self.gui.settings.set(f"PROMPT_SET_{char_id}", str(data))
            try:
                self.gui.settings.save_settings()
            except Exception:
                pass
            self.gui.event_bus.emit(Events.Character.RELOAD_DATA)
        except Exception as exc:
            logger.error(f"Failed to switch prompt set: {exc}")
        self._refresh_debug_summary()

    # --------- Character -----------
    def _populate_chat_character_combobox(self):
        combo = getattr(self.gui, "chat_character_combobox", None)
        if combo is None:
            return

        all_characters = self.gui.event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
        character_list = all_characters[0] if all_characters else ["Crazy"]
        if not character_list:
            character_list = ["Crazy"]

        current_char_id = self._get_current_character_id() or character_list[0]

        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(character_list)
            index = combo.findText(str(current_char_id), Qt.MatchFlag.MatchFixedString)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _on_chat_character_changed(self, character_id):
        character_id = str(character_id or "").strip()
        if not character_id:
            return

        settings_combo = getattr(self.gui, "character_combobox", None)
        if settings_combo is not None and settings_combo.currentText() != character_id:
            index = settings_combo.findText(character_id, Qt.MatchFlag.MatchFixedString)
            if index >= 0:
                settings_combo.setCurrentIndex(index)
                if self._chat_panel is not None:
                    self._chat_panel.on_activated()
                self._refresh_character_avatar()
                self._populate_prompt_pack_combobox()
                self._refresh_debug_summary()
                return

        self.gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})
        self.gui.event_bus.emit(Events.Character.RELOAD_DATA)
        if self._chat_panel is not None:
            self._chat_panel.on_activated()
        self._refresh_character_avatar()
        self._populate_prompt_pack_combobox()
        self._refresh_debug_summary()

    def _open_selected_character_history(self):
        combo = getattr(self.gui, "chat_character_combobox", None)
        character_id = combo.currentText().strip() if combo is not None else ""
        if character_id:
            self.gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})
        try:
            from ui.settings.character_settings.logic import open_db_viewer
            open_db_viewer(self.gui)
        except Exception as exc:
            logger.error(f"Failed to open character history: {exc}", exc_info=True)

    # --------- RAG / memory profile -----------
    def _memory_profile_labels(self):
        from ui.settings.memory_profile import KEY_TO_LABEL_EN, KEY_TO_LABEL_RU
        lang = str(self.gui._get_setting("LANGUAGE", "RU") or "RU").upper()
        return KEY_TO_LABEL_EN if lang == "EN" else KEY_TO_LABEL_RU

    def _rag_preset_name(self) -> str:
        """Name of the active RAG *pipeline* preset — what/how RAG retrieves
        (Keyword+FTS, Vector+FTS, …). The embedding model is appended only when
        vector search is on, since that's the only mode where it's actually used.
        (Not the memory profile, which is a separate memory-window concept.)"""
        try:
            from managers.settings_manager import SettingsManager
            from managers.rag.pipeline.config import (
                RAG_PIPELINE_PRESETS, match_pipeline_preset, _b,
            )
            try:
                from ui.settings.rag_memory_settings import _load_user_presets
                user_presets = _load_user_presets() or {}
            except Exception:
                user_presets = {}

            name = str(SettingsManager.get("RAG_PIPELINE_PRESET", "Keyword+FTS only") or "").strip()
            known = set(RAG_PIPELINE_PRESETS) | set(user_presets)
            if name in ("", "Custom") or name not in known:
                # Stored selection is 'Custom' (or unknown) — try to recognise the
                # current settings as a built-in/user preset before giving up.
                name = match_pipeline_preset(user_presets) or _("Custom", "Custom")

            if _b(SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", False), False):
                from handlers.embedding_presets import resolve_full_config
                cfg = resolve_full_config() or {}
                model_name = self._short_rag_model_name(
                    cfg.get("model") or cfg.get("hf_name") or cfg.get("db_model_key") or ""
                )
                if model_name:
                    name = f"{name} · {model_name}"

            # Компактная подпись для узкого статус-чипа: суффикс « only» в
            # названиях пресетов («Keyword+FTS only») лишь съедает место и
            # обрезается до невнятного «Keyword+FT…». Полный текст остаётся в тултипе.
            name = name.replace(" only", "")
            return name or _("Включён", "Enabled")
        except Exception:
            return _("Включён", "Enabled")

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

    def _refresh_memory_summary(self):
        """Live mini-stats for the current character: real counts vs. limits,
        plus the forgotten-memory count (RAG keeps these retrievable)."""
        if not self._memory_limit_values:
            return

        get = self.gui._get_setting
        msg_limit = get("MODEL_MESSAGE_LIMIT", 35)
        mem_limit = get("MEMORY_CAPACITY", 50)
        cid = self._get_current_character_id()

        try:
            from managers.database_manager import DatabaseManager
            db = DatabaseManager()
            stats = db.get_world_stats(cid)
        except Exception:
            db = None
            stats = {}

        # Missing embeddings for the current model (stale-index indicator).
        miss_h = miss_m = None
        if db is not None and cid:
            try:
                miss_h, miss_m = db.count_missing_embeddings(cid)
            except Exception:
                miss_h = miss_m = None

        def _fmt(count, limit=None):
            if count is None:
                return "—"
            return f"{count} / {limit}" if limit is not None else str(count)

        def _pair(a, b):
            if a is None and b is None:
                return "—"
            return f"{a or 0} / {b or 0}"

        mapping = {
            "messages": _fmt(stats.get("history_active"), msg_limit),
            "memories": _fmt(stats.get("memories_active"), mem_limit),
            "forgotten": _fmt(stats.get("memories_forgotten")),
            "missing": _pair(miss_h, miss_m),
            "trash": _pair(stats.get("history_deleted"), stats.get("memories_deleted")),
            "last": self._fmt_timestamp(stats.get("last_activity")),
            "dbsize": self._fmt_bytes(stats.get("db_size_bytes")),
        }
        for stat_key, text in mapping.items():
            label = self._memory_limit_values.get(stat_key)
            if label is not None:
                label.setText(text)

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
        get = self.gui._get_setting
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
            if getattr(self.gui, "current_main_page", None) != "sandbox":
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
        self._schedule_activation_step(ticket, 105, lambda: self.gui.update_status_colors())
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

    def _make_strip(self, title_text: str, icon_name: str | None = None) -> tuple[QWidget, QVBoxLayout]:
        """Stack-panel section: flat, no card border, just a title row
        with an optional icon and an underline. Used everywhere except the
        State tab (which keeps cards on the character_state_panel)."""
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
        guide_button.clicked.connect(self.gui._show_guide)
        actions.addWidget(guide_button)

        wiki_button = tr_set(QPushButton(), "Вики", "Wiki")
        wiki_button.setObjectName("SandboxHeaderButton")
        wiki_button.clicked.connect(lambda: self.gui.switch_main_page("wiki"))
        actions.addWidget(wiki_button)

        settings_button = tr_set(QPushButton(), "Настройки", "Settings")
        settings_button.setObjectName("SandboxHeaderButton")
        settings_button.clicked.connect(lambda: self.gui.switch_main_page("settings"))
        actions.addWidget(settings_button)

        home_button = tr_set(QPushButton(), "На главную", "Home")
        home_button.setObjectName("SandboxHeaderPrimaryButton")
        home_button.clicked.connect(lambda: self.gui.switch_main_page("home"))
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
            setattr(self.gui, attr, combo)
            return combo

        def _combo_row(strip_layout, label_text: str, combo: QComboBox, leading=None) -> None:
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
        _combo_row(active_layout, _("Персонаж", "Character"), char_combo, leading=self._character_avatar_label)

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
        status_strip, status_layout = self._make_strip(_("Статус", "Status"), "fa6s.wave-square")

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
        screen_row, self._capture_screen_cb = self._make_toggle_row(
            _("Захват экрана", "Screen capture"),
            lambda v: self._on_capture_toggle("ENABLE_SCREEN_ANALYSIS", v),
            bool(self.gui._get_setting("ENABLE_SCREEN_ANALYSIS", False)),
            with_dot=True,
        )
        capture_layout.addWidget(screen_row)

        attach_row, self._capture_auto_attach_cb = self._make_toggle_row(
            _("Авто-прикрепление", "Auto-attach"),
            lambda v: self._on_capture_toggle("AUTO_ATTACH_IMAGES", v),
            bool(self.gui._get_setting("AUTO_ATTACH_IMAGES", False)),
            with_dot=True,
        )
        capture_layout.addWidget(attach_row)

        camera_row, self._capture_camera_cb = self._make_toggle_row(
            _("Захват с камеры", "Camera capture"),
            lambda v: self._on_capture_toggle("ENABLE_CAMERA_CAPTURE", v),
            bool(self.gui._get_setting("ENABLE_CAMERA_CAPTURE", False)),
            with_dot=True,
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
        full_settings_btn.clicked.connect(lambda: self.gui.switch_main_page("settings"))
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
            from ui.widgets.sandbox_panels import is_panel_enabled
        except Exception:
            return
        for key, widget in self._panels.items():
            if widget is not None:
                widget.setVisible(is_panel_enabled(key))

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
        if self._budget_bar is None:
            return
        try:
            res = self.gui.event_bus.emit_and_wait(Events.Model.GET_CURRENT_CONTEXT_TOKENS, timeout=0.5)
            used = int(res[0]) if res and res[0] is not None else 0
        except Exception:
            used = 0
        try:
            max_tokens = int(self.gui._get_setting("MAX_MODEL_TOKENS", 32000) or 32000)
        except Exception:
            max_tokens = 32000
        max_tokens = max(1, max_tokens)
        try:
            cres = self.gui.event_bus.emit_and_wait(Events.Model.CALCULATE_COST, timeout=0.5)
            cost = float(cres[0]) if cres and cres[0] is not None else 0.0
        except Exception:
            cost = 0.0

        pct = min(100, int(used * 100 / max_tokens))
        self._budget_bar.setValue(pct)
        if self._budget_value is not None:
            self._budget_value.setText(
                _("{used} / {max} токенов · {pct}% · ~{cost:.4f} ₽",
                  "{used} / {max} tokens · {pct}% · ~{cost:.4f} ₽").format(
                    used=used, max=max_tokens, pct=pct, cost=cost)
            )

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

    # --------- Diagnostics event wiring -----------
    def _wire_diagnostics(self):
        """Subscribe to the model request lifecycle so the Last-request panel
        and the context budget stay live. Event callbacks may fire on worker
        threads, so they only set primitives / emit Qt signals; the actual
        widget updates happen on the GUI thread via the connected slots."""
        self._lr_started_signal.connect(self._on_lr_started_ui)
        self._lr_finished_signal.connect(self._on_lr_finished_ui)
        self._budget_refresh_signal.connect(self._refresh_context_budget)
        self._indicator_signal.connect(self._on_indicator_ui)
        self._setting_changed_signal.connect(self._on_setting_changed_ui)

        bus = getattr(self.gui, "event_bus", None)
        if bus is None:
            return
        try:
            bus.subscribe(Events.Model.ON_STARTED_RESPONSE_GENERATION, self._on_resp_started_evt, weak=False)
            bus.subscribe(Events.Model.ON_SUCCESSFUL_RESPONSE, self._on_resp_success_evt, weak=False)
            bus.subscribe(Events.Model.ON_FAILED_RESPONSE, self._on_resp_failed_evt, weak=False)
            bus.subscribe(Events.GUI.UPDATE_TOKEN_COUNT_UI, self._on_token_count_evt, weak=False)
            bus.subscribe(Events.GUI.SET_SETTINGS_ICON_INDICATOR, self._on_indicator_evt, weak=False)
            bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed_evt, weak=False)
        except Exception as exc:
            logger.debug(f"Sandbox diagnostics wiring failed: {exc}")

    # Keys that affect the status rows / context budget / memory-stat readouts.
    _STATUS_KEYS = frozenset({
        "USE_VOICEOVER", "VOICEOVER_METHOD", "LOCAL_VOICE_MODEL_ID", "NM_CURRENT_VOICEOVER",
        "MIC_ACTIVE", "RECOGNIZER_TYPE", "RAG_ENABLED", "RAG_EMBED_PRESET_ID",
        "RAG_EMBED_MODEL", "MEMORY_PROFILE",
    })
    _BUDGET_KEYS = frozenset({"MAX_MODEL_TOKENS"})
    _MEMORY_KEYS = frozenset({"MODEL_MESSAGE_LIMIT", "MEMORY_CAPACITY"})

    def _on_setting_changed_evt(self, event):
        data = getattr(event, "data", None) or {}
        key = str(data.get("key") or "")
        if key:
            self._setting_changed_signal.emit(key)

    def _on_setting_changed_ui(self, key: str):
        if key in self._STATUS_KEYS:
            self._refresh_status_values()
            try:
                self.gui.update_status_colors()
            except Exception:
                pass
        if key in self._BUDGET_KEYS:
            self._refresh_context_budget()
        if key in self._MEMORY_KEYS:
            self._refresh_memory_summary()

    def _on_indicator_evt(self, event):
        data = getattr(event, "data", None) or {}
        self._indicator_signal.emit({
            "category": str(data.get("category") or ""),
            "state": data.get("state"),
        })

    def _on_indicator_ui(self, info: dict):
        # Route the loading/red/green indicator to the matching status row so
        # the dot can show init (yellow) / error (red) live.
        row = {
            "voice": self._voice_status_row,
            "microphone": self._mic_status_row,
            "models": self._rag_status_row,
        }.get(str(info.get("category") or ""))
        if row is not None:
            row.set_indicator(info.get("state"))

    def _on_resp_started_evt(self, event):
        self._lr_t0 = time.perf_counter()
        data = getattr(event, "data", None) or {}
        self._lr_started_signal.emit({"character": str(data.get("character_name") or "")})

    def _on_resp_success_evt(self, event):
        self._emit_lr_finished(True, "")

    def _on_resp_failed_evt(self, event):
        data = getattr(event, "data", None) or {}
        self._emit_lr_finished(False, str(data.get("error") or ""))

    def _emit_lr_finished(self, ok: bool, error: str):
        latency = None
        if self._lr_t0 is not None:
            latency = time.perf_counter() - self._lr_t0
        self._lr_finished_signal.emit({"ok": bool(ok), "error": error, "latency": latency})

    def _on_token_count_evt(self, event):
        self._budget_refresh_signal.emit()

    def _on_lr_started_ui(self, info: dict):
        if not self._lr_values:
            return
        self._lr_values["status"].setText(_("Генерация…", "Generating…"))
        self._lr_values["model"].setText(self._current_preset_name() or "—")

    def _on_lr_finished_ui(self, info: dict):
        if not self._lr_values:
            return
        if info.get("ok"):
            self._lr_values["status"].setText(_("✓ Успех", "✓ Success"))
        else:
            err = str(info.get("error") or "").strip()
            self._lr_values["status"].setText(_("✗ Ошибка", "✗ Error") + (f": {err}" if err else ""))

        latency = info.get("latency")
        if isinstance(latency, (int, float)):
            self._lr_values["latency"].setText(_("{:.2f} с", "{:.2f} s").format(latency))
        else:
            self._lr_values["latency"].setText("—")

        self._lr_values["model"].setText(self._current_preset_name() or "—")
        # Context tokens as a proxy for prompt usage — the real API usage object
        # isn't surfaced up the stack yet (see _refresh_context_budget).
        try:
            res = self.gui.event_bus.emit_and_wait(Events.Model.GET_CURRENT_CONTEXT_TOKENS, timeout=0.5)
            used = int(res[0]) if res and res[0] is not None else 0
        except Exception:
            used = 0
        self._lr_values["tokens"].setText(self._fmt_tokens(used))
        self._lr_values["time"].setText(time.strftime("%H:%M:%S"))
        self._refresh_context_budget()
        # A message (and possibly memories) just changed — refresh the DB stats.
        self._refresh_memory_summary()

    def _sync_toggles_from_settings(self):
        """Re-sync the capture/display checkboxes from the current settings so a
        change made on the settings page is reflected when the Sandbox is shown.
        (The Voice/Mic/RAG pills are synced separately by _refresh_status_values,
        and live via the SETTING_CHANGED subscription.)"""
        get = self.gui._get_setting
        pairs = (
            ("_capture_screen_cb", "ENABLE_SCREEN_ANALYSIS", False),
            ("_capture_auto_attach_cb", "AUTO_ATTACH_IMAGES", False),
            ("_capture_camera_cb", "ENABLE_CAMERA_CAPTURE", False),
            ("_show_thinking_cb", "SHOW_THINK_IN_GUI", False),
            ("_hide_tags_cb", "HIDE_CHAT_TAGS", True),
            ("_show_ts_cb", "SHOW_CHAT_TIMESTAMPS", True),
            ("_show_sys_cb", "SHOW_SYSTEM_MESSAGES", False),
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
        # Route through SAVE_SETTING (not a bare settings.set) so the change emits
        # SETTING_CHANGED — that's what reloads the chat for display toggles, wakes
        # the capture controllers, and keeps the settings page in sync.
        try:
            self.gui.event_bus.emit(Events.Settings.SAVE_SETTING, {"key": key, "value": bool(value)})
        except Exception:
            try:
                self.gui.settings.set(key, bool(value))
                self.gui.settings.save_settings()
            except Exception:
                pass
        self._refresh_debug_summary()

    def _on_view_last_request(self) -> None:
        """Open the last-request context viewer. Reuses the host view's handler
        so the SavedMessages fallback lookup stays in one place."""
        handler = getattr(self.gui, "_on_debug_view_last_context", None)
        if callable(handler):
            handler()

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
        try:
            self.gui.event_bus.emit(Events.Character.CLEAR_HISTORY)
        except Exception as exc:
            logger.error(f"Failed to reset character: {exc}", exc_info=True)
            return
        try:
            self.gui.clear_chat_display()
        except Exception:
            pass

    def _build_inspector_state_tab(self) -> QWidget:
        page, layout = self._make_tab_page()
        self._character_state_panel = CharacterStatePanel(self.gui)
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
        think_cb.setChecked(bool(self.gui._get_setting("SHOW_THINK_IN_GUI", False)))
        tr_set(think_cb,
               "Показывать содержимое блока мышления модели как отдельное сообщение в чате.",
               "Show the model's thinking block as a separate chat message.",
               "setToolTip")
        think_cb.toggled.connect(lambda v: self._on_capture_toggle("SHOW_THINK_IN_GUI", v))
        display_layout.addWidget(think_cb)
        self._show_thinking_cb = think_cb

        tags_cb = tr_set(QCheckBox(), "Скрывать теги в чате", "Hide tags in chat")
        tags_cb.setObjectName("SandboxCaptureToggle")
        tags_cb.setChecked(bool(self.gui._get_setting("HIDE_CHAT_TAGS", True)))
        tags_cb.toggled.connect(lambda v: self._on_capture_toggle("HIDE_CHAT_TAGS", v))
        display_layout.addWidget(tags_cb)
        self._hide_tags_cb = tags_cb

        ts_cb = tr_set(QCheckBox(), "Показывать время сообщений", "Show timestamps")
        ts_cb.setObjectName("SandboxCaptureToggle")
        ts_cb.setChecked(bool(self.gui._get_setting("SHOW_CHAT_TIMESTAMPS", True)))
        ts_cb.toggled.connect(lambda v: self._on_capture_toggle("SHOW_CHAT_TIMESTAMPS", v))
        display_layout.addWidget(ts_cb)
        self._show_ts_cb = ts_cb

        sys_cb = tr_set(QCheckBox(), "Показывать системные сообщения", "Show system messages")
        sys_cb.setObjectName("SandboxCaptureToggle")
        sys_cb.setChecked(bool(self.gui._get_setting("SHOW_SYSTEM_MESSAGES", False)))
        tr_set(sys_cb, "Показывать системные/контекстные заметки (например «[Easel drawing]…») в чате. По умолчанию скрыты.",
                "Show system/context notes (e.g. \"[Easel drawing]…\") in chat. Hidden by default.", "setToolTip")
        sys_cb.toggled.connect(lambda v: self._on_capture_toggle("SHOW_SYSTEM_MESSAGES", v))
        display_layout.addWidget(sys_cb)
        self._show_sys_cb = sys_cb
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
        logs_btn.clicked.connect(lambda: self.gui.switch_main_page("logs"))
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
            setup_debug_panel_controls(self.gui, debug_panel_layout)
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
        self.gui.sandbox_inspector_tabs = stack
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

        self._chat_panel = ChatPanel(self.gui)
        chat_host = QFrame()
        chat_host.setObjectName("SandboxChatHost")
        chat_host_layout = QVBoxLayout(chat_host)
        chat_host_layout.setContentsMargins(14, 14, 14, 14)
        chat_host_layout.setSpacing(0)
        chat_host_layout.addWidget(self._chat_panel)

        shell_layout.addWidget(chat_host, 1, 0)
        shell_layout.addWidget(self._build_inspector(), 1, 1)
        page_layout.addWidget(workspace_shell, 1)


def build_sandbox_page(window) -> QWidget:
    return SandboxPage(window)
