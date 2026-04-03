# src/ui/settings/data_settings.py
"""
Панель настроек для сбора данных дообучения.
"""
from __future__ import annotations

import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QLabel, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QPushButton, QLineEdit, QFileDialog, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from ui.gui_templates import create_section_header
from utils import getTranslationVariant as _


def setup_data_settings_controls(self, parent):
    create_section_header(parent, _("Данные для дообучения", "Finetune Data"))

    # ── Explanatory info block ────────────────────────────────────────────────
    info_widget = QWidget()
    info_widget.setStyleSheet(
        "QWidget { background: #1e2a1e; border: 1px solid #2d5a2d; border-radius: 6px; }"
    )
    info_layout = QVBoxLayout(info_widget)
    info_layout.setContentsMargins(10, 8, 10, 8)
    info_layout.setSpacing(4)

    desc_label = QLabel(_(
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
    ))
    desc_label.setWordWrap(True)
    desc_label.setStyleSheet(
        "QLabel { background: transparent; border: none; color: #b0c4b0; font-size: 11px; }"
    )
    info_layout.addWidget(desc_label)

    link_label = QLabel(_(
        '📤 Загружать данные сюда: <a href="https://drive.google.com/drive/folders/1_RZPS7nTrHI60ZCLTglKNKc1ijG_Wg7X?usp=drive_link" '
        'style="color:#7ecf7e;">Google Drive — NeuroMita Finetune</a>',

        '📤 Upload data here: <a href="https://drive.google.com/drive/folders/1_RZPS7nTrHI60ZCLTglKNKc1ijG_Wg7X?usp=drive_link" '
        'style="color:#7ecf7e;">Google Drive — NeuroMita Finetune</a>'
    ))
    link_label.setOpenExternalLinks(True)
    link_label.setWordWrap(True)
    link_label.setStyleSheet(
        "QLabel { background: transparent; border: none; color: #b0c4b0; font-size: 11px; }"
    )
    info_layout.addWidget(link_label)

    parent.addWidget(info_widget)

    # ── Collection toggle ─────────────────────────────────────────────────────
    chk = QCheckBox(_("Включить сбор данных", "Enable data collection"))
    chk.setToolTip(_(
        "При включении каждый запрос к модели и ответ сохраняются "
        "в FineTuneData/ для последующего дообучения.",
        "When enabled, every model request and response is saved "
        "to FineTuneData/ for later fine-tuning."
    ))
    try:
        chk.setChecked(bool(self.settings.get("FINETUNE_COLLECTION_ENABLED", False)))
    except Exception:
        pass

    def _on_toggle(state):
        val = state == Qt.CheckState.Checked.value
        try:
            self._save_setting("FINETUNE_COLLECTION_ENABLED", val)
        except Exception:
            pass
        try:
            from managers.finetune_collector import FineTuneCollector
            fc = FineTuneCollector.instance
            if fc:
                fc.set_enabled(val)
        except Exception:
            pass

    chk.stateChanged.connect(_on_toggle)
    parent.addWidget(chk)

    # ── Storage path with folder picker ──────────────────────────────────────
    path_row = QHBoxLayout()
    path_row.setSpacing(6)
    path_row.setContentsMargins(0, 2, 0, 2)

    path_lbl = QLabel(_("📁 Папка:", "📁 Folder:"))
    path_lbl.setStyleSheet("color: #a0a0a0; font-size: 11px; background: transparent; border: none;")
    path_lbl.setFixedWidth(60)
    path_row.addWidget(path_lbl)

    path_edit = QLineEdit(_get_current_data_dir())
    path_edit.setReadOnly(True)
    path_edit.setStyleSheet(
        "QLineEdit { background: #2a2a2a; border: 1px solid #555; border-radius: 4px; "
        "color: #b0b0b0; font-size: 11px; padding: 3px 6px; }"
    )
    path_row.addWidget(path_edit, stretch=1)

    browse_btn = QPushButton(_("Обзор...", "Browse..."))
    browse_btn.setFixedWidth(80)
    browse_btn.setStyleSheet(
        "QPushButton { background: #2a3a2a; border: 1px solid #3a5a3a; border-radius: 4px; "
        "color: #7ecf7e; font-size: 11px; padding: 3px 8px; }"
        "QPushButton:hover { background: #334a33; }"
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
        try:
            from managers.settings_manager import SettingsManager
            SettingsManager.set("FINETUNE_DATA_DIR", chosen)
        except Exception:
            pass
        try:
            from managers.finetune_collector import FineTuneCollector
            fc = FineTuneCollector.instance
            if fc is not None:
                fc.data_dir = Path(new_data_dir)
                fc.data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    browse_btn.clicked.connect(_on_browse)
    path_row.addWidget(browse_btn)

    path_container = QWidget()
    path_container.setObjectName("PathContainer")
    path_container.setStyleSheet("QWidget#PathContainer { background: transparent; border: none; }")
    path_container.setLayout(path_row)
    parent.addWidget(path_container)

    # ── Separator ─────────────────────────────────────────────────────────────
    sep1 = QFrame()
    sep1.setFrameShape(QFrame.Shape.HLine)
    sep1.setStyleSheet("border: none; border-top: 1px solid #333; margin: 4px 0;")
    parent.addWidget(sep1)

    # ── Stats section ─────────────────────────────────────────────────────────
    parent.addWidget(_LiveStatsWidget())

    # ── Separator ─────────────────────────────────────────────────────────────
    sep2 = QFrame()
    sep2.setFrameShape(QFrame.Shape.HLine)
    sep2.setStyleSheet("border: none; border-top: 1px solid #333; margin: 4px 0;")
    parent.addWidget(sep2)

    # ── Export + Clear buttons in one row ─────────────────────────────────────
    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    btn_row.setContentsMargins(0, 0, 0, 0)

    export_btn = QPushButton(_("📤 Экспортировать...", "📤 Export..."))
    export_btn.setToolTip(_(
        "Открыть диалог экспорта с фильтрацией и выбором формата.",
        "Open export dialog with filtering and format selection."
    ))
    export_btn.clicked.connect(lambda: _open_export_dialog(self))
    btn_row.addWidget(export_btn)

    clear_btn = QPushButton(_("🗑 Очистить данные...", "🗑 Clear data..."))
    clear_btn.setToolTip(_(
        "Удалить все накопленные файлы данных дообучения. Действие необратимо.",
        "Delete all accumulated fine-tuning data files. This action is irreversible."
    ))
    clear_btn.clicked.connect(lambda: _clear_all_data(self))
    btn_row.addWidget(clear_btn)

    btn_container = QWidget()
    btn_container.setObjectName("BtnContainer")
    btn_container.setStyleSheet("QWidget#BtnContainer { background: transparent; border: none; }")
    btn_container.setLayout(btn_row)
    parent.addWidget(btn_container)

    # ── Motivation image ──────────────────────────────────────────────────────
    parent.addWidget(_MotivationImage())


# ── Live stats widget ─────────────────────────────────────────────────────────

class _LiveStatsWidget(QFrame):
    """Виджет статистики, пересчитывающийся при каждом показе панели."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: transparent; border: none; }"
            "QLabel { background: transparent; border: none; color: #c8c8c8; font-size: 11px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header_row = QHBoxLayout()
        header_row.setSpacing(6)

        header = QLabel(_("Статистика", "Statistics"))
        header.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #dcdcdc; "
            "padding: 2px 0; background: transparent; border: none;"
        )
        header_row.addWidget(header)
        header_row.addStretch()

        refresh_btn = QPushButton(_("↻ Обновить", "↻ Refresh"))
        refresh_btn.setFixedHeight(22)
        refresh_btn.setStyleSheet(
            "QPushButton { background: #2a3a2a; border: 1px solid #3a5a3a; border-radius: 4px; "
            "color: #7ecf7e; font-size: 10px; padding: 1px 8px; }"
            "QPushButton:hover { background: #334a33; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        header_row.addWidget(refresh_btn)

        layout.addLayout(header_row)

        self._stats_layout = layout

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._refresh()

    def _refresh(self):
        # keep header row (index 0) only
        while self._stats_layout.count() > 1:
            item = self._stats_layout.takeAt(1)
            if item and item.widget():
                item.widget().deleteLater()

        for text in self._build_lines():
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "background: transparent; border: none; color: #c8c8c8; font-size: 11px;"
            )
            lbl.setWordWrap(True)
            self._stats_layout.addWidget(lbl)

    @staticmethod
    def _build_lines() -> list:
        try:
            from managers.finetune_collector import FineTuneCollector
            fc = FineTuneCollector.instance
            if fc is None:
                return [_("Сборщик не инициализирован", "Collector not initialized")]

            stats = fc.get_stats()
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: transparent; border: none; margin-top: 8px;")

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._update_image()

    def _update_image(self):
        total = 0
        try:
            from managers.finetune_collector import FineTuneCollector
            fc = FineTuneCollector.instance
            if fc:
                total = fc.get_stats().get("total", 0)
        except Exception:
            pass

        path = self._IMG_100 if total >= 100 else self._IMG_NORMAL
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            pixmap = pixmap.scaledToWidth(self._WIDTH, Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(pixmap)
        else:
            self.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_current_data_dir() -> str:
    try:
        from managers.settings_manager import SettingsManager
        saved = SettingsManager.get("FINETUNE_DATA_DIR")
        if saved:
            return str(Path(saved) / "FineTuneData")
    except Exception:
        pass
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
        from managers.finetune_collector import FineTuneCollector
        fc = FineTuneCollector.instance
        if fc:
            count = fc.clear_all()
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
        dlg = ExportDialog(gui if hasattr(gui, "isWindow") else None)
        dlg.exec()
    except Exception as e:
        from main_logger import logger
        logger.error(f"Failed to open ExportDialog: {e}", exc_info=True)
