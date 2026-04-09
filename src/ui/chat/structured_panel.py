"""
StructuredOutputPanel — compact debug display of structured AI response data.

Compact collapsible panel with stat badges, segment cards, and memory block.
Designed to sit as a separate widget under the message in the chat scroll area.
"""

import json
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

# ── Compact font size override ───────────────────────────────────────────────
_COMPACT_FONT = 8  # pt — used instead of caller's font_size for compactness

# ── Color constants ──────────────────────────────────────────────────────────
CLR_BADGE_BG      = "rgba(255,255,255,0.06)"
CLR_BADGE_BORDER  = "rgba(255,255,255,0.10)"
# Badge label colors
CLR_ATT           = "#FF69B4"   # pink
CLR_BORE          = "#9370DB"   # purple
CLR_STRESS        = "#FFD700"   # yellow
# Value change colors
CLR_POSITIVE      = "#4CAF50"   # green
CLR_NEGATIVE      = "#EF5350"   # red
CLR_NEUTRAL       = "#9a9aa2"   # gray for ±0

CLR_SEG_BORDER    = "rgba(120,160,210,0.18)"
CLR_SEG_BG        = "rgba(120,160,210,0.05)"
CLR_SEG_HEADER    = "#8fb0cc"
CLR_TEXT_QUOTE     = "#c8c8c8"
CLR_FIELD_LABEL   = "#8aa0b8"
CLR_FIELD_VALUE   = "#c8c8c8"
CLR_MEMORY_BORDER   = "rgba(122,184,112,0.18)"
CLR_MEMORY_BG       = "rgba(122,184,112,0.05)"
CLR_MEMORY_HEADER   = "#7ab870"
CLR_MEMORY_TEXT     = "#8aa0b8"
CLR_REMIND_BORDER   = "rgba(255,180,80,0.20)"
CLR_REMIND_BG       = "rgba(255,180,80,0.05)"
CLR_REMIND_HEADER   = "#e8a040"
CLR_REMIND_TEXT     = "#c8b080"
CLR_TOOL_BORDER     = "rgba(100,200,255,0.22)"
CLR_TOOL_BG         = "rgba(100,200,255,0.05)"
CLR_TOOL_HEADER     = "#64c8ff"
CLR_TOOL_TEXT       = "#a8d8ee"
CLR_HEADER_TEXT   = "rgba(255,255,255,0.35)"

MAX_PANEL_WIDTH = 520


def _fmt_val(v: float) -> str:
    if v == 0:
        return "±0"
    return f"+{v:.2g}" if v > 0 else f"{v:.2g}"


def _val_color(v: float) -> str:
    if v > 0:
        return CLR_POSITIVE
    elif v < 0:
        return CLR_NEGATIVE
    return CLR_NEUTRAL


def _make_badge(label: str, value: float, label_color: str, parent=None) -> QFrame:
    badge = QFrame(parent)
    badge.setObjectName("StatBadge")
    badge.setStyleSheet(f"""
        QFrame#StatBadge {{
            background-color: {CLR_BADGE_BG};
            border: 1px solid {CLR_BADGE_BORDER};
            border-radius: 8px;
            padding: 1px 6px;
        }}
    """)
    lay = QHBoxLayout(badge)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)

    lbl = QLabel(label, badge)
    lbl.setStyleSheet(f"color: {label_color}; font-weight: bold; font-size: {_COMPACT_FONT}pt; "
                       "background: transparent; border: none;")
    val_lbl = QLabel(_fmt_val(value), badge)
    val_color = _val_color(value)
    val_lbl.setStyleSheet(f"color: {val_color}; font-weight: bold; font-size: {_COMPACT_FONT}pt; "
                           "background: transparent; border: none;")
    lay.addWidget(lbl)
    lay.addWidget(val_lbl)
    badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return badge


