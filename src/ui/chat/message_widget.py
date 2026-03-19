"""
MessageWidget — comic-style speech bubble chat messages.

Layout (assistant):          Layout (user):
  [avatar]  ◄─bubble─┐      ┌─bubble─► [avatar]
            │  text   │      │  text  │
            │   time ─┤      ├─ time  │
            └─────────┘      └────────┘

Avatar is bottom-aligned. Bubble has a pointed tail toward the avatar.
Text is selectable. Timestamps are semi-transparent at the bottom-right.
"""

import os
import time as _time
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget, QSizePolicy, QPushButton,
)
from PyQt6.QtCore import Qt, QSize, QRectF, QPointF
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QFont, QBrush, QPen, QPolygonF,
)


# ── Avatar paths ────────────────────────────────────────────────────────────
AVATAR_DIR = os.path.join("assets", "avatars")

AVATAR_MAP = {
    "Crazy Mita":     "crazy.png",
    "Kind Mita":      "kind.png",
    "ShortHair Mita": "shorthair.png",
    "Ghost Mita":     "ghost.png",
    "Cappie":         "cappie.png",
    "Mila":           "mila.png",
    "Creepy Mita":    "creepy.png",
    "Sleepy Mita":    "sleepy.png",
    "GameMaster":     "gamemaster.png",
}

AVATAR_SIZE = 36
TAIL_W = 8        # width of the speech-bubble tail
TAIL_H = 10       # height of the tail triangle
BUBBLE_RADIUS = 10

ROLE_COLORS = {
    "user":      "#FFD700",
    "assistant": "#FF69B4",
    "system":    "#66ccff",
    "think":     "#aaaaaa",
}
CARD_BG = {
    "user":      QColor(255, 215, 0, 15),
    "assistant": QColor(255, 105, 180, 10),
    "system":    QColor(102, 204, 255, 10),
    "think":     QColor(170, 170, 170, 10),
}
CARD_BORDER = {
    "user":      QColor(255, 215, 0, 30),
    "assistant": QColor(255, 105, 180, 20),
    "system":    QColor(102, 204, 255, 20),
    "think":     QColor(170, 170, 170, 20),
}


# ── Avatar helpers ──────────────────────────────────────────────────────────

def _round_pixmap(pixmap: QPixmap, size: int) -> QPixmap:
    scaled = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return result


def _initials(name: str) -> str:
    """Get 1-2 letter initials from name. 'Crazy Mita' -> 'CM'."""
    parts = (name or "").split()
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1]).upper()
    return (name or "M")[:1].upper()


def _placeholder_avatar(size: int, color: str, name: str = "M") -> QPixmap:
    letters = _initials(name)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.setPen(QColor("#ffffff"))
    fs = size // 3 if len(letters) == 1 else size // 4
    font = QFont("Arial", fs, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, letters)
    painter.end()
    return pm


def _get_avatar_pixmap(character_name: str, role: str) -> QPixmap:
    filename = AVATAR_MAP.get(character_name)
    if filename:
        path = os.path.join(AVATAR_DIR, filename)
        if os.path.isfile(path):
            pm = QPixmap(path)
            if not pm.isNull():
                return _round_pixmap(pm, AVATAR_SIZE)
    color = ROLE_COLORS.get(role, "#8a2be2")
    return _placeholder_avatar(AVATAR_SIZE, color, character_name)


# ── Speech bubble frame ─────────────────────────────────────────────────────

