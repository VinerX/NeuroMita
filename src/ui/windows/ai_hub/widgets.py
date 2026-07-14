from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
)

from utils import getTranslationVariant as _t

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
        elif variant == "onnx":
            self.setObjectName("AIHubChipOnnx")
        elif variant == "not_recommended":
            self.setObjectName("AIHubChipNotRecommended")
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

    def setLabel(self, label: str) -> None:
        self._label_lbl.setText(str(label or ""))

    def setCount(self, count: int) -> None:
        self._count_lbl.setText(str(count))
        # Поясняем, что цифра — это число компонентов в категории, а не «индикатор»
        # чего-то срочного (фидбэк #22: путались, почему «светится» только у TTS).
        tip = _t("Доступно компонентов: {n}", "Components available: {n}").format(n=count)
        self._count_lbl.setToolTip(tip)
        self.setToolTip(tip)

    def setSelected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        # restyle on property change
        self.style().unpolish(self)
        self.style().polish(self)
        self._set_icon("#b74b7d" if selected else "#bca9bb")

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
        pix = qpixmap(icon_name, "#b74b7d", 16)
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

    def setLabel(self, label: str) -> None:
        self._label_lbl.setText(str(label or ""))


class ModelCard(QFrame):
    """Single model row.

    Layout:
        [title + description]  [meta chips]  [status]  [action]

    Status / action change depending on state:
      - installed     → green "Установлено" + ⋮ menu (Settings / Uninstall)
      - not installed → status icon + Install button
      - incompatible  → grey-out + red "Несовместимо" chip; the action button
                        is disabled
    """

    def __init__(
        self,
        row: dict[str, Any],
        on_install: Callable[[str], None],
        on_uninstall: Callable[[str], None],
        on_open_settings: Callable[[str], None],
        parent=None,
        on_reinstall: Callable[[str], None] | None = None,
    ):
        super().__init__(parent)
        self._row = row
        self._on_install = on_install
        self._on_uninstall = on_uninstall
        self._on_open_settings = on_open_settings
        self._on_reinstall = on_reinstall
        self._install_btn = None
        self._install_btn_text = ""
        self._menu_btn = None
        self._compatible = True
        self.setObjectName("AIHubModelCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        from .constants import STATUS_ICONS, status_label
        from .helpers import (
            meta_from_row,
            status_from_row,
        )

        meta = meta_from_row(self._row)
        status = status_from_row(self._row)
        status_code = str(status.get("code") or "unknown")
        installed = bool(status.get("ready")) or status_code == "ready"
        details = status.get("details") if isinstance(status.get("details"), dict) else {}
        update_available = installed and bool(details.get("update_available"))
        compatibility = self._row.get("compatibility")
        compatibility = compatibility if isinstance(compatibility, dict) else {}
        compatible = bool(compatibility.get("supported", False))
        not_recommended = compatible and not bool(compatibility.get("recommended", False))
        compatibility_warning = str(compatibility.get("warning") or "").strip()
        backend = str(compatibility.get("backend") or meta.get("backend") or "none").lower()
        self._compatible = compatible

        # mark whole card visually as incompatible (drives QSS via property)
        self.setProperty("incompatible", "true" if (not compatible and not installed) else "false")
        # also expose 'state' for any future styling
        if installed:
            self.setProperty("state", "installed")
        elif not compatible:
            self.setProperty("state", "incompatible")
        else:
            self.setProperty("state", "available")

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(14)

        # ---- left: title + description
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title = QLabel(str(meta.get("title") or meta.get("id") or "-"))
        title.setObjectName("AIHubCardTitle")
        # Allow long model names (e.g. "Whisper Large v3 turbo (ONNX)") to wrap
        # onto a second line instead of being clipped.
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_row.addWidget(title, 1)

        if not compatible and not installed:
            warn_chip = Chip(
                _t("Несовместимо", "Incompatible"),
                tooltip=compatibility_warning or _t(
                    "Эта модель требует другого backend и не запустится на вашем оборудовании.",
                    "This model needs a different backend and won't run on your hardware.",
                ),
            )
            warn_chip.setObjectName("AIHubChipDanger")
            title_row.addWidget(warn_chip, 0, Qt.AlignmentFlag.AlignTop)
        elif not_recommended:
            title_row.addWidget(
                Chip(
                    _t("Не рекомендуется", "Not recommended"),
                    variant="not_recommended",
                    tooltip=compatibility_warning or _t(
                        "DirectML разрешён на NVIDIA, но CUDA-реализация обычно быстрее и лучше оптимизирована.",
                        "DirectML is supported on NVIDIA, but the CUDA implementation is usually faster and better optimized.",
                    ),
                ),
                0,
                Qt.AlignmentFlag.AlignTop,
            )

        info_col.addLayout(title_row)

        description = str(meta.get("description") or "").strip()
        desc = QLabel(description)
        desc.setObjectName("AIHubCardDesc")
        desc.setWordWrap(True)
        info_col.addWidget(desc)
        info_col.addStretch(1)

        info_wrap = QFrame()
        info_wrap.setLayout(info_col)
        info_wrap.setMinimumWidth(220)
        root.addWidget(info_wrap, 3)

        # ---- middle: chips
        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.setSpacing(6)
        chips_row.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        vram = str(meta.get("vram") or meta.get("vram_range") or "").strip()
        if vram:
            chips_row.addWidget(Chip(f"VRAM {vram}"))

        if backend == "cuda":
            chips_row.addWidget(Chip("NVIDIA", variant="gpu_ok"))
        elif backend == "onnx":
            chips_row.addWidget(Chip("ONNX", variant="onnx"))
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

        # ---- right: status indicator (dot + label for installed)
        from .helpers import qicon

        if installed:
            if update_available:
                ok_lbl = QLabel(_t("Обновление", "Update"))
                ok_lbl.setObjectName("AIHubStatusUpdate")
                ok_lbl.setToolTip(str(status.get("message") or ""))
            else:
                ok_lbl = QLabel(_t("Установлено", "Installed"))
                ok_lbl.setObjectName("AIHubStatusInstalled")
            ok_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            root.addWidget(ok_lbl, 0)
        else:
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
            dot.setToolTip(status_label(status_code))
            root.addWidget(dot, 0)

        # ---- right: action button or ⋮ menu
        from PyQt6.QtWidgets import QPushButton

        if installed:
            if update_available:
                # Голос установлен, но в релизе версия новее — кнопка «Обновить»
                # запускает обычную установку; build_install_plan сам увидит апдейт
                # и перекачает. Рядом оставляем ⋮-меню (Переустановить/Удалить).
                upd = QPushButton(_t("Обновить", "Update"))
                upd.setObjectName("AIHubCardPrimary")
                upd_icon = qicon("fa5s.sync", "white")
                if upd_icon is not None:
                    upd.setIcon(upd_icon)
                upd.setCursor(Qt.CursorShape.PointingHandCursor)
                upd.clicked.connect(self._handle_install_click)
                self._install_btn = upd
                self._install_btn_text = upd.text()
                root.addWidget(upd, 0)
            btn = QPushButton("⋮")
            btn.setObjectName("AIHubCardMenuBtn")
            btn.setFixedSize(34, 34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self._show_menu)
            self._menu_btn = btn
        else:
            btn = QPushButton(
                _t("Установить", "Install")
                if compatible
                else _t("Недоступно", "Unavailable")
            )
            if compatible:
                btn.setObjectName("AIHubCardPrimary")
            else:
                btn.setObjectName("AIHubCardUnavailable")
            icon = qicon("fa5s.download", "white" if compatible else "#77727c")
            if icon is not None:
                btn.setIcon(icon)
            btn.setCursor(
                Qt.CursorShape.PointingHandCursor
                if compatible
                else Qt.CursorShape.ForbiddenCursor
            )
            btn.setEnabled(compatible)
            if not compatible:
                btn.setToolTip(
                    _t(
                        "Эта реализация не поддерживается обнаруженным оборудованием.",
                        "This implementation is not supported by the detected hardware.",
                    )
                )
            btn.clicked.connect(self._handle_install_click)
            self._install_btn = btn
            self._install_btn_text = btn.text()
        root.addWidget(btn, 0)

    # ------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        """Apply the global catalog activity state to this card's actions."""
        btn = self._install_btn
        menu = self._menu_btn
        self.setProperty("activity", state)
        self.style().unpolish(self)
        self.style().polish(self)

        if menu is not None:
            menu.setEnabled(state == "idle")
            menu.setCursor(
                Qt.CursorShape.PointingHandCursor
                if state == "idle"
                else Qt.CursorShape.ForbiddenCursor
            )
            menu.setToolTip(
                ""
                if state == "idle"
                else _t(
                    "Дождитесь завершения текущей операции.",
                    "Wait for the current operation to finish.",
                )
            )

        if btn is None:
            return
        if state == "running":
            btn.setEnabled(False)
            btn.setText(_t("Установка…", "Installing…"))
            btn.setToolTip(_t("Установка выполняется", "Installation is running"))
        elif state == "queued":
            btn.setEnabled(False)
            btn.setText(_t("В очереди", "Queued"))
            btn.setToolTip(_t("Операция находится в очереди", "Operation is queued"))
        elif state == "checking":
            btn.setEnabled(False)
            btn.setText(self._install_btn_text or _t("Установить", "Install"))
            btn.setToolTip(
                _t(
                    "Дождитесь завершения проверки компонентов.",
                    "Wait for the component check to finish.",
                )
            )
        elif state == "global_busy":
            btn.setEnabled(False)
            btn.setText(self._install_btn_text or _t("Установить", "Install"))
            btn.setToolTip(
                _t(
                    "Дождитесь завершения текущей установки.",
                    "Wait for the current installation to finish.",
                )
            )
        else:
            btn.setEnabled(self._compatible)
            btn.setText(self._install_btn_text or _t("Установить", "Install"))
            if self._compatible:
                btn.setToolTip("")

    # ------------------------------------------------------------------
    def _component_id(self) -> str:
        from .helpers import meta_from_row
        return str(meta_from_row(self._row).get("id") or "").strip()

    def _handle_install_click(self) -> None:
        if not self._compatible:
            return
        cid = self._component_id()
        if cid:
            # Мгновенно блокируем кнопку (оптимистично), не дожидаясь события
            # QUEUE_CHANGED — иначе между кликом и обновлением очереди кнопка
            # выглядит серой, но остаётся нажимаемой (фидбэк Артёма: «плохо
            # заблокирована, только текст посерел»). Точное состояние
            # (running/queued) выставит _apply_busy_state по событию очереди.
            self.set_state("queued")
            self._on_install(cid)

    def _show_menu(self) -> None:
        from PyQt6.QtWidgets import QMenu
        from .helpers import qicon

        cid = self._component_id()
        menu = QMenu(self)
        menu.setObjectName("AIHubCardMenu")

        act_settings = menu.addAction(_t("Открыть настройки", "Open settings"))
        ic = qicon("fa5s.sliders-h", "#f3edf6")
        if ic is not None:
            act_settings.setIcon(ic)

        act_reinstall = None
        if self._on_reinstall is not None:
            act_reinstall = menu.addAction(_t("Переустановить начисто", "Clean reinstall"))
            ic_re = qicon("fa5s.sync", "#f3edf6")
            if ic_re is not None:
                act_reinstall.setIcon(ic_re)

        act_uninstall = menu.addAction(_t("Удалить", "Uninstall"))
        ic2 = qicon("fa5s.trash-alt", "#ffb4c5")
        if ic2 is not None:
            act_uninstall.setIcon(ic2)

        btn = getattr(self, "_menu_btn", None)
        anchor = btn.mapToGlobal(btn.rect().bottomLeft()) if btn is not None else self.mapToGlobal(self.rect().bottomRight())
        chosen = menu.exec(anchor)
        if chosen is act_settings:
            self._on_open_settings(cid)
        elif act_reinstall is not None and chosen is act_reinstall:
            self._confirm_and_reinstall(cid)
        elif chosen is act_uninstall:
            self._confirm_and_uninstall(cid)

    def _confirm_and_reinstall(self, cid: str) -> None:
        from .helpers import meta_from_row
        title = str(meta_from_row(self._row).get("title") or cid)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_t("Переустановить начисто", "Clean reinstall"))
        box.setText(
            _t(
                f"Удалить загруженные файлы «{title}» и скачать заново?",
                f"Delete the downloaded files of “{title}” and download them again?",
            )
        )
        box.setInformativeText(
            _t(
                "Помогает, если установка оборвалась и файлы повредились.",
                "Use this if a download was interrupted and the files got corrupted.",
            )
        )
        yes = box.addButton(_t("Переустановить", "Reinstall"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_t("Отмена", "Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes and self._on_reinstall is not None:
            self._on_reinstall(cid)

    def _confirm_and_uninstall(self, cid: str) -> None:
        from .helpers import meta_from_row
        meta = meta_from_row(self._row)
        title = str(meta.get("title") or cid)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(_t("Удаление модели", "Uninstall model"))
        box.setText(
            _t(
                "Удалить «{title}»?",
                "Uninstall «{title}»?",
            ).format(title=title)
        )
        box.setInformativeText(
            _t(
                "Файлы и зависимости модели будут удалены. Это действие нельзя отменить.",
                "Model files and dependencies will be removed. This cannot be undone.",
            )
        )
        yes = box.addButton(_t("Удалить", "Uninstall"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(_t("Отмена", "Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self._on_uninstall(cid)
