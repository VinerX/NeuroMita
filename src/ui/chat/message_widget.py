"""
MessageWidget — comic-style speech bubble chat messages.
"""

import os
import math
import time as _time
import base64
import qtawesome as qta
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout,
    QLabel, QWidget, QSizePolicy, QMenu, QApplication, QPushButton,
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

# Аватары используются почти в каждом сообщении. Держим уже загруженные и
# округлённые pixmap в памяти, чтобы повторно не читать PNG и не перерисовывать
# маску при каждом новом ответе.
_AVATAR_CACHE: dict[tuple[str, str, int], QPixmap] = {}

# Modern, balanced chat colors (Telegram/Discord inspired)
ROLE_COLORS = {
    "user":      "#ff7ab8",
    "assistant": "#ff9cd2",
    "system":    "#9aa1b8",
    "event":     "#9aa1b8",
    "think":     "#bdb4c7",
}
CARD_BG = {
    "user":      QColor(171, 44, 102, 242),
    "assistant": QColor(46, 24, 52, 244),
    "system":    QColor(255, 255, 255, 13),
    "event":     QColor(255, 255, 255, 13),
    "think":     QColor(74, 58, 82, 72),
}
CARD_BORDER = {
    "user":      QColor(255, 133, 188, 165),
    "assistant": QColor(255, 132, 191, 70),
    "system":    QColor(255, 255, 255, 30),
    "event":     QColor(255, 255, 255, 30),
    "think":     QColor(189, 180, 199, 42),
}
TEXT_COLOR = {
    "user":      "#fff6fb",
    "assistant": "#f3eaf3",
    "system":    "#c7ccdc",
    "event":     "#c7ccdc",
    "think":     "#cbc1d1",
}
NAME_COLOR = {
    "user":      "#ffd7ea",
    "assistant": "#ff8fc8",
    "system":    "#9aa1b8",
    "event":     "#9aa1b8",
    "think":     "#bdb4c7",
}
TIME_COLOR = {
    "user":      "rgba(255,255,255,0.55)",
    "assistant": "rgba(255,255,255,0.42)",
    "system":    "rgba(255,255,255,0.42)",
    "event":     "rgba(255,255,255,0.42)",
    "think":     "rgba(255,255,255,0.28)",
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
    cache_key = (str(character_name or ""), str(role or ""), AVATAR_SIZE)
    cached = _AVATAR_CACHE.get(cache_key)
    if cached is not None:
        return cached
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
            if not pm.isNull():
                result = _round_pixmap(pm, AVATAR_SIZE)
                _AVATAR_CACHE[cache_key] = result
                return result
    result = _placeholder_avatar(AVATAR_SIZE, ROLE_COLORS.get(role, "#A78BFA"), character_name)
    _AVATAR_CACHE[cache_key] = result
    return result


def resolve_character_avatar(character_id: str, size: int = 32, role: str = "assistant") -> QPixmap:
    """Аватар персонажа по его ID ИЛИ display-name. В отличие от
    _get_avatar_pixmap (матчит только точные/префиксные ключи AVATAR_MAP —
    display-имена вида "Kind Mita"), понимает и голый id "KindMita", и "Kind".
    Если реального файла нет — плашка с инициалом."""
    char_id = (character_id or "").strip()
    candidates = []
    if char_id:
        low = char_id.lower()
        for key, fn in AVATAR_MAP.items():
            kl = key.lower()
            if kl.startswith(low) or low.startswith(kl.split()[0]):
                candidates.append(fn)
        candidates.append(f"{low}.png")
    avatar_dir = _get_avatar_dir()
    for fn in candidates:
        path = os.path.join(avatar_dir, fn)
        if os.path.isfile(path):
            pm = QPixmap(path)
            if not pm.isNull():
                return _round_pixmap(pm, size)
    return _placeholder_avatar(size, ROLE_COLORS.get(role, "#A78BFA"), char_id)

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
    retry_requested = pyqtSignal(str)  # emits message_id: «отправить снова» упавшего сообщения
    copy_requested = pyqtSignal(str)
    view_context_requested = pyqtSignal(str)  # emits sample_id
    view_response_context_requested = pyqtSignal(str)  # emits sample_id

    def __init__(self, role="assistant", speaker_name="", content_text="", show_avatar=True, font_size=12,
                 message_time="", show_timestamp=True, max_bubble_width=600, sample_id=None, message_id=None,
                 show_rating_controls=False, rating_callback=None, parent=None):
        super().__init__(parent)
        self._role = role
        self._speaker_name = speaker_name
        self._font_size = font_size
        self._font_sm = max(8, font_size - 2)
        self._font_xs = max(7, font_size - 3)
        self._structured_panel = None
        self._sample_id = sample_id
        self._message_id = message_id
        self._show_rating_controls = bool(show_rating_controls)
        self._rating_callback = rating_callback

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
        if role not in ("system", "event", "think", "structured"):
            tail_side = "right" if is_user else "left"

        self._avatar_label = None
        if show_avatar and role not in ("system", "event", "think", "structured"):
            self._avatar_label = QLabel(self)
            self._avatar_label.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            self._avatar_label.setStyleSheet("background: transparent; border: none;")
            self._avatar_label.setPixmap(_get_avatar_pixmap(speaker_name, role))

        # Placeholder to keep bubble aligned if avatar is hidden (for split messages)
        spacer = None
        if not show_avatar and role not in ("system", "event", "think", "structured"):
            spacer = QWidget()
            spacer.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)

        if not is_user:
            if self._avatar_label: outer.addWidget(self._avatar_label, 0, Qt.AlignmentFlag.AlignBottom)
            elif spacer: outer.addWidget(spacer, 0, Qt.AlignmentFlag.AlignBottom)

        if is_user or role in ("system", "event"): outer.addStretch()

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

        # Индикатор «сейчас озвучивается это сообщение» (скрыт по умолчанию).
        self._voicing_label = QLabel(self._card)
        self._voicing_label.setStyleSheet("background: transparent; border: none;")
        self._voicing_label.setToolTip(_("Озвучивается", "Voicing"))
        try:
            _vic = max(10, self._font_sm + 2)
            self._voicing_label.setPixmap(
                qta.icon("fa6s.volume-high", color="#ff9cd2").pixmap(_vic, _vic)
            )
        except Exception:
            self._voicing_label.setText("🔊")
        self._voicing_label.setVisible(False)
        name_row.addWidget(self._voicing_label)

        # Индикатор «сообщение не дошло» (скрыт по умолчанию). Кликом отправить
        # снова, тултип поясняет по наведению. Показывается через set_error().
        self._errored = False
        self._error_btn = QPushButton(self._card)
        self._error_btn.setFixedSize(max(14, self._font_sm + 4), max(14, self._font_sm + 4))
        self._error_btn.setFlat(True)
        self._error_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._error_btn.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0px; }")
        try:
            _eic = max(11, self._font_sm + 1)
            self._error_btn.setIcon(qta.icon("fa6s.circle-exclamation", color="#ff6b6b"))
            self._error_btn.setIconSize(QSize(_eic, _eic))
        except Exception:
            self._error_btn.setText("⚠")
        self._error_btn.setVisible(False)
        self._error_btn.clicked.connect(lambda: self.retry_requested.emit(self._message_id or ""))
        name_row.addWidget(self._error_btn)

        name_row.addStretch()

        if role == "assistant" and sample_id and self._show_rating_controls:
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

    def set_voicing(self, on: bool):
        """Показать/скрыть индикатор «это сообщение сейчас озвучивается»."""
        lbl = getattr(self, "_voicing_label", None)
        if lbl is not None:
            lbl.setVisible(bool(on))

    def set_error(self, reason: str = ""):
        """Пометить пузырь как «сообщение не дошло»: показать иконку-кнопку.

        Клик по иконке (или пункт меню) шлёт retry_requested — «отправить снова».
        `reason` (причина от провайдера) добавляется в тултип отдельной строкой.
        """
        self._errored = True
        btn = getattr(self, "_error_btn", None)
        if btn is not None:
            head = _("Сообщение не дошло.", "Message was not delivered.")
            hint = _("Нажмите, чтобы отправить снова.", "Click to send again.")
            reason = str(reason or "").strip()
            tooltip = f"{head}\n{reason}\n{hint}" if reason else f"{head} {hint}"
            btn.setToolTip(tooltip)
            btn.setVisible(True)

    def clear_error(self):
        self._errored = False
        btn = getattr(self, "_error_btn", None)
        if btn is not None:
            btn.setVisible(False)

    def set_text(self, text: str): self._body.set_text(text)
    def append_text(self, text: str): self._body.append_text(text)
    def get_text(self) -> str: return self._body.get_text()
    def set_speaker_name(self, name: str):
        self._speaker_name = name
        self._name_label.setText(name)
        if self._avatar_label: self._avatar_label.setPixmap(_get_avatar_pixmap(name, self._role))
    def set_time(self, ts: str): self._body.set_time(ts)
    def set_structured_ref(self, panel): self._structured_panel = panel

    def set_message_id(self, message_id: str):
        """Проставить id уже показанному пузырю.

        При стриминге виджет рождается раньше, чем ответ записан в историю и
        получил id, — без этого у него мёртвое контекстное меню.
        """
        self._message_id = message_id or None

    def set_sample_id(self, sample_id: str):
        """То же для finetune-сэмпла: он создаётся только после ответа модели."""
        self._sample_id = sample_id or None

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
            self._rate_up_btn.setToolTip("👍 " + _("Хороший ответ", "Good response"))
            self._rate_up_btn.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0px; }")
            self._rate_up_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            self._rate_down_btn = QPushButton(btn_container)
            self._rate_down_btn.setIcon(qta.icon("fa5s.thumbs-down", color="#9CA3AF"))
            self._rate_down_btn.setFixedSize(16, 16)
            self._rate_down_btn.setFlat(True)
            self._rate_down_btn.setToolTip("👎 " + _("Плохой ответ", "Bad response"))
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
            import qtawesome as qta
            if self._rating_callback is None:
                raise RuntimeError("MessageWidget rating callback is not configured")
            self._rating_callback(sample_id, rating)

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
            QMenu { background-color: rgba(16,13,25,0.96); color: #f3edf6; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: rgba(183, 75, 125,0.20); }
        """)

        if getattr(self, "_errored", False):
            retry_action = QAction(_("Отправить снова", "Send again"), self)
            retry_action.triggered.connect(lambda: self.retry_requested.emit(self._message_id or ""))
            menu.addAction(retry_action)
            menu.addSeparator()

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
                ctx_action = QAction(_("Просмотреть контекст запроса", "View request context"), self)
                _sid = self._sample_id or ""
                ctx_action.triggered.connect(lambda: self.view_context_requested.emit(_sid))
                menu.addAction(ctx_action)
                resp_ctx_action = QAction(_("Просмотреть контекст ответа", "View response context"), self)
                resp_ctx_action.triggered.connect(lambda: self.view_response_context_requested.emit(_sid))
                menu.addAction(resp_ctx_action)
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
    """
    A single image in the chat, displayed inside a BubbleFrame (same visual
    style as text messages).  Left-click opens the image at full resolution.
    """

    _THUMB_MAX_W = 360
    _THUMB_MAX_H = 400

    def __init__(self, image_data, role="assistant", max_bubble_width=600, description="", parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        self._description = description or ""

        thumb_w = min(self._THUMB_MAX_W, max_bubble_width - TAIL_W - 24)

        # Load once; keep original for full-size view
        self._original_pixmap = self._load_image(image_data)

        # Bubble consistent with text messages
        tail_side = "right" if role == "user" else "left"
        bubble = BubbleFrame(role, tail_side=tail_side, parent=self)

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(0)

        if not self._original_pixmap.isNull():
            scaled = self._scale_pixmap(self._original_pixmap, thumb_w, self._THUMB_MAX_H)

            img_label = QLabel(bubble)
            img_label.setPixmap(scaled)
            img_label.setStyleSheet(
                "background: transparent; border: none; border-radius: 6px; padding: 0px;")
            img_label.setCursor(Qt.CursorShape.PointingHandCursor)
            if self._description:
                img_label.setToolTip(
                    _("Нажмите для просмотра (есть описание ↓)",
                      "Click to view (description available ↓)")
                )
            else:
                img_label.setToolTip(
                    _("Нажмите для просмотра в полном размере",
                      "Click to view full size")
                )
            img_label.mousePressEvent = self._on_click
            bubble_layout.addWidget(img_label)
        else:
            err_label = QLabel("⚠️ " + _("Ошибка загрузки", "Load error"), bubble)
            err_label.setStyleSheet("color: #EF4444; padding: 12px; font-weight: bold;")
            bubble_layout.addWidget(err_label)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(bubble)

        self.setMaximumWidth(thumb_w + TAIL_W + 24 + 4)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _scale_pixmap(pixmap: QPixmap, max_w: int, max_h: int) -> QPixmap:
        if pixmap.width() <= max_w and pixmap.height() <= max_h:
            return pixmap
        scaled = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        if scaled.height() > max_h:
            scaled = pixmap.scaledToHeight(max_h, Qt.TransformationMode.SmoothTransformation)
        return scaled

    def _load_image(self, image_data) -> QPixmap:
        try:
            pixmap = QPixmap()
            if isinstance(image_data, str):
                if image_data.startswith("data:image"):
                    parts = image_data.split(",", 1)
                    if len(parts) == 2:
                        pixmap.loadFromData(base64.b64decode(parts[1]))
                else:
                    pixmap.load(image_data)
            elif isinstance(image_data, bytes):
                pixmap.loadFromData(image_data)
            return pixmap
        except Exception:
            return QPixmap()

    # ── click → full-size viewer ──────────────────────────────────────────────

    def _on_click(self, event=None) -> None:
        if event is not None and event.button() != Qt.MouseButton.LeftButton:
            return
        if self._original_pixmap.isNull():
            return
        self._show_fullsize()

    def _show_fullsize(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(_("Изображение", "Image"))
        dlg.setModal(True)
        dlg.setWindowFlags(
            dlg.windowFlags()
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        screen = QApplication.primaryScreen()
        if screen:
            avail  = screen.availableGeometry()
            max_w  = max(400, avail.width()  - 80)
            # Reserve vertical space for description if present
            max_h  = max(300, avail.height() - (200 if self._description else 80))
        else:
            max_w, max_h = 1200, 800

        pix = self._scale_pixmap(self._original_pixmap, max_w, max_h)

        img_lbl = QLabel()
        img_lbl.setPixmap(pix)
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        img_lbl.setToolTip(_("Нажмите для закрытия", "Click to close"))
        img_lbl.mousePressEvent = lambda _e: dlg.accept()

        scroll = QScrollArea(dlg)
        scroll.setWidget(img_lbl)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(scroll, 1)

        if self._description:
            from PyQt6.QtWidgets import QPlainTextEdit
            desc_box = QPlainTextEdit()
            desc_box.setPlainText(self._description)
            desc_box.setReadOnly(True)
            desc_box.setMinimumHeight(150)
            desc_box.setMaximumHeight(160)
            desc_box.setStyleSheet(
                "background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.85); "
                "border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; "
                "font-size: 11pt; padding: 6px;"
            )
            root.addWidget(desc_box)

        # Minimum width: 520 so long descriptions don't get squished in a tiny column
        dlg_w = max(520, min(pix.width() + 32, max_w))
        dlg_h = min(pix.height() + (180 if self._description else 32),
                    avail.height() - 40 if screen else max_h)
        dlg.resize(dlg_w, dlg_h)
        dlg.exec()

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
        # Автор у размышлений не выводится — аватар и имя принадлежат основному
        # пузырю ответа, а не мыслям (см. фидбэк по UI).
        if is_streaming: self._header.setText("▼ 💭 " + _("Размышляет", "Thinking") + ".")
        else:
            arrow = "▶" if self._collapsed else "▼"
            self._header.setText(f"{arrow} 💭 " + _("Размышления", "Reasoning"))
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
        self._header.setText(f"{arrow} 💭 " + _("Размышления", "Reasoning"))

    def append_content(self, text: str):
        self._content_text += text
        self._content_label.setText(self._content_text)

    def finalize(self):
        self._is_streaming = False
        self._stop_animation()
        self._header.setText("▼ 💭 " + _("Размышления", "Reasoning"))

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
        self._header.setText("▼ 💭 " + _("Размышляет", "Thinking") + dots)
