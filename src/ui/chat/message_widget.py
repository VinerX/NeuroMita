"""
MessageWidget — comic-style speech bubble chat messages.
"""

import os
import math
import time as _time
import base64
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget, QSizePolicy,
    QMenu, QApplication,
)
from PyQt6.QtCore import Qt, QSize, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QFont, QBrush, QPen, QTextDocument,
    QTextLayout, QTextOption, QAction,
)
from main_logger import logger
from utils import _

def _get_avatar_dir() -> str:
    base = os.environ.get("NEUROMITA_BASE_DIR", "")
    return os.path.join(base, "assets", "avatars") if base else os.path.join("assets", "avatars")
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
TAIL_H = 12
BUBBLE_RADIUS = 12

# Modern, balanced chat colors (Telegram/Discord inspired)
ROLE_COLORS = {
    "user":      "#F4D35E",  # Soft Gold
    "assistant": "#A78BFA",  # Soft Purple
    "system":    "#60A5FA",  # Soft Blue
    "think":     "#9CA3AF",  # Soft Gray
}
CARD_BG = {
    "user":      QColor(232, 203, 100, 245),
    "assistant": QColor(38, 43, 68, 245), 
    "system":    QColor(96, 165, 250, 30),
    "think":     QColor(156, 163, 175, 20),
}
CARD_BORDER = {
    "user":      QColor(232, 203, 100, 100),
    "assistant": QColor(255, 255, 255, 15),
    "system":    QColor(96, 165, 250, 50),
    "think":     QColor(156, 163, 175, 30),
}
TEXT_COLOR = {
    "user":      "#1E1E24", 
    "assistant": "#EAEAEA",
    "system":    "#EAEAEA",
    "think":     "#A0A0A5",
}
NAME_COLOR = {
    "user":      "#8C6B14",
    "assistant": "#D896FF",
    "system":    "#60A5FA",
    "think":     "#9CA3AF",
}
TIME_COLOR = {
    "user":      "rgba(0,0,0,0.4)",
    "assistant": "rgba(255,255,255,0.35)",
    "system":    "rgba(255,255,255,0.35)",
    "think":     "rgba(255,255,255,0.25)",
}