class BubbleFrame(QFrame):
    """
    A QFrame that paints itself as a comic-style speech bubble.
    tail_side='left' means the pointed tail is on the left (assistant).
    tail_side='right' means the pointed tail is on the right (user).
    tail_side=None means no tail (system, etc.).
    """

    def __init__(self, role: str, tail_side: str | None = "left", parent=None):
        super().__init__(parent)
        self._bg = CARD_BG.get(role, QColor(30, 30, 35, 240))
        self._border = CARD_BORDER.get(role, QColor(255, 255, 255, 15))
        self._tail_side = tail_side
        # Extra left/right margin for the tail
        left_margin = TAIL_W if tail_side == "left" else 0
        right_margin = TAIL_W if tail_side == "right" else 0
        self.setContentsMargins(left_margin + 10, 6, right_margin + 10, 8)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        r = BUBBLE_RADIUS
        tw = TAIL_W
        th = TAIL_H

        # Bubble rect (inset from tail side)
        if self._tail_side == "left":
            bx, by, bw, bh = tw, 0, w - tw, h
        elif self._tail_side == "right":
            bx, by, bw, bh = 0, 0, w - tw, h
        else:
            bx, by, bw, bh = 0, 0, w, h

        path = QPainterPath()

        if self._tail_side == "left":
            # Rounded rect but bottom-left corner is sharp (tail)
            path.moveTo(bx + r, by)
            path.lineTo(bx + bw - r, by)
            path.arcTo(bx + bw - 2*r, by, 2*r, 2*r, 90, -90)           # top-right
            path.lineTo(bx + bw, by + bh - r)
            path.arcTo(bx + bw - 2*r, by + bh - 2*r, 2*r, 2*r, 0, -90) # bottom-right
            path.lineTo(bx + r, by + bh)
            # Tail: bottom-left pointed toward avatar
            path.lineTo(bx, by + bh)              # bottom edge to tail start
            path.lineTo(bx - tw, by + bh)          # tail tip (points left)
            path.lineTo(bx, by + bh - th)          # back up
            path.lineTo(bx, by + r)
            path.arcTo(bx, by, 2*r, 2*r, 180, -90)                      # top-left
            path.closeSubpath()

        elif self._tail_side == "right":
            # Rounded rect but bottom-right corner is sharp (tail)
            path.moveTo(bx + r, by)
            path.lineTo(bx + bw - r, by)
            path.arcTo(bx + bw - 2*r, by, 2*r, 2*r, 90, -90)           # top-right
            path.lineTo(bx + bw, by + r)
            path.lineTo(bx + bw, by + bh - th)     # right side down to tail
            path.lineTo(bx + bw + tw, by + bh)      # tail tip (points right)
            path.lineTo(bx + bw, by + bh)           # back
            path.lineTo(bx + r, by + bh)
            path.arcTo(bx, by + bh - 2*r, 2*r, 2*r, 270, -90)          # bottom-left
            path.lineTo(bx, by + r)
            path.arcTo(bx, by, 2*r, 2*r, 180, -90)                      # top-left
            path.closeSubpath()

        else:
            path.addRoundedRect(QRectF(bx, by, bw, bh), r, r)

        painter.setBrush(QBrush(self._bg))
        painter.setPen(QPen(self._border, 1))
        painter.drawPath(path)
        painter.end()


# ── Main message widget ─────────────────────────────────────────────────────

