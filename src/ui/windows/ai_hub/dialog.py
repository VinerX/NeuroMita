from __future__ import annotations

import datetime as _dt
import os
import shutil
from typing import Any

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.events import Events, get_event_bus
from main_logger import logger
from styles.ai_hub_styles import get_stylesheet as get_ai_hub_stylesheet
from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider

from .constants import CATEGORY_ICONS, CATEGORY_LABELS, CATEGORY_ORDER, ROW_CATEGORY_MAP
from .helpers import meta_from_row, qicon, qpixmap, row_category, status_from_row
from .widgets import CategoryButton, ModelCard, Stat


class AIHubDialog(QDialog):
    # Cross-thread dispatcher: event-bus callbacks emit a lambda here and the
    # connected slot runs it on the GUI thread (QueuedConnection by default).
    _ui_call_requested = pyqtSignal(object)

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
        self._category_buttons: dict[str, CategoryButton] = {}

        self._ui_call_requested.connect(self._execute_ui_call)

        self._build()
        self._bind_events()
        QTimer.singleShot(0, lambda: self.refresh(force=True))

    # ------------------------------------------------------------ thread hop
    def _execute_ui_call(self, fn) -> None:
        try:
            fn()
        except Exception:
            logger.exception("AI Hub: UI callback failed")

    def _on_gui_thread(self, fn) -> None:
        """Schedule `fn` to run on the GUI thread.

        Event-bus callbacks fire on the bus's processor thread, so any Qt
        widget mutation (incl. QTimer.start) must be marshalled here first.
        """
        self._ui_call_requested.emit(fn)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.setObjectName("AIHubDialog")
        self.setWindowTitle(_("AI Hub", "AI Hub"))
        self.setModal(False)
        self.resize(1280, 820)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(get_ai_hub_stylesheet())

        # Use the native OS window chrome — no custom title bar, no shadow.
        # The root frame stays as a styling anchor so the QSS still matches
        # everything inside it.
        root_outer = QVBoxLayout(self)
        root_outer.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame()
        self._card.setObjectName("AIHubRoot")
        root_outer.addWidget(self._card)

        root = QVBoxLayout(self._card)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addLayout(self._build_header())
        root.addLayout(self._build_body(), 1)
        root.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)

        badge = QLabel()
        badge.setObjectName("AIHubIconBadge")
        badge.setFixedSize(48, 48)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = qpixmap("fa5s.magic", "#db6596", 22)
        if pix is not None:
            badge.setPixmap(pix)
        else:
            badge.setText("✦")
        header.addWidget(badge, 0)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        title = QLabel(_("AI Hub", "AI Hub"))
        title.setObjectName("AIHubTitle")
        title_box.addWidget(title)
        subtitle = QLabel(
            _(
                "Установка, удаление и обслуживание локальных AI-моделей и системных зависимостей.",
                "Install, remove and maintain local AI models and system dependencies.",
            )
        )
        subtitle.setObjectName("AIHubSubtitle")
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        # native OS window chrome already provides a close button
        return header

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        body.addWidget(self._build_sidebar(), 0)
        body.addLayout(self._build_main_column(), 1)
        return body

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("AIHubSidebar")
        sidebar.setFixedWidth(258)
        l = QVBoxLayout(sidebar)
        l.setContentsMargins(14, 16, 14, 14)
        l.setSpacing(8)

        cat_header = QLabel(_("КАТЕГОРИИ", "CATEGORIES"))
        cat_header.setObjectName("AIHubSidebarHeader")
        l.addWidget(cat_header)

        for key in CATEGORY_ORDER:
            btn = CategoryButton(
                key,
                CATEGORY_LABELS.get(key, key),
                CATEGORY_ICONS.get(key, "fa5s.circle"),
                self._select_category,
                sidebar,
            )
            self._category_buttons[key] = btn
            l.addWidget(btn, 0)

        # task status (install / progress)
        self.task_status_label = QLabel("")
        self.task_status_label.setObjectName("AIHubSidebarStatus")
        self.task_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.task_status_label.setWordWrap(True)
        self.task_status_label.setVisible(False)
        l.addWidget(self.task_status_label)

        l.addStretch(1)

        # "Check for updates" button sits at the very bottom of the sidebar
        self.btn_refresh = QPushButton(_("Проверить обновления", "Check for updates"))
        self.btn_refresh.setObjectName("AIHubSidebarBtn")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        ic = qicon("fa5s.sync", "#db6596")
        if ic is not None:
            self.btn_refresh.setIcon(ic)
            self.btn_refresh.setIconSize(QSize(13, 13))
        self.btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        l.addWidget(self.btn_refresh)

        return sidebar

    def _build_main_column(self) -> QVBoxLayout:
        from PyQt6.QtWidgets import QStackedWidget
        from .settings_panel import SettingsPanel

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)

        col.addLayout(self._build_tab_switcher())
        col.addWidget(self._build_banner())

        # ---- stacked content: page 0 = install (list), page 1 = settings
        self._stack = QStackedWidget()
        self._stack.setObjectName("AIHubStack")

        # install page (existing layout)
        install_page = QWidget()
        ip = QVBoxLayout(install_page)
        ip.setContentsMargins(0, 0, 0, 0)
        ip.setSpacing(14)
        ip.addLayout(self._build_toolbar())
        ip.addWidget(self._build_scroll(), 1)
        self._stack.addWidget(install_page)

        # settings page
        self._settings_panel = SettingsPanel()
        self._stack.addWidget(self._settings_panel)

        col.addWidget(self._stack, 1)
        return col

    def _build_banner(self) -> QFrame:
        self.banner = QFrame()
        self.banner.setObjectName("AIHubBanner")
        self.banner.setVisible(False)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(18, 14, 18, 14)
        bl.setSpacing(14)

        ico = QLabel()
        ico.setObjectName("AIHubBannerIcon")
        ico.setFixedSize(46, 46)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = qpixmap("fa5s.microchip", "#db6596", 22)
        if pix is not None:
            ico.setPixmap(pix)
        bl.addWidget(ico, 0)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        self.banner_title = QLabel("")
        self.banner_title.setObjectName("AIHubBannerTitle")
        self.banner_title.setTextFormat(Qt.TextFormat.RichText)
        text_col.addWidget(self.banner_title)
        self.banner_body = QLabel("")
        self.banner_body.setObjectName("AIHubBannerBody")
        self.banner_body.setWordWrap(True)
        text_col.addWidget(self.banner_body)
        bl.addLayout(text_col, 1)

        self.banner_button = QPushButton(_("Оптимизировать", "Optimize"))
        self.banner_button.setObjectName("AIHubPrimary")
        self.banner_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bi = qicon("fa5s.bolt", "white")
        if bi is not None:
            self.banner_button.setIcon(bi)
            self.banner_button.setIconSize(QSize(13, 13))
        self.banner_button.clicked.connect(self._install_cuda_backend)
        bl.addWidget(self.banner_button, 0)

        self.banner_dismiss = QPushButton(_("Позже", "Later"))
        self.banner_dismiss.setObjectName("AIHubSecondary")
        self.banner_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self.banner_dismiss.clicked.connect(lambda: self.banner.setVisible(False))
        bl.addWidget(self.banner_dismiss, 0)

        return self.banner

    def _build_toolbar(self) -> QVBoxLayout:
        """Two-row toolbar.

        Row 1: «Доступные модели» (page header) + backend filter pills
               + search + sort.
        Row 2: install / settings tab switcher.
        """
        wrap = QVBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)

        title = QLabel(_("Доступные модели", "Available models"))
        title.setObjectName("AIHubSectionTitle")
        top.addWidget(title, 0)
        top.addStretch(1)

        # backend filter pills
        self._backend_filter = "all"
        self._backend_filter_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("all", _("Все", "All")),
            ("cuda", "NVIDIA / CUDA"),
            ("onnx", "ONNX"),
            ("cpu", "CPU"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("AIHubFilterPill")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("active", "true" if key == "all" else "false")
            btn.clicked.connect(lambda _checked, k=key: self._set_backend_filter(k))
            self._backend_filter_buttons[key] = btn
            top.addWidget(btn, 0)
        self._backend_filter_buttons["all"].setChecked(True)

        top.addSpacing(6)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("AIHubSearch")
        self.search_box.setPlaceholderText(_("Поиск моделей...", "Search models..."))
        self.search_box.setFixedWidth(240)
        si = qicon("fa5s.search", "#bca9bb")
        if si is not None:
            action = self.search_box.addAction(si, QLineEdit.ActionPosition.LeadingPosition)
            action.setEnabled(False)
        self.search_box.textChanged.connect(self._rebuild_component_list)
        top.addWidget(self.search_box, 0)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("AIHubSort")
        self.sort_combo.setFixedWidth(220)
        self.sort_combo.addItem(_("По умолчанию", "Default"), "default")
        self.sort_combo.addItem(_("Сначала установленные", "Installed first"), "installed")
        self.sort_combo.addItem(_("По имени", "By name"), "name")
        self.sort_combo.currentIndexChanged.connect(self._rebuild_component_list)
        top.addWidget(self.sort_combo, 0)

        wrap.addLayout(top)
        return wrap

    def _build_tab_switcher(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._tab_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("install", _("Установка", "Install")),
            ("settings", _("Настройки", "Settings")),
        ):
            btn = QPushButton(label)
            btn.setObjectName("AIHubTabBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("active", "true" if key == "install" else "false")
            btn.clicked.connect(lambda _c, k=key: self._set_tab(k))
            row.addWidget(btn, 0)
            self._tab_buttons[key] = btn
        row.addStretch(1)
        return row

    def _build_scroll(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("AIHubScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._scroll_content = QWidget()
        self._scroll_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 8, 0)
        self._scroll_layout.setSpacing(10)
        self._scroll_layout.addStretch(1)

        scroll.setWidget(self._scroll_content)
        return scroll

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)

        self.stat_installed = Stat("fa5s.download", _("Установлено", "Installed"))
        self.stat_updates = Stat("fa5s.sync", _("Доступно обновлений", "Updates available"))
        self.stat_disk = Stat("fa5s.hdd", _("Свободно на диске", "Free disk"))
        self.stat_check = Stat("fa5s.clock", _("Последняя проверка", "Last check"))

        for s in (self.stat_installed, self.stat_updates, self.stat_disk, self.stat_check):
            s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            footer.addWidget(s, 1)

        return footer

    # ----------------------------------------------------------- events
    def _bind_events(self) -> None:
        self.event_bus.subscribe(Events.Install.TASK_STARTED, self._on_install_started, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)

    def apply_payload(self, payload: dict[str, Any] | None) -> None:
        data = payload if isinstance(payload, dict) else {}
        cat = str(data.get("category") or "").strip().lower()
        cat = ROW_CATEGORY_MAP.get(cat, cat)
        cid = str(data.get("component_id") or "").strip()
        if cat:
            self._pending_category = cat
        if cid:
            self._pending_component_id = cid
        if self._loaded_once and self._rows:
            self._refresh_views()
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
        self._refresh_views()

    def _refresh_views(self) -> None:
        self._rebuild_category_list()
        self._update_banner()
        self._rebuild_component_list()
        self._update_summary()
        # propagate the same row set to the Settings panel
        if hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, self._selected_category)

    # ----------------------------------------------------------- tabs & filters
    def _set_tab(self, key: str) -> None:
        key = key if key in ("install", "settings") else "install"
        for k, btn in self._tab_buttons.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.setChecked(k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._stack.setCurrentIndex(1 if key == "settings" else 0)
        # the settings panel should reflect the current category when shown
        if key == "settings" and hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, self._selected_category)

    def _set_backend_filter(self, key: str) -> None:
        key = key if key in ("all", "cuda", "onnx", "cpu") else "all"
        self._backend_filter = key
        for k, btn in self._backend_filter_buttons.items():
            btn.setChecked(k == key)
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._rebuild_component_list()

    def _open_component_settings(self, component_id: str) -> None:
        self._set_tab("settings")
        if hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, self._selected_category)
            self._settings_panel.select_component(component_id)

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

    # ----------------------------------------------------------- categories
    def _rebuild_category_list(self) -> None:
        counts = {key: 0 for key in CATEGORY_ORDER}
        for row in self._rows:
            cat = row_category(row)
            if cat in counts:
                counts[cat] += 1

        selected = self._pending_category or self._selected_category or "tts"
        if selected not in CATEGORY_ORDER:
            selected = "tts"

        for key, btn in self._category_buttons.items():
            btn.setCount(counts.get(key, 0))
            btn.setSelected(key == selected)

        self._selected_category = selected
        self._pending_category = None

    def _select_category(self, key: str) -> None:
        if key not in CATEGORY_ORDER:
            return
        self._selected_category = key
        for k, btn in self._category_buttons.items():
            btn.setSelected(k == key)
        self._rebuild_component_list()
        if hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, key)
        self._update_summary()

    # ----------------------------------------------------------- filtering
    def _filtered_rows(self) -> list[dict[str, Any]]:
        from .helpers import is_backend_compatible

        query = str(self.search_box.text() or "").strip().lower()
        category = self._selected_category
        backend_filter = getattr(self, "_backend_filter", "all")
        gpu_vendor = self._detect_gpu_vendor()

        rows: list[dict[str, Any]] = []
        for row in self._rows:
            meta = meta_from_row(row)
            status = status_from_row(row)
            if category and row_category(row) != category:
                continue
            backend = str(meta.get("backend") or "").strip().lower()
            if backend_filter != "all" and backend != backend_filter:
                # exception: "cpu"/"none" components stay visible under any
                # filter — they're universally compatible
                if backend not in ("cpu", "none", ""):
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

        mode = str(self.sort_combo.currentData() or "default")

        def _compat_rank(r: dict[str, Any]) -> int:
            # 0 = compatible or already installed; 1 = incompatible -> bottom
            status = status_from_row(r)
            if status.get("installed") or status.get("ready"):
                return 0
            return 0 if is_backend_compatible(str(meta_from_row(r).get("backend") or ""), gpu_vendor) else 1

        if mode == "installed":
            rows.sort(
                key=lambda r: (
                    _compat_rank(r),
                    0 if status_from_row(r).get("installed") else 1,
                    str(meta_from_row(r).get("title") or ""),
                )
            )
        elif mode == "name":
            rows.sort(key=lambda r: (_compat_rank(r), str(meta_from_row(r).get("title") or "")))
        else:
            # default — preserve original order but push incompatible to the bottom
            rows.sort(key=_compat_rank)
        return rows

    def _detect_gpu_vendor(self) -> str:
        try:
            return str(check_gpu_provider() or "CPU").upper()
        except Exception:
            return "CPU"

    # ----------------------------------------------------------- list rendering
    def _clear_scroll(self) -> None:
        # Remove every child widget but keep the trailing stretch.
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _rebuild_component_list(self) -> None:
        rows = self._filtered_rows()
        self._clear_scroll()
        if not rows:
            empty = QLabel(
                _("Ничего не найдено по выбранным критериям.",
                  "No components match the current filters.")
            )
            empty.setObjectName("AIHubEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, empty)
            return

        gpu_vendor = self._detect_gpu_vendor()
        for row in rows:
            card = ModelCard(
                row,
                on_install=lambda cid: self._emit_component_action_by_id(cid, Events.Installable.INSTALL),
                on_uninstall=lambda cid: self._emit_component_action_by_id(cid, Events.Installable.UNINSTALL),
                on_open_settings=self._open_component_settings,
                gpu_vendor=gpu_vendor,
                parent=self._scroll_content,
            )
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, card)

    # ----------------------------------------------------------- summary / banner
    def _update_summary(self) -> None:
        # "Models" stats — count only model categories (tts/asr/rag).
        # Backend ('Системное ядро') and deps ('Зависимости') aren't models.
        _MODEL_CATEGORIES = {"tts", "asr", "rag"}
        model_rows = [r for r in self._rows if row_category(r) in _MODEL_CATEGORIES]
        installed = sum(1 for r in model_rows if status_from_row(r).get("installed"))
        updates = sum(
            1
            for r in model_rows
            if str(status_from_row(r).get("code") or "") == "needs_update"
            or status_from_row(r).get("update_available")
        )
        models_word = _("моделей", "models")
        self.stat_installed.setValue(str(installed), models_word)
        self.stat_updates.setValue(str(updates), models_word)

        try:
            usage = shutil.disk_usage(os.path.abspath(os.sep))
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            self.stat_disk.setValue(
                f"{free_gb:.1f} GB",
                _("из {total:.0f} GB", "of {total:.0f} GB").format(total=total_gb),
            )
        except Exception:
            self.stat_disk.setValue("-", "")

        if self._last_check_ts is not None:
            delta = _dt.datetime.now() - self._last_check_ts
            mins = max(0, int(delta.total_seconds() // 60))
            if mins <= 0:
                ago = _("только что", "just now")
            elif mins < 60:
                ago = _("{n} мин. назад", "{n} min ago").format(n=mins)
            else:
                ago = _("{n} ч. назад", "{n} h ago").format(n=mins // 60)
            self.stat_check.setValue(ago, self._last_check_ts.strftime("%d.%m.%Y %H:%M"))
        else:
            self.stat_check.setValue("-", "")

    def _update_banner(self) -> None:
        try:
            gpu_vendor = str(check_gpu_provider() or "CPU").upper()
        except Exception:
            gpu_vendor = "CPU"

        row_cpu = self._row_by_id("backend:cpu")
        row_cuda = self._row_by_id("backend:cuda")
        cpu_ready = bool(status_from_row(row_cpu or {}).get("ready"))
        cuda_ready = bool(status_from_row(row_cuda or {}).get("ready"))

        show = gpu_vendor == "NVIDIA" and cpu_ready and not cuda_ready
        self.banner.setVisible(show)
        if show:
            self.banner_title.setText(
                _(
                    "Обнаружена видеокарта <span style='color:#db6596;font-weight:800;'>NVIDIA</span>,"
                    " но активен <span style='color:#db6596;font-weight:800;'>CPU-бэкенд</span>",
                    "Detected <span style='color:#db6596;font-weight:800;'>NVIDIA</span> GPU,"
                    " but the <span style='color:#db6596;font-weight:800;'>CPU backend</span> is active",
                )
            )
            self.banner_body.setText(
                _(
                    "Можно скачать оптимизированную CUDA-версию (~3 GB), чтобы значительно ускорить работу.",
                    "You can download the optimized CUDA version (~3 GB) to significantly speed things up.",
                )
            )

    def _install_cuda_backend(self) -> None:
        self._pending_category = "backend"
        self._pending_component_id = "backend:cuda"
        self._emit_component_action_by_id("backend:cuda", Events.Installable.INSTALL)

    def _row_by_id(self, component_id: str) -> dict[str, Any] | None:
        for row in self._rows:
            if str(meta_from_row(row).get("id") or "") == component_id:
                return row
        return None

    def _emit_component_action_by_id(self, component_id: str, event_name: str) -> None:
        if not component_id:
            return
        self.event_bus.emit(
            event_name,
            {
                "component_id": component_id,
                "with_ui": True,
                "meta": {"source": "ai_hub"},
            },
        )
        self._set_task_status(_("Запуск задачи...", "Starting task..."))

    # ----------------------------------------------------------- task events
    def _set_task_status(self, text: str) -> None:
        self._last_task_status = text or ""
        if self._last_task_status:
            self.task_status_label.setText(self._last_task_status)
            self.task_status_label.setVisible(True)
        else:
            self.task_status_label.setVisible(False)

    def _is_installable_task(self, event) -> bool:
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta.get("category") in CATEGORY_ORDER or meta.get("category") in ROW_CATEGORY_MAP:
            return True
        cid = str(meta.get("component_id") or data.get("component_id") or "")
        return ":" in cid

    def _on_install_started(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        text = str(data.get("status") or _("Подготовка...", "Preparing..."))
        self._on_gui_thread(lambda: self._set_task_status(text))

    def _on_install_progress(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        status = str(data.get("status") or "").strip()
        progress = data.get("progress")
        if not status:
            return
        text = f"{status} ({progress}%)" if progress is not None else status
        self._on_gui_thread(lambda: self._set_task_status(text))

    def _on_install_finished(self, event) -> None:
        if not self._is_installable_task(event):
            return
        done_text = _("Готово", "Done")

        def _apply() -> None:
            self._set_task_status(done_text)
            QTimer.singleShot(250, lambda: (self.refresh(force=True), self._set_task_status("")))

        self._on_gui_thread(_apply)

    def _on_install_failed(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        text = str(data.get("error") or _("Ошибка установки", "Install failed"))

        def _apply() -> None:
            self._set_task_status(text)
            QTimer.singleShot(250, lambda: self.refresh(force=True))

        self._on_gui_thread(_apply)
