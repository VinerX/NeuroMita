# src/ui/settings/data_settings.py
"""
Панель настроек для сбора данных дообучения.
"""
from __future__ import annotations

import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QPushButton, QLineEdit, QFileDialog, QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from ui.presentation import run_ui_async as run_async
import qtawesome as qta

from ui.gui_templates import create_section_header, SettingsBodyWidget
from utils import getTranslationVariant as _
from localization.live import tr_set, register_if_tr


def setup_data_settings_controls(self, parent):
    create_section_header(parent, _("Данные для дообучения", "Finetune Data"))

    # ── Explanatory info block ────────────────────────────────────────────────
    info_widget = SettingsBodyWidget()
    info_layout = QVBoxLayout(info_widget)
    info_layout.setContentsMargins(10, 8, 10, 8)
    info_layout.setSpacing(4)

    _desc_tr = _(
        "При включённом сборе каждый диалог с моделью сохраняется локально "
        "вместе с метаданными (модель, провайдер, температура, персонаж). "
        "Накопленные данные можно выгрузить и использовать для дообучения "
        "через Unsloth или другие инструменты.\n\n"
        "⚠ Файлы могут занять значительное место: каждый запрос включает "
        "полный системный промт и историю (~20 сообщений).",

        "When collection is enabled, every model dialogue is saved locally "
        "with metadata (model, provider, temperature, character). "
        "Collected data can be exported and used for fine-tuning "
        "via Unsloth or other tools.\n\n"
        "⚠ Files can take significant space: each request includes "
        "the full system prompt and history (~20 messages)."
    )
    desc_label = QLabel(_desc_tr)
    register_if_tr(desc_label, _desc_tr)
    desc_label.setWordWrap(True)
    desc_label.setStyleSheet(
        "QLabel { background: transparent; border: none; color: #bca9bb; font-size: 11px; }"
    )
    info_layout.addWidget(desc_label)

    _link_tr = _(
        'Загружать данные сюда: <a href="https://drive.google.com/drive/folders/1_RZPS7nTrHI60ZCLTglKNKc1ijG_Wg7X?usp=drive_link" '
        'style="color:#7bc6ff;">Google Drive — NeuroMita Finetune</a>',

        'Upload data here: <a href="https://drive.google.com/drive/folders/1_RZPS7nTrHI60ZCLTglKNKc1ijG_Wg7X?usp=drive_link" '
        'style="color:#7bc6ff;">Google Drive — NeuroMita Finetune</a>'
    )
    link_label = QLabel(_link_tr)
    register_if_tr(link_label, _link_tr)
    link_label.setOpenExternalLinks(True)
    link_label.setWordWrap(True)
    link_label.setStyleSheet(
        "QLabel { background: transparent; border: none; color: #bca9bb; font-size: 11px; }"
    )
    info_layout.addWidget(link_label)

    parent.addWidget(info_widget)

    # ── Collection toggle ─────────────────────────────────────────────────────
    chk = tr_set(QCheckBox(), "Включить сбор данных", "Enable data collection")
    chk.setStyleSheet("background: transparent; border: none;")
    tr_set(chk, "При включении каждый запрос к модели и ответ сохраняются "
        "в FineTuneData/ для последующего дообучения.",
        "When enabled, every model request and response is saved "
        "to FineTuneData/ for later fine-tuning.", "setToolTip")
    try:
        chk.setChecked(bool(self.settings.get("FINETUNE_COLLECTION_ENABLED", True)))
    except Exception:
        pass

    def _on_toggle(state):
        val = state == Qt.CheckState.Checked.value
        try:
            self._save_setting("FINETUNE_COLLECTION_ENABLED", val)
        except Exception:
            pass

    chk.stateChanged.connect(_on_toggle)
    parent.addWidget(chk)

    rating_chk = tr_set(QCheckBox(), "Показывать элементы оценки", "Show rating controls")
    rating_chk.setStyleSheet("background: transparent; border: none;")
    tr_set(rating_chk, "Показывать кнопки оценки на пузырьках ответов ассистента. Работает только при включённом сборе данных.",
        "Show rating buttons on assistant message bubbles. Works only when data collection is enabled.", "setToolTip")
    try:
        rating_chk.setChecked(bool(self.settings.get("SHOW_MESSAGE_RATING_CONTROLS", False)))
    except Exception:
        pass

    def _on_rating_toggle(state):
        val = state == Qt.CheckState.Checked.value
        try:
            self._save_setting("SHOW_MESSAGE_RATING_CONTROLS", val)
        except Exception:
            pass

    rating_chk.stateChanged.connect(_on_rating_toggle)
    parent.addWidget(rating_chk)

    # ── Record limit (keep last N) + unlimited ────────────────────────────────
    # Default keeps only the last 50 samples so the latest requests stay easy to
    # inspect/debug without the store growing unbounded. "Без лимита" disables
    # the cap for accumulating a full fine-tuning corpus.
    limit_row = QHBoxLayout()
    limit_row.setSpacing(8)
    limit_row.setContentsMargins(0, 2, 0, 2)

    limit_lbl = tr_set(QLabel(), "Хранить последних:", "Keep last:")
    limit_lbl.setStyleSheet("color: #bca9bb; font-size: 11px; background: transparent; border: none;")
    limit_row.addWidget(limit_lbl)

    from PyQt6.QtWidgets import QSpinBox
    limit_spin = QSpinBox()
    limit_spin.setRange(1, 1_000_000)
    limit_spin.setFixedWidth(110)
    try:
        limit_spin.setValue(int(self.settings.get("FINETUNE_MAX_RECORDS", 50) or 50))
    except Exception:
        limit_spin.setValue(50)
    limit_spin.setSuffix(_(" записей", " records"))
    tr_set(limit_spin, "Сколько последних записей хранить. Старые удаляются автоматически.",
        "How many most-recent records to keep. Older ones are pruned automatically.", "setToolTip")
    limit_spin.setStyleSheet(
        "QSpinBox { background: transparent; border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; "
        "color: #f3edf6; font-size: 11px; padding: 5px 8px; }"
    )
    limit_row.addWidget(limit_spin)

    unlimited_chk = tr_set(QCheckBox(), "Без лимита", "Unlimited")
    unlimited_chk.setStyleSheet("background: transparent; border: none; color: #bca9bb; font-size: 11px;")
    tr_set(unlimited_chk, "Хранить все записи без ограничения. Может занять много места.",
        "Keep all records with no cap. May use a lot of disk space.", "setToolTip")
    try:
        unlimited_chk.setChecked(bool(self.settings.get("FINETUNE_UNLIMITED", False)))
    except Exception:
        pass
    limit_row.addWidget(unlimited_chk)
    limit_row.addStretch()

    def _apply_limit_now():
        try:
            self.presentation.finetune.enforce_limit()
        except Exception:
            pass

    def _on_limit_changed(value):
        try:
            self._save_setting("FINETUNE_MAX_RECORDS", int(value))
        except Exception:
            pass
        if not unlimited_chk.isChecked():
            _apply_limit_now()

    def _on_unlimited_toggled(state):
        val = state == Qt.CheckState.Checked.value
        try:
            self._save_setting("FINETUNE_UNLIMITED", val)
        except Exception:
            pass
        limit_spin.setDisabled(val)
        if not val:
            _apply_limit_now()

    limit_spin.valueChanged.connect(_on_limit_changed)
    unlimited_chk.stateChanged.connect(_on_unlimited_toggled)
    limit_spin.setDisabled(unlimited_chk.isChecked())

    limit_container = SettingsBodyWidget()
    limit_container.setLayout(limit_row)
    parent.addWidget(limit_container)

    # ── Storage path with folder picker ──────────────────────────────────────
    path_row = QHBoxLayout()
    path_row.setSpacing(6)
    path_row.setContentsMargins(0, 2, 0, 2)

    path_lbl = tr_set(QLabel(), "Папка:", "Folder:")
    path_lbl.setStyleSheet("color: #bca9bb; font-size: 11px; background: transparent; border: none;")
    path_lbl.setFixedWidth(60)
    path_row.addWidget(path_lbl)

    path_edit = QLineEdit(_get_current_data_dir(self.presentation.settings))
    path_edit.setReadOnly(True)
    path_edit.setStyleSheet(
        "QLineEdit { background: transparent; border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; "
        "color: #bca9bb; font-size: 11px; padding: 6px 10px; }"
    )
    path_row.addWidget(path_edit, stretch=1)

    browse_btn = tr_set(QPushButton(), "Обзор...", "Browse...")
    browse_btn.setFixedWidth(80)
    browse_btn.setStyleSheet(
        "QPushButton { background: #b74b7d; color: #ffffff; font-weight: 600; border: 1px solid rgba(183, 75, 125,0.46); border-radius: 10px; "
        "font-size: 11px; padding: 7px 14px; }"
        "QPushButton:hover { background: #c04c80; }"
    )

    def _on_browse():
        chosen = QFileDialog.getExistingDirectory(
            None,
            _("Выберите папку для хранения данных", "Choose data storage folder"),
            path_edit.text(),
        )
        if not chosen:
            return
        new_data_dir = str(Path(chosen) / "FineTuneData")
        path_edit.setText(new_data_dir)
        self.presentation.settings.set("FINETUNE_DATA_DIR", chosen)
        try:
            self.presentation.finetune.set_data_directory(new_data_dir)
        except Exception:
            pass

    browse_btn.clicked.connect(_on_browse)
    path_row.addWidget(browse_btn)

    path_container = SettingsBodyWidget()
    path_container.setLayout(path_row)
    parent.addWidget(path_container)

    # ── Separator ─────────────────────────────────────────────────────────────
    sep1 = QFrame()
    sep1.setFrameShape(QFrame.Shape.HLine)
    sep1.setStyleSheet("border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 4px 0;")
    parent.addWidget(sep1)

    # ── Stats section ─────────────────────────────────────────────────────────
    parent.addWidget(_LiveStatsWidget(self.presentation.finetune, parent=self))

    # ── Separator ─────────────────────────────────────────────────────────────
    sep2 = QFrame()
    sep2.setFrameShape(QFrame.Shape.HLine)
    sep2.setStyleSheet("border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 4px 0;")
    parent.addWidget(sep2)

    # ── Export + Clear buttons in one row ─────────────────────────────────────
    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    btn_row.setContentsMargins(0, 0, 0, 0)

    export_btn = tr_set(QPushButton(), "Экспортировать...", "Export...")
    export_btn.setIcon(qta.icon("fa6s.file-export", color="#ffffff"))
    tr_set(export_btn, "Открыть диалог экспорта с фильтрацией и выбором формата.",
        "Open export dialog with filtering and format selection.", "setToolTip")
    export_btn.clicked.connect(lambda: _open_export_dialog(self))
    btn_row.addWidget(export_btn)

    clear_btn = tr_set(QPushButton(), "Очистить данные...", "Clear data...")
    clear_btn.setIcon(qta.icon("fa6s.trash-can", color="#ffffff"))
    tr_set(clear_btn, "Удалить все накопленные файлы данных дообучения. Действие необратимо.",
        "Delete all accumulated fine-tuning data files. This action is irreversible.", "setToolTip")
    clear_btn.clicked.connect(lambda: _clear_all_data(self))
    btn_row.addWidget(clear_btn)

    btn_container = SettingsBodyWidget()
    btn_container.setLayout(btn_row)
    parent.addWidget(btn_container)

    # ── Motivation image ──────────────────────────────────────────────────────
    parent.addWidget(_MotivationImage(self.presentation.finetune, parent=self))