class MessageWidget(QWidget):
    """
    Comic-style chat message with speech-bubble tail, avatar at bottom,
    selectable text, and optional structured output toggle.
    """

    def __init__(
        self,
        role: str = "assistant",
        speaker_name: str = "",
        content_text: str = "",
        show_avatar: bool = True,
        font_size: int = 12,
        message_time: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._role = role
        self._speaker_name = speaker_name
        self._font_size = font_size
        self._structured_panel = None
        self._toggle_btn = None

        self.setStyleSheet("background: transparent; border: none;")

        label_color = ROLE_COLORS.get(role, "#dcdcdc")
        is_user = (role == "user")

        # ── Outer row ───────────────────────────────────────────────────────
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(4)
        outer.setAlignment(Qt.AlignmentFlag.AlignBottom)

        # Determine tail direction
        tail_side = None
        if show_avatar and role in ("assistant", "user"):
            tail_side = "right" if is_user else "left"

        # ── Avatar ──────────────────────────────────────────────────────────
        self._avatar_label = None
        if show_avatar and role in ("assistant", "user"):
            self._avatar_label = QLabel()
            self._avatar_label.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            self._avatar_label.setStyleSheet("background: transparent; border: none;")
            pm = _get_avatar_pixmap(speaker_name, role)
            self._avatar_label.setPixmap(pm)

        # Assistant: avatar on the left
        if not is_user and self._avatar_label:
            outer.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignBottom)

        # User: stretch on the left to push right
        if is_user:
            outer.addStretch()

        # ── Bubble ──────────────────────────────────────────────────────────
        self._card = BubbleFrame(role, tail_side)
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(3)
        self._card.setLayout(card_layout)

        # Name row: [name] [stretch] [toggle btn]
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)

        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            f"color: {label_color}; font-weight: bold; font-size: {font_size}pt; "
            f"background: transparent; border: none; padding: 0px;"
        )
        self._name_label.setText(speaker_name or "")
        name_row.addWidget(self._name_label)
        name_row.addStretch()

        # Toggle button (hidden until structured panel attached)
        self._toggle_btn = QPushButton("▼")
        self._toggle_btn.setFixedSize(22, 22)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px;
                color: rgba(255,255,255,0.35);
                font-size: 10pt; font-weight: bold; padding: 0px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.12);
                color: rgba(255,255,255,0.6);
            }
        """)
        self._toggle_btn.clicked.connect(self._on_toggle_structured)
        self._toggle_btn.hide()
        name_row.addWidget(self._toggle_btn)

        card_layout.addLayout(name_row)

        # Text label — SELECTABLE
        self._text_label = QLabel()
        self._text_label.setWordWrap(True)
        self._text_label.setTextFormat(Qt.TextFormat.PlainText)
        self._text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._text_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._text_label.setStyleSheet(
            f"color: #e6e6eb; font-size: {font_size}pt; "
            f"background: transparent; border: none; padding: 0px;"
        )
        self._text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if content_text:
            self._text_label.setText(content_text)
        card_layout.addWidget(self._text_label)

        # Structured output container
        self._structured_container = QVBoxLayout()
        self._structured_container.setContentsMargins(0, 0, 0, 0)
        self._structured_container.setSpacing(0)
        card_layout.addLayout(self._structured_container)

        # Timestamp row (bottom-right, semi-transparent)
        self._time_label = QLabel()
        self._time_label.setStyleSheet(
            f"color: rgba(255,255,255,0.25); font-size: {max(font_size - 3, 7)}pt; "
            f"background: transparent; border: none; padding: 0px;"
        )
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        ts = message_time or _time.strftime("%H:%M")
        self._time_label.setText(ts)
        card_layout.addWidget(self._time_label)

        self._card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(self._card, 1)

        # User: avatar on the right
        if is_user and self._avatar_label:
            outer.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignBottom)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_text(self, text: str):
        self._text_label.setText(text)

    def append_text(self, text: str):
        self._text_label.setText(self._text_label.text() + text)

    def get_text(self) -> str:
        return self._text_label.text()

    def set_speaker_name(self, name: str):
        self._speaker_name = name
        self._name_label.setText(name)
        if self._avatar_label:
            pm = _get_avatar_pixmap(name, self._role)
            self._avatar_label.setPixmap(pm)

    def set_time(self, ts: str):
        self._time_label.setText(ts)

    def add_structured_widget(self, widget: QWidget):
        self._structured_panel = widget
        self._structured_container.addWidget(widget)
        self._toggle_btn.show()
        self._update_toggle_icon()

    def get_content_layout(self) -> QVBoxLayout:
        return self._structured_container

    @property
    def role(self) -> str:
        return self._role

    # ── Toggle ──────────────────────────────────────────────────────────────

    def _on_toggle_structured(self):
        if self._structured_panel and hasattr(self._structured_panel, 'toggle'):
            self._structured_panel.toggle()
            self._update_toggle_icon()

    def _update_toggle_icon(self):
        if self._structured_panel and hasattr(self._structured_panel, 'is_collapsed'):
            self._toggle_btn.setText("▶" if self._structured_panel.is_collapsed() else "▼")


# ── ThinkBlockWidget ────────────────────────────────────────────────────────

class ThinkBlockWidget(QFrame):
    """Collapsible think/reasoning block."""

    def __init__(
        self,
        speaker_name: str = "",
        content_text: str = "",
        is_streaming: bool = False,
        font_size: int = 12,
        parent=None,
    ):
        super().__init__(parent)
        self._collapsed = False
        self._is_streaming = is_streaming
        self._content_text = content_text
        self._anim_phase = 0
        self._anim_timer = None
        self.setObjectName("ThinkBlock")
        self.setStyleSheet("""
            QFrame#ThinkBlock {
                background-color: rgba(170, 170, 170, 0.04);
                border: 1px solid rgba(255,255,255,0.06);
                border-left: 3px solid #aaaaaa;
                border-radius: 8px;
                margin: 2px 0px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        self._header = QLabel()
        self._header.setStyleSheet(
            f"color: #aaaaaa; font-weight: bold; font-size: {font_size}pt; "
            f"background: transparent; border: none;"
        )
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = lambda e: self.toggle()
        verb = "думает" if is_streaming else "думала"
        dots = "." if is_streaming else "..."
        self._header.setText(f"▼ {speaker_name} {verb}{dots}")
        layout.addWidget(self._header)

        self._content_label = QLabel()
        self._content_label.setWordWrap(True)
        self._content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._content_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._content_label.setStyleSheet(
            f"color: #b0b0b0; font-size: {font_size}pt; font-style: italic; "
            f"background: transparent; border: none;"
        )
        self._content_label.setText(content_text)
        layout.addWidget(self._content_label)

        self._speaker_name = speaker_name
        if is_streaming:
            self._start_animation()

    def toggle(self):
        if self._is_streaming:
            return
        self._collapsed = not self._collapsed
        self._content_label.setVisible(not self._collapsed)
        arrow = "▶" if self._collapsed else "▼"
        self._header.setText(f"{arrow} {self._speaker_name} думала...")

    def append_content(self, text: str):
        self._content_text += text
        self._content_label.setText(self._content_text)

    def finalize(self):
        self._is_streaming = False
        self._stop_animation()
        self._header.setText(f"▼ {self._speaker_name} думала...")

    def _start_animation(self):
        from PyQt6.QtCore import QTimer
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(400)

    def _stop_animation(self):
        if self._anim_timer:
            self._anim_timer.stop()
            self._anim_timer = None

    def _tick(self):
        phases = [".  ", ".. ", "..."]
        self._anim_phase = (self._anim_phase + 1) % 3
        dots = phases[self._anim_phase]
        self._header.setText(f"▼ {self._speaker_name} думает{dots}")
