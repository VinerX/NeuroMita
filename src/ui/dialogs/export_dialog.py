# src/ui/dialogs/export_dialog.py
"""
ExportDialog — диалог экспорта данных для дообучения.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QListWidget, QListWidgetItem,
    QDateEdit, QGroupBox, QComboBox,
    QFileDialog, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QDate

from utils import getTranslationVariant as tr
from main_logger import logger


class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Экспорт данных дообучения", "Export Finetune Data"))
        self.setMinimumWidth(500)
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
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Date range ────────────────────────────────────────────────────────
        date_group = QGroupBox(tr("Диапазон дат", "Date range"))
        date_layout = QHBoxLayout(date_group)
        date_layout.setContentsMargins(10, 14, 10, 10)
        date_layout.setSpacing(8)

        date_layout.addWidget(QLabel(tr("С:", "From:")))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate.currentDate().addMonths(-3))
        self._date_from.dateChanged.connect(self._update_count)
        self._date_from.setFixedWidth(110)
        date_layout.addWidget(self._date_from)

        date_layout.addSpacing(8)
        date_layout.addWidget(QLabel(tr("По:", "To:")))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.dateChanged.connect(self._update_count)
        self._date_to.setFixedWidth(110)
        date_layout.addWidget(self._date_to)
        date_layout.addStretch()

        layout.addWidget(date_group)

        # ── Characters ────────────────────────────────────────────────────────
        char_group = QGroupBox(tr(
            "Персонажи (ничего не отмечено = все)",
            "Characters (nothing checked = all)"
        ))
        char_layout = QVBoxLayout(char_group)
        char_layout.setContentsMargins(10, 14, 10, 10)

        self._char_list = QListWidget()
        self._char_list.setMaximumHeight(100)
        self._char_list.setStyleSheet(
            "QListWidget { background: #2a2a2a; border: 1px solid #555; border-radius: 4px; }"
            "QListWidget::item { padding: 3px 6px; }"
            "QListWidget::item:hover { background: #3a3a3a; }"
        )
        self._char_list.itemChanged.connect(self._update_count)
        char_layout.addWidget(self._char_list)

        layout.addWidget(char_group)

        # ── Rating filter ─────────────────────────────────────────────────────
        rating_group = QGroupBox(tr("Фильтр по рейтингу", "Rating filter"))
        rating_layout = QHBoxLayout(rating_group)
        rating_layout.setContentsMargins(10, 14, 10, 10)

        self._rating_combo = QComboBox()
        self._rating_combo.addItem(tr("Все записи", "All records"), None)
        self._rating_combo.addItem(tr("Без отрицательных (👍 и без оценки)", "No negatives (👍 and unrated)"), 0)
        self._rating_combo.addItem(tr("Только 👍 положительные", "Only 👍 positive"), 1)
        self._rating_combo.currentIndexChanged.connect(self._update_count)
        self._rating_combo.setMinimumWidth(280)
        rating_layout.addWidget(self._rating_combo)
        rating_layout.addStretch()

        layout.addWidget(rating_group)

        # ── Format ────────────────────────────────────────────────────────────
        fmt_group = QGroupBox(tr("Формат экспорта", "Export format"))
        fmt_layout = QVBoxLayout(fmt_group)
        fmt_layout.setContentsMargins(10, 14, 10, 10)
        fmt_layout.setSpacing(6)

        self._fmt_sharegpt = QRadioButton(
            tr("ShareGPT / ChatML (для Unsloth — рекомендуется)", "ShareGPT / ChatML (for Unsloth — recommended)")
        )
        self._fmt_sharegpt.setChecked(True)
        self._fmt_raw = QRadioButton(tr("Сырой JSONL (со всеми метаданными)", "Raw JSONL (with all metadata)"))

        self._fmt_group = QButtonGroup(self)
        self._fmt_group.addButton(self._fmt_sharegpt, 0)
        self._fmt_group.addButton(self._fmt_raw, 1)

        fmt_layout.addWidget(self._fmt_sharegpt)
        fmt_layout.addWidget(self._fmt_raw)

        layout.addWidget(fmt_group)

        # ── Separator + count + buttons ───────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #444; margin-top: 4px;")
        layout.addWidget(sep)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self._count_label = QLabel(tr("Записей: ...", "Records: ..."))
        self._count_label.setStyleSheet("color: #aaa; font-size: 11px;")
        bottom.addWidget(self._count_label)
        bottom.addStretch()

        self._cancel_btn = QPushButton(tr("Отмена", "Cancel"))
        self._cancel_btn.setMinimumWidth(80)
        self._cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(self._cancel_btn)

        self._export_btn = QPushButton(tr("Экспортировать", "Export"))
        self._export_btn.setMinimumWidth(100)
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
                item = QListWidgetItem(f"{char_id}  ({count} {tr('записей', 'records')})")
                item.setData(Qt.ItemDataRole.UserRole, char_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
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

        selected_chars = []
        for i in range(self._char_list.count()):
            item = self._char_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_chars.append(item.data(Qt.ItemDataRole.UserRole))

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
            self._count_label.setText(tr("Сбор данных не активен", "Collector not active"))
            return
        try:
            filters = self._build_filters()
            samples = self._collector.load_samples(filters)
            n = len(samples)
            self._count_label.setText(tr("Записей подходит: ", "Records matched: ") + str(n))
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
                    tr("Нет данных", "No data"),
                    tr("По выбранным фильтрам записей не найдено.", "No records match the selected filters.")
                )
                return

            is_sharegpt = self._fmt_sharegpt.isChecked()
            if is_sharegpt:
                default_name = "finetune_sharegpt.jsonl"
            else:
                default_name = "finetune_raw.jsonl"

            path, _filter = QFileDialog.getSaveFileName(
                self,
                tr("Сохранить файл", "Save file"),
                default_name,
                "JSONL (*.jsonl)"
            )
            if not path:
                return

            if is_sharegpt:
                count = self._collector.export_sharegpt(samples, path)
            else:
                count = self._collector.export_raw_jsonl(samples, path)

            QMessageBox.information(
                self,
                tr("Готово", "Done"),
                tr("Экспортировано записей: ", "Exported records: ") + str(count)
            )
            self.accept()

        except Exception as e:
            logger.error(f"ExportDialog export error: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                tr("Ошибка", "Error"),
                str(e)
            )