# ── Live stats widget ─────────────────────────────────────────────────────────

class _LiveStatsWidget(QFrame):
    """Виджет статистики, пересчитывающийся при каждом показе панели."""

    _lines_ready = pyqtSignal(list)

    def __init__(self, finetune_controller, parent=None):
        super().__init__(parent)
        self._finetune = finetune_controller
        self._lines_ready.connect(self._apply_lines)
        self.setStyleSheet(
            "QFrame { background: transparent; border: none; }"
            "QLabel { background: transparent; border: none; color: #bca9bb; font-size: 11px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header_row = QHBoxLayout()
        header_row.setSpacing(6)

        header = tr_set(QLabel(), "Статистика", "Statistics")
        header.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #f3edf6; "
            "padding: 2px 0; background: transparent; border: none;"
        )
        header_row.addWidget(header)
        header_row.addStretch()

        refresh_btn = tr_set(QPushButton(), "Обновить", "Refresh")
        refresh_btn.setIcon(qta.icon("fa6s.rotate", color="#ffffff"))
        refresh_btn.setFixedHeight(22)
        refresh_btn.setStyleSheet(
            "QPushButton { background: #b74b7d; color: #ffffff; font-weight: 600; border: 1px solid rgba(183, 75, 125,0.46); border-radius: 10px; "
            "font-size: 10px; padding: 4px 10px; }"
            "QPushButton:hover { background: #c04c80; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        header_row.addWidget(refresh_btn)

        layout.addLayout(header_row)

        self._stats_layout = layout

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._refresh()

    def _refresh(self):
        # Парсинг jsonl может быть тяжёлым — считаем в фоне, чтобы не морозить GUI
        # при открытии вкладки. Пока считается — плейсхолдер.
        self._apply_lines([_("Загрузка статистики…", "Loading statistics…")])
        run_async(self, self._compute_async, name="data-statistics-compute")

    def _compute_async(self):
        lines = self._build_lines()
        try:
            self._lines_ready.emit(lines)
        except Exception:
            pass

    def _apply_lines(self, lines: list):
        # keep header row (index 0) only
        while self._stats_layout.count() > 1:
            item = self._stats_layout.takeAt(1)
            if item and item.widget():
                item.widget().deleteLater()

        for text in lines:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "background: transparent; border: none; color: #bca9bb; font-size: 11px;"
            )
            lbl.setWordWrap(True)
            self._stats_layout.addWidget(lbl)

    def _build_lines(self) -> list:
        try:
            if not self._finetune.available():
                return [_("Сборщик не инициализирован", "Collector not initialized")]

            stats = self._finetune.get_stats()
            total    = stats.get("total", 0)
            rated    = stats.get("rated", 0)
            positive = stats.get("positive", 0)
            negative = stats.get("negative", 0)

            lines = [
                _("Всего записей: ", "Total records: ") + str(total),
                _("С рейтингом: ", "Rated: ") + f"{rated}  (👍 {positive} / 👎 {negative})",
            ]

            by_char = stats.get("by_character", {})
            if by_char:
                lines.append(_("По персонажам:", "By character:"))
                for char_id, cnt in sorted(by_char.items()):
                    lines.append(f"   {char_id}: {cnt}")

            return lines
        except Exception as e:
            return [f"Error: {e}"]


