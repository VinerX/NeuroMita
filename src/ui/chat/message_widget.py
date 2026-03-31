"""
MessageWidget — comic-style speech bubble chat messages.

Avatar is bottom-aligned. Bubble has a pointed tail toward the avatar.
Text is selectable. Timestamps are semi-transparent at the bottom-right.
Structured output is a SEPARATE widget added after the message in the scroll area.
"""

import os
import math
import time as _time
import base64
import io
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt, QSize, QRectF, QPointF
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QFont, QBrush, QPen, QTextDocument,
    QTextLayout, QTextOption, QFontMetrics
)
from main_logger import logger


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
TAIL_W = 8
TAIL_H = 10
BUBBLE_RADIUS = 10

MAX_BUBBLE_WIDTH_ASSISTANT = 500  # ~60% of typical chat area
MAX_BUBBLE_WIDTH_USER = 400

ROLE_COLORS = {
    "user":      "#FFD700",
    "assistant": "#FF69B4",
    "system":    "#66ccff",
    "think":     "#aaaaaa",
}
CARD_BG = {
    "user":      QColor(0xfb, 0xdc, 0x6d),       # #fbdc6d — gold
    "assistant": QColor(0x2b, 0x35, 0x59),        # #2b3559 — dark blue
    "system":    QColor(102, 204, 255, 25),
    "think":     QColor(170, 170, 170, 15),
}
CARD_BORDER = {
    "user":      QColor(0xfb, 0xdc, 0x6d, 80),
    "assistant": QColor(0x2b, 0x35, 0x59, 80),
    "system":    QColor(102, 204, 255, 30),
    "think":     QColor(170, 170, 170, 25),
}
# Text color inside bubble
TEXT_COLOR = {
    "user":      "#1a1a2e",   # dark on gold bg
    "assistant": "#e6e6eb",   # light on dark bg
    "system":    "#e6e6eb",
    "think":     "#b0b0b0",
}
NAME_COLOR = {
    "user":      "#5a4a00",   # dark gold
    "assistant": "#FF69B4",   # hot pink
    "system":    "#66ccff",
    "think":     "#aaaaaa",
}
TIME_COLOR = {
    "user":      "rgba(0,0,0,0.3)",
    "assistant": "rgba(255,255,255,0.25)",
    "system":    "rgba(255,255,255,0.25)",
    "think":     "rgba(255,255,255,0.2)",
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
    """QFrame painted as a comic-style speech bubble with a pointed tail."""

    def __init__(self, role: str, tail_side: str | None = "left", parent=None):
        super().__init__(parent)
        self._bg = CARD_BG.get(role, QColor(30, 30, 35, 240))
        self._border = CARD_BORDER.get(role, QColor(255, 255, 255, 15))
        self._tail_side = tail_side
        left_margin = TAIL_W if tail_side == "left" else 0
        right_margin = TAIL_W if tail_side == "right" else 0
        self.setContentsMargins(left_margin + 10, 6, right_margin + 10, 6)

    def hasHeightForWidth(self) -> bool:
        lyt = self.layout()
        return lyt.hasHeightForWidth() if lyt else False

    def heightForWidth(self, w: int) -> int:
        lyt = self.layout()
        if lyt and lyt.hasHeightForWidth():
            m = self.contentsMargins()
            inner_w = max(0, w - m.left() - m.right())
            return lyt.heightForWidth(inner_w) + m.top() + m.bottom()
        return super().heightForWidth(w)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        r, tw, th = BUBBLE_RADIUS, TAIL_W, TAIL_H

        if self._tail_side == "left":
            bx, by, bw, bh = tw, 0, w - tw, h
        elif self._tail_side == "right":
            bx, by, bw, bh = 0, 0, w - tw, h
        else:
            bx, by, bw, bh = 0, 0, w, h

        path = QPainterPath()

        if self._tail_side == "left":
            path.moveTo(bx + r, by)
            path.lineTo(bx + bw - r, by)
            path.arcTo(bx + bw - 2*r, by, 2*r, 2*r, 90, -90)
            path.lineTo(bx + bw, by + bh - r)
            path.arcTo(bx + bw - 2*r, by + bh - 2*r, 2*r, 2*r, 0, -90)
            path.lineTo(bx + r, by + bh)
            path.lineTo(bx, by + bh)
            path.lineTo(bx - tw, by + bh)
            path.lineTo(bx, by + bh - th)
            path.lineTo(bx, by + r)
            path.arcTo(bx, by, 2*r, 2*r, 180, -90)
            path.closeSubpath()

        elif self._tail_side == "right":
            path.moveTo(bx + r, by)
            path.lineTo(bx + bw - r, by)
            path.arcTo(bx + bw - 2*r, by, 2*r, 2*r, 90, -90)
            path.lineTo(bx + bw, by + bh - th)
            path.lineTo(bx + bw + tw, by + bh)
            path.lineTo(bx + bw, by + bh)
            path.lineTo(bx + r, by + bh)
            path.arcTo(bx, by + bh - 2*r, 2*r, 2*r, 270, -90)
            path.lineTo(bx, by + r)
            path.arcTo(bx, by, 2*r, 2*r, 180, -90)
            path.closeSubpath()

        else:
            path.addRoundedRect(QRectF(bx, by, bw, bh), r, r)

        painter.setBrush(QBrush(self._bg))
        painter.setPen(QPen(self._border, 1))
        painter.drawPath(path)
        painter.end()


# ── Text body with smart timestamp overlay ──────────────────────────────────

class _TextBodyWidget(QWidget):
    """
    Message text area with timestamp pinned to the bottom-right corner.

    When the last text line is short enough for the timestamp to fit beside it,
    no extra height is added (timestamp overlays the empty space next to the
    last line).  When the last line is too long, a spacer equal to the timestamp
    height is inserted below the text so the timestamp never covers any text.
    """

    def __init__(self, text_color: str, time_color: str, font_size: int,
                 ts_text: str, show_ts: bool, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._show_ts = show_ts
        self._needs_row: bool | None = None  # tracks current row state

        # Text label in layout — auto-adjusts to content height
        self._text_label = QLabel(self)
        self._text_label.setWordWrap(True)
        self._text_label.setTextFormat(Qt.TextFormat.PlainText)
        self._text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._text_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._text_label.setStyleSheet(
            f"color: {text_color}; font-size: {font_size}pt; "
            f"background: transparent; border: none; padding: 0px;"
        )
        # Explicitly set font so heightForWidth() uses correct metrics immediately,
        # before Qt's stylesheet polishing cycle (which is asynchronous).
        _tf = self._text_label.font()
        _tf.setPointSize(font_size)
        self._text_label.setFont(_tf)
        self._text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # Spacer that expands to ts_h when timestamp needs its own row
        self._ts_spacer = QWidget(self)
        self._ts_spacer.setStyleSheet("background: transparent;")
        self._ts_spacer.setMaximumHeight(0)
        self._ts_spacer.setMinimumHeight(0)

        lyt = QVBoxLayout(self)
        lyt.setContentsMargins(0, 0, 0, 0)
        lyt.setSpacing(0)
        lyt.addWidget(self._text_label)
        lyt.addWidget(self._ts_spacer)

        # Timestamp: absolute overlay, NOT in layout
        self._time_label = QLabel(ts_text, self)
        self._time_label.setStyleSheet(
            f"color: {time_color}; font-size: {max(font_size - 3, 7)}pt; "
            f"background: transparent; border: none; padding: 0px;"
        )
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._time_label.setVisible(show_ts)
        if not show_ts:
            self._time_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._ts_hint = self._time_label.sizeHint()

    # ── Public API ───────────────────────────────────────────────────────────

    def set_text(self, text: str):
        self._text_label.setText(text)
        self._recheck()

    def append_text(self, chunk: str):
        self._text_label.setText(self._text_label.text() + chunk)
        if self.width() > 0:
            self._recheck()

    def get_text(self) -> str:
        return self._text_label.text()

    def set_time(self, ts: str):
        self._time_label.setText(ts)
        self._ts_hint = self._time_label.sizeHint()
        self._recheck()

    # ── Qt layout protocol ───────────────────────────────────────────────────

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self._text_label.font())
        doc.setPlainText(self._text_label.text())
        doc.setTextWidth(w)
        text_h = max(math.ceil(doc.size().height()), 1)

        if not self._show_ts:
            return text_h
        # Always query fresh hint — stylesheet may not have been applied at init
        hint = self._time_label.sizeHint()
        ts_h = hint.height()
        ts_w = hint.width() + 6
        if ts_h <= 0:
            return text_h
        if self._ts_needs_row(self._text_label.text(), w, ts_w):
            return text_h + ts_h
        return text_h

    def sizeHint(self) -> QSize:
        w = self.width() or 300
        return QSize(w, self.heightForWidth(w))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recheck()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _recheck(self):
        """Recompute layout: force correct minimum height + timestamp placement."""
        w = self.width()
        if not w:
            return

        # Always force minimum height so parent layouts can't clip the last line.
        # heightForWidth() already includes lineSpacing() virtual padding.
        needed_h = self.heightForWidth(w)
        if self.minimumHeight() != needed_h:
            self.setMinimumHeight(needed_h)
            self.updateGeometry()

        if not self._show_ts:
            return
        # Refresh hint every time — stylesheet polish happens after widget construction
        self._ts_hint = self._time_label.sizeHint()
        ts_h = self._ts_hint.height()
        ts_w = self._ts_hint.width() + 6
        if ts_h <= 0:
            return
        new_needs = self._ts_needs_row(self._text_label.text(), w, ts_w)
        if new_needs != self._needs_row:
            self._needs_row = new_needs
            h = ts_h if new_needs else 0
            self._ts_spacer.setMinimumHeight(h)
            self._ts_spacer.setMaximumHeight(h)
            self.updateGeometry()
        self._place_ts()

    def _place_ts(self):
        if not self._show_ts:
            return
        ts_h = self._ts_hint.height()
        ts_w = self._ts_hint.width() + 6
        ts_x = max(0, self.width() - ts_w)
        ts_y = 0
        self._time_label.setGeometry(ts_x, ts_y, ts_w, ts_h)
        self._time_label.raise_()

    def _ts_needs_row(self, text: str, avail_w: int, ts_w: int) -> bool:
        """True if the last text line is too wide to share a row with the timestamp."""
        if not text or avail_w <= 0:
            return False
        try:
            tl = QTextLayout(text, self._text_label.font())
            opt = QTextOption(Qt.AlignmentFlag.AlignLeft)
            opt.setWrapMode(QTextOption.WrapMode.WordWrap)
            tl.setTextOption(opt)
            tl.beginLayout()
            y = 0.0
            last_w = 0.0
            while True:
                line = tl.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(avail_w)
                line.setPosition(QPointF(0, y))
                y += line.height()
                last_w = line.naturalTextWidth()
            tl.endLayout()
            # +8 safety margin: QTextLayout vs QLabel rendering can differ by a few px
            return (last_w + ts_w + 8) > avail_w
        except Exception:
            return True  # safe fallback


# ── Main message widget ─────────────────────────────────────────────────────

class MessageWidget(QWidget):
    """
    Comic-style chat message. Structured output is NOT inside the bubble —
    it's a separate widget added to the scroll area by the renderer.
    The toggle button in the name row controls the external panel.
    """

    def __init__(
        self,
        role: str = "assistant",
        speaker_name: str = "",
        content_text: str = "",
        show_avatar: bool = True,
        font_size: int = 12,
        message_time: str = "",
        show_timestamp: bool = True,
        max_bubble_width: int = 600,
        parent=None,
    ):
        super().__init__(parent)
        self._role = role
        self._speaker_name = speaker_name
        self._font_size = font_size
        self._structured_panel = None  # external widget ref

        self.setStyleSheet("background: transparent; border: none;")

        label_color = NAME_COLOR.get(role, "#dcdcdc")
        text_color = TEXT_COLOR.get(role, "#e6e6eb")
        time_color = TIME_COLOR.get(role, "rgba(255,255,255,0.25)")
        is_user = (role == "user")

        # ── Outer row ───────────────────────────────────────────────────────
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(4)
        outer.setAlignment(Qt.AlignmentFlag.AlignBottom)

        tail_side = None
        if show_avatar and role in ("assistant", "user"):
            tail_side = "right" if is_user else "left"

        # ── Avatar ──────────────────────────────────────────────────────────
        self._avatar_label = None
        if show_avatar and role in ("assistant", "user"):
            self._avatar_label = QLabel(self)
            self._avatar_label.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            self._avatar_label.setStyleSheet("background: transparent; border: none;")
            pm = _get_avatar_pixmap(speaker_name, role)
            self._avatar_label.setPixmap(pm)

        # Assistant: avatar left
        if not is_user and self._avatar_label:
            outer.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignBottom)

        # User: push to right
        if is_user:
            outer.addStretch()

        # ── Bubble ──────────────────────────────────────────────────────────
        self._card = BubbleFrame(role, tail_side, self)
        if max_bubble_width > 0:
            self._card.setMaximumWidth(max_bubble_width)
        self._card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(1)
        self._card.setLayout(card_layout)
        self._card_layout = card_layout  # Store for adding structured widgets later

        # Name row: [name] [stretch]
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)

        self._name_label = QLabel(self._card)
        self._name_label.setStyleSheet(
            f"color: {label_color}; font-weight: bold; font-size: {font_size}pt; "
            f"background: transparent; border: none; padding: 0px;"
        )
        _nf = self._name_label.font()
        _nf.setPointSize(font_size)
        _nf.setBold(True)
        self._name_label.setFont(_nf)
        self._name_label.setText(speaker_name or "")
        name_row.addWidget(self._name_label)
        name_row.addStretch()

        # Timestamp in name row, right-aligned
        ts = message_time or _time.strftime("%H:%M")
        self._time_label = QLabel(ts, self._card)
        self._time_label.setStyleSheet(
            f"color: {time_color}; font-size: {max(font_size - 3, 7)}pt; "
            f"background: transparent; border: none; padding: 0px;"
        )
        self._time_label.setVisible(show_timestamp)
        name_row.addWidget(self._time_label)

        card_layout.addLayout(name_row)

        # Text body (no timestamp overlay)
        self._body = _TextBodyWidget(text_color, time_color, font_size, ts, False, self._card)
        self._text_label = self._body._text_label   # compat ref
        if content_text:
            self._body.set_text(content_text)
        card_layout.addWidget(self._body)

        outer.addWidget(self._card, 0)  # stretch=0 so it doesn't expand

        # User: avatar right
        if is_user and self._avatar_label:
            outer.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignBottom)

        # Non-user: push remaining space right
        if not is_user:
            outer.addStretch()

    def hasHeightForWidth(self) -> bool:
        lyt = self.layout()
        return lyt.hasHeightForWidth() if lyt else False

    def heightForWidth(self, w: int) -> int:
        lyt = self.layout()
        if lyt and lyt.hasHeightForWidth():
            m = self.contentsMargins()
            inner_w = max(0, w - m.left() - m.right())
            return lyt.heightForWidth(inner_w) + m.top() + m.bottom()
        return super().heightForWidth(w)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_text(self, text: str):
        self._body.set_text(text)

    def append_text(self, text: str):
        self._body.append_text(text)

    def get_text(self) -> str:
        return self._body.get_text()

    def set_speaker_name(self, name: str):
        self._speaker_name = name
        self._name_label.setText(name)
        if self._avatar_label:
            pm = _get_avatar_pixmap(name, self._role)
            self._avatar_label.setPixmap(pm)

    def set_time(self, ts: str):
        self._time_label.setText(ts)

    def set_structured_ref(self, panel):
        """Store a reference to an external structured panel."""
        self._structured_panel = panel

    def add_structured_widget(self, widget: QWidget):
        """Compat: same as set_structured_ref."""
        self.set_structured_ref(widget)

    def add_structured_widget_attached(self, widget: QWidget):
        """Compat: stores ref only. Panel is added separately to scroll area."""
        self.set_structured_ref(widget)

    def get_content_layout(self) -> QVBoxLayout | None:
        return None

    @property
    def role(self) -> str:
        return self._role