class SegmentCard(QFrame):
    """Compact segment card."""

    FIELDS = [
        ("emotions",       "emotions",    "\U0001f33a"),
        ("animations",     "anim",        "\U0001f3ad"),
        ("commands",       "cmd",         ">_"),
        ("movement_modes", "move",        "\U0001f6b6"),
        ("visual_effects", "fx",          "\u2728"),
        ("clothes",        "clothes",     "\U0001f457"),
        ("music",          "music",       "\U0001f3b5"),
        ("interactions",   "interact",    "\U0001f91d"),
        ("face_params",    "face",        "\U0001f60a"),
    ]
    SCALAR_FIELDS = [
        ("start_game", "start_game"),
        ("end_game",   "end_game"),
        ("target",     "target"),
        ("hint",       "hint"),
    ]

    def __init__(self, index: int, segment_data: dict, font_size: int = 8, parent=None):
        super().__init__(parent)
        fs = _COMPACT_FONT
        self.setObjectName("SegmentCard")
        self.setStyleSheet(f"""
            QFrame#SegmentCard {{
                background-color: {CLR_SEG_BG};
                border: 1px solid {CLR_SEG_BORDER};
                border-radius: 6px;
                margin: 1px 0px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        header = QLabel(f"seg {index}", self)
        header.setStyleSheet(
            f"color: {CLR_SEG_HEADER}; font-weight: bold; font-size: {fs}pt; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        text = (segment_data.get("text") or "").strip()
        if text:
            display_text = text if len(text) <= 120 else text[:117] + "..."
            text_label = QLabel(f'"{display_text}"', self)
            text_label.setWordWrap(True)
            text_label.setCursor(Qt.CursorShape.IBeamCursor)
            text_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            text_label.setStyleSheet(
                f"color: {CLR_TEXT_QUOTE}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 2px;"
            )
            layout.addWidget(text_label)

        for field_key, display_label, emoji in self.FIELDS:
            vals = segment_data.get(field_key) or []
            if vals:
                line = QLabel(f"{emoji} {display_label}: {', '.join(str(v) for v in vals)}", self)
                line.setWordWrap(True)
                line.setCursor(Qt.CursorShape.IBeamCursor)
                line.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
                line.setStyleSheet(
                    f"color: {CLR_FIELD_LABEL}; font-size: {fs}pt; "
                    f"background: transparent; border: none; padding-left: 2px;"
                )
                layout.addWidget(line)

        for field_key, display_label in self.SCALAR_FIELDS:
            val = segment_data.get(field_key)
            if val:
                line = QLabel(f"{display_label}: {val}", self)
                line.setCursor(Qt.CursorShape.IBeamCursor)
                line.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
                line.setStyleSheet(
                    f"color: {CLR_FIELD_LABEL}; font-size: {fs}pt; "
                    f"background: transparent; border: none; padding-left: 2px;"
                )
                layout.addWidget(line)

        if segment_data.get("allow_sleep") is not None:
            line = QLabel(f"sleep: {segment_data['allow_sleep']}", self)
            line.setCursor(Qt.CursorShape.IBeamCursor)
            line.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            line.setStyleSheet(
                f"color: {CLR_FIELD_LABEL}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 2px;"
            )
            layout.addWidget(line)


class MemoryBlock(QFrame):
    """Compact memory operations block."""

    def __init__(self, mem_add: list, mem_update: list, mem_delete: list,
                 font_size: int = 8, parent=None):
        super().__init__(parent)
        fs = _COMPACT_FONT
        self.setObjectName("MemoryBlock")
        self.setStyleSheet(f"""
            QFrame#MemoryBlock {{
                background-color: {CLR_MEMORY_BG};
                border: 1px solid {CLR_MEMORY_BORDER};
                border-radius: 6px;
                margin: 1px 0px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        header = QLabel("memory", self)
        header.setStyleSheet(
            f"color: {CLR_MEMORY_HEADER}; font-weight: bold; font-size: {fs}pt; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        for entry in mem_add:
            text = str(entry)
            if "|" in text:
                priority, content = text.split("|", 1)
                display = f"+ [{priority.strip()}] {content.strip()}"
            else:
                display = f"+ {text}"
            lbl = QLabel(display, self)
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.IBeamCursor)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            lbl.setStyleSheet(
                f"color: {CLR_MEMORY_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)

        for entry in mem_update:
            lbl = QLabel(f"~ {entry}", self)
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.IBeamCursor)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            lbl.setStyleSheet(
                f"color: {CLR_MEMORY_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)

        for entry in mem_delete:
            lbl = QLabel(f"- #{entry}", self)
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.IBeamCursor)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            lbl.setStyleSheet(
                f"color: {CLR_MEMORY_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)


class ReminderBlock(QFrame):
    """Compact reminder operations block."""

    def __init__(self, rem_add: list, rem_delete: list, font_size: int = 8, parent=None):
        super().__init__(parent)
        fs = _COMPACT_FONT
        self.setObjectName("ReminderBlock")
        self.setStyleSheet(f"""
            QFrame#ReminderBlock {{
                background-color: {CLR_REMIND_BG};
                border: 1px solid {CLR_REMIND_BORDER};
                border-radius: 6px;
                margin: 1px 0px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        header = QLabel("\u23f0 reminder", self)
        header.setStyleSheet(
            f"color: {CLR_REMIND_HEADER}; font-weight: bold; font-size: {fs}pt; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        for entry in rem_add:
            text = str(entry)
            if "|" in text:
                when, content = text.split("|", 1)
                display = f"+ [{when.strip()}] {content.strip()}"
            else:
                display = f"+ {text}"
            lbl = QLabel(display, self)
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.IBeamCursor)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            lbl.setStyleSheet(
                f"color: {CLR_REMIND_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)

        for entry in rem_delete:
            lbl = QLabel(f"- #{entry}", self)
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.IBeamCursor)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            lbl.setStyleSheet(
                f"color: {CLR_REMIND_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)


class ToolCallBlock(QFrame):
    """Compact tool call block."""

    def __init__(self, tool_name: str, tool_args: dict, font_size: int = 8, parent=None):
        super().__init__(parent)
        fs = _COMPACT_FONT
        self.setObjectName("ToolCallBlock")
        self.setStyleSheet(f"""
            QFrame#ToolCallBlock {{
                background-color: {CLR_TOOL_BG};
                border: 1px solid {CLR_TOOL_BORDER};
                border-radius: 6px;
                margin: 1px 0px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        header = QLabel(f"\u2699\ufe0f tool_call: {tool_name}", self)
        header.setStyleSheet(
            f"color: {CLR_TOOL_HEADER}; font-weight: bold; font-size: {fs}pt; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        if tool_args:
            import json as _json
            args_text = _json.dumps(tool_args, ensure_ascii=False)
            lbl = QLabel(args_text, self)
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.IBeamCursor)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            lbl.setStyleSheet(
                f"color: {CLR_TOOL_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)


class StructuredOutputPanel(QFrame):
    """
    Compact collapsible structured output panel.

    Clickable header row with colored stat badges; click to expand/collapse.
    No "debug" label — just the badges themselves.
    """

    def __init__(self, structured_data: dict, font_size: int = 10,
                 start_expanded: bool = True, mode: str = "brief", parent=None,
                 attached_to_message: bool = False):
        super().__init__(parent)
        self._collapsed = not start_expanded
        self._data = structured_data
        self._attached = attached_to_message
        self.setObjectName("StructuredPanel")
        self.setMaximumWidth(MAX_PANEL_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self.setStyleSheet("""
            QFrame#StructuredPanel {
                background: transparent;
                border: none;
                margin: 0px 0px;
            }
        """)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(2)

        # ── Header row (always visible, clickable) — no "debug" label ────────
        self._header_widget = QWidget(self)
        self._header_widget.setStyleSheet("background: transparent; border: none;")
        self._header_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self._header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        self._arrow = QLabel("▼" if start_expanded else "▶", self._header_widget)
        self._arrow.setStyleSheet(
            f"color: rgba(255,255,255,0.25); font-size: {_COMPACT_FONT}pt; font-weight: bold; "
            f"background: transparent; border: none;"
        )
        header_layout.addWidget(self._arrow)

        # Full-word badge names with distinct colors
        att    = structured_data.get("attitude_change", 0) or 0
        bore   = structured_data.get("boredom_change",  0) or 0
        stress = structured_data.get("stress_change",   0) or 0
        header_layout.addWidget(_make_badge("Attitude", att, CLR_ATT, self._header_widget))
        header_layout.addWidget(_make_badge("Boredom", bore, CLR_BORE, self._header_widget))
        header_layout.addWidget(_make_badge("Stress", stress, CLR_STRESS, self._header_widget))
        header_layout.addStretch()

        self._header_widget.mousePressEvent = lambda e: self.toggle()
        outer_layout.addWidget(self._header_widget)

        # ── Content area (collapsible) ───────────────────────────────────────
        self._content = QWidget(self)
        self._content.setStyleSheet("background: transparent; border: none;")
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 2, 0, 0)
        content_layout.setSpacing(2)

        if mode == "json":
            self._build_json_view(content_layout, structured_data, font_size)
        else:
            self._build_brief_view(content_layout, structured_data, font_size)

        outer_layout.addWidget(self._content)
        self._content.setVisible(start_expanded)

    def _build_brief_view(self, layout: QVBoxLayout, data: dict, font_size: int):
        segments = data.get("segments") or []
        for i, seg in enumerate(segments, 1):
            card = SegmentCard(i, seg, _COMPACT_FONT, layout.parentWidget())
            layout.addWidget(card)

        tool_call = data.get("tool_call")
        if tool_call:
            tc_block = ToolCallBlock(
                tool_name=tool_call.get("name", "?"),
                tool_args=tool_call.get("args") or {},
                font_size=_COMPACT_FONT,
                parent=layout.parentWidget(),
            )
            layout.addWidget(tc_block)

        mem_add    = data.get("memory_add") or []
        mem_update = data.get("memory_update") or []
        mem_delete = data.get("memory_delete") or []
        if mem_add or mem_update or mem_delete:
            mem_block = MemoryBlock(mem_add, mem_update, mem_delete, _COMPACT_FONT, layout.parentWidget())
            layout.addWidget(mem_block)

        rem_add    = data.get("reminder_add") or []
        rem_delete = data.get("reminder_delete") or []
        if rem_add or rem_delete:
            rem_block = ReminderBlock(rem_add, rem_delete, _COMPACT_FONT, layout.parentWidget())
            layout.addWidget(rem_block)

    def _build_json_view(self, layout: QVBoxLayout, data: dict, font_size: int):
        raw = data.get("_raw_json")
        if raw:
            json_text = raw
        else:
            json_text = json.dumps(
                {k: v for k, v in data.items() if k != "_raw_json"},
                ensure_ascii=False, indent=2
            )
        lbl = QLabel(json_text, layout.parentWidget())
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setCursor(Qt.CursorShape.IBeamCursor)
        lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        # No maximum height — full JSON is visible
        lbl.setStyleSheet(
            f"color: #8aa0b8; font-family: 'Courier New', monospace; "
            f"font-size: {_COMPACT_FONT}pt; background: rgba(0,0,0,0.15); "
            f"border: 1px solid rgba(255,255,255,0.05); border-radius: 4px; "
            f"padding: 4px;"
        )
        layout.addWidget(lbl)

    def toggle(self):
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        self._arrow.setText("▶" if self._collapsed else "▼")

    def is_collapsed(self) -> bool:
        return self._collapsed
