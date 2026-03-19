"""
MessageWidget — Telegram-style chat message: avatar separate from card.

Layout (assistant):
  [avatar]  ┌─────────────────────────────┐
            │ SpeakerName          [≡ btn] │
            │ message text ...             │
            │ [structured output panel]    │
            └─────────────────────────────┘

Layout (user, left-aligned, no avatar):
  ┌──────────────────────────┐
  │ You:                     │
  │ message text ...         │
  └──────────────────────────┘
"""

import os
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget, QSizePolicy, QPushButton,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont


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
ROLE_COLORS = {
    "user":      "#FFD700",   # gold
    "assistant": "#FF69B4",   # hot pink
    "system":    "#66ccff",   # cyan
    "think":     "#aaaaaa",   # grey
}
CARD_BG = {
    "user":      "rgba(255, 215, 0, 0.06)",
    "assistant": "rgba(255, 105, 180, 0.04)",
    "system":    "rgba(102, 204, 255, 0.04)",
    "think":     "rgba(170, 170, 170, 0.04)",
}


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


def _placeholder_avatar(size: int, color: str, letter: str = "M") -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Arial", size // 3, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, letter)
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
    letter = (character_name or "M")[:1].upper()
    return _placeholder_avatar(AVATAR_SIZE, color, letter)


class MessageWidget(QWidget):
    """
    Chat message: avatar sits outside the card frame (Telegram-style).
    User messages are flush-left with no avatar.
    """

    def __init__(
        self,
        role: str = "assistant",
        speaker_name: str = "",
        content_text: str = "",
        show_avatar: bool = True,
        font_size: int = 12,
        parent=None,
    ):
        super().__init__(parent)
        self._role = role
        self._speaker_name = speaker_name
        self._font_size = font_size
        self._structured_panel = None  # will be set by add_structured_widget
        self._toggle_btn = None

        self.setStyleSheet("background: transparent; border: none;")

        label_color = ROLE_COLORS.get(role, "#dcdcdc")
        bg = CARD_BG.get(role, "transparent")
        border_color = label_color

        # ── Outer row: [avatar] [card] ──────────────────────────────────────
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(8)
        outer.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Avatar (only for assistant; user is left-flush without avatar)
        self._avatar_label = None
        if show_avatar and role == "assistant":
            self._avatar_label = QLabel()
            self._avatar_label.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            self._avatar_label.setStyleSheet("background: transparent; border: none;")
            pm = _get_avatar_pixmap(speaker_name, role)
            self._avatar_label.setPixmap(pm)
            outer.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignTop)

        # ── Card frame ──────────────────────────────────────────────────────
        self._card = QFrame()
        self._card.setObjectName("MsgCard")
        self._card.setStyleSheet(f"""
            QFrame#MsgCard {{
                background-color: {bg};
                border: 1px solid rgba(255,255,255,0.06);
                border-left: 3px solid {border_color};
                border-radius: 8px;
            }}
        """)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(10, 6, 10, 8)
        card_layout.setSpacing(4)

        # ── Name row: [name] [stretch] [toggle btn] ────────────────────────
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)

        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            f"color: {label_color}; font-weight: bold; font-size: {font_size}pt; "
            f"background: transparent; border: none; padding: 0px;"
        )
        self._name_label.setText(f"{speaker_name}" if speaker_name else "")
        name_row.addWidget(self._name_label)
        name_row.addStretch()

        # Toggle button placeholder — hidden by default, shown when structured panel attached
        self._toggle_btn = QPushButton("▼")
        self._toggle_btn.setFixedSize(22, 22)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px;
                color: rgba(255,255,255,0.35);
                font-size: 10pt;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: rgba(255,255,255,0.12);
                color: rgba(255,255,255,0.6);
            }}
        """)
        self._toggle_btn.clicked.connect(self._on_toggle_structured)
        self._toggle_btn.hide()
        name_row.addWidget(self._toggle_btn)

        card_layout.addLayout(name_row)

        # Text label
        self._text_label = QLabel()
        self._text_label.setWordWrap(True)
        self._text_label.setTextFormat(Qt.TextFormat.PlainText)
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

        # Add card to outer layout
        if role == "user":
            # User: card flush-left, limited width
            self._card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            outer.addWidget(self._card, 1)
        else:
            self._card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            outer.addWidget(self._card, 1)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_text(self, text: str):
        self._text_label.setText(text)

    def append_text(self, text: str):
        current = self._text_label.text()
        self._text_label.setText(current + text)

    def get_text(self) -> str:
        return self._text_label.text()

    def set_speaker_name(self, name: str):
        self._speaker_name = name
        self._name_label.setText(f"{name}")
        if self._avatar_label:
            pm = _get_avatar_pixmap(name, self._role)
            self._avatar_label.setPixmap(pm)

    def add_structured_widget(self, widget: QWidget):
        """Add a structured output panel below the message text and show toggle button."""
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
            if self._structured_panel.is_collapsed():
                self._toggle_btn.setText("▶")
            else:
                self._toggle_btn.setText("▼")


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

        # Header (clickable)
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

        # Content
        self._content_label = QLabel()
        self._content_label.setWordWrap(True)
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
