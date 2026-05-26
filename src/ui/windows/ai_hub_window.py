from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
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


_CATEGORY_ORDER = ("tts", "asr", "rag", "beats", "backend")
_CATEGORY_LABELS = {
    "tts": _("Синтез речи", "TTS"),
    "asr": _("Распознавание", "ASR"),
    "rag": _("Поиск и память", "RAG"),
    "beats": _("Beat Sync", "Beat Sync"),
    "backend": _("Системный backend", "Backend"),
}
_STATUS_LABELS = {
    "ready": _("Готово", "Ready"),
    "installed": _("Установлено", "Installed"),
    "not_installed": _("Не установлено", "Not installed"),
    "backend_missing": _("Нет backend", "Backend missing"),
    "failed": _("Ошибка", "Failed"),
    "unknown": _("Неизвестно", "Unknown"),
}
_STATUS_COLORS = {
    "ready": "#65d46e",
    "installed": "#65d46e",
    "not_installed": "#f1b84b",
    "backend_missing": "#ff7b7b",
    "failed": "#ff7b7b",
    "unknown": "#9ca3af",
}


class AIHubComponentItem(QWidget):
    def __init__(self, row: dict[str, Any], parent=None):
        super().__init__(parent)
        self.row = row
        self._build()

    def _build(self) -> None:
        meta = self.row.get("metadata") if isinstance(self.row.get("metadata"), dict) else {}
        status = self.row.get("status") if isinstance(self.row.get("status"), dict) else {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        title = QLabel(str(meta.get("title") or meta.get("id") or "—"))
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: #f4f4f5;")
        top.addWidget(title, 1)

        status_code = str(status.get("code") or "unknown")
        status_text = _STATUS_LABELS.get(status_code, status_code)
        status_color = _STATUS_COLORS.get(status_code, "#9ca3af")
        chip = QLabel(status_text)
        chip.setStyleSheet(
            "padding: 3px 10px; border-radius: 10px; "
            f"background: rgba(255,255,255,0.05); color: {status_color}; font-weight: 600;"
        )
        top.addWidget(chip, 0)
        root.addLayout(top)

        desc_parts: list[str] = []
        backend = str(meta.get("backend") or "").strip()
        if backend and backend != "none":
            desc_parts.append(backend.upper())
        for item in meta.get("languages") or []:
            text = str(item or "").strip()
            if text:
                desc_parts.append(text.upper())
        for item in meta.get("tags") or []:
            text = str(item or "").strip()
            if text and text not in desc_parts:
                desc_parts.append(text)

        message = str(status.get("message") or "").strip()
        sub = " • ".join(desc_parts[:4])
        if message:
            sub = f"{sub} • {message}" if sub else message
        if not sub:
            sub = str(meta.get("id") or "")

        subtitle = QLabel(sub)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 11px; color: #a1a1aa;")
        root.addWidget(subtitle)


class AIHubDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.event_bus = get_event_bus()
        self._rows: list[dict[str, Any]] = []
        self._selected_category = "tts"
        self._pending_category: str | None = None
        self._pending_component_id: str | None = None
        self._last_task_status = ""
        self._build()
        self._bind_events()
        QTimer.singleShot(0, self.refresh)

    def _build(self) -> None:
        self.setObjectName("AIHubDialog")
        self.setWindowTitle(_("AI Hub", "AI Hub"))
        self.setModal(False)
        self.resize(1180, 760)
        self.setMinimumSize(980, 620)
        self.setStyleSheet(
            """
            QDialog#AIHubDialog {
                background: #0f0f17;
                color: #f4f4f5;
            }
            QFrame#AIHubCard, QFrame#AIHubBanner {
                background: #171725;
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 14px;
            }
            QListWidget#AIHubCategoryList, QListWidget#AIHubComponentList {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget#AIHubCategoryList::item, QListWidget#AIHubComponentList::item {
                border: none;
                margin: 4px 0;
            }
            QListWidget#AIHubCategoryList::item:selected, QListWidget#AIHubComponentList::item:selected {
                background: rgba(255,255,255,0.06);
                border-radius: 12px;
            }
            QLineEdit#AIHubSearch, QComboBox#AIHubSort {
                background: #11111b;
                color: #f4f4f5;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 10px;
                padding: 7px 10px;
            }
            QLabel#AIHubSectionTitle {
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#AIHubMuted {
                color: #a1a1aa;
            }
            QPushButton#AIHubPrimary {
                background: #f05a98;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 9px 14px;
                font-weight: 600;
            }
            QPushButton#AIHubPrimary:disabled {
                background: #6b3e53;
                color: #d6d3d1;
            }
            QPushButton#AIHubSecondary {
                background: #1e1e2f;
                color: #f4f4f5;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 10px;
                padding: 9px 14px;
                font-weight: 600;
            }
            QPushButton#AIHubDanger {
                background: #34161f;
                color: #ffb4c5;
                border: 1px solid rgba(255,120,150,0.18);
                border-radius: 10px;
                padding: 9px 14px;
                font-weight: 600;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        icon = QLabel()
        icon.setFixedSize(28, 28)
        if qta:
            try:
                icon.setPixmap(qta.icon("fa5s.microchip", color="#f05a98").pixmap(QSize(28, 28)))
            except Exception:
                icon.setText("AI")
        else:
            icon.setText("AI")
        header.addWidget(icon, 0)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        title = QLabel(_("AI Hub", "AI Hub"))
        title.setObjectName("AIHubSectionTitle")
        title_box.addWidget(title)
        subtitle = QLabel(
            _("Единая установка, удаление и проверка локальных AI-компонентов.",
              "Unified install, uninstall and validation for local AI components.")
        )
        subtitle.setObjectName("AIHubMuted")
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        self.btn_refresh = QPushButton(_("Обновить", "Refresh"))
        self.btn_refresh.setObjectName("AIHubSecondary")
        self.btn_refresh.clicked.connect(self.refresh)
        header.addWidget(self.btn_refresh, 0)
        root.addLayout(header)

        self.banner = QFrame()
        self.banner.setObjectName("AIHubBanner")
        self.banner.setVisible(False)
        banner_l = QHBoxLayout(self.banner)
        banner_l.setContentsMargins(14, 12, 14, 12)
        banner_l.setSpacing(12)
        self.banner_label = QLabel("")
        self.banner_label.setWordWrap(True)
        banner_l.addWidget(self.banner_label, 1)
        self.banner_button = QPushButton(_("Оптимизировать", "Optimize"))
        self.banner_button.setObjectName("AIHubPrimary")
        self.banner_button.clicked.connect(self._install_cuda_backend)
        banner_l.addWidget(self.banner_button, 0)
        root.addWidget(self.banner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)
        root.addWidget(splitter, 1)

        left = QFrame()
        left.setObjectName("AIHubCard")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(12, 12, 12, 12)
        left_l.setSpacing(8)
        left_title = QLabel(_("Категории", "Categories"))
        left_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        left_l.addWidget(left_title)

        self.category_list = QListWidget()
        self.category_list.setObjectName("AIHubCategoryList")
        self.category_list.itemSelectionChanged.connect(self._on_category_changed)
        left_l.addWidget(self.category_list, 1)
        splitter.addWidget(left)

        center = QFrame()
        center.setObjectName("AIHubCard")
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(12, 12, 12, 12)
        center_l.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("AIHubSearch")
        self.search_box.setPlaceholderText(_("Поиск компонентов...", "Search components..."))
        self.search_box.textChanged.connect(self._rebuild_component_list)
        toolbar.addWidget(self.search_box, 1)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("AIHubSort")
        self.sort_combo.addItem(_("По умолчанию", "Default"), "default")
        self.sort_combo.addItem(_("Сначала установленные", "Installed first"), "installed")
        self.sort_combo.addItem(_("По имени", "By name"), "name")
        self.sort_combo.currentIndexChanged.connect(self._rebuild_component_list)
        toolbar.addWidget(self.sort_combo, 0)
        center_l.addLayout(toolbar)

        self.component_list = QListWidget()
        self.component_list.setObjectName("AIHubComponentList")
        self.component_list.itemSelectionChanged.connect(self._on_component_changed)
        center_l.addWidget(self.component_list, 1)
        splitter.addWidget(center)

        right = QFrame()
        right.setObjectName("AIHubCard")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(14, 14, 14, 14)
        right_l.setSpacing(10)

        self.detail_title = QLabel("—")
        self.detail_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        right_l.addWidget(self.detail_title)

        self.detail_status = QLabel("—")
        self.detail_status.setObjectName("AIHubMuted")
        self.detail_status.setWordWrap(True)
        right_l.addWidget(self.detail_status)

        self.detail_meta = QLabel("")
        self.detail_meta.setObjectName("AIHubMuted")
        self.detail_meta.setWordWrap(True)
        right_l.addWidget(self.detail_meta)

        self.detail_desc = QLabel("—")
        self.detail_desc.setWordWrap(True)
        self.detail_desc.setStyleSheet("color: #d4d4d8;")
        right_l.addWidget(self.detail_desc)
        right_l.addStretch(1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        self.btn_install = QPushButton(_("Установить", "Install"))
        self.btn_install.setObjectName("AIHubPrimary")
        self.btn_install.clicked.connect(self._run_install)
        actions.addWidget(self.btn_install, 1)

        self.btn_initialize = QPushButton(_("Инициализировать", "Initialize"))
        self.btn_initialize.setObjectName("AIHubSecondary")
        self.btn_initialize.clicked.connect(self._run_initialize)
        actions.addWidget(self.btn_initialize, 1)

        self.btn_uninstall = QPushButton(_("Удалить", "Uninstall"))
        self.btn_uninstall.setObjectName("AIHubDanger")
        self.btn_uninstall.clicked.connect(self._run_uninstall)
        actions.addWidget(self.btn_uninstall, 1)
        right_l.addLayout(actions)

        splitter.addWidget(right)
        splitter.setSizes([220, 560, 320])

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("AIHubMuted")
        footer.addWidget(self.summary_label, 1)
        self.task_label = QLabel("")
        self.task_label.setObjectName("AIHubMuted")
        self.task_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(self.task_label, 1)
        root.addLayout(footer)

    def _bind_events(self) -> None:
        self.event_bus.subscribe(Events.Install.TASK_STARTED, self._on_install_started, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)

    def apply_payload(self, payload: dict[str, Any] | None) -> None:
        data = payload if isinstance(payload, dict) else {}
        category = str(data.get("category") or "").strip().lower()
        component_id = str(data.get("component_id") or "").strip()
        if category:
            self._pending_category = category
        if component_id:
            self._pending_component_id = component_id
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        rows = self._fetch_rows()
        self._rows = rows
        self._rebuild_category_list()
        self._update_banner()
        self._rebuild_component_list()
        self._update_summary()

    def _fetch_rows(self) -> list[dict[str, Any]]:
        try:
            result = self.event_bus.emit_and_wait(
                Events.Installable.LIST,
                {"include_status": True, "refresh": True},
                timeout=5.0,
            )
            rows = result[0] if result and isinstance(result[0], list) else []
            return [row for row in rows if isinstance(row, dict)]
        except Exception as exc:
            logger.error(f"AI Hub refresh failed: {exc}", exc_info=True)
            return []

    def _rebuild_category_list(self) -> None:
        counts = {category: 0 for category in _CATEGORY_ORDER}
        for row in self._rows:
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            category = str(meta.get("category") or "")
            if category in counts:
                counts[category] += 1

        selected = self._pending_category or self._selected_category or "tts"
        self.category_list.blockSignals(True)
        try:
            self.category_list.clear()
            for category in _CATEGORY_ORDER:
                item = QListWidgetItem(f"{_CATEGORY_LABELS.get(category, category)} ({counts.get(category, 0)})")
                item.setData(Qt.ItemDataRole.UserRole, category)
                self.category_list.addItem(item)
                if category == selected:
                    self.category_list.setCurrentItem(item)
        finally:
            self.category_list.blockSignals(False)

        if self.category_list.currentRow() < 0 and self.category_list.count():
            self.category_list.setCurrentRow(0)
        self._selected_category = selected
        self._pending_category = None

    def _filtered_rows(self) -> list[dict[str, Any]]:
        query = str(self.search_box.text() or "").strip().lower()
        category = self._selected_category
        rows = []
        for row in self._rows:
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            status = row.get("status") if isinstance(row.get("status"), dict) else {}
            if category and str(meta.get("category") or "") != category:
                continue
            haystack = " ".join(
                [
                    str(meta.get("id") or ""),
                    str(meta.get("title") or ""),
                    str(meta.get("description") or ""),
                    str(meta.get("backend") or ""),
                    str(status.get("message") or ""),
                    " ".join(str(x) for x in (meta.get("tags") or [])),
                    " ".join(str(x) for x in (meta.get("languages") or [])),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            rows.append(row)

        sort_mode = str(self.sort_combo.currentData() or "default")
        if sort_mode == "installed":
            rows.sort(
                key=lambda row: (
                    0 if (row.get("status") or {}).get("installed") else 1,
                    str((row.get("metadata") or {}).get("title") or ""),
                )
            )
        elif sort_mode == "name":
            rows.sort(key=lambda row: str((row.get("metadata") or {}).get("title") or ""))
        return rows

    def _rebuild_component_list(self) -> None:
        selected_id = self._pending_component_id or self._current_component_id()
        rows = self._filtered_rows()

        self.component_list.blockSignals(True)
        try:
            self.component_list.clear()
            for row in rows:
                meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                component_id = str(meta.get("id") or "")
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, component_id)
                item.setSizeHint(QSize(0, 72))
                self.component_list.addItem(item)
                self.component_list.setItemWidget(item, AIHubComponentItem(row))
                if component_id and component_id == selected_id:
                    self.component_list.setCurrentItem(item)
        finally:
            self.component_list.blockSignals(False)

        if self.component_list.currentRow() < 0 and self.component_list.count():
            self.component_list.setCurrentRow(0)
        if not self.component_list.count():
            self._render_detail(None)
        self._pending_component_id = None

    def _on_category_changed(self) -> None:
        item = self.category_list.currentItem()
        if not item:
            return
        self._selected_category = str(item.data(Qt.ItemDataRole.UserRole) or "tts")
        self._rebuild_component_list()
        self._update_summary()

    def _on_component_changed(self) -> None:
        self._render_detail(self._current_row())

    def _current_component_id(self) -> str | None:
        item = self.component_list.currentItem()
        if item is None:
            return None
        component_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        return component_id or None

    def _current_row(self) -> dict[str, Any] | None:
        component_id = self._current_component_id()
        if not component_id:
            return None
        for row in self._rows:
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if str(meta.get("id") or "") == component_id:
                return row
        return None

    def _render_detail(self, row: dict[str, Any] | None) -> None:
        if not row:
            self.detail_title.setText("—")
            self.detail_status.setText(_("Выберите компонент.", "Select a component."))
            self.detail_meta.setText("")
            self.detail_desc.setText("")
            self.btn_install.setVisible(False)
            self.btn_initialize.setVisible(False)
            self.btn_uninstall.setVisible(False)
            return

        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        status = row.get("status") if isinstance(row.get("status"), dict) else {}
        category = str(meta.get("category") or "")
        item_id = str(meta.get("item_id") or "")
        component_id = str(meta.get("id") or "")
        status_code = str(status.get("code") or "unknown")
        status_text = _STATUS_LABELS.get(status_code, status_code)
        status_msg = str(status.get("message") or "").strip()

        self.detail_title.setText(str(meta.get("title") or component_id or "—"))
        self.detail_status.setText(
            f"{status_text}: {status_msg}" if status_msg else status_text
        )

        meta_parts = [
            _CATEGORY_LABELS.get(category, category),
            component_id,
        ]
        backend = str(meta.get("backend") or "").strip()
        if backend and backend != "none":
            meta_parts.append(f"backend={backend}")
        langs = [str(x).upper() for x in (meta.get("languages") or []) if str(x).strip()]
        if langs:
            meta_parts.append("/".join(langs))
        self.detail_meta.setText(" • ".join(part for part in meta_parts if part))

        description = str(meta.get("description") or "").strip()
        if not description:
            description = _("Компонент установки и проверки.", "Installable validation component.")
        self.detail_desc.setText(description)

        install_visible = (not bool(status.get("ready"))) or status_code in ("backend_missing", "failed")
        install_text = _("Починить", "Repair") if bool(status.get("installed")) and not bool(status.get("ready")) else _("Установить", "Install")
        if category == "backend":
            install_text = _("Активировать", "Activate")

        uninstall_visible = False
        if category == "tts" and bool(status.get("installed")):
            uninstall_visible = True
        if category == "beats" and item_id == "beat_this" and bool(status.get("installed")):
            uninstall_visible = True

        initialize_visible = category == "beats"

        self.btn_install.setText(install_text)
        self.btn_install.setVisible(install_visible)
        self.btn_install.setEnabled(True)

        self.btn_uninstall.setVisible(uninstall_visible)
        self.btn_uninstall.setEnabled(uninstall_visible)

        self.btn_initialize.setVisible(initialize_visible)
        self.btn_initialize.setEnabled(initialize_visible)

    def _emit_component_action(self, event_name: str) -> None:
        row = self._current_row()
        if not row:
            return
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        component_id = str(meta.get("id") or "").strip()
        if not component_id:
            return
        self._emit_component_action_by_id(component_id, event_name)

    def _emit_component_action_by_id(self, component_id: str, event_name: str) -> None:
        self.event_bus.emit(
            event_name,
            {
                "component_id": component_id,
                "with_ui": True,
                "meta": {"source": "ai_hub"},
            },
        )
        self.task_label.setText(_("Запуск установки...", "Starting task..."))
        QTimer.singleShot(500, self.refresh)

    def _run_install(self) -> None:
        self._emit_component_action(Events.Installable.INSTALL)

    def _run_uninstall(self) -> None:
        self._emit_component_action(Events.Installable.UNINSTALL)

    def _run_initialize(self) -> None:
        self._emit_component_action(Events.Installable.INITIALIZE)

    def _update_summary(self) -> None:
        total = len(self._filtered_rows())
        installed = 0
        ready = 0
        for row in self._filtered_rows():
            status = row.get("status") if isinstance(row.get("status"), dict) else {}
            if status.get("installed"):
                installed += 1
            if status.get("ready"):
                ready += 1
        self.summary_label.setText(
            _("Показано: {total} • Установлено: {installed} • Готово: {ready}",
              "Shown: {total} • Installed: {installed} • Ready: {ready}").format(
                total=total,
                installed=installed,
                ready=ready,
            )
        )
        if not self._last_task_status:
            self.task_label.setText("")

    def _update_banner(self) -> None:
        gpu_vendor = "CPU"
        try:
            gpu_vendor = str(check_gpu_provider() or "CPU").upper()
        except Exception:
            gpu_vendor = "CPU"

        row_cpu = self._row_by_id("backend:cpu")
        row_cuda = self._row_by_id("backend:cuda")
        cpu_ready = bool(((row_cpu or {}).get("status") or {}).get("ready"))
        cuda_ready = bool(((row_cuda or {}).get("status") or {}).get("ready"))

        show = gpu_vendor == "NVIDIA" and cpu_ready and not cuda_ready
        self.banner.setVisible(show)
        if show:
            self.banner_label.setText(
                _("Обнаружена NVIDIA, но активен CPU-backend. Можно установить CUDA backend для локальных моделей.",
                  "NVIDIA detected, but CPU backend is active. You can install the CUDA backend for local models.")
            )

    def _install_cuda_backend(self) -> None:
        self._pending_category = "backend"
        self._pending_component_id = "backend:cuda"
        self._emit_component_action_by_id("backend:cuda", Events.Installable.INSTALL)

    def _row_by_id(self, component_id: str) -> dict[str, Any] | None:
        for row in self._rows:
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if str(meta.get("id") or "") == component_id:
                return row
        return None

    def _is_installable_task(self, event) -> bool:
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta.get("category") in _CATEGORY_ORDER:
            return True
        component_id = str(meta.get("component_id") or data.get("component_id") or "")
        return ":" in component_id

    def _on_install_started(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        self._last_task_status = str(data.get("status") or _("Подготовка...", "Preparing..."))
        self.task_label.setText(self._last_task_status)

    def _on_install_progress(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        status = str(data.get("status") or "").strip()
        progress = data.get("progress")
        if status:
            if progress is not None:
                self._last_task_status = f"{status} ({progress}%)"
            else:
                self._last_task_status = status
            self.task_label.setText(self._last_task_status)

    def _on_install_finished(self, event) -> None:
        if not self._is_installable_task(event):
            return
        self._last_task_status = _("Готово", "Done")
        self.task_label.setText(self._last_task_status)
        QTimer.singleShot(250, self.refresh)

    def _on_install_failed(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        error = str(data.get("error") or _("Ошибка установки", "Install failed"))
        self._last_task_status = error
        self.task_label.setText(error)
        QTimer.singleShot(250, self.refresh)
