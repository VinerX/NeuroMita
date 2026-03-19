"""
StructuredOutputPanel — compact debug display of structured AI response data.

Compact collapsible panel with stat badges, segment cards, and memory block.
Designed to sit as a separate widget in the chat scroll area, not inside message bubbles.
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
CLR_ATT           = "#c8a84b"
CLR_BORE          = "#c8a84b"
CLR_STRESS        = "#c8a84b"
CLR_SEG_BORDER    = "rgba(120,160,210,0.18)"
CLR_SEG_BG        = "rgba(120,160,210,0.05)"
CLR_SEG_HEADER    = "#8fb0cc"
CLR_TEXT_QUOTE     = "#c8c8c8"
CLR_FIELD_LABEL   = "#8aa0b8"
CLR_FIELD_VALUE   = "#c8c8c8"
CLR_MEMORY_BORDER = "rgba(122,184,112,0.18)"
CLR_MEMORY_BG     = "rgba(122,184,112,0.05)"
CLR_MEMORY_HEADER = "#7ab870"
CLR_MEMORY_TEXT   = "#8aa0b8"
CLR_HEADER_TEXT   = "rgba(255,255,255,0.35)"

MAX_PANEL_WIDTH = 520


def _fmt_val(v: float) -> str:
    if v == 0:
        return "±0"
    return f"+{v:.2g}" if v > 0 else f"{v:.2g}"


def _make_badge(label: str, value: float, color: str) -> QFrame:
    badge = QFrame()
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

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: {_COMPACT_FONT}pt; "
                       "background: transparent; border: none;")
    val_lbl = QLabel(_fmt_val(value))
    val_lbl.setStyleSheet(f"color: {CLR_FIELD_VALUE}; font-size: {_COMPACT_FONT}pt; "
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

        header = QLabel(f"seg {index}")
        header.setStyleSheet(
            f"color: {CLR_SEG_HEADER}; font-weight: bold; font-size: {fs}pt; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        text = (segment_data.get("text") or "").strip()
        if text:
            # Truncate long text
            display_text = text if len(text) <= 120 else text[:117] + "..."
            text_label = QLabel(f'"{display_text}"')
            text_label.setWordWrap(True)
            text_label.setStyleSheet(
                f"color: {CLR_TEXT_QUOTE}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 2px;"
            )
            layout.addWidget(text_label)

        for field_key, display_label, emoji in self.FIELDS:
            vals = segment_data.get(field_key) or []
            if vals:
                line = QLabel(f"{emoji} {display_label}: {', '.join(str(v) for v in vals)}")
                line.setWordWrap(True)
                line.setStyleSheet(
                    f"color: {CLR_FIELD_LABEL}; font-size: {fs}pt; "
                    f"background: transparent; border: none; padding-left: 2px;"
                )
                layout.addWidget(line)

        for field_key, display_label in self.SCALAR_FIELDS:
            val = segment_data.get(field_key)
            if val:
                line = QLabel(f"{display_label}: {val}")
                line.setStyleSheet(
                    f"color: {CLR_FIELD_LABEL}; font-size: {fs}pt; "
                    f"background: transparent; border: none; padding-left: 2px;"
                )
                layout.addWidget(line)

        if segment_data.get("allow_sleep") is not None:
            line = QLabel(f"sleep: {segment_data['allow_sleep']}")
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

        header = QLabel("memory")
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
            lbl = QLabel(display)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {CLR_MEMORY_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)

        for entry in mem_update:
            lbl = QLabel(f"~ {entry}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {CLR_MEMORY_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)

        for entry in mem_delete:
            lbl = QLabel(f"- #{entry}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {CLR_MEMORY_TEXT}; font-size: {fs}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(lbl)


class StructuredOutputPanel(QFrame):
    """
    Compact collapsible structured output panel.

    Has a clickable header row with badges; click to expand/collapse segment details.
    """

    def __init__(self, structured_data: dict, font_size: int = 10,
                 start_expanded: bool = True, mode: str = "brief", parent=None):
        super().__init__(parent)
        self._collapsed = not start_expanded
        self._data = structured_data
        self.setObjectName("StructuredPanel")
        self.setMaximumWidth(MAX_PANEL_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("""
            QFrame#StructuredPanel {
                background: rgba(255,255,255,0.02);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 8px;
                margin: 1px 0px;
            }
        """)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(6, 4, 6, 4)
        outer_layout.setSpacing(2)

        # ── Header row (always visible, clickable) ───────────────────────────
        self._header_widget = QWidget()
        self._header_widget.setStyleSheet("background: transparent; border: none;")
        self._header_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self._header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self._arrow = QLabel("▼" if start_expanded else "▶")
        self._arrow.setStyleSheet(
            f"color: {CLR_HEADER_TEXT}; font-size: {_COMPACT_FONT}pt; font-weight: bold; "
            f"background: transparent; border: none;"
        )
        header_layout.addWidget(self._arrow)

        title = QLabel("debug")
        title.setStyleSheet(
            f"color: {CLR_HEADER_TEXT}; font-size: {_COMPACT_FONT}pt; font-weight: bold; "
            f"background: transparent; border: none;"
        )
        header_layout.addWidget(title)

        # Inline stat badges in header
        att    = structured_data.get("attitude_change", 0) or 0
        bore   = structured_data.get("boredom_change",  0) or 0
        stress = structured_data.get("stress_change",   0) or 0
        header_layout.addWidget(_make_badge("att", att, CLR_ATT))
        header_layout.addWidget(_make_badge("bore", bore, CLR_BORE))
        header_layout.addWidget(_make_badge("stress", stress, CLR_STRESS))
        header_layout.addStretch()

        self._header_widget.mousePressEvent = lambda e: self.toggle()
        outer_layout.addWidget(self._header_widget)

        # ── Content area (collapsible) ───────────────────────────────────────
        self._content = QWidget()
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
            card = SegmentCard(i, seg, _COMPACT_FONT)
            layout.addWidget(card)

        mem_add    = data.get("memory_add") or []
        mem_update = data.get("memory_update") or []
        mem_delete = data.get("memory_delete") or []
        if mem_add or mem_update or mem_delete:
            mem_block = MemoryBlock(mem_add, mem_update, mem_delete, _COMPACT_FONT)
            layout.addWidget(mem_block)

    def _build_json_view(self, layout: QVBoxLayout, data: dict, font_size: int):
        json_text = json.dumps(data, ensure_ascii=False, indent=2)
        lbl = QLabel(json_text)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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
