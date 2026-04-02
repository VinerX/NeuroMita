# src/ui/settings/data_settings.py
"""
Панель настроек для сбора данных дообучения.
"""
from __future__ import annotations

import os
from PyQt6.QtWidgets import QPushButton, QLabel
from PyQt6.QtCore import Qt

from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _


def setup_data_settings_controls(self, parent):
    create_section_header(parent, _("Данные для дообучения", "Finetune Data"))

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

    # ── Export button ─────────────────────────────────────────────────────────
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
    ]
    create_settings_section(
        self,
        parent,
        _("Экспорт", "Export"),
        export_config,
        icon_name="fa5s.download",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_data_dir_label() -> str:
    try:
        base = os.environ.get("NEUROMITA_BASE_DIR", os.getcwd())
        path = os.path.join(base, "FineTuneData")
        return path
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
                "label": _("С рейтингом: ", "Rated: ") + f"{rated} (👍 {positive} / 👎 {negative})",
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


def _open_export_dialog(gui):
    try:
        from ui.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(gui if hasattr(gui, "isWindow") else None)
        dlg.exec()
    except Exception as e:
        from main_logger import logger
        logger.error(f"Failed to open ExportDialog: {e}", exc_info=True)