# ── Motivation image widget ───────────────────────────────────────────────────

class _MotivationImage(QLabel):
    """Картинка внизу панели. При 100+ записях показывает пасхалку."""

    _IMG_NORMAL = os.path.join("assets", "finetune_motivation.png")
    _IMG_100    = os.path.join("assets", "finetune_motivation_100.png")
    _WIDTH      = 360

    _total_ready = pyqtSignal(int)

    def __init__(self, finetune_controller, parent=None):
        super().__init__(parent)
        self._finetune = finetune_controller
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: transparent; border: none; margin-top: 8px;")
        self._total_ready.connect(self._apply_total)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        # get_stats() дорогой — считаем в фоне, картинку ставим по готовности.
        run_async(self, self._compute_async, name="finetune-total-compute")

    def _compute_async(self):
        total = 0
        try:
            total = self._finetune.get_stats().get("total", 0)
        except Exception:
            pass
        try:
            self._total_ready.emit(int(total))
        except Exception:
            pass

    def _apply_total(self, total: int):
        path = self._IMG_100 if total >= 100 else self._IMG_NORMAL
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            pixmap = pixmap.scaledToWidth(self._WIDTH, Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(pixmap)
        else:
            self.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_current_data_dir(settings) -> str:
    saved = settings.get("FINETUNE_DATA_DIR")
    if saved:
        return str(Path(saved) / "FineTuneData")
    base = os.environ.get("NEUROMITA_BASE_DIR", os.getcwd())
    return os.path.join(base, "FineTuneData")


def _clear_all_data(gui):
    try:
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            None,
            _("Подтверждение", "Confirmation"),
            _(
                "Удалить все файлы данных дообучения?\nЭто действие необратимо.",
                "Delete all fine-tuning data files?\nThis action is irreversible."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if gui.presentation.finetune.available():
            count = gui.presentation.finetune.clear_all()
            QMessageBox.information(
                None,
                _("Готово", "Done"),
                _("Удалено файлов: ", "Files deleted: ") + str(count),
            )
    except Exception as e:
        from main_logger import logger
        logger.error(f"Failed to clear finetune data: {e}", exc_info=True)


def _open_export_dialog(gui):
    try:
        from ui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(gui.presentation.finetune, gui if hasattr(gui, "isWindow") else None)
        dlg.exec()
    except Exception as e:
        from main_logger import logger
        logger.error(f"Failed to open ExportDialog: {e}", exc_info=True)
