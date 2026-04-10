"""
StructuredOutputPanel — compact debug display of structured AI response data.
"""

import json
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QSizePolicy
from PyQt6.QtCore import Qt

# Modern Dashboard Colors
CLR_BADGE_BG      = "rgba(255, 255, 255, 0.05)"
CLR_BADGE_BORDER  = "rgba(255, 255, 255, 0.10)"
CLR_ATT           = "#F472B6"   # Pink
CLR_BORE          = "#A78BFA"   # Purple
CLR_STRESS        = "#FBBF24"   # Yellow
CLR_POSITIVE      = "#34D399"   # Emerald
CLR_NEGATIVE      = "#F87171"   # Red
CLR_NEUTRAL       = "#9CA3AF"   # Gray

CLR_SEG_BORDER    = "rgba(96, 165, 250, 0.2)"
CLR_SEG_BG        = "rgba(96, 165, 250, 0.05)"
CLR_SEG_HEADER    = "#60A5FA"
CLR_TEXT_QUOTE    = "#D1D5DB"
CLR_FIELD_LABEL   = "#9CA3AF"
CLR_FIELD_VALUE   = "#D1D5DB"

CLR_MEMORY_BORDER = "rgba(52, 211, 153, 0.2)"
CLR_MEMORY_BG     = "rgba(52, 211, 153, 0.05)"
CLR_MEMORY_HEADER = "#34D399"
CLR_MEMORY_TEXT   = "#A7F3D0"

CLR_REMIND_BORDER = "rgba(251, 191, 36, 0.2)"
CLR_REMIND_BG     = "rgba(251, 191, 36, 0.05)"
CLR_REMIND_HEADER = "#FBBF24"
CLR_REMIND_TEXT   = "#FDE68A"

CLR_TOOL_BORDER   = "rgba(167, 139, 250, 0.2)"
CLR_TOOL_BG       = "rgba(167, 139, 250, 0.05)"
CLR_TOOL_HEADER   = "#A78BFA"
CLR_TOOL_TEXT     = "#DDD6FE"

def _fmt_val(v: float) -> str: return "±0" if v == 0 else f"+{v:.2g}" if v > 0 else f"{v:.2g}"
def _val_color(v: float) -> str: return CLR_POSITIVE if v > 0 else CLR_NEGATIVE if v < 0 else CLR_NEUTRAL

def _make_badge(label: str, value: float, label_color: str, font_xs: int, parent=None) -> QFrame:
    badge = QFrame(parent)
    badge.setObjectName("StatBadge")
    badge.setStyleSheet(f"QFrame#StatBadge {{ background-color: {CLR_BADGE_BG}; border: 1px solid {CLR_BADGE_BORDER}; border-radius: 6px; padding: 2px 8px; }}")
    lay = QHBoxLayout(badge)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)

    lbl = QLabel(label, badge)
    lbl.setStyleSheet(f"color: {label_color}; font-weight: bold; font-size: {font_xs}pt; background: transparent; border: none;")
    val_lbl = QLabel(_fmt_val(value), badge)
    val_lbl.setStyleSheet(f"color: {_val_color(value)}; font-weight: bold; font-size: {font_xs}pt; background: transparent; border: none;")
    
    lay.addWidget(lbl)
    lay.addWidget(val_lbl)
    badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return badge

