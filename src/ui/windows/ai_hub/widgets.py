from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from .helpers import qpixmap


class Chip(QLabel):
    """Inline tag chip. Hugs its content; no vertical stretching."""

    _MAX_LANG_TAGS = 3  # show individual flags up to this count; collapse beyond

    def __init__(self, text: str, *, variant: str = "default", tooltip: str = "", parent=None):
        super().__init__(text, parent)
        if variant == "backend":
            self.setObjectName("AIHubChipBackend")
        elif variant == "gpu_ok":
            self.setObjectName("AIHubChipGpuOk")
        elif variant == "multilingual":
            self.setObjectName("AIHubChipMulti")
        else:
            self.setObjectName("AIHubChip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        if tooltip:
            self.setToolTip(tooltip)

    @classmethod
    def for_languages(cls, langs: list[str], parent=None) -> "Chip | None":
        """Build either a compact 'EN/RU' chip or a 'Multilingual N' chip
        with the full list in the tooltip."""
        langs = [str(x).strip().upper() for x in (langs or []) if str(x).strip()]
        if not langs:
            return None
        if len(langs) <= cls._MAX_LANG_TAGS:
            return cls(" / ".join(langs), parent=parent)
        from utils import getTranslationVariant as t
        label = t("Multilingual {n}", "Multilingual {n}").format(n=len(langs))
        return cls(label, variant="multilingual", tooltip=", ".join(langs), parent=parent)


class CategoryButton(QFrame):
    """Sidebar entry: icon + label + counter pill. Click triggers callback."""

    def __init__(
        self,
        key: str,
        label: str,
        icon_name: str,
        on_click: Callable[[str], None],
        parent=None,
    ):
        super().__init__(parent)
        self.key = key
        self._icon_name = icon_name
        self._on_click = on_click
        self._selected = False

        self.setObjectName("AIHubCategoryButton")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(18, 18)
        self._set_icon("#bca9bb")
        lay.addWidget(self._icon_lbl, 0)

        self._label_lbl = QLabel(label)
        self._label_lbl.setObjectName("AIHubCategoryLabel")
        lay.addWidget(self._label_lbl, 1)

        self._count_lbl = QLabel("0")
        self._count_lbl.setObjectName("AIHubCategoryCount")
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._count_lbl, 0)

    def setCount(self, count: int) -> None:
        self._count_lbl.setText(str(count))

    def setSelected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        # restyle on property change
        self.style().unpolish(self)
        self.style().polish(self)
        self._set_icon("#db6596" if selected else "#bca9bb")

    def _set_icon(self, color: str) -> None:
        pix = qpixmap(self._icon_name, color, 16)
        if pix is not None:
            self._icon_lbl.setPixmap(pix)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click(self.key)
        super().mousePressEvent(event)


