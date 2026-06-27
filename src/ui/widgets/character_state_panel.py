from __future__ import annotations

from typing import Any, Dict, List, Optional

import qtawesome as qta
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.events import Events
from main_logger import logger
from utils import _
from localization.live import tr_set



class _StatBar(QWidget):
    """A labelled horizontal progress bar with min/max/current value."""

    def __init__(self, label: str, color: str = "#ff5ca8", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CharacterStatBar")
        self._color = color
        self._min = 0.0
        self._max = 100.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)

        self._label = QLabel(label)
        self._label.setObjectName("CharacterStatLabel")
        head.addWidget(self._label, 1, Qt.AlignmentFlag.AlignLeft)

        self._value_label = QLabel("—")
        self._value_label.setObjectName("CharacterStatValue")
        head.addWidget(self._value_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(head)

        self._bar = QProgressBar()
        self._bar.setObjectName("CharacterStatProgress")
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(8)
        self._bar.setRange(0, 1000)
        self._bar.setStyleSheet(
            f"QProgressBar#CharacterStatProgress {{ background: rgba(255,255,255,0.06); border: none; border-radius: 4px; }}"
            f"QProgressBar#CharacterStatProgress::chunk {{ background: {color}; border-radius: 4px; }}"
        )
        layout.addWidget(self._bar)

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_range(self, vmin: float, vmax: float) -> None:
        if vmax <= vmin:
            vmax = vmin + 1.0
        self._min = float(vmin)
        self._max = float(vmax)

    def set_value(self, value: float, *, suffix: str | None = None) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = self._min
        clamped = max(self._min, min(self._max, v))
        ratio = (clamped - self._min) / (self._max - self._min) if self._max > self._min else 0.0
        self._bar.setValue(int(round(ratio * 1000)))

        # Pretty value text: int when no fractional part
        if abs(v - round(v)) < 0.05:
            text = f"{int(round(v))}"
        else:
            text = f"{v:.1f}"
        if self._max not in (0.0, 1.0):
            text = f"{text}/{int(self._max) if abs(self._max - round(self._max)) < 0.05 else self._max:g}"
        if suffix:
            text = f"{text} {suffix}"
        self._value_label.setText(text)


class _VariableSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self._key_fmt = QTextCharFormat()
        self._key_fmt.setForeground(QColor("#ff8ad1"))
        self._key_fmt.setFontWeight(QFont.Weight.Bold)

        self._str_fmt = QTextCharFormat()
        self._str_fmt.setForeground(QColor("#89f7b2"))

        self._num_fmt = QTextCharFormat()
        self._num_fmt.setForeground(QColor("#ffd86b"))

        self._bool_fmt = QTextCharFormat()
        self._bool_fmt.setForeground(QColor("#79d7ff"))

        self._none_fmt = QTextCharFormat()
        self._none_fmt.setForeground(QColor("#8d8d96"))
        self._none_fmt.setFontItalic(True)

        self._default_fmt = QTextCharFormat()
        self._default_fmt.setForeground(QColor("#f3edf6"))

    def highlightBlock(self, text: str) -> None:
        colon_idx = text.find(": ")
        if colon_idx >= 0:
            self.setFormat(0, colon_idx, self._key_fmt)
            value_part = text[colon_idx + 2:]
            self._highlight_value(colon_idx + 2, len(value_part), value_part.strip())
        else:
            self.setFormat(0, len(text), self._default_fmt)

    def _highlight_value(self, start: int, length: int, value: str) -> None:
        if length == 0:
            return
        lower = value.lower()
        if lower == "true" or lower == "false":
            self.setFormat(start, length, self._bool_fmt)
        elif value == "None" or value == "null" or value == "—":
            self.setFormat(start, length, self._none_fmt)
        elif value.startswith('"') or value.startswith("'"):
            self.setFormat(start, length, self._str_fmt)
        else:
            try:
                float(value)
                self.setFormat(start, length, self._num_fmt)
            except ValueError:
                self.setFormat(start, length, self._default_fmt)


class CharacterStatePanel(QWidget):
    """Right-panel widget showing live character state.

    Builds bars for attitude/boredom/stress (from config bounds), conditional
    badges (secretExposed), all custom_params (numeric → bar, bool → badge),
    a mood label, and a collapsible textarea with all variables.
    """

    def __init__(self, gui, parent: QWidget | None = None):
        super().__init__(parent)
        self.gui = gui
        self.setObjectName("SandboxStatePanel")

        self._dynamic_bars: Dict[str, _StatBar] = {}
        self._dynamic_badges: Dict[str, QLabel] = {}
        self._current_char_id: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # ── Core stats card ──
        core_card = QFrame()
        core_card.setObjectName("SandboxInspectorCard")
        core_layout = QVBoxLayout(core_card)
        core_layout.setContentsMargins(14, 14, 14, 14)
        core_layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        icon = QLabel()
        icon.setPixmap(qta.icon("fa6s.heart-pulse", color="#ffd2ec").pixmap(14, 14))
        title_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        title = tr_set(QLabel(), "Состояние персонажа", "Character state")
        title.setObjectName("SandboxInspectorTitle")
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        core_layout.addLayout(title_row)

        self._attitude_bar = _StatBar(_("Отношение", "Attitude"), "#ff5ca8")
        self._boredom_bar = _StatBar(_("Скука", "Boredom"), "#9d6cff")
        self._stress_bar = _StatBar(_("Стресс", "Stress"), "#ffb86b")
        core_layout.addWidget(self._attitude_bar)
        core_layout.addWidget(self._boredom_bar)
        core_layout.addWidget(self._stress_bar)

        # Secret badge (conditional)
        self._secret_badge = tr_set(QLabel(), "Секрет раскрыт", "Secret exposed")
        self._secret_badge.setObjectName("CharacterStateBadge")
        self._secret_badge.setProperty("kind", "secret")
        self._secret_badge.setVisible(False)
        self._secret_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        core_layout.addWidget(self._secret_badge)

        root.addWidget(core_card)

        # ── Custom params card (filled dynamically) ──
        self._custom_card = QFrame()
        self._custom_card.setObjectName("SandboxInspectorCard")
        self._custom_layout = QVBoxLayout(self._custom_card)
        self._custom_layout.setContentsMargins(14, 14, 14, 14)
        self._custom_layout.setSpacing(8)
        self._custom_title = tr_set(QLabel(), "Дополнительно", "Custom params")
        self._custom_title.setObjectName("SandboxInspectorTitle")
        self._custom_layout.addWidget(self._custom_title)
        self._custom_card.setVisible(False)
        root.addWidget(self._custom_card)

        # ── All variables collapsible ──
        all_card = QFrame()
        all_card.setObjectName("SandboxInspectorCard")
        all_layout = QVBoxLayout(all_card)
        all_layout.setContentsMargins(14, 14, 14, 14)
        all_layout.setSpacing(6)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(6)
        self._all_toggle = QToolButton()
        self._all_toggle.setObjectName("SandboxInspectorToggle")
        tr_set(self._all_toggle, "Все переменные", "All variables")
        self._all_toggle.setCheckable(True)
        self._all_toggle.setChecked(False)
        self._all_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._all_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._all_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._all_toggle.toggled.connect(self._on_toggle_all)
        toggle_row.addWidget(self._all_toggle, 1, Qt.AlignmentFlag.AlignLeft)
        all_layout.addLayout(toggle_row)

        self._all_text = QPlainTextEdit()
        self._all_text.setObjectName("SandboxInspectorMonoText")
        self._all_text.setReadOnly(True)
        self._all_text.setVisible(False)
        self._all_text.setMaximumHeight(280)
        self._all_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._all_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._all_text.setFont(font)
        self._highlighter = _VariableSyntaxHighlighter(self._all_text.document())
        all_layout.addWidget(self._all_text)

        root.addWidget(all_card)
        root.addStretch(1)

        # Subscribe to events
        try:
            eb = self.gui.event_bus
            eb.subscribe(Events.Character.CURRENT_CHANGED, lambda e: self._schedule_refresh(rebuild=True), weak=False)
            try:
                eb.subscribe(Events.Character.RELOAD_DATA, lambda e: self._schedule_refresh(rebuild=True), weak=False)
            except Exception:
                pass
            try:
                from core.events import Events as _Ev
                def _on_response(e):
                    self._schedule_refresh(rebuild=False)
                    if self._all_text.isVisible():
                        QTimer.singleShot(100, self._refresh_all_text)
                eb.subscribe(_Ev.LLM.ON_SUCCESSFUL_RESPONSE, _on_response, weak=False)
            except Exception:
                pass
        except Exception:
            pass

        self.refresh(rebuild=True)

    # ─────────────────────────────────────────────────────────────
    def _on_toggle_all(self, checked: bool) -> None:
        self._all_text.setVisible(checked)
        self._all_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        if checked:
            self._refresh_all_text()

    def _schedule_refresh(self, *, rebuild: bool = False) -> None:
        QTimer.singleShot(50, lambda: self.refresh(rebuild=rebuild))

    # ─────────────────────────────────────────────────────────────
    def _get_current_character(self):
        try:
            res = self.gui.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=0.3)
            profile = res[0] if res else {}
        except Exception:
            profile = {}
        char_id = str((profile or {}).get("character_id") or "")
        if not char_id:
            return None
        try:
            res = self.gui.event_bus.emit_and_wait(Events.Character.GET, {"character_id": char_id}, timeout=0.3)
            return res[0] if res else None
        except Exception:
            return None

    def _bounds_for(self, character, key: str, default_min: float, default_max: float) -> tuple[float, float]:
        try:
            vmin = float(character.get_variable(f"{key}_min", default_min))
            vmax = float(character.get_variable(f"{key}_max", default_max))
        except Exception:
            vmin, vmax = default_min, default_max
        return vmin, vmax

    def _custom_param_bounds(self, param: Dict[str, Any], character) -> Optional[tuple[float, float]]:
        # Explicit min/max wins
        for key_min, key_max in (("min", "max"), ("value_min", "value_max")):
            if key_min in param or key_max in param:
                try:
                    return float(param.get(key_min, 0.0)), float(param.get(key_max, 100.0))
                except Exception:
                    pass
        # Try parsing formula like "max(A, min(<name> + <change>, B))"
        formula = str(param.get("formula") or "")
        if formula:
            import re

            m = re.search(r"max\(\s*(-?\d+(?:\.\d+)?)\s*,\s*min\(.*?,\s*(-?\d+(?:\.\d+)?)\s*\)", formula)
            if m:
                try:
                    return float(m.group(1)), float(m.group(2))
                except Exception:
                    pass
        # Fallback: use current value to derive a reasonable range
        try:
            cur = float(character.get_variable(str(param.get("name") or ""), 0.0) or 0.0)
        except Exception:
            cur = 0.0
        if cur <= 0:
            return 0.0, 100.0
        # Round the upper bound up to a nice number
        upper = max(100.0, ((int(cur) // 50) + 1) * 50.0)
        return 0.0, upper

    # ─────────────────────────────────────────────────────────────
    def _rebuild_dynamic(self, character) -> None:
        # Wipe existing dynamic widgets
        for w in list(self._dynamic_bars.values()):
            w.setParent(None)
            w.deleteLater()
        for w in list(self._dynamic_badges.values()):
            w.setParent(None)
            w.deleteLater()
        self._dynamic_bars.clear()
        self._dynamic_badges.clear()

        params: List[Dict[str, Any]] = list(getattr(character, "custom_params", []) or [])
        any_widget = False
        for param in params:
            name = str(param.get("name") or "").strip()
            if not name:
                continue
            ptype = str(param.get("type") or "float").lower()
            if ptype in ("float", "int"):
                bounds = self._custom_param_bounds(param, character)
                if bounds is None:
                    continue
                bar = _StatBar(name, color="#ff8ad1")
                bar.set_range(*bounds)
                self._custom_layout.addWidget(bar)
                self._dynamic_bars[name] = bar
                any_widget = True
            elif ptype == "bool":
                badge = QLabel(name)
                badge.setObjectName("CharacterStateBadge")
                badge.setProperty("kind", "neutral")
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge.setVisible(False)
                self._custom_layout.addWidget(badge)
                self._dynamic_badges[name] = badge
                any_widget = True
            # str — skipped (would clutter; visible in "All variables")

        self._custom_card.setVisible(any_widget)

    def _refresh_all_text(self) -> None:
        if self._all_text.hasFocus():
            return
        character = self._get_current_character()
        if character is None:
            self._all_text.setPlainText("—")
            return
        try:
            variables = dict(getattr(character, "variables", {}) or {})
        except Exception:
            variables = {}
        lines: List[str] = []
        for k in sorted(variables.keys(), key=str.lower):
            v = variables[k]
            try:
                if isinstance(v, bool):
                    v_text = "true" if v else "false"
                elif v is None:
                    v_text = "None"
                elif isinstance(v, float):
                    v_text = f"{v:.3f}".rstrip("0").rstrip(".")
                elif isinstance(v, str):
                    v_text = f'"{v}"' if len(v) > 0 and (" " in v or "\n" in v or v[0] in "{[#") else v
                else:
                    v_text = str(v)
            except Exception:
                v_text = repr(v)
            if len(v_text) > 300:
                v_text = v_text[:297] + "…"
            lines.append(f"{k}: {v_text}")
        new_text = "\n".join(lines) if lines else "—"
        scrollbar = self._all_text.verticalScrollBar()
        scroll_val = scrollbar.value() if scrollbar else 0
        self._all_text.setPlainText(new_text)
        if scrollbar:
            scrollbar.setValue(scroll_val)

    # ─────────────────────────────────────────────────────────────
    def refresh(self, *, rebuild: bool = False) -> None:
        character = self._get_current_character()
        if character is None:
            self._attitude_bar.set_value(0)
            self._boredom_bar.set_value(0)
            self._stress_bar.set_value(0)
            self._secret_badge.setVisible(False)
            self._custom_card.setVisible(False)
            return

        char_id = str(getattr(character, "char_id", "") or "")
        if rebuild or char_id != self._current_char_id:
            self._current_char_id = char_id
            self._rebuild_dynamic(character)

        try:
            attitude = float(character.get_variable("attitude", 0) or 0)
            boredom = float(character.get_variable("boredom", 0) or 0)
            stress = float(character.get_variable("stress", 0) or 0)
        except Exception:
            attitude = boredom = stress = 0.0

        self._attitude_bar.set_range(*self._bounds_for(character, "attitude", 0.0, 100.0))
        self._boredom_bar.set_range(*self._bounds_for(character, "boredom", 0.0, 100.0))
        self._stress_bar.set_range(*self._bounds_for(character, "stress", 0.0, 100.0))

        self._attitude_bar.set_value(attitude)
        self._boredom_bar.set_value(boredom)
        self._stress_bar.set_value(stress)

        # Secret exposed (only show if the variable exists in the character's state)
        try:
            variables = dict(getattr(character, "variables", {}) or {})
        except Exception:
            variables = {}
        if "secretExposed" in variables:
            exposed = bool(variables.get("secretExposed"))
            self._secret_badge.setVisible(exposed)
            if exposed:
                self._secret_badge.setProperty("kind", "secret")
                self._secret_badge.style().unpolish(self._secret_badge)
                self._secret_badge.style().polish(self._secret_badge)
        else:
            self._secret_badge.setVisible(False)

        # Custom params live values
        for name, bar in self._dynamic_bars.items():
            try:
                v = float(variables.get(name, 0) or 0)
            except Exception:
                v = 0.0
            bar.set_value(v)

        for name, badge in self._dynamic_badges.items():
            val = variables.get(name)
            visible = bool(val) and val is not None
            badge.setVisible(visible)
            if visible:
                badge.setProperty("kind", "active" if bool(val) else "neutral")
                badge.style().unpolish(badge)
                badge.style().polish(badge)

        # all_text refreshes only on response events, not on timer tick