class SegmentCard(QFrame):
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
    SCALAR_FIELDS = [("start_game", "start_game"), ("end_game", "end_game"), ("target", "target"), ("hint", "hint")]

    def __init__(self, index: int, segment_data: dict, font_sm: int, parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentCard")
        self.setStyleSheet(f"QFrame#SegmentCard {{ background-color: {CLR_SEG_BG}; border: 1px solid {CLR_SEG_BORDER}; border-radius: 8px; margin: 2px 0px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        header = QLabel(f"seg {index}", self)
        header.setStyleSheet(f"color: {CLR_SEG_HEADER}; font-weight: bold; font-size: {font_sm}pt; background: transparent; border: none;")
        layout.addWidget(header)

        text = (segment_data.get("text") or "").strip()
        if text:
            text_label = QLabel(f'"{text if len(text) <= 120 else text[:117] + "..."}"', self)
            text_label.setWordWrap(True)
            text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_label.setStyleSheet(f"color: {CLR_TEXT_QUOTE}; font-size: {font_sm}pt; background: transparent; border: none; padding-left: 4px;")
            layout.addWidget(text_label)

        for field_key, display_label, emoji in self.FIELDS:
            vals = segment_data.get(field_key) or []
            if vals:
                line = QLabel(f"{emoji} {display_label}: {', '.join(str(v) for v in vals)}", self)
                line.setWordWrap(True)
                line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                line.setStyleSheet(f"color: {CLR_FIELD_LABEL}; font-size: {font_sm}pt; background: transparent; border: none; padding-left: 4px;")
                layout.addWidget(line)

        for field_key, display_label in self.SCALAR_FIELDS:
            val = segment_data.get(field_key)
            if val:
                line = QLabel(f"{display_label}: {val}", self)
                line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                line.setStyleSheet(f"color: {CLR_FIELD_LABEL}; font-size: {font_sm}pt; background: transparent; border: none; padding-left: 4px;")
                layout.addWidget(line)

        if segment_data.get("allow_sleep") is not None:
            line = QLabel(f"sleep: {segment_data['allow_sleep']}", self)
            line.setStyleSheet(f"color: {CLR_FIELD_LABEL}; font-size: {font_sm}pt; background: transparent; border: none; padding-left: 4px;")
            layout.addWidget(line)

class MemoryBlock(QFrame):
    def __init__(self, mem_add: list, mem_update: list, mem_delete: list, font_sm: int, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ background-color: {CLR_MEMORY_BG}; border: 1px solid {CLR_MEMORY_BORDER}; border-radius: 8px; margin: 2px 0px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        header = QLabel("memory", self)
        header.setStyleSheet(f"color: {CLR_MEMORY_HEADER}; font-weight: bold; font-size: {font_sm}pt; background: transparent; border: none;")
        layout.addWidget(header)

        for lst, prefix in [(mem_add, "+"), (mem_update, "~"), (mem_delete, "-")]:
            for entry in lst:
                lbl = QLabel(f"{prefix} {entry}", self)
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                lbl.setStyleSheet(f"color: {CLR_MEMORY_TEXT}; font-size: {font_sm}pt; background: transparent; border: none; padding-left: 4px;")
                layout.addWidget(lbl)

class ReminderBlock(QFrame):
    def __init__(self, rem_add: list, rem_delete: list, font_sm: int, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ background-color: {CLR_REMIND_BG}; border: 1px solid {CLR_REMIND_BORDER}; border-radius: 8px; margin: 2px 0px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        header = QLabel("\u23f0 reminder", self)
        header.setStyleSheet(f"color: {CLR_REMIND_HEADER}; font-weight: bold; font-size: {font_sm}pt; background: transparent; border: none;")
        layout.addWidget(header)

        for lst, prefix in [(rem_add, "+"), (rem_delete, "-")]:
            for entry in lst:
                lbl = QLabel(f"{prefix} {entry}", self)
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                lbl.setStyleSheet(f"color: {CLR_REMIND_TEXT}; font-size: {font_sm}pt; background: transparent; border: none; padding-left: 4px;")
                layout.addWidget(lbl)

class ToolCallBlock(QFrame):
    def __init__(self, tool_name: str, tool_args: dict, font_sm: int, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ background-color: {CLR_TOOL_BG}; border: 1px solid {CLR_TOOL_BORDER}; border-radius: 8px; margin: 2px 0px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        header = QLabel(f"\u2699\ufe0f tool_call: {tool_name}", self)
        header.setStyleSheet(f"color: {CLR_TOOL_HEADER}; font-weight: bold; font-size: {font_sm}pt; background: transparent; border: none;")
        layout.addWidget(header)

        if tool_args:
            import json as _json
            lbl = QLabel(_json.dumps(tool_args, ensure_ascii=False), self)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setStyleSheet(f"color: {CLR_TOOL_TEXT}; font-size: {font_sm}pt; background: transparent; border: none; padding-left: 4px;")
            layout.addWidget(lbl)

class StructuredOutputPanel(QFrame):
    def __init__(self, structured_data: dict, font_size: int = 12, max_bubble_width: int = 600,
                 start_expanded: bool = True, mode: str = "brief", parent=None):
        super().__init__(parent)
        self._collapsed = not start_expanded
        self._data = structured_data
        self._font_sm = max(8, font_size - 2)
        self._font_xs = max(7, font_size - 3)
        
        self.setObjectName("StructuredPanel")
        self.setMaximumWidth(max(300, max_bubble_width))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("QFrame#StructuredPanel { background: transparent; border: none; margin: 0px; }")

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(4)

        self._header_widget = QWidget(self)
        self._header_widget.setStyleSheet("background: transparent; border: none;")
        self._header_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self._header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self._arrow = QLabel("▼" if start_expanded else "▶", self._header_widget)
        self._arrow.setStyleSheet(f"color: rgba(255,255,255,0.4); font-size: {self._font_sm}pt; font-weight: bold; background: transparent; border: none;")
        header_layout.addWidget(self._arrow)

        att = structured_data.get("attitude_change", 0) or 0
        bore = structured_data.get("boredom_change", 0) or 0
        stress = structured_data.get("stress_change", 0) or 0
        
        header_layout.addWidget(_make_badge("Attitude", att, CLR_ATT, self._font_xs, self._header_widget))
        header_layout.addWidget(_make_badge("Boredom", bore, CLR_BORE, self._font_xs, self._header_widget))
        header_layout.addWidget(_make_badge("Stress", stress, CLR_STRESS, self._font_xs, self._header_widget))
        header_layout.addStretch()

        self._header_widget.mousePressEvent = lambda e: self.toggle()
        outer_layout.addWidget(self._header_widget)

        self._content = QWidget(self)
        self._content.setStyleSheet("background: transparent; border: none;")
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 4, 0, 0)
        content_layout.setSpacing(4)

        if mode == "json": self._build_json_view(content_layout, structured_data)
        else: self._build_brief_view(content_layout, structured_data)

        outer_layout.addWidget(self._content)
        self._content.setVisible(start_expanded)

    def _build_brief_view(self, layout: QVBoxLayout, data: dict):
        for i, seg in enumerate(data.get("segments") or [], 1):
            layout.addWidget(SegmentCard(i, seg, self._font_sm, layout.parentWidget()))

        if data.get("tool_call"):
            layout.addWidget(ToolCallBlock(data["tool_call"].get("name", "?"), data["tool_call"].get("args") or {}, self._font_sm, layout.parentWidget()))

        mem_add, mem_update, mem_delete = data.get("memory_add") or [], data.get("memory_update") or [], data.get("memory_delete") or []
        if mem_add or mem_update or mem_delete:
            layout.addWidget(MemoryBlock(mem_add, mem_update, mem_delete, self._font_sm, layout.parentWidget()))

        rem_add, rem_delete = data.get("reminder_add") or [], data.get("reminder_delete") or []
        if rem_add or rem_delete:
            layout.addWidget(ReminderBlock(rem_add, rem_delete, self._font_sm, layout.parentWidget()))

    def _build_json_view(self, layout: QVBoxLayout, data: dict):
        raw = data.get("_raw_json") or json.dumps({k: v for k, v in data.items() if k != "_raw_json"}, ensure_ascii=False, indent=2)
        lbl = QLabel(raw, layout.parentWidget())
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet(f"color: #9CA3AF; font-family: 'Courier New', monospace; font-size: {self._font_sm}pt; background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 8px;")
        layout.addWidget(lbl)

    def toggle(self):
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        self._arrow.setText("▶" if self._collapsed else "▼")