class Stat(QFrame):
    """Footer stat tile: icon badge + label + value (+ optional subline)."""

    def __init__(self, icon_name: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("AIHubStat")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        icon_box = QLabel()
        icon_box.setObjectName("AIHubStatIcon")
        icon_box.setFixedSize(32, 32)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = qpixmap(icon_name, "#db6596", 16)
        if pix is not None:
            icon_box.setPixmap(pix)
        lay.addWidget(icon_box, 0)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self._label_lbl = QLabel(label)
        self._label_lbl.setObjectName("AIHubStatLabel")
        col.addWidget(self._label_lbl)

        self._value_lbl = QLabel("-")
        self._value_lbl.setObjectName("AIHubStatValue")
        col.addWidget(self._value_lbl)

        self._sub_lbl = QLabel("")
        self._sub_lbl.setObjectName("AIHubStatSub")
        self._sub_lbl.setVisible(False)
        col.addWidget(self._sub_lbl)

        lay.addLayout(col, 1)

    def setValue(self, value: str, subline: str = "") -> None:
        self._value_lbl.setText(value)
        self._sub_lbl.setText(subline)
        self._sub_lbl.setVisible(bool(subline))


class ModelCard(QFrame):
    """Single model row: title + description on the left,
    meta chips in the middle, status + action button on the right."""

    def __init__(
        self,
        row: dict[str, Any],
        on_install: Callable[[str], None],
        on_uninstall: Callable[[str], None],
        parent=None,
    ):
        super().__init__(parent)
        self._row = row
        self._on_install = on_install
        self._on_uninstall = on_uninstall
        self.setObjectName("AIHubModelCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build()

    # Keep build pieces small; widgets get all their style from QSS.
    def _build(self) -> None:
        from .constants import STATUS_LABELS, STATUS_ICONS
        from .helpers import meta_from_row, status_from_row

        meta = meta_from_row(self._row)
        status = status_from_row(self._row)
        status_code = str(status.get("code") or "unknown")
        installed = bool(status.get("installed")) or status_code in ("ready", "installed")

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(14)

        # ---- left: title + description (40% of width)
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(4)

        title = QLabel(str(meta.get("title") or meta.get("id") or "-"))
        title.setObjectName("AIHubCardTitle")
        info_col.addWidget(title)

        description = str(meta.get("description") or "").strip()
        if not description:
            description = ""
        desc = QLabel(description)
        desc.setObjectName("AIHubCardDesc")
        desc.setWordWrap(True)
        info_col.addWidget(desc)
        info_col.addStretch(1)

        info_wrap = QFrame()
        info_wrap.setLayout(info_col)
        info_wrap.setMinimumWidth(220)
        root.addWidget(info_wrap, 3)

        # ---- middle: chips (auto width, hugged)
        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.setSpacing(6)
        chips_row.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        vram = str(meta.get("vram") or meta.get("vram_range") or "").strip()
        if vram:
            chips_row.addWidget(Chip(f"VRAM {vram}"))

        backend = str(meta.get("backend") or "").strip().lower()
        if backend == "cuda":
            chips_row.addWidget(Chip("NVIDIA", variant="gpu_ok"))
        elif backend == "cpu":
            chips_row.addWidget(Chip("CPU"))
        elif backend and backend != "none":
            chips_row.addWidget(Chip(backend.upper(), variant="backend"))

        lang_chip = Chip.for_languages(meta.get("languages") or [])
        if lang_chip is not None:
            chips_row.addWidget(lang_chip)

        size = str(meta.get("size") or "").strip()
        if size:
            chips_row.addWidget(Chip(size))

        chips_wrap = QFrame()
        chips_wrap.setLayout(chips_row)
        chips_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(chips_wrap, 4)

        # ---- right: tiny circular status indicator (no duplicate label;
        # button text already conveys installed/not installed semantics)
        from .constants import STATUS_LABELS as _SL
        icon_name, icon_color = STATUS_ICONS.get(status_code, STATUS_ICONS["unknown"])
        dot = QLabel()
        dot.setFixedSize(18, 18)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = qpixmap(icon_name, icon_color, 14)
        if pix is not None:
            dot.setPixmap(pix)
        else:
            dot.setText("●")
            dot.setStyleSheet(f"color: {icon_color};")
        dot.setToolTip(_SL.get(status_code, status_code))
        root.addWidget(dot, 0)

        # ---- right: action button
        from PyQt6.QtWidgets import QPushButton
        from .helpers import qicon

        if installed:
            btn = QPushButton(self._txt_uninstall())
            btn.setObjectName("AIHubCardDanger")
            icon = qicon("fa5s.trash-alt", "#ffb4c5")
            btn.clicked.connect(self._handle_uninstall)
        else:
            btn = QPushButton(self._txt_install())
            btn.setObjectName("AIHubCardPrimary")
            icon = qicon("fa5s.download", "white")
            btn.clicked.connect(self._handle_install)
        if icon is not None:
            btn.setIcon(icon)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(btn, 0)

    # translations kept local — avoid clobbering `_` in this scope
    @staticmethod
    def _txt_install() -> str:
        from utils import getTranslationVariant as t
        return t("Установить", "Install")

    @staticmethod
    def _txt_uninstall() -> str:
        from utils import getTranslationVariant as t
        return t("Удалить", "Uninstall")

    def _component_id(self) -> str:
        from .helpers import meta_from_row
        return str(meta_from_row(self._row).get("id") or "").strip()

    def _handle_install(self) -> None:
        cid = self._component_id()
        if cid:
            self._on_install(cid)

    def _handle_uninstall(self) -> None:
        cid = self._component_id()
        if cid:
            self._on_uninstall(cid)
