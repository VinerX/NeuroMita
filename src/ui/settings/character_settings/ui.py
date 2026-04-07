# File: src/ui/settings/character_settings/ui.py

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QSizePolicy, QStyle
)
import qtawesome as qta

from ui.gui_templates import create_section_header
from managers.settings_manager import InnerCollapsibleSection
from utils import getTranslationVariant as _


def _make_row(label_text: str, field_widget: QWidget, label_w: int) -> QWidget:
    row = QWidget()
    hl = QHBoxLayout(row)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(6)

    lbl = QLabel(label_text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    lbl.setFixedWidth(label_w)
    hl.addWidget(lbl, 0)

    hl.addWidget(field_widget, 1)
    return row


def _make_info_value_label(self, key: str) -> QLabel:
    lab = QLabel("")
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    lab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    self.prompt_info_labels[key] = lab
    return lab


def _make_separator() -> QWidget:
    sep = QWidget()
    sep.setFixedHeight(1)
    sep.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.12);")
    return sep


def build_character_settings_ui(self, parent_layout):
    try:
        scrollbar_guard = max(12, self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
    except Exception:
        scrollbar_guard = 14

    sidebar_w = getattr(self, "SETTINGS_SIDEBAR_WIDTH", 50)
    right_pad = max(scrollbar_guard, min(18, int(sidebar_w * 0.25)))

    container = QWidget()
    container_lay = QVBoxLayout(container)
    container_lay.setContentsMargins(0, 0, right_pad, 0)
    container_lay.setSpacing(6)

    create_section_header(container_lay, _("Настройки персонажей", "Characters Settings"))

    overlay_w = getattr(self, "SETTINGS_PANEL_WIDTH", 400)
    label_w = max(90, min(120, int(overlay_w * 0.3)))
    self.mic_label_width = label_w

    root = QWidget()
    lay = QVBoxLayout(root)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)

    character_field = QWidget()
    ch_h = QHBoxLayout(character_field)
    ch_h.setContentsMargins(0, 0, 0, 0)
    ch_h.setSpacing(6)

    self.character_combobox = QComboBox()
    self.character_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    ch_h.addWidget(self.character_combobox, 1)
    lay.addWidget(_make_row(_("Персонажи", "Characters"), character_field, label_w))

    prompt_field = QWidget()
    pr_h = QHBoxLayout(prompt_field)
    pr_h.setContentsMargins(0, 0, 0, 0)
    pr_h.setSpacing(6)

    self.prompt_pack_combobox = QComboBox()
    self.prompt_pack_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    pr_h.addWidget(self.prompt_pack_combobox, 1)
    lay.addWidget(_make_row(_("Набор промптов", "Prompt set"), prompt_field, label_w))

    provider_field = QWidget()
    pv_h = QHBoxLayout(provider_field)
    pv_h.setContentsMargins(0, 0, 0, 0)
    pv_h.setSpacing(6)

    self.char_provider_combobox = QComboBox()
    self.char_provider_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    pv_h.addWidget(self.char_provider_combobox, 1)
    lay.addWidget(_make_row(_("Провайдер для персонажа", "Provider for character"), provider_field, label_w))

    sub_title1 = QLabel(_("Управление персонажем", "Character management"))
    sub_title1.setStyleSheet("font-weight: 600;")
    lay.addWidget(sub_title1)

    self.btn_reload_character_data = QPushButton(_("Перезагрузить", "Reload"))
    self.btn_reload_character_data.setObjectName("SecondaryButton")
    self.btn_reload_character_data.setIcon(qta.icon('fa5s.sync', color='#ffffff'))
    self.btn_reload_character_data.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    lay.addWidget(self.btn_reload_character_data)

    mgmt_row = QWidget()
    mg_h = QHBoxLayout(mgmt_row)
    mg_h.setContentsMargins(0, 0, 0, 0)
    mg_h.setSpacing(6)

    self.btn_open_character_folder = QPushButton(_("Открыть папку набора", "Open prompt set folder"))
    self.btn_open_character_folder.setObjectName("SecondaryButton")
    self.btn_open_character_folder.setIcon(qta.icon('fa5s.folder-open', color='#ffffff'))
    mg_h.addWidget(self.btn_open_character_folder, 1)

    self.btn_open_history_folder = QPushButton(_("Папку истории", "History folder"))
    self.btn_open_history_folder.setObjectName("SecondaryButton")
    self.btn_open_history_folder.setIcon(qta.icon('fa5s.clock', color='#ffffff'))
    mg_h.addWidget(self.btn_open_history_folder, 1)

    lay.addWidget(mgmt_row)

    lay.addSpacing(6)

    self.prompt_info_section = InnerCollapsibleSection(_("Информация о наборе", "Set information"), parent=self)
    lay.addWidget(self.prompt_info_section)

    try:
        if getattr(self.prompt_info_section, "is_collapsed", False):
            self.prompt_info_section.toggle()
    except Exception:
        pass

    try:
        self.prompt_info_section.content_layout.setContentsMargins(16, 8, 12, 8)
        self.prompt_info_section.content_layout.setSpacing(8)
    except Exception:
        pass

    self.prompt_info_labels = {}

    self.prompt_info_section.add_widget(
        _make_row(_("Автор:", "Author:"), _make_info_value_label(self, "author"), label_w)
    )
    self.prompt_info_section.add_widget(
        _make_row(_("Версия:", "Version:"), _make_info_value_label(self, "version"), label_w)
    )

    desc_title = QLabel(_("Описание:", "Description:"))
    desc_title.setStyleSheet("font-weight: 600;")
    self.prompt_info_section.add_widget(desc_title)

    self.prompt_info_section.add_widget(_make_info_value_label(self, "description"))

    lay.addSpacing(6)

    # ══════════════════════════════════════════════════════
    # Секция «История» — просмотр, сброс, экспорт, дедупликация
    # ══════════════════════════════════════════════════════

    self.history_section = InnerCollapsibleSection(_("История", "History"), parent=self)
    lay.addWidget(self.history_section)

    try:
        orig_toggle = self.history_section.toggle

        def _toggle_and_save(_=None):
            orig_toggle()
            if hasattr(self, "settings"):
                self.settings.set("SHOW_HISTORY_RESET_SECTION", not self.history_section.is_collapsed)

        self.history_section.header.mousePressEvent = _toggle_and_save
    except Exception:
        pass

    try:
        self.history_section.content_layout.setContentsMargins(16, 8, 12, 8)
        self.history_section.content_layout.setSpacing(8)
    except Exception:
        pass

    def _mark_danger_hover(btn: QPushButton):
        btn.setObjectName("SecondaryButton")
        btn.setProperty("dangerHover", True)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    def _make_compact(btn: QPushButton):
        btn.setProperty("compact", True)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    # -------- Для выбранного персонажа --------
    char_hist_title = QLabel(_("Для выбранного персонажа", "For selected character"))
    char_hist_title.setStyleSheet("font-weight: 600;")
    self.history_section.add_widget(char_hist_title)

    self.btn_db_viewer = QPushButton(_("История", "History"))
    self.btn_db_viewer.setToolTip(_("Просмотр базы данных (истории)", "View database (history)"))
    self.btn_db_viewer.setIcon(qta.icon('fa5s.table', color='#ffffff'))
    self.btn_db_viewer.setObjectName("SecondaryButton")
    _make_compact(self.btn_db_viewer)

    self.btn_clear_history = QPushButton(_("Сброс", "Reset"))
    self.btn_clear_history.setToolTip(_("Сбросить историю персонажа", "Reset character history"))
    self.btn_clear_history.setIcon(qta.icon('fa5s.trash', color='#ffffff'))
    _mark_danger_hover(self.btn_clear_history)
    _make_compact(self.btn_clear_history)

    row_char_1 = QWidget()
    row_char_1_l = QHBoxLayout(row_char_1)
    row_char_1_l.setContentsMargins(0, 0, 0, 0)
    row_char_1_l.setSpacing(6)
    row_char_1_l.addWidget(self.btn_db_viewer, 1)
    row_char_1_l.addWidget(self.btn_clear_history, 1)
    self.history_section.add_widget(row_char_1)

    self.btn_export_db = QPushButton(_("Выгрузить", "Export"))
    self.btn_export_db.setToolTip(_("Выгрузить данные из БД в файл", "Export data from DB to file"))
    self.btn_export_db.setIcon(qta.icon('fa5s.file-export', color='#ffffff'))
    self.btn_export_db.setObjectName("SecondaryButton")
    _make_compact(self.btn_export_db)

    self.btn_import_db = QPushButton(_("Загрузить", "Import"))
    self.btn_import_db.setToolTip(_("Загрузить данные из файла в БД", "Import data from file to DB"))
    self.btn_import_db.setIcon(qta.icon('fa5s.file-import', color='#ffffff'))
    self.btn_import_db.setObjectName("SecondaryButton")
    _make_compact(self.btn_import_db)

    row_char_export = QWidget()
    row_char_export_l = QHBoxLayout(row_char_export)
    row_char_export_l.setContentsMargins(0, 0, 0, 0)
    row_char_export_l.setSpacing(6)
    row_char_export_l.addWidget(self.btn_export_db, 1)
    row_char_export_l.addWidget(self.btn_import_db, 1)
    self.history_section.add_widget(row_char_export)

    self.btn_dedupe_history = QPushButton(_("Удалить дубли", "Remove duplicates"))
    self.btn_dedupe_history.setToolTip(_("Удалить дубликаты сообщений", "Remove duplicate messages"))
    self.btn_dedupe_history.setIcon(qta.icon('fa5s.broom', color='#ffffff'))
    self.btn_dedupe_history.setObjectName("SecondaryButton")
    self.btn_dedupe_history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _make_compact(self.btn_dedupe_history)
    self.history_section.add_widget(self.btn_dedupe_history)

    # -------- Разделитель --------
    self.history_section.add_widget(_make_separator())

    # -------- Для всех персонажей --------
    global_hist_title = QLabel(_("Для всех персонажей", "For all characters"))
    global_hist_title.setStyleSheet("font-weight: 600;")
    self.history_section.add_widget(global_hist_title)

    self.btn_db_viewer_global = QPushButton(_("История (все)", "History (All)"))
    self.btn_db_viewer_global.setToolTip(_("Просмотр базы данных (глобально)", "Global DB viewer"))
    self.btn_db_viewer_global.setIcon(qta.icon('fa5s.table', color='#ffffff'))
    self.btn_db_viewer_global.setObjectName("SecondaryButton")
    _make_compact(self.btn_db_viewer_global)

    self.btn_clear_all_histories = QPushButton(_("Сброс (все)", "Reset (All)"))
    self.btn_clear_all_histories.setToolTip(_("Сбросить историю всех персонажей", "Clear history for all chars"))
    self.btn_clear_all_histories.setIcon(qta.icon('fa5s.trash-alt', color='#ffffff'))
    _mark_danger_hover(self.btn_clear_all_histories)
    _make_compact(self.btn_clear_all_histories)

    row_all_1 = QWidget()
    row_all_1_l = QHBoxLayout(row_all_1)
    row_all_1_l.setContentsMargins(0, 0, 0, 0)
    row_all_1_l.setSpacing(6)
    row_all_1_l.addWidget(self.btn_db_viewer_global, 1)
    row_all_1_l.addWidget(self.btn_clear_all_histories, 1)
    self.history_section.add_widget(row_all_1)

    self.btn_export_db_global = QPushButton(_("Выгрузить (все)", "Export (All)"))
    self.btn_export_db_global.setToolTip(
        _("Выгрузить данные всех персонажей в файл", "Export all characters data to file"))
    self.btn_export_db_global.setIcon(qta.icon('fa5s.file-export', color='#ffffff'))
    self.btn_export_db_global.setObjectName("SecondaryButton")
    _make_compact(self.btn_export_db_global)

    self.btn_import_db_global = QPushButton(_("Загрузить (все)", "Import (All)"))
    self.btn_import_db_global.setToolTip(
        _("Загрузить данные из файла в БД (все персонажи)", "Import data from file to DB (all)"))
    self.btn_import_db_global.setIcon(qta.icon('fa5s.file-import', color='#ffffff'))
    self.btn_import_db_global.setObjectName("SecondaryButton")
    _make_compact(self.btn_import_db_global)

    row_all_export = QWidget()
    row_all_export_l = QHBoxLayout(row_all_export)
    row_all_export_l.setContentsMargins(0, 0, 0, 0)
    row_all_export_l.setSpacing(6)
    row_all_export_l.addWidget(self.btn_export_db_global, 1)
    row_all_export_l.addWidget(self.btn_import_db_global, 1)
    self.history_section.add_widget(row_all_export)

    self.btn_dedupe_all = QPushButton(_("Удалить дубли (все)", "Remove duplicates (All)"))
    self.btn_dedupe_all.setToolTip(_("Удалить дубликаты у всех персонажей", "Remove duplicates for all characters"))
    self.btn_dedupe_all.setIcon(qta.icon('fa5s.broom', color='#ffffff'))
    self.btn_dedupe_all.setObjectName("SecondaryButton")
    self.btn_dedupe_all.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _make_compact(self.btn_dedupe_all)
    self.history_section.add_widget(self.btn_dedupe_all)

    # ══════════════════════════════════════════════════════
    # Секция «Обслуживание» — миграции данных и RAG-индексация
    # ══════════════════════════════════════════════════════

    lay.addSpacing(4)

    self.maintenance_section = InnerCollapsibleSection(_("Обслуживание", "Maintenance"), parent=self)
    lay.addWidget(self.maintenance_section)

    try:
        # Свёрнута по умолчанию
        if not getattr(self.maintenance_section, "is_collapsed", True):
            self.maintenance_section.toggle()
    except Exception:
        pass

    try:
        self.maintenance_section.content_layout.setContentsMargins(16, 8, 12, 8)
        self.maintenance_section.content_layout.setSpacing(8)
    except Exception:
        pass

    # -------- Миграции данных — для выбранного персонажа --------
    mig_char_title = QLabel(_("Для выбранного персонажа", "For selected character"))
    mig_char_title.setStyleSheet("font-weight: 600;")
    self.maintenance_section.add_widget(mig_char_title)

    # "Файлы → БД" — перенос JSON истории в SQLite
    self.btn_migrate_db = QPushButton(_("Файлы → БД", "Files → DB"))
    self.btn_migrate_db.setToolTip(
        _("Перенести историю из JSON-файлов в базу данных SQLite",
          "Import history from JSON files into the SQLite database"))
    self.btn_migrate_db.setIcon(qta.icon('fa5s.database', color='#ffffff'))
    self.btn_migrate_db.setObjectName("SecondaryButton")
    _make_compact(self.btn_migrate_db)

    # "Теги → структуру" — перенос inline-тегов из content в structured_data
    self.btn_migrate_to_structured = QPushButton(_("Теги → структуру", "Tags → structure"))
    self.btn_migrate_to_structured.setToolTip(
        _("Перенести теги из поля content в колонку structured_data",
          "Move inline tags from the content field into the structured_data column"))
    self.btn_migrate_to_structured.setIcon(qta.icon('fa5s.exchange-alt', color='#ffffff'))
    self.btn_migrate_to_structured.setObjectName("SecondaryButton")
    _make_compact(self.btn_migrate_to_structured)

    row_mig_char_1 = QWidget()
    row_mig_char_1_l = QHBoxLayout(row_mig_char_1)
    row_mig_char_1_l.setContentsMargins(0, 0, 0, 0)
    row_mig_char_1_l.setSpacing(6)
    row_mig_char_1_l.addWidget(self.btn_migrate_db, 1)
    row_mig_char_1_l.addWidget(self.btn_migrate_to_structured, 1)
    self.maintenance_section.add_widget(row_mig_char_1)

    # "Обновить формат файла" — конвертировать JSON файл в новый structured формат
    self.btn_migrate_history = QPushButton(_("Обновить формат файла", "Update file format"))
    self.btn_migrate_history.setToolTip(
        _("Конвертировать JSON-файл истории в новый structured формат (создаёт резервную копию)",
          "Convert JSON history file to the new structured format (creates a backup)"))
    self.btn_migrate_history.setObjectName("SecondaryButton")
    self.btn_migrate_history.setIcon(qta.icon('fa5s.file-code', color='#ffffff'))
    self.btn_migrate_history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _make_compact(self.btn_migrate_history)
    self.maintenance_section.add_widget(self.btn_migrate_history)

    # "Индексировать новое" / "Переиндексировать всё" — RAG-векторизация
    self.btn_reindex = QPushButton(_("Индексировать новое", "Index new"))
    self.btn_reindex.setToolTip(
        _("Заполнить отсутствующие векторы для RAG", "Fill missing embedding vectors for RAG"))
    self.btn_reindex.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_reindex.setObjectName("SecondaryButton")
    _make_compact(self.btn_reindex)

    self.btn_reindex_all = QPushButton(_("Переиндексировать всё", "Reindex all"))
    self.btn_reindex_all.setToolTip(
        _("Пересоздать все векторы для RAG (медленно)", "Regenerate ALL embedding vectors for RAG (slow)"))
    self.btn_reindex_all.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_reindex_all.setObjectName("SecondaryButton")
    _make_compact(self.btn_reindex_all)

    row_mig_char_2 = QWidget()
    row_mig_char_2_l = QHBoxLayout(row_mig_char_2)
    row_mig_char_2_l.setContentsMargins(0, 0, 0, 0)
    row_mig_char_2_l.setSpacing(6)
    row_mig_char_2_l.addWidget(self.btn_reindex, 1)
    row_mig_char_2_l.addWidget(self.btn_reindex_all, 1)
    self.maintenance_section.add_widget(row_mig_char_2)

    # -------- Разделитель --------
    self.maintenance_section.add_widget(_make_separator())

    # -------- Миграции данных — для всех персонажей --------
    mig_all_title = QLabel(_("Для всех персонажей", "For all characters"))
    mig_all_title.setStyleSheet("font-weight: 600;")
    self.maintenance_section.add_widget(mig_all_title)

    self.btn_migrate_db_all = QPushButton(_("Файлы → БД (все)", "Files → DB (All)"))
    self.btn_migrate_db_all.setToolTip(
        _("Перенести историю ВСЕХ персонажей из JSON-файлов в SQLite",
          "Import history for ALL characters from JSON files into SQLite"))
    self.btn_migrate_db_all.setIcon(qta.icon('fa5s.database', color='#ffffff'))
    self.btn_migrate_db_all.setObjectName("SecondaryButton")
    _make_compact(self.btn_migrate_db_all)

    self.btn_migrate_to_structured_all = QPushButton(_("Теги → структуру (все)", "Tags → structure (All)"))
    self.btn_migrate_to_structured_all.setToolTip(
        _("Перенести теги из content в structured_data для ВСЕХ персонажей",
          "Move inline tags into structured_data for ALL characters"))
    self.btn_migrate_to_structured_all.setIcon(qta.icon('fa5s.exchange-alt', color='#ffffff'))
    self.btn_migrate_to_structured_all.setObjectName("SecondaryButton")
    _make_compact(self.btn_migrate_to_structured_all)

    row_mig_all_1 = QWidget()
    row_mig_all_1_l = QHBoxLayout(row_mig_all_1)
    row_mig_all_1_l.setContentsMargins(0, 0, 0, 0)
    row_mig_all_1_l.setSpacing(6)
    row_mig_all_1_l.addWidget(self.btn_migrate_db_all, 1)
    row_mig_all_1_l.addWidget(self.btn_migrate_to_structured_all, 1)
    self.maintenance_section.add_widget(row_mig_all_1)

    self.btn_reindex_global = QPushButton(_("Индексировать новое (все)", "Index new (All)"))
    self.btn_reindex_global.setToolTip(
        _("Заполнить отсутствующие векторы для всех персонажей", "Fill missing vectors for all characters"))
    self.btn_reindex_global.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_reindex_global.setObjectName("SecondaryButton")
    _make_compact(self.btn_reindex_global)

    self.btn_reindex_all_global = QPushButton(_("Переиндексировать всё (все)", "Reindex all (All)"))
    self.btn_reindex_all_global.setToolTip(
        _("Пересоздать все векторы для всех персонажей (медленно)",
          "Regenerate ALL vectors for all characters (slow)"))
    self.btn_reindex_all_global.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_reindex_all_global.setObjectName("SecondaryButton")
    _make_compact(self.btn_reindex_all_global)

    row_mig_all_2 = QWidget()
    row_mig_all_2_l = QHBoxLayout(row_mig_all_2)
    row_mig_all_2_l.setContentsMargins(0, 0, 0, 0)
    row_mig_all_2_l.setSpacing(6)
    row_mig_all_2_l.addWidget(self.btn_reindex_global, 1)
    row_mig_all_2_l.addWidget(self.btn_reindex_all_global, 1)
    self.maintenance_section.add_widget(row_mig_all_2)

    # -------- Разделитель --------
    self.maintenance_section.add_widget(_make_separator())

    self.btn_purge_deleted = QPushButton(_("Очистить удалённое (все)", "Purge deleted (All)"))
    self.btn_purge_deleted.setToolTip(
        _("Физически удалить is_deleted=1 записи для всех персонажей с резервной копией",
          "Physically delete is_deleted=1 records for all characters with backup")
    )
    self.btn_purge_deleted.setIcon(qta.icon('fa5s.fire-alt', color='#ffffff'))
    self.btn_purge_deleted.setStyleSheet(
        "QPushButton { background-color: #8b1a1a; color: #ffffff; border-radius: 4px; }"
        "QPushButton:hover { background-color: #b22222; }"
        "QPushButton:pressed { background-color: #6a0f0f; }"
    )
    self.btn_purge_deleted.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _make_compact(self.btn_purge_deleted)
    self.maintenance_section.add_widget(self.btn_purge_deleted)

    container_lay.addWidget(root)
    parent_layout.addWidget(container)
