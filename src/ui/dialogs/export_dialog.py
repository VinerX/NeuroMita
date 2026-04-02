# src/ui/dialogs/export_dialog.py
"""
ExportDialog — диалог экспорта данных для дообучения.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QListWidget, QListWidgetItem,
    QAbstractItemView, QDateEdit, QGroupBox, QComboBox,
    QFileDialog, QMessageBox, QWidget, QFrame
)
from PyQt6.QtCore import Qt, QDate

from utils import _
from main_logger import logger


class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Экспорт данных дообучения", "Export Finetune Data"))
        self.setMinimumWidth(480)
        self.setModal(True)

        self._collector = None
        try:
            from managers.finetune_collector import FineTuneCollector
            self._collector = FineTuneCollector.instance
        except Exception:
            pass

        self._build_ui()
        self._populate_characters()
        self._update_count()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Date range ────────────────────────────────────────────────────────
        date_group = QGroupBox(_("Диапазон дат", "Date range"))
        date_layout = QHBoxLayout(date_group)

        date_layout.addWidget(QLabel(_("С:", "From:")))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate.currentDate().addMonths(-3))
        self._date_from.dateChanged.connect(self._update_count)
        date_layout.addWidget(self._date_from)

        date_layout.addWidget(QLabel(_("По:", "To:")))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.dateChanged.connect(self._update_count)
        date_layout.addWidget(self._date_to)

        layout.addWidget(date_group)

        # ── Characters ────────────────────────────────────────────────────────
        char_group = QGroupBox(_("Персонажи (не выбрано = все)", "Characters (none selected = all)"))
        char_layout = QVBoxLayout(char_group)

        self._char_list = QListWidget()
        self._char_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._char_list.setMaximumHeight(110)
        self._char_list.itemSelectionChanged.connect(self._update_count)
        char_layout.addWidget(self._char_list)

        layout.addWidget(char_group)

        # ── Rating filter ─────────────────────────────────────────────────────
        rating_group = QGroupBox(_("Фильтр по рейтингу", "Rating filter"))
        rating_layout = QHBoxLayout(rating_group)

        self._rating_combo = QComboBox()
        self._rating_combo.addItem(_("Все записи", "All records"), None)
        self._rating_combo.addItem(_("Без отрицательных (0+)", "No negatives (0+)"), 0)
        self._rating_combo.addItem(_("Только 👍 положительные", "Only 👍 positive"), 1)
        self._rating_combo.currentIndexChanged.connect(self._update_count)
        rating_layout.addWidget(self._rating_combo)
        rating_layout.addStretch()

        layout.addWidget(rating_group)

        # ── Format ────────────────────────────────────────────────────────────
        fmt_group = QGroupBox(_("Формат экспорта", "Export format"))
        fmt_layout = QVBoxLayout(fmt_group)

        self._fmt_sharegpt = QRadioButton(
            _("ShareGPT / ChatML (для Unsloth, рекомендуется)", "ShareGPT / ChatML (for Unsloth, recommended)")
        )
        self._fmt_sharegpt.setChecked(True)
        self._fmt_raw = QRadioButton(_("Сырой JSONL (со всеми метаданными)", "Raw JSONL (with all metadata)"))

        self._fmt_group = QButtonGroup(self)
        self._fmt_group.addButton(self._fmt_sharegpt, 0)
        self._fmt_group.addButton(self._fmt_raw, 1)

        fmt_layout.addWidget(self._fmt_sharegpt)
        fmt_layout.addWidget(self._fmt_raw)

        layout.addWidget(fmt_group)

        # ── Count + actions ───────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid #444;")
        layout.addWidget(sep)

        bottom = QHBoxLayout()
        self._count_label = QLabel(_("Записей: ...", "Records: ..."))
        self._count_label.setStyleSheet("color: #aaa; font-size: 11px;")
        bottom.addWidget(self._count_label)
        bottom.addStretch()

        self._cancel_btn = QPushButton(_("Отмена", "Cancel"))
        self._cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(self._cancel_btn)

        self._export_btn = QPushButton(_("Экспортировать", "Export"))
        self._export_btn.setObjectName("PrimaryButton")
        self._export_btn.clicked.connect(self._do_export)
        bottom.addWidget(self._export_btn)

        layout.addLayout(bottom)

    # ── Populate ──────────────────────────────────────────────────────────────

    def _populate_characters(self):
        if not self._collector:
            return
        try:
            stats = self._collector.get_stats()
            for char_id, count in sorted(stats.get("by_character", {}).items()):
                item = QListWidgetItem(f"{char_id} ({count})")
                item.setData(Qt.ItemDataRole.UserRole, char_id)
                self._char_list.addItem(item)
        except Exception as e:
            logger.error(f"ExportDialog populate_characters: {e}")

    # ── Filters ───────────────────────────────────────────────────────────────

    def _build_filters(self) -> dict:
        qd_from = self._date_from.date()
        qd_to = self._date_to.date()

        date_from = datetime(
            qd_from.year(), qd_from.month(), qd_from.day(), tzinfo=timezone.utc
        )
        date_to = datetime(
            qd_to.year(), qd_to.month(), qd_to.day(), 23, 59, 59, tzinfo=timezone.utc
        )

        selected_chars = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._char_list.selectedItems()
        ]

        min_rating = self._rating_combo.currentData()

        return {
            "date_from": date_from,
            "date_to": date_to,
            "characters": selected_chars,
            "min_rating": min_rating,
        }

    # ── Count update ──────────────────────────────────────────────────────────

    def _update_count(self):
        if not self._collector:
            self._count_label.setText(_("Сбор данных не активен", "Collector not active"))
            return
        try:
            filters = self._build_filters()
            samples = self._collector.load_samples(filters)
            n = len(samples)
            self._count_label.setText(_("Записей: ", "Records: ") + str(n))
            self._export_btn.setEnabled(n > 0)
        except Exception as e:
            self._count_label.setText(f"Error: {e}")

    # ── Export ────────────────────────────────────────────────────────────────

    def _do_export(self):
        if not self._collector:
            return

        try:
            filters = self._build_filters()
            samples = self._collector.load_samples(filters)
            if not samples:
                QMessageBox.information(
                    self,
                    _("Нет данных", "No data"),
                    _("По выбранным фильтрам записей не найдено.", "No records match the selected filters.")
                )
                return

            is_sharegpt = self._fmt_sharegpt.isChecked()
            ext = ".jsonl"
            if is_sharegpt:
                default_name = "finetune_sharegpt.jsonl"
                filter_str = "JSONL (*.jsonl)"
            else:
                default_name = "finetune_raw.jsonl"
                filter_str = "JSONL (*.jsonl)"

            path, _ = QFileDialog.getSaveFileName(
                self,
                _("Сохранить файл", "Save file"),
                default_name,
                filter_str
            )
            if not path:
                return

            if is_sharegpt:
                count = self._collector.export_sharegpt(samples, path)
            else:
                count = self._collector.export_raw_jsonl(samples, path)

            QMessageBox.information(
                self,
                _("Готово", "Done"),
                _("Экспортировано записей: ", "Exported records: ") + str(count)
            )
            self.accept()

        except Exception as e:
            logger.error(f"ExportDialog export error: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                _("Ошибка", "Error"),
                str(e)
            )