def _round_pixmap(pixmap: QPixmap, size: int) -> QPixmap:
    scaled = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
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
    if len(parts) >= 2: return (parts[0][:1] + parts[1][:1]).upper()
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
    painter.setPen(QColor("#ffffff") if QColor(color).lightness() < 180 else QColor("#1e1e1e"))
    font = QFont("Arial", size // 3 if len(letters) == 1 else size // 4, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, letters)
    painter.end()
    return pm

def _get_avatar_pixmap(character_name: str, role: str) -> QPixmap:
    filename = AVATAR_MAP.get(character_name)
    if not filename and character_name:
        for key, val in AVATAR_MAP.items():
            if character_name.startswith(key):
                filename = val
                break
    if filename:
        path = os.path.join(_get_avatar_dir(), filename)
        if os.path.isfile(path):
            pm = QPixmap(path)
            if not pm.isNull(): return _round_pixmap(pm, AVATAR_SIZE)
    return _placeholder_avatar(AVATAR_SIZE, ROLE_COLORS.get(role, "#A78BFA"), character_name)

class BubbleFrame(QFrame):
    def __init__(self, role: str, tail_side: str | None = "left", parent=None):
        super().__init__(parent)
        self._bg = CARD_BG.get(role, QColor(30, 30, 35, 240))
        self._border = CARD_BORDER.get(role, QColor(255, 255, 255, 15))
        self._tail_side = tail_side
        left_margin = TAIL_W if tail_side == "left" else 0
        right_margin = TAIL_W if tail_side == "right" else 0
        self.setContentsMargins(left_margin + 12, 8, right_margin + 12, 8)
        self.setMinimumHeight(AVATAR_SIZE)

    def hasHeightForWidth(self) -> bool:
        lyt = self.layout()
        return lyt.hasHeightForWidth() if lyt else False

    def heightForWidth(self, w: int) -> int:
        lyt = self.layout()
        if lyt and lyt.hasHeightForWidth():
            m = self.contentsMargins()
            return lyt.heightForWidth(max(0, w - m.left() - m.right())) + m.top() + m.bottom()
        return super().heightForWidth(w)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r, tw, th = BUBBLE_RADIUS, TAIL_W, TAIL_H

        if self._tail_side == "left": bx, by, bw, bh = tw, 0, w - tw, h
        elif self._tail_side == "right": bx, by, bw, bh = 0, 0, w - tw, h
        else: bx, by, bw, bh = 0, 0, w, h

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

class _TextBodyWidget(QWidget):
    def __init__(self, text_color: str, time_color: str, font_size: int, font_xs: int, ts_text: str, show_ts: bool, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._show_ts = show_ts
        self._needs_row: bool | None = None

        self._text_label = QLabel(self)
        self._text_label.setWordWrap(True)
        self._text_label.setTextFormat(Qt.TextFormat.PlainText)
        self._text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self._text_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._text_label.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._text_label.setStyleSheet(f"color: {text_color}; font-size: {font_size}pt; background: transparent; border: none; padding: 0px;")
        
        _tf = self._text_label.font()
        _tf.setPointSize(font_size)
        self._text_label.setFont(_tf)
        self._text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._ts_spacer = QWidget(self)
        self._ts_spacer.setStyleSheet("background: transparent;")
        self._ts_spacer.setMaximumHeight(0)
        self._ts_spacer.setMinimumHeight(0)

        lyt = QVBoxLayout(self)
        lyt.setContentsMargins(0, 0, 0, 0)
        lyt.setSpacing(0)
        lyt.addWidget(self._text_label)
        lyt.addWidget(self._ts_spacer)

        self._time_label = QLabel(ts_text, self)
        self._time_label.setStyleSheet(f"color: {time_color}; font-size: {font_xs}pt; background: transparent; border: none; padding: 0px;")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._time_label.setVisible(show_ts)
        if not show_ts: self._time_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._ts_hint = self._time_label.sizeHint()

    def contextMenuEvent(self, event): event.ignore()
    def set_text(self, text: str):
        self._text_label.setText(text)
        self._recheck()
    def append_text(self, chunk: str):
        self._text_label.setText(self._text_label.text() + chunk)
        if self.width() > 0: self._recheck()
    def get_text(self) -> str: return self._text_label.text()
    def set_time(self, ts: str):
        self._time_label.setText(ts)
        self._ts_hint = self._time_label.sizeHint()
        self._recheck()

    def hasHeightForWidth(self) -> bool: return True
    def heightForWidth(self, w: int) -> int:
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self._text_label.font())
        doc.setPlainText(self._text_label.text())
        doc.setTextWidth(w)
        text_h = max(math.ceil(doc.size().height()), 1)

        if not self._show_ts: return text_h
        hint = self._time_label.sizeHint()
        ts_h, ts_w = hint.height(), hint.width() + 6
        if ts_h <= 0: return text_h
        return text_h + ts_h if self._ts_needs_row(self._text_label.text(), w, ts_w) else text_h + 4

    def sizeHint(self) -> QSize:
        w = self.width() or 300
        return QSize(w, self.heightForWidth(w))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recheck()

    def _recheck(self):
        w = self.width()
        if not w: return
        needed_h = self.heightForWidth(w)
        if self.minimumHeight() != needed_h:
            self.setMinimumHeight(needed_h)
            self.updateGeometry()

        if not self._show_ts: return
        self._ts_hint = self._time_label.sizeHint()
        ts_h, ts_w = self._ts_hint.height(), self._ts_hint.width() + 6
        if ts_h <= 0: return
        new_needs = self._ts_needs_row(self._text_label.text(), w, ts_w)
        target_spacer_h = ts_h if new_needs else 4
        if new_needs != self._needs_row or self._ts_spacer.maximumHeight() != target_spacer_h:
            self._needs_row = new_needs
            self._ts_spacer.setMinimumHeight(target_spacer_h)
            self._ts_spacer.setMaximumHeight(target_spacer_h)
            self.updateGeometry()
        self._place_ts()

    def _place_ts(self):
        if not self._show_ts: return
        ts_h, ts_w = self._ts_hint.height(), self._ts_hint.width() + 6
        ts_x, ts_y = max(0, self.width() - ts_w), max(0, self.height() - ts_h)
        self._time_label.setGeometry(ts_x, ts_y, ts_w, ts_h)
        self._time_label.raise_()

    def _ts_needs_row(self, text: str, avail_w: int, ts_w: int) -> bool:
        if not text or avail_w <= 0: return False
        try:
            tl = QTextLayout(text, self._text_label.font())
            opt = QTextOption(Qt.AlignmentFlag.AlignLeft)
            opt.setWrapMode(QTextOption.WrapMode.WordWrap)
            tl.setTextOption(opt)
            tl.beginLayout()
            y, last_w = 0.0, 0.0
            while True:
                line = tl.createLine()
                if not line.isValid(): break
                line.setLineWidth(avail_w)
                line.setPosition(QPointF(0, y))
                y += line.height()
                last_w = line.naturalTextWidth()
            tl.endLayout()
            return (last_w + ts_w + 8) > avail_w
        except Exception:
            return True

class MessageWidget(QWidget):
    delete_requested = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    regenerate_requested = pyqtSignal(str)
    regenerate_from_requested = pyqtSignal(str)
    copy_requested = pyqtSignal(str)

    def __init__(self, role="assistant", speaker_name="", content_text="", show_avatar=True, font_size=12,
                 message_time="", show_timestamp=True, max_bubble_width=600, sample_id=None, message_id=None, parent=None):
        super().__init__(parent)
        self._role = role
        self._speaker_name = speaker_name
        self._font_size = font_size
        self._font_sm = max(8, font_size - 2)
        self._font_xs = max(7, font_size - 3)
        self._structured_panel = None
        self._sample_id = sample_id
        self._message_id = message_id

        self.setStyleSheet("background: transparent; border: none;")

        label_color = NAME_COLOR.get(role, "#A78BFA")
        text_color = TEXT_COLOR.get(role, "#EAEAEA")
        time_color = TIME_COLOR.get(role, "rgba(255,255,255,0.35)")
        is_user = (role == "user")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(8)
        outer.setAlignment(Qt.AlignmentFlag.AlignBottom)

        tail_side = None
        if role not in ("system", "think", "structured"):
            tail_side = "right" if is_user else "left"

        self._avatar_label = None
        if show_avatar and role not in ("system", "think", "structured"):
            self._avatar_label = QLabel(self)
            self._avatar_label.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            self._avatar_label.setStyleSheet("background: transparent; border: none;")
            self._avatar_label.setPixmap(_get_avatar_pixmap(speaker_name, role))

        # Placeholder to keep bubble aligned if avatar is hidden (for split messages)
        spacer = None
        if not show_avatar and role not in ("system", "think", "structured"):
            spacer = QWidget()
            spacer.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)

        if not is_user:
            if self._avatar_label: outer.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignBottom)
            elif spacer: outer.addWidget(spacer, 0, Qt.AlignmentFlag.AlignBottom)

        if is_user or role == "system": outer.addStretch()

        self._card = BubbleFrame(role, tail_side, self)
        if max_bubble_width > 0: self._card.setMaximumWidth(max_bubble_width)
        self._card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(2)
        self._card.setLayout(card_layout)

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)

        self._name_label = QLabel(self._card)
        self._name_label.setStyleSheet(f"color: {label_color}; font-weight: bold; font-size: {self._font_sm}pt; background: transparent; border: none; padding: 0px;")
        _nf = self._name_label.font()
        _nf.setPointSize(self._font_sm)
        _nf.setBold(True)
        self._name_label.setFont(_nf)
        self._name_label.setText(speaker_name or "")
        name_row.addWidget(self._name_label)
        name_row.addStretch()

        if role == "assistant" and sample_id:
            self._add_rating_buttons(name_row, sample_id, self._font_sm)

        ts = message_time or _time.strftime("%H:%M")
        card_layout.addLayout(name_row)

        self._body = _TextBodyWidget(text_color, time_color, font_size, self._font_xs, ts, show_timestamp, self._card)
        if content_text: self._body.set_text(content_text)
        card_layout.addWidget(self._body)

        outer.addWidget(self._card, 0)

        if is_user:
            if self._avatar_label: outer.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignBottom)
            elif spacer: outer.addWidget(spacer, 0, Qt.AlignmentFlag.AlignBottom)

        if not is_user: outer.addStretch()

    def hasHeightForWidth(self) -> bool:
        lyt = self.layout()
        return lyt.hasHeightForWidth() if lyt else False
    def heightForWidth(self, w: int) -> int:
        lyt = self.layout()
        if lyt and lyt.hasHeightForWidth():
            m = self.contentsMargins()
            return lyt.heightForWidth(max(0, w - m.left() - m.right())) + m.top() + m.bottom()
        return super().heightForWidth(w)

    def set_text(self, text: str): self._body.set_text(text)
    def append_text(self, text: str): self._body.append_text(text)
    def get_text(self) -> str: return self._body.get_text()
    def set_speaker_name(self, name: str):
        self._speaker_name = name
        self._name_label.setText(name)
        if self._avatar_label: self._avatar_label.setPixmap(_get_avatar_pixmap(name, self._role))
    def set_time(self, ts: str): self._body.set_time(ts)
    def set_structured_ref(self, panel): self._structured_panel = panel

    def _add_rating_buttons(self, name_row, sample_id: str, font_size: int):
        try:
            import qtawesome as qta
            from PyQt6.QtWidgets import QPushButton, QHBoxLayout
            btn_container = QWidget(self._card)
            btn_container.setStyleSheet("background: transparent; border: none;")
            btn_layout = QHBoxLayout(btn_container)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(4)

            self._rate_up_btn = QPushButton(btn_container)
            self._rate_up_btn.setIcon(qta.icon("fa5s.thumbs-up", color="#9CA3AF"))
            self._rate_up_btn.setFixedSize(16, 16)
            self._rate_up_btn.setFlat(True)
            self._rate_up_btn.setToolTip("👍 Хороший ответ")
            self._rate_up_btn.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0px; }")
            self._rate_up_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            self._rate_down_btn = QPushButton(btn_container)
            self._rate_down_btn.setIcon(qta.icon("fa5s.thumbs-down", color="#9CA3AF"))
            self._rate_down_btn.setFixedSize(16, 16)
            self._rate_down_btn.setFlat(True)
            self._rate_down_btn.setToolTip("👎 Плохой ответ")
            self._rate_down_btn.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0px; }")
            self._rate_down_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            self._rate_up_btn.clicked.connect(lambda: self._on_rate(sample_id, 1))
            self._rate_down_btn.clicked.connect(lambda: self._on_rate(sample_id, -1))

            btn_layout.addWidget(self._rate_up_btn)
            btn_layout.addWidget(self._rate_down_btn)
            name_row.addWidget(btn_container)
        except Exception: pass

    def _on_rate(self, sample_id: str, rating: int):
        try:
            from managers.finetune_collector import FineTuneCollector
            import qtawesome as qta
            fc = FineTuneCollector.instance
            if fc: fc.update_rating(sample_id, rating)

            _ACTIVE_UP   = "QPushButton { background: #10B981; border-radius: 4px; border: none; }"
            _ACTIVE_DOWN = "QPushButton { background: #EF4444; border-radius: 4px; border: none; }"
            _INACTIVE    = "QPushButton { background: transparent; border: none; opacity: 0.5; }"

            if rating > 0:
                self._rate_up_btn.setIcon(qta.icon("fa5s.thumbs-up", color="#FFFFFF"))
                self._rate_up_btn.setStyleSheet(_ACTIVE_UP)
                self._rate_down_btn.setStyleSheet(_INACTIVE)
            else:
                self._rate_down_btn.setIcon(qta.icon("fa5s.thumbs-down", color="#FFFFFF"))
                self._rate_down_btn.setStyleSheet(_ACTIVE_DOWN)
                self._rate_up_btn.setStyleSheet(_INACTIVE)

            self._rate_up_btn.setEnabled(False)
            self._rate_down_btn.setEnabled(False)
        except Exception: pass

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1E1E24; color: #EAEAEA; border: 1px solid #3A3A4A; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: #383A59; }
        """)

        if self._role == "user":
            edit_action = QAction(_("Редактировать", "Edit"), self)
            edit_action.triggered.connect(lambda: self.edit_requested.emit(self._message_id or ""))
            menu.addAction(edit_action)
            if self._message_id:
                regen_from_action = QAction(_("Регенерировать отсюда", "Regenerate from here"), self)
                regen_from_action.triggered.connect(lambda: self.regenerate_from_requested.emit(self._message_id))
                menu.addAction(regen_from_action)
        elif self._role in ("assistant", "system"):
            if self._role == "assistant":
                regen_action = QAction(_("Регенерировать", "Regenerate"), self)
                regen_action.triggered.connect(lambda: self.regenerate_requested.emit(self._message_id or ""))
                menu.addAction(regen_action)
            if self._message_id:
                regen_from_action = QAction(_("Регенерировать отсюда", "Regenerate from here"), self)
                regen_from_action.triggered.connect(lambda: self.regenerate_from_requested.emit(self._message_id))
                menu.addAction(regen_from_action)

        selected = self._body._text_label.selectedText() if hasattr(self, '_body') else ""
        if selected:
            copy_sel_action = QAction(_("Копировать выделенное", "Copy selected"), self)
            copy_sel_action.triggered.connect(lambda: QApplication.clipboard().setText(selected))
            menu.addAction(copy_sel_action)
        copy_action = QAction(_("Копировать всё", "Copy all"), self)
        copy_action.triggered.connect(lambda: self._on_copy())
        menu.addAction(copy_action)

        if self._message_id:
            menu.addSeparator()
            del_action = QAction(_("Удалить", "Delete"), self)
            del_action.triggered.connect(lambda: self.delete_requested.emit(self._message_id))
            menu.addAction(del_action)

        menu.exec(event.globalPos())

    def _on_copy(self):
        text = self.get_text()
        QApplication.clipboard().setText(text)
        self.copy_requested.emit(text)

class ImageWidget(QWidget):
    def __init__(self, image_data, role="assistant", max_bubble_width=600, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        self.MAX_WIDTH = min(400, max_bubble_width)
        self.MAX_HEIGHT = 400

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        frame = QFrame(self)
        frame.setStyleSheet("""
            QFrame { background-color: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 0px; }
        """)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        pixmap = self._load_image(image_data)
        if not pixmap.isNull():
            scaled = pixmap.scaledToWidth(self.MAX_WIDTH, Qt.TransformationMode.SmoothTransformation)
            if scaled.height() > self.MAX_HEIGHT:
                scaled = pixmap.scaledToHeight(self.MAX_HEIGHT, Qt.TransformationMode.SmoothTransformation)
            img_label = QLabel(frame)
            img_label.setPixmap(scaled)
            img_label.setStyleSheet("background: transparent; border: none; padding: 0px;")
            frame_layout.addWidget(img_label)
        else:
            err_label = QLabel("⚠️ " + _("Ошибка загрузки", "Load error"), frame)
            err_label.setStyleSheet("color: #EF4444; padding: 12px; font-weight: bold;")
            frame_layout.addWidget(err_label)

        layout.addWidget(frame)
        self.setMaximumWidth(self.MAX_WIDTH + 20)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def _load_image(self, image_data) -> QPixmap:
        try:
            pixmap = QPixmap()
            if isinstance(image_data, str):
                if image_data.startswith("data:image"):
                    parts = image_data.split(",", 1)
                    if len(parts) == 2: pixmap.loadFromData(base64.b64decode(parts[1]))
                else: pixmap.load(image_data)
            elif isinstance(image_data, bytes): pixmap.loadFromData(image_data)
            return pixmap
        except Exception: return QPixmap()

class ThinkBlockWidget(QFrame):
    def __init__(self, speaker_name="", content_text="", is_streaming=False, font_size=12, max_bubble_width=600, parent=None):
        super().__init__(parent)
        self._collapsed = not is_streaming
        self._is_streaming = is_streaming
        self._content_text = content_text
        self._anim_phase = 0
        self._anim_timer = None
        self._font_sm = max(8, font_size - 2)
        
        self.setObjectName("ThinkBlock")
        self.setMaximumWidth(max(100, max_bubble_width))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("""
            QFrame#ThinkBlock { background-color: rgba(156, 163, 175, 0.08); border: 1px solid rgba(156, 163, 175, 0.15); border-radius: 8px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self._header = QLabel(self)
        self._header.setStyleSheet(f"color: #9CA3AF; font-weight: bold; font-size: {self._font_sm}pt; background: transparent; border: none;")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = lambda e: self.toggle()
        if is_streaming: self._header.setText(f"▼ 💭 {speaker_name} думает.")
        else:
            arrow = "▶" if self._collapsed else "▼"
            self._header.setText(f"{arrow} 💭 {speaker_name} думала...")
        layout.addWidget(self._header)

        self._content_label = QLabel(self)
        self._content_label.setWordWrap(True)
        self._content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._content_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._content_label.setStyleSheet(f"color: rgba(234,234,234,0.7); font-size: {self._font_sm}pt; font-style: italic; background: transparent; border: none;")
        self._content_label.setText(content_text)
        self._content_label.setVisible(not self._collapsed)
        layout.addWidget(self._content_label)

        self._speaker_name = speaker_name
        if is_streaming: self._start_animation()

    def toggle(self):
        if self._is_streaming: return
        self._collapsed = not self._collapsed
        self._content_label.setVisible(not self._collapsed)
        arrow = "▶" if self._collapsed else "▼"
        self._header.setText(f"{arrow} 💭 {self._speaker_name} думала...")

    def append_content(self, text: str):
        self._content_text += text
        self._content_label.setText(self._content_text)

    def finalize(self):
        self._is_streaming = False
        self._stop_animation()
        self._header.setText(f"▼ 💭 {self._speaker_name} думала...")

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
        self._header.setText(f"▼ 💭 {self._speaker_name} думает{dots}")