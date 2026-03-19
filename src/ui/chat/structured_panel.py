"""
StructuredOutputPanel — widget-based display of structured AI response data.

Renders stat badges, segment cards, and memory block as real QWidgets
instead of formatted text in a QTextBrowser.

Layout matches the debug overlay style:
┌──────────────────────────────────────┐
│ [att -0.5] [bore -1.5] [stress -0.5]│  ← stat badges
│                                      │
│ ┌─ Seg 1 ──────────────────────────┐ │
│ │ ☺ "text..."                      │ │
│ │ 🌺 emotions: smileteeth          │ │
│ │ >_ commands: cmd1, cmd2          │ │
│ └──────────────────────────────────┘ │
│                                      │
│ ┌─ memory ─────────────────────────┐ │
│ │ + [normal] entry text            │ │
│ └──────────────────────────────────┘ │
└──────────────────────────────────────┘
"""

import json
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QSizePolicy,
    QGridLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor


# ── Color constants (match screenshot) ──────────────────────────────────────
CLR_BADGE_BG      = "rgba(255,255,255,0.08)"
CLR_BADGE_BORDER  = "rgba(255,255,255,0.12)"
CLR_ATT           = "#c8a84b"  # amber
CLR_BORE          = "#c8a84b"
CLR_STRESS        = "#c8a84b"
CLR_SEG_BORDER    = "rgba(120,160,210,0.25)"
CLR_SEG_BG        = "rgba(120,160,210,0.06)"
CLR_SEG_HEADER    = "#8fb0cc"  # blue-grey
CLR_TEXT_QUOTE     = "#d4d4d4"  # near-white
CLR_FIELD_LABEL   = "#9ab5cc"  # lighter blue
CLR_FIELD_VALUE   = "#d4d4d4"
CLR_MEMORY_BORDER = "rgba(122,184,112,0.25)"
CLR_MEMORY_BG     = "rgba(122,184,112,0.06)"
CLR_MEMORY_HEADER = "#7ab870"  # green
CLR_MEMORY_TEXT   = "#9ab5cc"
CLR_EMOJI_PREFIX  = "#9ab5cc"


def _fmt_val(v: float) -> str:
    if v == 0:
        return "±0"
    s = f"+{v:.2g}" if v > 0 else f"{v:.2g}"
    return s


def _make_badge(label: str, value: float, color: str) -> QFrame:
    """Create a stat badge pill widget: [label value]"""
    badge = QFrame()
    badge.setObjectName("StatBadge")
    badge.setStyleSheet(f"""
        QFrame#StatBadge {{
            background-color: {CLR_BADGE_BG};
            border: 1px solid {CLR_BADGE_BORDER};
            border-radius: 10px;
            padding: 2px 10px;
        }}
    """)
    lay = QHBoxLayout(badge)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 9pt; "
                       "background: transparent; border: none;")
    val_lbl = QLabel(_fmt_val(value))
    val_lbl.setStyleSheet(f"color: {CLR_FIELD_VALUE}; font-size: 9pt; "
                           "background: transparent; border: none;")
    lay.addWidget(lbl)
    lay.addWidget(val_lbl)
    badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return badge


