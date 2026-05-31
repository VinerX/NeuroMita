from __future__ import annotations

from typing import Any, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from utils import _


class SortableTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        try:
            if left is None:
                return False
            if right is None:
                return True
            return left < right
        except Exception:
            return super().__lt__(other)


class ModelsLoadedDialog(QDialog):
    _COLUMN_HEADERS = [
        _("Модель", "Model"),
        _("Тип", "Type"),
        _("Контекст", "Context"),
        _("Input $/1M", "Input $/1M"),
        _("Output $/1M", "Output $/1M"),
        _("Cache read $/1M", "Cache read $/1M"),
        _("Cache write $/1M", "Cache write $/1M"),
        _("Latency", "Latency"),
        _("Tok/s", "Tok/s"),
    ]

    def __init__(self, parent, *, models: List[str], model_infos: List[dict] | None = None, message: str = ""):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(_("Загруженные модели", "Loaded models"))

        self._selected: str = ""
        self._model_infos = self._normalize_model_infos(models=models, model_infos=model_infos or [])
        self._has_free_models = any(bool(info.get("is_free")) for info in self._model_infos)
        self._has_paid_models = any(not bool(info.get("is_free")) for info in self._model_infos)

        lay = QVBoxLayout(self)

        if message:
            self.message_label = QLabel(str(message))
            self.message_label.setWordWrap(True)
            lay.addWidget(self.message_label)

        controls_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Поиск...", "Search..."))
        controls_row.addWidget(self.search, 1)

        self.include_paid_cb = QCheckBox(_("Включать платные", "Include paid"))
        self.include_paid_cb.setChecked(False)
        self.include_paid_cb.setEnabled(self._has_free_models and self._has_paid_models)
        controls_row.addWidget(self.include_paid_cb)
        lay.addLayout(controls_row)

        self.status_label = QLabel("")
        lay.addWidget(self.status_label)

        self.table = QTableWidget(0, len(self._COLUMN_HEADERS))
        self.table.setHorizontalHeaderLabels(self._COLUMN_HEADERS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for idx in range(1, len(self._COLUMN_HEADERS)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)

        lay.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.btn_use = QPushButton(_("Выбрать", "Use selected"))
        self.btn_copy = QPushButton(_("Копировать видимое", "Copy visible"))
        self.btn_close = QPushButton(_("Закрыть", "Close"))
        btn_row.addWidget(self.btn_use)
        btn_row.addWidget(self.btn_copy)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_close)
        lay.addLayout(btn_row)

        self.search.textChanged.connect(self._rebuild_table)
        self.include_paid_cb.toggled.connect(self._rebuild_table)
        self.btn_use.clicked.connect(self._accept_selected)
        self.table.itemDoubleClicked.connect(lambda _it: self._accept_selected())
        self.btn_copy.clicked.connect(self._copy_visible)
        self.btn_close.clicked.connect(self.reject)

        self._rebuild_table()
        self.resize(1100, 620)

    def _normalize_model_infos(self, *, models: List[str], model_infos: List[dict]) -> List[dict]:
        normalized: List[dict] = []
        seen: set[str] = set()

        def append_info(info: dict) -> None:
            model_id = str(info.get("id") or "").strip()
            if not model_id or model_id in seen:
                return

            seen.add(model_id)
            normalized.append({
                "id": model_id,
                "name": str(info.get("name") or model_id).strip(),
                "canonical_slug": info.get("canonical_slug"),
                "context_length": info.get("context_length") or info.get("top_provider_context_length"),
                "max_completion_tokens": info.get("max_completion_tokens"),
                "is_free": bool(info.get("is_free")),
                "pricing": info.get("pricing") if isinstance(info.get("pricing"), dict) else {},
                "top_provider": info.get("top_provider") if isinstance(info.get("top_provider"), dict) else {},
                "latency": info.get("latency"),
                "tokens_per_second": info.get("tokens_per_second"),
            })

        for info in model_infos:
            if isinstance(info, dict):
                append_info(info)

        for model in models or []:
            model_id = str(model or "").strip()
            if not model_id:
                continue
            append_info({"id": model_id, "name": model_id})

        return normalized

    @staticmethod
    def _parse_float(value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except Exception:
            return None

    @classmethod
    def _format_price_per_million(cls, value: Any) -> str:
        numeric = cls._parse_float(value)
        if numeric is None:
            return "-"

        per_million = numeric * 1_000_000
        if per_million >= 100:
            text = f"{per_million:.2f}"
        elif per_million >= 1:
            text = f"{per_million:.3f}"
        elif per_million >= 0.01:
            text = f"{per_million:.4f}"
        else:
            text = f"{per_million:.6f}"
        return f"${text.rstrip('0').rstrip('.')}"

    @staticmethod
    def _format_integer(value: Any) -> str:
        try:
            if value in (None, ""):
                return "-"
            return f"{int(value):,}".replace(",", " ")
        except Exception:
            return "-"

    @classmethod
    def _format_metric(cls, value: Any, suffix: str = "") -> str:
        numeric = cls._parse_float(value)
        if numeric is None:
            return "-"

        if numeric >= 100:
            text = f"{numeric:.0f}"
        elif numeric >= 10:
            text = f"{numeric:.1f}"
        else:
            text = f"{numeric:.2f}"
        text = text.rstrip("0").rstrip(".")
        return f"{text}{suffix}"

    def _matches_filters(self, info: dict, needle: str) -> bool:
        if self._has_free_models and not self.include_paid_cb.isChecked() and not bool(info.get("is_free")):
            return False

        if not needle:
            return True

        haystack = " ".join(
            [
                str(info.get("id") or ""),
                str(info.get("name") or ""),
                str(info.get("canonical_slug") or ""),
            ]
        ).lower()
        return needle in haystack

    def _visible_model_infos(self) -> List[dict]:
        needle = str(self.search.text() or "").strip().lower()
        return [info for info in self._model_infos if self._matches_filters(info, needle)]

    def _set_cell(self, row: int, column: int, text: str, *, sort_value: Any = None, tooltip: str | None = None) -> None:
        item = SortableTableWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, sort_value if sort_value is not None else text)
        if tooltip:
            item.setToolTip(tooltip)
        self.table.setItem(row, column, item)

    def _rebuild_table(self, *_args) -> None:
        visible = self._visible_model_infos()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible))

        for row, info in enumerate(visible):
            model_id = str(info.get("id") or "").strip()
            display_name = str(info.get("name") or model_id).strip()
            tooltip = display_name if display_name and display_name != model_id else None
            pricing = info.get("pricing") if isinstance(info.get("pricing"), dict) else {}
            if self._has_free_models:
                type_text = _("Free", "Free") if bool(info.get("is_free")) else _("Paid", "Paid")
                type_sort = 0 if bool(info.get("is_free")) else 1
            else:
                type_text = "-"
                type_sort = 0

            self._set_cell(row, 0, model_id, sort_value=model_id, tooltip=tooltip)
            self._set_cell(row, 1, type_text, sort_value=type_sort)
            self._set_cell(row, 2, self._format_integer(info.get("context_length")), sort_value=self._parse_float(info.get("context_length")) or 0)
            self._set_cell(row, 3, self._format_price_per_million(pricing.get("prompt")), sort_value=self._parse_float(pricing.get("prompt")))
            self._set_cell(row, 4, self._format_price_per_million(pricing.get("completion")), sort_value=self._parse_float(pricing.get("completion")))
            self._set_cell(row, 5, self._format_price_per_million(pricing.get("input_cache_read")), sort_value=self._parse_float(pricing.get("input_cache_read")))
            self._set_cell(row, 6, self._format_price_per_million(pricing.get("input_cache_write")), sort_value=self._parse_float(pricing.get("input_cache_write")))
            self._set_cell(row, 7, self._format_metric(info.get("latency")), sort_value=self._parse_float(info.get("latency")))
            self._set_cell(row, 8, self._format_metric(info.get("tokens_per_second")), sort_value=self._parse_float(info.get("tokens_per_second")))

        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)

        if self.table.rowCount() > 0:
            self.table.selectRow(0)

        total = len(self._model_infos)
        shown = len(visible)
        self.status_label.setText(
            _("Показано {shown} из {total}", "Showing {shown} of {total}").format(shown=shown, total=total)
        )

    def _accept_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        self._selected = item.text().strip()
        if self._selected:
            self.accept()

    def _copy_visible(self) -> None:
        visible_models = [str(info.get("id") or "").strip() for info in self._visible_model_infos() if str(info.get("id") or "").strip()]
        QApplication.clipboard().setText("\n".join(visible_models))

    def selected_model(self) -> str:
        return self._selected
