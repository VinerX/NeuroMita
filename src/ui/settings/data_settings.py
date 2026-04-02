# src/ui/settings/data_settings.py
"""
Панель настроек для сбора данных дообучения.
"""
from __future__ import annotations

import os
from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt

from ui.gui_templates import create_settings_section, create_section_header
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

    # Clickable link to upload destination
    link_label = QLabel(_(
        '📤 Загружать данные сюда: <a href="https://drive.google.com/drive/folders/1yiF5QSS4YHBNrKTHnFnelxHtSgtS6-GL" '
        'style="color:#7ecf7e;">Google Drive — NeuroMita Finetune</a>',

        '📤 Upload data here: <a href="https://drive.google.com/drive/folders/1yiF5QSS4YHBNrKTHnFnelxHtSgtS6-GL" '
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
    collection_config = [
        {
            "label": _("Включить сбор данных", "Enable data collection"),
            "key": "FINETUNE_COLLECTION_ENABLED",
            "type": "checkbutton",
            "default_checkbutton": False,
            "tooltip": _(
                "При включении каждый запрос к модели и ответ сохраняются "
                "в FineTuneData/ для последующего дообучения.",
                "When enabled, every model request and response is saved "
                "to FineTuneData/ for later fine-tuning."
            ),
        },
    ]
    create_settings_section(
        self,
        parent,
        _("Сбор данных", "Data Collection"),
        collection_config,
        icon_name="fa5s.database",
    )

    # ── Storage path info ─────────────────────────────────────────────────────
    path_info_config = [
        {"label": _("Путь хранения:", "Storage path:"), "type": "text"},
        {"label": _get_data_dir_label(), "type": "text"},
    ]
    create_settings_section(
        self,
        parent,
        _("Расположение файлов", "File location"),
        path_info_config,
        icon_name="fa5s.folder-open",
    )

    # ── Stats section ─────────────────────────────────────────────────────────
    stats_config = _build_stats_config()
    create_settings_section(
        self,
        parent,
        _("Статистика", "Statistics"),
        stats_config,
        icon_name="fa5s.chart-bar",
    )

    # ── Export + Clear buttons ────────────────────────────────────────────────
    export_config = [
        {
            "label": _("Экспортировать данные...", "Export data..."),
            "type": "button",
            "command": lambda: _open_export_dialog(self),
            "tooltip": _(
                "Открыть диалог экспорта с фильтрацией и выбором формата.",
                "Open export dialog with filtering and format selection."
            ),
        },
        {
            "label": _("Очистить все данные...", "Clear all data..."),
            "type": "button",
            "command": lambda: _clear_all_data(self),
            "tooltip": _(
                "Удалить все накопленные файлы данных дообучения. Действие необратимо.",
                "Delete all accumulated fine-tuning data files. This action is irreversible."
            ),
        },
    ]
    create_settings_section(
        self,
        parent,
        _("Экспорт / Очистка", "Export / Clear"),
        export_config,
        icon_name="fa5s.download",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_data_dir_label() -> str:
    try:
        base = os.environ.get("NEUROMITA_BASE_DIR", os.getcwd())
        return os.path.join(base, "FineTuneData")
    except Exception:
        return "FineTuneData/"


def _build_stats_config() -> list:
    try:
        from managers.finetune_collector import FineTuneCollector
        fc = FineTuneCollector.instance
        if fc is None:
            return [{"label": _("Сборщик не инициализирован", "Collector not initialized"), "type": "text"}]

        stats = fc.get_stats()
        total = stats.get("total", 0)
        rated = stats.get("rated", 0)
        positive = stats.get("positive", 0)
        negative = stats.get("negative", 0)

        lines = [
            {
                "label": _("Всего записей: ", "Total records: ") + str(total),
                "type": "text",
            },
            {
                "label": _("С рейтингом: ", "Rated: ") + f"{rated}  (👍 {positive} / 👎 {negative})",
                "type": "text",
            },
        ]

        by_char = stats.get("by_character", {})
        if by_char:
            lines.append({"label": _("По персонажам:", "By character:"), "type": "text"})
            for char_id, cnt in sorted(by_char.items()):
                lines.append({"label": f"  {char_id}: {cnt}", "type": "text"})

        return lines

    except Exception as e:
        return [{"label": f"Error: {e}", "type": "text"}]


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