# ── ImageWidget ─────────────────────────────────────────────────────────────

class ImageWidget(QWidget):
    """Display an image in chat (like Telegram)."""

    MAX_WIDTH = 300
    MAX_HEIGHT = 400

    def __init__(self, image_data, role: str = "assistant", parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Left padding for assistant, right for user
        if role == "user":
            layout.addStretch()

        # Image frame
        frame = QFrame(self)
        frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                padding: 0px;
            }
        """)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # Load and display image
        pixmap = self._load_image(image_data)
        if not pixmap.isNull():
            # Scale to max dimensions while preserving aspect ratio
            scaled = pixmap.scaledToWidth(
                self.MAX_WIDTH,
                Qt.TransformationMode.SmoothTransformation
            )
            if scaled.height() > self.MAX_HEIGHT:
                scaled = pixmap.scaledToHeight(
                    self.MAX_HEIGHT,
                    Qt.TransformationMode.SmoothTransformation
                )

            img_label = QLabel(frame)
            img_label.setPixmap(scaled)
            img_label.setStyleSheet("background: transparent; border: none; padding: 0px;")
            frame_layout.addWidget(img_label)

        layout.addWidget(frame)

        # Right padding for assistant, left for user
        if role != "user":
            layout.addStretch()

        self.setMaximumWidth(self.MAX_WIDTH + 20)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def _load_image(self, image_data) -> QPixmap:
        """Load image from base64, file path, or bytes."""
        try:
            pixmap = QPixmap()
            if isinstance(image_data, str):
                if image_data.startswith("data:image"):
                    # Base64-encoded data URI
                    parts = image_data.split(",", 1)
                    if len(parts) == 2:
                        base64_str = parts[1]
                        image_bytes = base64.b64decode(base64_str)
                        pixmap.loadFromData(image_bytes)
                else:
                    # File path
                    pixmap.load(image_data)
            elif isinstance(image_data, bytes):
                pixmap.loadFromData(image_data)
            return pixmap
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            return QPixmap()


# ── ThinkBlockWidget ────────────────────────────────────────────────────────

class ThinkBlockWidget(QFrame):
    """Compact collapsible think/reasoning block (Telegram-style)."""

    def __init__(
        self,
        speaker_name: str = "",
        content_text: str = "",
        is_streaming: bool = False,
        font_size: int = 12,
        parent=None,
    ):
        super().__init__(parent)
        self._collapsed = not is_streaming  # start collapsed when loaded from history
        self._is_streaming = is_streaming
        self._content_text = content_text
        self._anim_phase = 0
        self._anim_timer = None
        self.setObjectName("ThinkBlock")
        self.setMaximumWidth(MAX_BUBBLE_WIDTH_ASSISTANT)
        self.setStyleSheet("""
            QFrame#ThinkBlock {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255,255,255,0.06);
                border-left: 2px solid rgba(170, 170, 170, 0.4);
                border-radius: 6px;
                margin: 1px 0px;
            }
        """)

        fs = max(font_size - 2, 8)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        self._header = QLabel(self)
        self._header.setStyleSheet(
            f"color: rgba(180,180,190,0.5); font-weight: bold; font-size: {fs}pt; "
            f"background: transparent; border: none;"
        )
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = lambda e: self.toggle()
        if is_streaming:
            self._header.setText(f"▼ {speaker_name} думает.")
        else:
            arrow = "▶" if self._collapsed else "▼"
            self._header.setText(f"{arrow} {speaker_name} думала...")
        layout.addWidget(self._header)

        self._content_label = QLabel(self)
        self._content_label.setWordWrap(True)
        self._content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._content_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._content_label.setStyleSheet(
            f"color: rgba(180,180,190,0.45); font-size: {fs}pt; font-style: italic; "
            f"background: transparent; border: none;"
        )
        self._content_label.setText(content_text)
        self._content_label.setVisible(not self._collapsed)
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