class SegmentCard(QFrame):
    """A single segment card with text, emotions, commands, etc."""

    # Field display config: (json_key, display_label, emoji_prefix)
    FIELDS = [
        ("emotions",       "emotions",    "🌺"),
        ("animations",     "animations",  "🎭"),
        ("commands",       "commands",    ">_"),
        ("movement_modes", "movement",    "🚶"),
        ("visual_effects", "effects",     "✨"),
        ("clothes",        "clothes",     "👗"),
        ("music",          "music",       "🎵"),
        ("interactions",   "interactions","🤝"),
        ("face_params",    "face",        "😊"),
    ]
    SCALAR_FIELDS = [
        ("start_game", "start_game"),
        ("end_game",   "end_game"),
        ("target",     "target"),
        ("hint",       "hint"),
    ]

    def __init__(self, index: int, segment_data: dict, font_size: int = 10, parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentCard")
        self.setStyleSheet(f"""
            QFrame#SegmentCard {{
                background-color: {CLR_SEG_BG};
                border: 1px solid {CLR_SEG_BORDER};
                border-radius: 8px;
                margin: 2px 0px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(3)

        # Header: "⁞ Seg N"
        header = QLabel(f"⁞ Seg {index}")
        header.setStyleSheet(
            f"color: {CLR_SEG_HEADER}; font-weight: bold; font-size: {font_size + 1}pt; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        # Text quote
        text = (segment_data.get("text") or "").strip()
        if text:
            text_label = QLabel(f'☺ "{text}"')
            text_label.setWordWrap(True)
            text_label.setStyleSheet(
                f"color: {CLR_TEXT_QUOTE}; font-size: {font_size}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(text_label)

        # List fields
        for field_key, display_label, emoji in self.FIELDS:
            vals = segment_data.get(field_key) or []
            if vals:
                line = QLabel(f"{emoji} {display_label}: {', '.join(str(v) for v in vals)}")
                line.setWordWrap(True)
                line.setStyleSheet(
                    f"color: {CLR_FIELD_LABEL}; font-size: {font_size}pt; "
                    f"background: transparent; border: none; padding-left: 4px;"
                )
                layout.addWidget(line)

        # Scalar fields
        for field_key, display_label in self.SCALAR_FIELDS:
            val = segment_data.get(field_key)
            if val:
                line = QLabel(f"  {display_label}: {val}")
                line.setStyleSheet(
                    f"color: {CLR_FIELD_LABEL}; font-size: {font_size}pt; "
                    f"background: transparent; border: none; padding-left: 4px;"
                )
                layout.addWidget(line)

        # allow_sleep
        if segment_data.get("allow_sleep") is not None:
            line = QLabel(f"  allow_sleep: {segment_data['allow_sleep']}")
            line.setStyleSheet(
                f"color: {CLR_FIELD_LABEL}; font-size: {font_size}pt; "
                f"background: transparent; border: none; padding-left: 4px;"
            )
            layout.addWidget(line)


class MemoryBlock(QFrame):
    """Memory operations block (add/update/delete)."""

    def __init__(self, mem_add: list, mem_update: list, mem_delete: list,
                 font_size: int = 10, parent=None):
        super().__init__(parent)
        self.setObjectName("MemoryBlock")
        self.setStyleSheet(f"""
            QFrame#MemoryBlock {{
                background-color: {CLR_MEMORY_BG};
                border: 1px solid {CLR_MEMORY_BORDER};
                border-radius: 8px;
                margin: 2px 0px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(2)

        header = QLabel("memory:")
        header.setStyleSheet(
            f"color: {CLR_MEMORY_HEADER}; font-weight: bold; font-size: {font_size + 1}pt; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {CLR_MEMORY_BORDER}; max-height: 1px; border: none;")
        layout.addWidget(sep)

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
                f"color: {CLR_MEMORY_TEXT}; font-size: {font_size}pt; "
                f"background: transparent; border: none; padding-left: 8px;"
            )
            layout.addWidget(lbl)

        for entry in mem_update:
            lbl = QLabel(f"~ {entry}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {CLR_MEMORY_TEXT}; font-size: {font_size}pt; "
                f"background: transparent; border: none; padding-left: 8px;"
            )
            layout.addWidget(lbl)

        for entry in mem_delete:
            lbl = QLabel(f"- #{entry}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {CLR_MEMORY_TEXT}; font-size: {font_size}pt; "
                f"background: transparent; border: none; padding-left: 8px;"
            )
            layout.addWidget(lbl)


class StructuredOutputPanel(QFrame):
    """
    Complete structured output panel with badges, segments, and memory.

    Collapsible — clicking the header toggles visibility.
    """

    def __init__(self, structured_data: dict, font_size: int = 10,
                 start_expanded: bool = True, mode: str = "brief", parent=None):
        super().__init__(parent)
        self._collapsed = not start_expanded
        self._data = structured_data
        self.setObjectName("StructuredPanel")
        self.setStyleSheet("""
            QFrame#StructuredPanel {
                background: transparent;
                border: none;
                margin: 4px 0px;
            }
        """)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 4, 0, 0)
        outer_layout.setSpacing(4)

        # ── Content area (collapsible) ──────────────────────────────────────
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent; border: none;")
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        if mode == "json":
            self._build_json_view(content_layout, structured_data, font_size)
        else:
            self._build_brief_view(content_layout, structured_data, font_size)

        outer_layout.addWidget(self._content)
        self._content.setVisible(start_expanded)

    def _build_brief_view(self, layout: QVBoxLayout, data: dict, font_size: int):
        """Build widget tree for brief structured output mode."""

        # ── Stat badges row ─────────────────────────────────────────────────
        att    = data.get("attitude_change", 0) or 0
        bore   = data.get("boredom_change",  0) or 0
        stress = data.get("stress_change",   0) or 0

        badges_row = QHBoxLayout()
        badges_row.setContentsMargins(0, 0, 0, 0)
        badges_row.setSpacing(8)
        badges_row.addWidget(_make_badge("att", att, CLR_ATT))
        badges_row.addWidget(_make_badge("bore", bore, CLR_BORE))
        badges_row.addWidget(_make_badge("stress", stress, CLR_STRESS))
        badges_row.addStretch()

        badge_container = QWidget()
        badge_container.setStyleSheet("background: transparent; border: none;")
        badge_container.setLayout(badges_row)
        layout.addWidget(badge_container)

        # ── Segment cards ───────────────────────────────────────────────────
        segments = data.get("segments") or []
        for i, seg in enumerate(segments, 1):
            card = SegmentCard(i, seg, font_size)
            layout.addWidget(card)

        # ── Memory block (separate from segments) ───────────────────────────
        mem_add    = data.get("memory_add") or []
        mem_update = data.get("memory_update") or []
        mem_delete = data.get("memory_delete") or []
        if mem_add or mem_update or mem_delete:
            mem_block = MemoryBlock(mem_add, mem_update, mem_delete, font_size)
            layout.addWidget(mem_block)

    def _build_json_view(self, layout: QVBoxLayout, data: dict, font_size: int):
        """Build JSON view of structured data."""
        json_text = json.dumps(data, ensure_ascii=False, indent=2)
        lbl = QLabel(json_text)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setStyleSheet(
            f"color: #9ab5cc; font-family: 'Courier New', monospace; "
            f"font-size: {font_size}pt; background: rgba(0,0,0,0.2); "
            f"border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; "
            f"padding: 8px;"
        )
        layout.addWidget(lbl)

    def toggle(self):
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed
