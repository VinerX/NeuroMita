from __future__ import annotations

import datetime as _dt
import os
import shutil
from typing import Any

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    import qtawesome as qta
except Exception:
    qta = None

from core.events import Events, get_event_bus
from main_logger import logger
from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider


_CATEGORY_ORDER = ("tts", "asr", "rag", "backend", "deps")
_CATEGORY_LABELS = {
    "tts": _("Синтез речи (TTS)", "TTS"),
    "asr": _("Распознавание (ASR)", "ASR"),
    "rag": _("Поиск и память (RAG)", "RAG"),
    "backend": _("Системное ядро", "Backend"),
    "deps": _("Зависимости", "Dependencies"),
}
_CATEGORY_ICONS = {
    "tts": "fa5s.wave-square",
    "asr": "fa5s.microphone",
    "rag": "fa5s.cube",
    "backend": "fa5s.microchip",
    "deps": "fa5s.plug",
}
# rows from registry use these category codes — map "beats" into deps bucket
_ROW_CATEGORY_MAP = {
    "tts": "tts",
    "asr": "asr",
    "rag": "rag",
    "backend": "backend",
    "beats": "deps",
    "deps": "deps",
}

_STATUS_LABELS = {
    "ready": _("Установлена", "Installed"),
    "installed": _("Установлена", "Installed"),
    "not_installed": _("Не установлена", "Not installed"),
    "backend_missing": _("Нет ядра", "Backend missing"),
    "failed": _("Ошибка", "Failed"),
    "unknown": _("Неизвестно", "Unknown"),
}
_STATUS_ICONS = {
    "ready": ("fa5s.check-circle", "#65d46e"),
    "installed": ("fa5s.check-circle", "#65d46e"),
    "not_installed": ("fa5s.clock", "#a1a1aa"),
    "backend_missing": ("fa5s.exclamation-circle", "#f1b84b"),
    "failed": ("fa5s.times-circle", "#ff7b7b"),
    "unknown": ("fa5s.question-circle", "#9ca3af"),
}

# Pink accent (matches NeuroMita brand and screenshot)
ACCENT = "#ec4899"
ACCENT_HOVER = "#f472b6"
ACCENT_DIM = "#6b2944"

CARD_BG = "#1a1726"
CARD_BG_HOVER = "#221d33"
DIALOG_BG = "#100c19"
PANEL_BG = "#181426"
SIDEBAR_BG = "#171225"
BORDER = "rgba(255,255,255,0.06)"
BORDER_STRONG = "rgba(255,255,255,0.10)"
MUTED = "#a1a1aa"
TEXT = "#f4f4f5"
DIM_TEXT = "#d4d4d8"


def _meta_from_row(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def _status_from_row(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("status")
    return value if isinstance(value, dict) else {}


def _row_category(row: dict[str, Any]) -> str:
    raw = str(_meta_from_row(row).get("category") or "").strip().lower()
    return _ROW_CATEGORY_MAP.get(raw, raw)


def _icon(name: str, color: str, size: int = 16):
    if not qta:
        return None
    try:
        return qta.icon(name, color=color).pixmap(QSize(size, size))
    except Exception:
        return None


class _Chip(QLabel):
    def __init__(self, text: str, *, bg: str = "rgba(255,255,255,0.06)", fg: str = TEXT, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 8px;"
            f"padding: 3px 9px; font-size: 11px; font-weight: 500;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class _ModelCard(QFrame):
    def __init__(self, row: dict[str, Any], parent: "AIHubDialog"):
        super().__init__(parent)
        self._row = row
        self._dialog = parent
        self.setObjectName("AIHubModelCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build()

    def _build(self) -> None:
        meta = _meta_from_row(self._row)
        status = _status_from_row(self._row)
        status_code = str(status.get("code") or "unknown")
        installed = bool(status.get("installed")) or status_code in ("ready", "installed")

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        # left: title + description
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(4)

        title_text = str(meta.get("title") or meta.get("id") or "-")
        title = QLabel(title_text)
        title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {TEXT};")
        info.addWidget(title)

        description = str(meta.get("description") or "").strip()
        if not description:
            description = _("Локальный AI-компонент.", "Local AI component.")
        # Highlight first word in pink to mimic screenshot accent
        first, _sep, rest = description.partition(" ")
        if first and rest:
            desc_html = (
                f'<span style="color:{ACCENT}; font-weight:600;">{first}</span>'
                f'<span style="color:{MUTED};"> {rest}</span>'
            )
        else:
            desc_html = f'<span style="color:{MUTED};">{description}</span>'
        desc = QLabel(desc_html)
        desc.setTextFormat(Qt.TextFormat.RichText)
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 11.5px;")
        info.addWidget(desc)
        root.addLayout(info, 1)

        # chips
        chips_box = QHBoxLayout()
        chips_box.setContentsMargins(0, 0, 0, 0)
        chips_box.setSpacing(6)

        size = str(meta.get("size") or "").strip()
        vram = str(meta.get("vram") or meta.get("vram_range") or "").strip()
        if not vram and size:
            # fall back: rough VRAM hint from size if not provided
            vram = ""
        if vram:
            chips_box.addWidget(_Chip(f"VRAM {vram}", bg="rgba(255,255,255,0.05)", fg=DIM_TEXT))

        backend = str(meta.get("backend") or "").strip().lower()
        if backend == "cuda":
            chips_box.addWidget(_Chip("NVIDIA", bg="rgba(101,212,110,0.10)", fg="#7ee089"))
        elif backend == "cpu":
            chips_box.addWidget(_Chip("CPU", bg="rgba(255,255,255,0.05)", fg=DIM_TEXT))
        elif backend and backend != "none":
            chips_box.addWidget(_Chip(backend.upper(), bg="rgba(255,255,255,0.05)", fg=DIM_TEXT))

        langs = [str(x).upper() for x in (meta.get("languages") or []) if str(x).strip()]
        if langs:
            chips_box.addWidget(_Chip(" / ".join(langs), bg="rgba(255,255,255,0.05)", fg=DIM_TEXT))

        if size:
            chips_box.addWidget(_Chip(size, bg="rgba(255,255,255,0.05)", fg=MUTED))

        root.addLayout(chips_box, 0)

        # status pill (icon + label)
        status_box = QHBoxLayout()
        status_box.setContentsMargins(0, 0, 0, 0)
        status_box.setSpacing(6)
        icon_name, icon_color = _STATUS_ICONS.get(status_code, _STATUS_ICONS["unknown"])
        icon_lbl = QLabel()
        pix = _icon(icon_name, icon_color, 14)
        if pix is not None:
            icon_lbl.setPixmap(pix)
        else:
            icon_lbl.setText("●")
            icon_lbl.setStyleSheet(f"color: {icon_color};")
        status_box.addWidget(icon_lbl, 0)
        status_lbl = QLabel(_STATUS_LABELS.get(status_code, status_code))
        status_lbl.setStyleSheet(f"color: {icon_color}; font-size: 11.5px; font-weight: 600;")
        status_box.addWidget(status_lbl, 0)
        status_wrap = QWidget()
        status_wrap.setLayout(status_box)
        status_wrap.setMinimumWidth(120)
        root.addWidget(status_wrap, 0)

        # action button
        if installed:
            btn = QPushButton(_("Удалить", "Uninstall"))
            btn.setObjectName("AIHubCardDanger")
            btn.clicked.connect(self._uninstall)
        else:
            btn = QPushButton(_("Установить", "Install"))
            btn.setObjectName("AIHubCardPrimary")
            btn.clicked.connect(self._install)
        # leading icon
        if qta:
            try:
                if installed:
                    btn.setIcon(qta.icon("fa5s.trash-alt", color="#ffb4c5"))
                else:
                    btn.setIcon(qta.icon("fa5s.download", color="white"))
                btn.setIconSize(QSize(13, 13))
            except Exception:
                pass
        btn.setMinimumWidth(118)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(btn, 0)

    def _component_id(self) -> str:
        return str(_meta_from_row(self._row).get("id") or "").strip()

    def _install(self) -> None:
        cid = self._component_id()
        if cid:
            self._dialog._emit_component_action_by_id(cid, Events.Installable.INSTALL)

    def _uninstall(self) -> None:
        cid = self._component_id()
        if cid:
            self._dialog._emit_component_action_by_id(cid, Events.Installable.UNINSTALL)


class _CategoryButton(QFrame):
    def __init__(self, key: str, label: str, count: int, icon_name: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._selected = False
        self.setObjectName("AIHubCategoryButton")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(18, 18)
        pix = _icon(icon_name, MUTED, 16)
        if pix is not None:
            self._icon_lbl.setPixmap(pix)
        lay.addWidget(self._icon_lbl, 0)

        self._label_lbl = QLabel(label)
        self._label_lbl.setStyleSheet(f"color: {DIM_TEXT}; font-size: 12.5px; font-weight: 500;")
        lay.addWidget(self._label_lbl, 1)

        self._count_lbl = QLabel(str(count))
        self._count_lbl.setStyleSheet(
            f"color: {MUTED}; background: rgba(255,255,255,0.04);"
            f"padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 600;"
        )
        lay.addWidget(self._count_lbl, 0)

        self._icon_name = icon_name
        self._apply_style()

    def setCount(self, count: int) -> None:
        self._count_lbl.setText(str(count))

    def setSelected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()
        color = ACCENT if selected else MUTED
        pix = _icon(self._icon_name, color, 16)
        if pix is not None:
            self._icon_lbl.setPixmap(pix)
        self._label_lbl.setStyleSheet(
            f"color: {TEXT if selected else DIM_TEXT}; font-size: 12.5px; font-weight: {'600' if selected else '500'};"
        )

    def _apply_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                "#AIHubCategoryButton {"
                f"background: rgba(236,72,153,0.10); border: 1px solid rgba(236,72,153,0.32);"
                "border-radius: 10px;"
                "}"
            )
        else:
            self.setStyleSheet(
                "#AIHubCategoryButton {"
                "background: transparent; border: 1px solid transparent; border-radius: 10px;"
                "}"
                "#AIHubCategoryButton:hover {"
                "background: rgba(255,255,255,0.04);"
                "}"
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            parent = self.parent()
            while parent and not isinstance(parent, AIHubDialog):
                parent = parent.parent()
            if isinstance(parent, AIHubDialog):
                parent._select_category(self.key)
        super().mousePressEvent(event)


class _Stat(QFrame):
    def __init__(self, icon_name: str, value: str, label: str, subline: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("AIHubStat")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#AIHubStat {"
            f"background: {CARD_BG}; border: 1px solid {BORDER};"
            "border-radius: 12px;"
            "}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setStyleSheet(
            "background: rgba(236,72,153,0.10); border-radius: 8px;"
        )
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = _icon(icon_name, ACCENT, 16)
        if pix is not None:
            icon_lbl.setPixmap(pix)
        lay.addWidget(icon_lbl, 0)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(0)

        top = QLabel(label)
        top.setStyleSheet(f"color: {MUTED}; font-size: 10.5px; font-weight: 500;")
        text_box.addWidget(top)

        self._value_lbl = QLabel(value)
        self._value_lbl.setStyleSheet(f"color: {TEXT}; font-size: 15px; font-weight: 700;")
        text_box.addWidget(self._value_lbl)

        self._subline_lbl = QLabel(subline)
        self._subline_lbl.setStyleSheet(f"color: {MUTED}; font-size: 10.5px;")
        self._subline_lbl.setVisible(bool(subline))
        text_box.addWidget(self._subline_lbl)

        lay.addLayout(text_box, 1)

    def setValue(self, value: str, subline: str = "") -> None:
        self._value_lbl.setText(value)
        self._subline_lbl.setText(subline)
        self._subline_lbl.setVisible(bool(subline))


class AIHubDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.event_bus = get_event_bus()
        self._rows: list[dict[str, Any]] = []
        self._selected_category = "tts"
        self._pending_category: str | None = None
        self._pending_component_id: str | None = None
        self._last_task_status = ""
        self._loaded_once = False
        self._last_check_ts: _dt.datetime | None = None
        self._category_buttons: dict[str, _CategoryButton] = {}
        self._drag_offset: QPoint | None = None
        self._build()
        self._bind_events()
        QTimer.singleShot(0, lambda: self.refresh(force=True))

    # ----- build UI -----
    def _build(self) -> None:
        self.setObjectName("AIHubDialog")
        self.setWindowTitle(_("AI Hub", "AI Hub"))
        self.setModal(False)
        self.resize(1280, 820)
        self.setMinimumSize(1100, 700)
        # Frameless rounded modal
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(self._stylesheet())

        # outer wrapper holds the rounded card so the shadow doesn't bleed
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        self._card = QFrame()
        self._card.setObjectName("AIHubRoot")
        outer.addWidget(self._card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self._card.setGraphicsEffect(shadow)

        root = QVBoxLayout(self._card)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(18)

        root.addLayout(self._build_header())
        root.addLayout(self._build_body(), 1)
        root.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)

        icon_badge = QLabel()
        icon_badge.setFixedSize(48, 48)
        icon_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_badge.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(236,72,153,0.22), stop:1 rgba(124,58,237,0.18));"
            f"border-radius: 12px; border: 1px solid rgba(236,72,153,0.25);"
        )
        pix = _icon("fa5s.magic", ACCENT, 22)
        if pix is not None:
            icon_badge.setPixmap(pix)
        else:
            icon_badge.setText("✦")
        header.addWidget(icon_badge, 0)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        title = QLabel(_("AI Hub", "AI Hub"))
        title.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: 800;")
        title_box.addWidget(title)
        subtitle = QLabel(
            _("Установка, удаление и обслуживание локальных AI-моделей и системных зависимостей.",
              "Install, remove and maintain local AI models and system dependencies.")
        )
        subtitle.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        close_btn = QPushButton()
        close_btn.setObjectName("AIHubClose")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if qta:
            try:
                close_btn.setIcon(qta.icon("fa5s.times", color=MUTED))
                close_btn.setIconSize(QSize(14, 14))
            except Exception:
                close_btn.setText("×")
        else:
            close_btn.setText("×")
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        # sidebar
        sidebar = QFrame()
        sidebar.setObjectName("AIHubSidebar")
        sidebar.setFixedWidth(260)
        sb_l = QVBoxLayout(sidebar)
        sb_l.setContentsMargins(14, 16, 14, 14)
        sb_l.setSpacing(8)

        cat_header = QLabel(_("КАТЕГОРИИ", "CATEGORIES"))
        cat_header.setStyleSheet(
            f"color: {MUTED}; font-size: 10.5px; font-weight: 700; letter-spacing: 1.4px;"
            "padding: 2px 4px;"
        )
        sb_l.addWidget(cat_header)

        for key in _CATEGORY_ORDER:
            btn = _CategoryButton(
                key,
                _CATEGORY_LABELS.get(key, key),
                0,
                _CATEGORY_ICONS.get(key, "fa5s.circle"),
                sidebar,
            )
            self._category_buttons[key] = btn
            sb_l.addWidget(btn, 0)

        sb_l.addSpacing(14)

        qa_header = QLabel(_("БЫСТРОЕ ДЕЙСТВИЕ", "QUICK ACTION"))
        qa_header.setStyleSheet(
            f"color: {MUTED}; font-size: 10.5px; font-weight: 700; letter-spacing: 1.4px;"
            "padding: 2px 4px;"
        )
        sb_l.addWidget(qa_header)

        self.btn_refresh = QPushButton(_("Проверить обновления", "Check for updates"))
        self.btn_refresh.setObjectName("AIHubSidebarBtn")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        if qta:
            try:
                self.btn_refresh.setIcon(qta.icon("fa5s.sync", color=DIM_TEXT))
                self.btn_refresh.setIconSize(QSize(13, 13))
            except Exception:
                pass
        self.btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        sb_l.addWidget(self.btn_refresh)

        self.last_check_label = QLabel("")
        self.last_check_label.setStyleSheet(f"color: {MUTED}; font-size: 10.5px; padding: 4px;")
        self.last_check_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_l.addWidget(self.last_check_label)

        sb_l.addStretch(1)

        # hint card
        hint = QFrame()
        hint.setObjectName("AIHubHint")
        hint_l = QVBoxLayout(hint)
        hint_l.setContentsMargins(14, 12, 14, 12)
        hint_l.setSpacing(6)
        hint_title = QLabel(_("Подсказка", "Tip"))
        hint_title.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: 700;")
        hint_l.addWidget(hint_title)
        hint_text = QLabel(
            _("Модели работают локально на вашем устройстве. Чем выше требования — тем быстрее отклик.",
              "Models run locally on your device. The higher the requirements, the faster the response.")
        )
        hint_text.setWordWrap(True)
        hint_text.setStyleSheet(f"color: {DIM_TEXT}; font-size: 11px;")
        hint_l.addWidget(hint_text)
        sb_l.addWidget(hint)

        body.addWidget(sidebar, 0)

        # main column
        main_col = QVBoxLayout()
        main_col.setContentsMargins(0, 0, 0, 0)
        main_col.setSpacing(14)

        # banner
        self.banner = QFrame()
        self.banner.setObjectName("AIHubBanner")
        self.banner.setVisible(False)
        banner_l = QHBoxLayout(self.banner)
        banner_l.setContentsMargins(18, 14, 18, 14)
        banner_l.setSpacing(14)

        b_icon = QLabel()
        b_icon.setFixedSize(46, 46)
        b_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_icon.setStyleSheet(
            "background: rgba(236,72,153,0.16); border-radius: 10px;"
        )
        bpix = _icon("fa5s.microchip", ACCENT, 22)
        if bpix is not None:
            b_icon.setPixmap(bpix)
        banner_l.addWidget(b_icon, 0)

        banner_text_box = QVBoxLayout()
        banner_text_box.setContentsMargins(0, 0, 0, 0)
        banner_text_box.setSpacing(2)
        self.banner_title = QLabel("")
        self.banner_title.setTextFormat(Qt.TextFormat.RichText)
        self.banner_title.setStyleSheet("font-size: 13.5px; font-weight: 700;")
        banner_text_box.addWidget(self.banner_title)
        self.banner_body = QLabel("")
        self.banner_body.setWordWrap(True)
        self.banner_body.setStyleSheet(f"color: {DIM_TEXT}; font-size: 11.5px;")
        banner_text_box.addWidget(self.banner_body)
        banner_l.addLayout(banner_text_box, 1)

        self.banner_button = QPushButton(_("Оптимизировать", "Optimize"))
        self.banner_button.setObjectName("AIHubPrimary")
        self.banner_button.setCursor(Qt.CursorShape.PointingHandCursor)
        if qta:
            try:
                self.banner_button.setIcon(qta.icon("fa5s.bolt", color="white"))
                self.banner_button.setIconSize(QSize(13, 13))
            except Exception:
                pass
        self.banner_button.clicked.connect(self._install_cuda_backend)
        banner_l.addWidget(self.banner_button, 0)

        self.banner_dismiss = QPushButton(_("Позже", "Later"))
        self.banner_dismiss.setObjectName("AIHubSecondary")
        self.banner_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self.banner_dismiss.clicked.connect(lambda: self.banner.setVisible(False))
        banner_l.addWidget(self.banner_dismiss, 0)

        main_col.addWidget(self.banner)

        # toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(10)

        toolbar_title = QLabel(_("Доступные модели", "Available models"))
        toolbar_title.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        toolbar.addWidget(toolbar_title, 0)

        info_icon = QLabel()
        info_icon.setFixedSize(16, 16)
        ipix = _icon("fa5s.info-circle", MUTED, 13)
        if ipix is not None:
            info_icon.setPixmap(ipix)
        info_icon.setToolTip(
            _("Локальные модели расходуют диск и видеопамять. Используйте поиск и сортировку.",
              "Local models use disk and VRAM. Use search and sorting.")
        )
        toolbar.addWidget(info_icon, 0)
        toolbar.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("AIHubSearch")
        self.search_box.setPlaceholderText(_("Поиск моделей...", "Search models..."))
        self.search_box.setFixedWidth(280)
        if qta:
            try:
                # use addAction to put a leading icon
                from PyQt6.QtWidgets import QLineEdit as _QLE  # noqa: F401
                action = self.search_box.addAction(
                    qta.icon("fa5s.search", color=MUTED),
                    QLineEdit.ActionPosition.TrailingPosition,
                )
                action.setEnabled(False)
            except Exception:
                pass
        self.search_box.textChanged.connect(self._rebuild_component_list)
        toolbar.addWidget(self.search_box, 0)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("AIHubSort")
        self.sort_combo.setFixedWidth(220)
        self.sort_combo.addItem(_("Сортировка: по умолчанию", "Sort: default"), "default")
        self.sort_combo.addItem(_("Сортировка: установленные", "Sort: installed first"), "installed")
        self.sort_combo.addItem(_("Сортировка: по имени", "Sort: by name"), "name")
        self.sort_combo.currentIndexChanged.connect(self._rebuild_component_list)
        toolbar.addWidget(self.sort_combo, 0)

        main_col.addLayout(toolbar)

        # component scroll
        self.component_list = QListWidget()
        self.component_list.setObjectName("AIHubComponentList")
        self.component_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.component_list.setSpacing(8)
        self.component_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.component_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_col.addWidget(self.component_list, 1)

        body.addLayout(main_col, 1)
        return body

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)

        self.stat_installed = _Stat("fa5s.download", "0", _("Установлено", "Installed"), _("моделей", "models"))
        self.stat_updates = _Stat("fa5s.sync", "0", _("Доступно обновлений", "Updates available"), _("моделей", "models"))
        self.stat_disk = _Stat("fa5s.hdd", "-", _("Свободно на диске", "Free disk space"), "")
        self.stat_check = _Stat("fa5s.clock", "-", _("Последняя проверка", "Last check"), "")

        footer.addWidget(self.stat_installed, 1)
        footer.addWidget(self.stat_updates, 1)
        footer.addWidget(self.stat_disk, 1)
        footer.addWidget(self.stat_check, 1)
        footer.addStretch(0)

        self.btn_close = QPushButton(_("Закрыть", "Close"))
        self.btn_close.setObjectName("AIHubSecondary")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setMinimumWidth(120)
        self.btn_close.clicked.connect(self.close)
        footer.addWidget(self.btn_close, 0)

        self.btn_apply = QPushButton(_("Применить изменения", "Apply changes"))
        self.btn_apply.setObjectName("AIHubPrimary")
        self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setMinimumWidth(180)
        self.btn_apply.clicked.connect(lambda: self.refresh(force=True))
        footer.addWidget(self.btn_apply, 0)

        return footer

    def _stylesheet(self) -> str:
        return f"""
            QDialog#AIHubDialog {{
                background: transparent;
            }}
            QFrame#AIHubRoot {{
                background: {DIALOG_BG};
                border: 1px solid {BORDER_STRONG};
                border-radius: 18px;
            }}
            QFrame#AIHubSidebar {{
                background: {SIDEBAR_BG};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
            QFrame#AIHubBanner {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 rgba(236,72,153,0.14), stop:1 rgba(124,58,237,0.10));
                border: 1px solid rgba(236,72,153,0.28);
                border-radius: 14px;
            }}
            QFrame#AIHubHint {{
                background: {CARD_BG};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            QFrame#AIHubModelCard {{
                background: {CARD_BG};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
            QFrame#AIHubModelCard:hover {{
                background: {CARD_BG_HOVER};
                border: 1px solid {BORDER_STRONG};
            }}
            QListWidget#AIHubComponentList {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QListWidget#AIHubComponentList::item {{
                border: none;
                background: transparent;
                padding: 0;
                margin: 0;
            }}
            QListWidget#AIHubComponentList::item:hover {{
                background: transparent;
            }}
            QListWidget#AIHubComponentList QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 4px 0;
            }}
            QListWidget#AIHubComponentList QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.10);
                border-radius: 4px;
                min-height: 24px;
            }}
            QListWidget#AIHubComponentList QScrollBar::add-line:vertical,
            QListWidget#AIHubComponentList QScrollBar::sub-line:vertical {{
                height: 0;
            }}

            QLineEdit#AIHubSearch {{
                background: {PANEL_BG};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 7px 12px;
                font-size: 12px;
            }}
            QLineEdit#AIHubSearch:focus {{
                border: 1px solid rgba(236,72,153,0.45);
            }}
            QComboBox#AIHubSort {{
                background: {PANEL_BG};
                color: {DIM_TEXT};
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 7px 12px;
                font-size: 12px;
            }}
            QComboBox#AIHubSort::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox#AIHubSort QAbstractItemView {{
                background: {PANEL_BG};
                color: {TEXT};
                selection-background-color: rgba(236,72,153,0.18);
                border: 1px solid {BORDER};
                outline: none;
            }}

            QPushButton#AIHubPrimary {{
                background: {ACCENT};
                color: white;
                border: none;
                border-radius: 10px;
                padding: 9px 18px;
                font-weight: 700;
                font-size: 12.5px;
            }}
            QPushButton#AIHubPrimary:hover {{
                background: {ACCENT_HOVER};
            }}
            QPushButton#AIHubPrimary:disabled {{
                background: {ACCENT_DIM};
                color: #f0d6e0;
            }}
            QPushButton#AIHubSecondary {{
                background: {PANEL_BG};
                color: {DIM_TEXT};
                border: 1px solid {BORDER_STRONG};
                border-radius: 10px;
                padding: 9px 18px;
                font-weight: 600;
                font-size: 12.5px;
            }}
            QPushButton#AIHubSecondary:hover {{
                background: #221d33;
                color: {TEXT};
            }}
            QPushButton#AIHubSidebarBtn {{
                background: {PANEL_BG};
                color: {DIM_TEXT};
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: 600;
                font-size: 12px;
                text-align: left;
            }}
            QPushButton#AIHubSidebarBtn:hover {{
                background: #221d33;
                color: {TEXT};
                border: 1px solid {BORDER_STRONG};
            }}
            QPushButton#AIHubClose {{
                background: rgba(255,255,255,0.04);
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            QPushButton#AIHubClose:hover {{
                background: rgba(255,123,123,0.12);
                border: 1px solid rgba(255,123,123,0.3);
            }}

            QPushButton#AIHubCardPrimary {{
                background: {ACCENT};
                color: white;
                border: none;
                border-radius: 9px;
                padding: 7px 14px;
                font-weight: 700;
                font-size: 12px;
            }}
            QPushButton#AIHubCardPrimary:hover {{
                background: {ACCENT_HOVER};
            }}
            QPushButton#AIHubCardDanger {{
                background: rgba(255,123,123,0.08);
                color: #ffb4c5;
                border: 1px solid rgba(255,123,123,0.22);
                border-radius: 9px;
                padding: 7px 14px;
                font-weight: 700;
                font-size: 12px;
            }}
            QPushButton#AIHubCardDanger:hover {{
                background: rgba(255,123,123,0.16);
            }}
        """

    # ----- window drag for frameless -----
    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            # only allow drag from top header strip
            if event.position().y() < 80:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # ----- events -----
    def _bind_events(self) -> None:
        self.event_bus.subscribe(Events.Install.TASK_STARTED, self._on_install_started, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)

    def apply_payload(self, payload: dict[str, Any] | None) -> None:
        data = payload if isinstance(payload, dict) else {}
        category = str(data.get("category") or "").strip().lower()
        category = _ROW_CATEGORY_MAP.get(category, category)
        component_id = str(data.get("component_id") or "").strip()
        if category:
            self._pending_category = category
        if component_id:
            self._pending_component_id = component_id
        if self._loaded_once and self._rows:
            self._rebuild_category_list()
            self._rebuild_component_list()
            self._update_summary()
        else:
            self.refresh(force=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded_once:
            QTimer.singleShot(0, lambda: self.refresh(force=True))

    def refresh(self, *, force: bool = False) -> None:
        self._rows = self._fetch_rows(force=force)
        self._loaded_once = True
        self._last_check_ts = _dt.datetime.now()
        self._rebuild_category_list()
        self._update_banner()
        self._rebuild_component_list()
        self._update_summary()

    def _fetch_rows(self, *, force: bool = False) -> list[dict[str, Any]]:
        try:
            result = self.event_bus.emit_and_wait(
                Events.Installable.LIST,
                {"include_status": True, "refresh": bool(force)},
                timeout=5.0,
            )
            rows = result[0] if result and isinstance(result[0], list) else []
            return [row for row in rows if isinstance(row, dict)]
        except Exception as exc:
            logger.error(f"AI Hub refresh failed: {exc}", exc_info=True)
            return []

    def _rebuild_category_list(self) -> None:
        counts = {key: 0 for key in _CATEGORY_ORDER}
        for row in self._rows:
            cat = _row_category(row)
            if cat in counts:
                counts[cat] += 1

        selected = self._pending_category or self._selected_category or "tts"
        if selected not in _CATEGORY_ORDER:
            selected = "tts"

        for key, btn in self._category_buttons.items():
            btn.setCount(counts.get(key, 0))
            btn.setSelected(key == selected)

        self._selected_category = selected
        self._pending_category = None

    def _select_category(self, key: str) -> None:
        if key not in _CATEGORY_ORDER:
            return
        self._selected_category = key
        for k, btn in self._category_buttons.items():
            btn.setSelected(k == key)
        self._rebuild_component_list()
        self._update_summary()

    def _filtered_rows(self) -> list[dict[str, Any]]:
        query = str(self.search_box.text() or "").strip().lower()
        category = self._selected_category
        rows: list[dict[str, Any]] = []
        for row in self._rows:
            meta = _meta_from_row(row)
            status = _status_from_row(row)
            if category and _row_category(row) != category:
                continue
            haystack = " ".join(
                [
                    str(meta.get("id") or ""),
                    str(meta.get("title") or ""),
                    str(meta.get("description") or ""),
                    str(meta.get("backend") or ""),
                    " ".join(str(x) for x in (meta.get("tags") or [])),
                    " ".join(str(x) for x in (meta.get("languages") or [])),
                    str(status.get("message") or ""),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            rows.append(row)

        sort_mode = str(self.sort_combo.currentData() or "default")
        if sort_mode == "installed":
            rows.sort(
                key=lambda row: (
                    0 if _status_from_row(row).get("installed") else 1,
                    str(_meta_from_row(row).get("title") or ""),
                )
            )
        elif sort_mode == "name":
            rows.sort(key=lambda row: str(_meta_from_row(row).get("title") or ""))
        return rows

    def _rebuild_component_list(self) -> None:
        rows = self._filtered_rows()
        self.component_list.clear()
        for row in rows:
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            card = _ModelCard(row, self)
            item.setSizeHint(QSize(0, card.sizeHint().height() + 8))
            self.component_list.addItem(item)
            self.component_list.setItemWidget(item, card)

        if not self.component_list.count():
            placeholder = QListWidgetItem()
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            empty = QLabel(_("Ничего не найдено по выбранным критериям.",
                             "No components match the current filters."))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {MUTED}; padding: 32px 0; font-size: 12.5px;")
            placeholder.setSizeHint(QSize(0, 80))
            self.component_list.addItem(placeholder)
            self.component_list.setItemWidget(placeholder, empty)

    def _emit_component_action_by_id(self, component_id: str, event_name: str) -> None:
        self.event_bus.emit(
            event_name,
            {
                "component_id": component_id,
                "with_ui": True,
                "meta": {"source": "ai_hub"},
            },
        )
        self._last_task_status = _("Запуск задачи...", "Starting task...")
        self._update_summary()

    def _update_summary(self) -> None:
        installed = sum(1 for row in self._rows if _status_from_row(row).get("installed"))
        # treat "needs_update" status code (if present) as update available
        updates = 0
        for row in self._rows:
            st = _status_from_row(row)
            code = str(st.get("code") or "")
            if code == "needs_update" or st.get("update_available"):
                updates += 1
        self.stat_installed.setValue(str(installed), _("моделей", "models"))
        self.stat_updates.setValue(str(updates), _("моделей", "models"))

        try:
            usage = shutil.disk_usage(os.path.abspath(os.sep))
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            self.stat_disk.setValue(
                _("{free:.1f} GB", "{free:.1f} GB").format(free=free_gb),
                _("из {total:.0f} GB", "of {total:.0f} GB").format(total=total_gb),
            )
        except Exception:
            self.stat_disk.setValue("-", "")

        if self._last_check_ts is not None:
            now = _dt.datetime.now()
            delta = now - self._last_check_ts
            mins = max(0, int(delta.total_seconds() // 60))
            if mins <= 0:
                ago = _("только что", "just now")
            elif mins < 60:
                ago = _("{n} мин. назад", "{n} min ago").format(n=mins)
            else:
                hours = mins // 60
                ago = _("{n} ч. назад", "{n} h ago").format(n=hours)
            self.stat_check.setValue(ago, self._last_check_ts.strftime("%d.%m.%Y %H:%M"))
            self.last_check_label.setText(_("Последняя проверка: {ago}", "Last check: {ago}").format(ago=ago))
        else:
            self.stat_check.setValue("-", "")
            self.last_check_label.setText("")

    def _update_banner(self) -> None:
        gpu_vendor = "CPU"
        try:
            gpu_vendor = str(check_gpu_provider() or "CPU").upper()
        except Exception:
            gpu_vendor = "CPU"

        row_cpu = self._row_by_id("backend:cpu")
        row_cuda = self._row_by_id("backend:cuda")
        cpu_ready = bool(_status_from_row(row_cpu or {}).get("ready"))
        cuda_ready = bool(_status_from_row(row_cuda or {}).get("ready"))

        show = gpu_vendor == "NVIDIA" and cpu_ready and not cuda_ready
        self.banner.setVisible(show)
        if show:
            self.banner_title.setText(
                _(
                    f"Обнаружена видеокарта <span style='color:{ACCENT};'>NVIDIA</span>, "
                    f"но установлен <span style='color:{ACCENT};'>CPU-бэкенд</span>",
                    f"Detected <span style='color:{ACCENT};'>NVIDIA</span> GPU, "
                    f"but the <span style='color:{ACCENT};'>CPU backend</span> is active",
                )
            )
            self.banner_body.setText(
                _("Можно скачать оптимизированную CUDA-версию (~3 GB), чтобы значительно ускорить работу.",
                  "You can download the optimized CUDA version (~3 GB) to significantly speed things up.")
            )

    def _install_cuda_backend(self) -> None:
        self._pending_category = "backend"
        self._pending_component_id = "backend:cuda"
        self._emit_component_action_by_id("backend:cuda", Events.Installable.INSTALL)

    def _row_by_id(self, component_id: str) -> dict[str, Any] | None:
        for row in self._rows:
            if str(_meta_from_row(row).get("id") or "") == component_id:
                return row
        return None

    def _is_installable_task(self, event) -> bool:
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta.get("category") in _CATEGORY_ORDER or meta.get("category") in _ROW_CATEGORY_MAP:
            return True
        component_id = str(meta.get("component_id") or data.get("component_id") or "")
        return ":" in component_id

    def _on_install_started(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        self._last_task_status = str(data.get("status") or _("Подготовка...", "Preparing..."))
        self.last_check_label.setText(self._last_task_status)

    def _on_install_progress(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        status = str(data.get("status") or "").strip()
        progress = data.get("progress")
        if status:
            self._last_task_status = f"{status} ({progress}%)" if progress is not None else status
            self.last_check_label.setText(self._last_task_status)

    def _on_install_finished(self, event) -> None:
        if not self._is_installable_task(event):
            return
        self._last_task_status = _("Готово", "Done")
        self.last_check_label.setText(self._last_task_status)
        QTimer.singleShot(250, lambda: self.refresh(force=True))

    def _on_install_failed(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        error = str(data.get("error") or _("Ошибка установки", "Install failed"))
        self._last_task_status = error
        self.last_check_label.setText(error)
        QTimer.singleShot(250, lambda: self.refresh(force=True))
