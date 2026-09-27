# File: src/ui/settings/character_settings/ui.py

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QSizePolicy, QStyle, QFrame, QLineEdit, QListWidget, QGridLayout
)
import qtawesome as qta

from ui.gui_templates import SettingsBodyWidget
from ui.widgets.tr_combobox import TRQComboBox
from ui.widgets.settings_sections import InnerCollapsibleSection, CollapsibleSection
from utils import getTranslationVariant as _
from localization.live import register_if_tr, tr_set, register
from styles.theme import THEME
from ui.character_names import character_display_name, retranslate_character_list
from .action_titles import ACTION_TITLES
from .widgets import CharacterWorkspace, CharacterWorkspaceSplitter, CharacterSection, CharacterListDelegate, tab_page


def _make_row(label_text: str, field_widget: QWidget, label_w: int) -> QWidget:
    row = SettingsBodyWidget()
    hl = QVBoxLayout(row)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(6)

    lbl = QLabel(label_text)
    register_if_tr(lbl, label_text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    hl.addWidget(lbl, 0)

    hl.addWidget(field_widget)
    return row


def _make_info_row(label_text: str, field_widget: QWidget) -> QWidget:
    """Строка «ключ: значение» для блока «Информация о наборе».

    В отличие от _make_row, не фиксирует ширину подписи в 120px (короткие
    «Автор:»/«Версия:» иначе отгоняют значение далеко вправо) и не добавляет
    левый отступ — чтобы подписи вставали по тому же краю, что и «Описание:».
    """
    row = SettingsBodyWidget()
    row.setObjectName("SettingRow")
    hl = QHBoxLayout(row)
    hl.setContentsMargins(0, 2, 0, 2)
    hl.setSpacing(8)

    lbl = QLabel(label_text)
    register_if_tr(lbl, label_text)
    lbl.setStyleSheet("font-weight: 600;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
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
    sep = SettingsBodyWidget()
    sep.setFixedHeight(1)
    sep.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.12);")
    return sep


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


def _btn_row(*widgets) -> QWidget:
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for button in widgets:
        action = QWidget()
        action.setObjectName("CharacterActionRow")
        line = QHBoxLayout(action)
        line.setContentsMargins(0, 4, 0, 4)
        line.setSpacing(14)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        title = QLabel(button.text())
        title.setObjectName("CharacterActionTitle")
        action_key = button.property("actionTitle")
        if action_key in ACTION_TITLES:
            tr_set(title, *ACTION_TITLES[action_key])
        else:
            register(title, lambda label, source=button: label.setText(source.text()))
        copy.addWidget(title)
        if button.toolTip():
            description = QLabel(button.toolTip())
            description.setWordWrap(True)
            description.setObjectName("CharacterActionDescription")
            register(description, lambda label, source=button: label.setText(source.toolTip()))
            copy.addWidget(description)
        line.addLayout(copy, 1)
        button.setMinimumWidth(180)
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        line.addWidget(button)
        layout.addWidget(action)
    return row


_DANGER_QSS = (
    f'QPushButton {{ background: {THEME["bg_root"]}; color: {THEME["danger"]}; '
    f'border: 1px solid {THEME["danger"]}; border-radius: 8px; }}'
    f'QPushButton:hover {{ background: {THEME["warn_bg"]}; }}'
)


def _build_char_config_panel(self, label_w: int) -> QWidget:
    panel = QWidget()
    grid = QGridLayout(panel)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(12)
    left_column = QWidget()
    left_layout = QVBoxLayout(left_column)
    left_layout.setContentsMargins(0, 0, 0, 0)
    left_layout.setSpacing(12)
    left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    right_column = QWidget()
    right_layout = QVBoxLayout(right_column)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(12)
    right_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    grid.addWidget(left_column, 0, 0, 1, 2)
    grid.addWidget(right_column, 1, 0, 1, 2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    grid.setRowStretch(3, 1)
    prompt_section = CollapsibleSection(_("Набор промптов", "Prompt set"), icon_name="fa5s.file-alt")
    self.character_prompt_section = prompt_section
    prompt_section.expand()
    left_layout.addWidget(prompt_section)
    main_layout = left_layout
    prompt_layout = prompt_section.content_layout
    history_section = CollapsibleSection(_("История персонажа", "Character history"), icon_name="fa5s.history")
    self.character_history_section = history_section
    right_layout.addWidget(history_section)
    history_layout = history_section.content_layout
    maintenance_layout = right_layout
    lay = prompt_layout

    # -------- Набор промптов + провайдер --------
    prompt_field = SettingsBodyWidget()
    pr_h = QHBoxLayout(prompt_field)
    pr_h.setContentsMargins(0, 0, 0, 0)
    pr_h.setSpacing(6)
    self.prompt_pack_combobox = TRQComboBox()
    self.prompt_pack_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    pr_h.addWidget(self.prompt_pack_combobox, 1)
    lay.addWidget(prompt_field)

    provider_field = SettingsBodyWidget()
    pv_h = QHBoxLayout(provider_field)
    pv_h.setContentsMargins(0, 0, 0, 0)
    pv_h.setSpacing(6)
    self.char_provider_combobox = TRQComboBox()
    self.char_provider_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    pv_h.addWidget(self.char_provider_combobox, 1)
    provider_section = CollapsibleSection(_("Провайдер для персонажа", "Provider for character"), icon_name="fa5s.plug")
    self.character_provider_section = provider_section
    provider_section.add_widget(provider_field)

    lay = prompt_layout

    # -------- Управление набором --------
    self.btn_reload_character_data = tr_set(QPushButton(), "Перезагрузить", "Reload")
    self.btn_reload_character_data.setObjectName("SecondaryButton")
    self.btn_reload_character_data.setIcon(qta.icon('fa5s.sync', color=THEME["text"]))
    self.btn_reload_character_data.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    lay.addWidget(self.btn_reload_character_data)

    mgmt_row = SettingsBodyWidget()
    mg_h = QHBoxLayout(mgmt_row)
    mg_h.setContentsMargins(0, 0, 0, 0)
    mg_h.setSpacing(6)
    self.btn_open_character_folder = tr_set(QPushButton(), "Открыть папку набора", "Open prompt set folder")
    self.btn_open_character_folder.setObjectName("SecondaryButton")
    self.btn_open_character_folder.setIcon(qta.icon('fa5s.folder-open', color=THEME["text"]))
    mg_h.addWidget(self.btn_open_character_folder, 1)
    self.btn_open_history_folder = tr_set(QPushButton(), "Папку истории", "History folder")
    self.btn_open_history_folder.setObjectName("SecondaryButton")
    self.btn_open_history_folder.setIcon(qta.icon('fa5s.clock', color=THEME["text"]))
    mg_h.addWidget(self.btn_open_history_folder, 1)
    lay.addWidget(mgmt_row)

    lay.addSpacing(6)

    lay = prompt_layout

    # -------- Информация о наборе (автор/версия/описание) --------
    self.prompt_info_section = SettingsBodyWidget()
    self.prompt_info_section.content_layout = QVBoxLayout(self.prompt_info_section)
    self.prompt_info_section.content_layout.setContentsMargins(0, 0, 0, 0)
    self.prompt_info_section.content_layout.setSpacing(4)
    lay.addWidget(self.prompt_info_section)
    self.prompt_info_labels = {}
    self.prompt_info_section.content_layout.addWidget(
        _make_info_row(_("Автор:", "Author:"), _make_info_value_label(self, "author"))
    )
    self.prompt_info_section.content_layout.addWidget(
        _make_info_row(_("Версия:", "Version:"), _make_info_value_label(self, "version"))
    )
    desc_title = tr_set(QLabel(), "Описание:", "Description:")
    desc_title.setStyleSheet("font-weight: 600;")
    self.prompt_info_section.content_layout.addWidget(desc_title)
    self.prompt_info_section.content_layout.addWidget(_make_info_value_label(self, "description"))

    prompt_layout.removeWidget(self.btn_reload_character_data)
    prompt_layout.removeWidget(mgmt_row)
    prompt_layout.addWidget(mgmt_row)
    mg_h.addWidget(self.btn_reload_character_data, 1)

    lay.addSpacing(6)

    left_layout.addWidget(provider_section)
    history_layout.addWidget(self.btn_open_history_folder)
    lay = history_layout

    # -------- История этого персонажа --------

    self.btn_history_view = tr_set(QPushButton(), "Открыть историю", "Open history")
    self.btn_history_view.setProperty("actionTitle", "history_view")
    tr_set(self.btn_history_view, "Просмотр базы данных истории", "View the history database", "setToolTip")
    self.btn_history_view.setIcon(qta.icon('fa5s.table', color=THEME["text"]))
    self.btn_history_view.setObjectName("SecondaryButton")
    _make_compact(self.btn_history_view)

    self.btn_history_export = tr_set(QPushButton(), "Выгрузить", "Export")
    self.btn_history_export.setProperty("actionTitle", "history_export")
    tr_set(self.btn_history_export, "Выгрузить данные из БД в файл", "Export data from DB to file", "setToolTip")
    self.btn_history_export.setIcon(qta.icon('fa5s.file-export', color=THEME["text"]))
    self.btn_history_export.setObjectName("SecondaryButton")
    _make_compact(self.btn_history_export)

    self.btn_history_import = tr_set(QPushButton(), "Загрузить", "Import")
    self.btn_history_import.setProperty("actionTitle", "history_import")
    tr_set(self.btn_history_import, "Загрузить данные из файла в БД", "Import data from file to DB", "setToolTip")
    self.btn_history_import.setIcon(qta.icon('fa5s.file-import', color=THEME["text"]))
    self.btn_history_import.setObjectName("SecondaryButton")
    _make_compact(self.btn_history_import)

    self.btn_history_reset = tr_set(QPushButton(), "Очистить историю", "Clear history")
    self.btn_history_reset.setProperty("actionTitle", "history_reset")
    tr_set(self.btn_history_reset, "Удалить историю переписки этого персонажа", "Delete this character's chat history", "setToolTip")
    self.btn_history_reset.setIcon(qta.icon('fa5s.undo-alt', color=THEME["text"]))
    _mark_danger_hover(self.btn_history_reset)
    _make_compact(self.btn_history_reset)

    lay.addWidget(_btn_row(self.btn_history_view, self.btn_history_export))
    lay.addWidget(_btn_row(self.btn_history_import, self.btn_history_reset))

    lay.addSpacing(4)

    lay = maintenance_layout

    # -------- Обслуживание (свёрнуто) — для этого персонажа --------
    self.maintenance_section = CollapsibleSection(_("Обслуживание", "Maintenance"), icon_name="fa5s.cog")
    lay.addWidget(self.maintenance_section)
    try:
        self.maintenance_section.content_layout.setContentsMargins(16, 8, 12, 8)
        self.maintenance_section.content_layout.setSpacing(8)
    except Exception:
        pass

    maint_hint = tr_set(QLabel(),
        "Действия применяются к этому персонажу.",
        "Actions apply to this character.")
    maint_hint.setObjectName("SeparatorLabel")
    maint_hint.setWordWrap(True)
    self.maintenance_section.add_widget(maint_hint)

    self.btn_maint_files_db = tr_set(QPushButton(), "Файлы → БД", "Files → DB")
    self.btn_maint_files_db.setProperty("actionTitle", "files_db")
    tr_set(self.btn_maint_files_db, "Перенести историю из JSON-файлов в базу данных SQLite",
          "Import history from JSON files into the SQLite database", "setToolTip")
    self.btn_maint_files_db.setIcon(qta.icon('fa5s.database', color=THEME["text"]))
    self.btn_maint_files_db.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_files_db)

    self.btn_maint_legacy_recovery = tr_set(QPushButton(), "Восстановить старую память…", "Restore old memory…")
    self.btn_maint_legacy_recovery.setProperty("actionTitle", "legacy_recovery")
    tr_set(self.btn_maint_legacy_recovery,
           "Выбрать ZIP, папку или JSON-файлы старого сохранения и восстановить их с предпросмотром",
           "Choose a ZIP, folder, or JSON files from an old backup and restore them with a preview", "setToolTip")
    self.btn_maint_legacy_recovery.setIcon(qta.icon('fa5s.life-ring', color=THEME["text"]))
    self.btn_maint_legacy_recovery.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_legacy_recovery)

    self.btn_maint_tags = tr_set(QPushButton(), "Теги → данные", "Tags → data")
    self.btn_maint_tags.setProperty("actionTitle", "tags")
    tr_set(self.btn_maint_tags, "Перенести теги из поля content в колонку structured_data",
          "Move inline tags from the content field into the structured_data column", "setToolTip")
    self.btn_maint_tags.setIcon(qta.icon('fa5s.exchange-alt', color=THEME["text"]))
    self.btn_maint_tags.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_tags)

    self.maintenance_section.add_widget(_btn_row(self.btn_maint_files_db, self.btn_maint_tags))
    self.maintenance_section.add_widget(_btn_row(self.btn_maint_legacy_recovery))

    self.btn_maint_index_new = tr_set(QPushButton(), "Индекс нового", "Index new")
    self.btn_maint_index_new.setProperty("actionTitle", "index_new")
    tr_set(self.btn_maint_index_new, "Заполнить отсутствующие векторы для RAG", "Fill missing embedding vectors for RAG", "setToolTip")
    self.btn_maint_index_new.setIcon(qta.icon('fa5s.brain', color=THEME["text"]))
    self.btn_maint_index_new.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_index_new)

    self.btn_maint_reindex = tr_set(QPushButton(), "Переиндексация", "Reindex")
    self.btn_maint_reindex.setProperty("actionTitle", "reindex")
    tr_set(self.btn_maint_reindex, "Пересоздать все векторы для RAG (медленно)", "Regenerate ALL embedding vectors for RAG (slow)", "setToolTip")
    self.btn_maint_reindex.setIcon(qta.icon('fa5s.brain', color=THEME["text"]))
    self.btn_maint_reindex.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_reindex)

    self.maintenance_section.add_widget(_btn_row(self.btn_maint_index_new, self.btn_maint_reindex))

    self.btn_maint_dedupe = tr_set(QPushButton(), "Удалить дубли", "Remove duplicates")
    self.btn_maint_dedupe.setProperty("actionTitle", "dedupe")
    tr_set(self.btn_maint_dedupe, "Удалить дубликаты сообщений", "Remove duplicate messages", "setToolTip")
    self.btn_maint_dedupe.setIcon(qta.icon('fa5s.broom', color=THEME["text"]))
    self.btn_maint_dedupe.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_dedupe)

    self.btn_maint_update_format = tr_set(QPushButton(), "Обновить формат", "Update format")
    self.btn_maint_update_format.setProperty("actionTitle", "update_format")
    tr_set(self.btn_maint_update_format,
           "Конвертировать JSON-файл истории в новый structured формат (создаёт резервную копию)",
           "Convert JSON history file to the new structured format (creates a backup)", "setToolTip")
    self.btn_maint_update_format.setIcon(qta.icon('fa5s.file-code', color=THEME["text"]))
    self.btn_maint_update_format.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_update_format)

    self.maintenance_section.add_widget(_btn_row(self.btn_maint_dedupe, self.btn_maint_update_format))

    self.character_danger_section = _build_danger_zone(self)
    grid.addWidget(self.character_danger_section, 2, 0, 1, 2)
    for button in panel.findChildren(QPushButton):
        button.setMinimumHeight(34)
    return panel


def _build_danger_zone(self) -> QWidget:
    """Опасная зона: действия «для ВСЕХ персонажей» вне секций персонажей (#17).

    Сюда вынесены красные деструктивные кнопки (сброс всей истории, физическая
    очистка удалённого) и «all»-обслуживание, чтобы их нельзя было случайно
    нажать, копаясь в настройках конкретной Миты.
    """
    section = CollapsibleSection(_("Опасная зона — все персонажи", "Danger zone — all characters"), icon_name="fa5s.exclamation-triangle")
    section.setProperty("danger", True)
    try:
        section.content_layout.setContentsMargins(16, 8, 12, 8)
        section.content_layout.setSpacing(8)
    except Exception:
        pass

    hint = tr_set(QLabel(),
        "Эти действия затрагивают ВСЕХ персонажей. Отмена невозможна.",
        "These actions affect ALL characters. They cannot be undone.")
    hint.setObjectName("SeparatorLabel")
    hint.setWordWrap(True)
    section.add_widget(hint)

    self.btn_all_history_view = tr_set(QPushButton(), "Открыть историю", "Open history")
    self.btn_all_history_view.setProperty("actionTitle", "history_view")
    tr_set(self.btn_all_history_view,
           "Просмотр базы данных истории всех персонажей",
           "View the history database for all characters", "setToolTip")
    self.btn_all_history_view.setIcon(qta.icon('fa5s.table', color=THEME["text"]))
    self.btn_all_history_view.setObjectName("SecondaryButton")
    _make_compact(self.btn_all_history_view)

    self.btn_all_history_export = tr_set(QPushButton(), "Выгрузить (все)", "Export (all)")
    self.btn_all_history_export.setProperty("actionTitle", "history_export")
    tr_set(self.btn_all_history_export,
           "Выгрузить данные всех персонажей из БД в файл",
           "Export all characters' data from DB to file", "setToolTip")
    self.btn_all_history_export.setIcon(qta.icon('fa5s.file-export', color=THEME["text"]))
    self.btn_all_history_export.setObjectName("SecondaryButton")
    _make_compact(self.btn_all_history_export)

    self.btn_all_history_import = tr_set(QPushButton(), "Загрузить (все)", "Import (all)")
    self.btn_all_history_import.setProperty("actionTitle", "history_import")
    tr_set(self.btn_all_history_import,
           "Загрузить данные из файла в БД для всех персонажей",
           "Import data from file into the DB for all characters", "setToolTip")
    self.btn_all_history_import.setIcon(qta.icon('fa5s.file-import', color=THEME["text"]))
    self.btn_all_history_import.setObjectName("SecondaryButton")
    _make_compact(self.btn_all_history_import)

    section.add_widget(_btn_row(self.btn_all_history_view, self.btn_all_history_export))
    section.add_widget(_btn_row(self.btn_all_history_import))

    # «all»-обслуживание (не деструктивное) — сверху.
    self.btn_all_files_db = tr_set(QPushButton(), "Файлы → БД (все)", "Files → DB (all)")
    self.btn_all_files_db.setProperty("actionTitle", "files_db")
    tr_set(self.btn_all_files_db, "Перенести историю из JSON-файлов в базу данных SQLite для всех персонажей",
           "Import history from JSON files into the SQLite database for all characters", "setToolTip")
    self.btn_all_files_db.setIcon(qta.icon('fa5s.database', color=THEME["text"]))
    self.btn_all_files_db.setObjectName("SecondaryButton")
    _make_compact(self.btn_all_files_db)

    self.btn_all_tags = tr_set(QPushButton(), "Теги → данные (все)", "Tags → data (all)")
    self.btn_all_tags.setProperty("actionTitle", "tags")
    tr_set(self.btn_all_tags,
           "Перенести теги из поля content в structured_data для всех персонажей",
           "Move inline tags from content into structured_data for all characters",
           "setToolTip")
    self.btn_all_tags.setIcon(qta.icon('fa5s.exchange-alt', color=THEME["text"]))
    self.btn_all_tags.setObjectName("SecondaryButton")
    _make_compact(self.btn_all_tags)

    self.btn_all_dedupe = tr_set(QPushButton(), "Удалить дубли (все)", "Remove duplicates (all)")
    self.btn_all_dedupe.setProperty("actionTitle", "dedupe")
    tr_set(self.btn_all_dedupe, "Удалить повторяющиеся сообщения из истории всех персонажей",
           "Remove duplicate messages from all characters' history", "setToolTip")
    self.btn_all_dedupe.setIcon(qta.icon('fa5s.broom', color=THEME["text"]))
    self.btn_all_dedupe.setObjectName("SecondaryButton")
    _make_compact(self.btn_all_dedupe)

    section.add_widget(_btn_row(self.btn_all_files_db, self.btn_all_dedupe))
    section.add_widget(_btn_row(self.btn_all_tags))

    self.btn_all_index_new = tr_set(QPushButton(), "Индекс нового (все)", "Index new (all)")
    self.btn_all_index_new.setProperty("actionTitle", "index_new")
    tr_set(self.btn_all_index_new, "Создать недостающие векторы памяти для RAG у всех персонажей",
           "Generate missing memory embeddings for RAG for all characters", "setToolTip")
    self.btn_all_index_new.setIcon(qta.icon('fa5s.brain', color=THEME["text"]))
    self.btn_all_index_new.setObjectName("SecondaryButton")
    _make_compact(self.btn_all_index_new)

    self.btn_all_reindex = tr_set(QPushButton(), "Переиндексация (все)", "Reindex (all)")
    self.btn_all_reindex.setProperty("actionTitle", "reindex")
    tr_set(self.btn_all_reindex, "Пересоздать все векторы памяти для RAG у всех персонажей (медленно)",
           "Regenerate all memory embeddings for RAG for all characters (slow)", "setToolTip")
    self.btn_all_reindex.setIcon(qta.icon('fa5s.brain', color=THEME["text"]))
    self.btn_all_reindex.setObjectName("SecondaryButton")
    _make_compact(self.btn_all_reindex)

    section.add_widget(_btn_row(self.btn_all_index_new, self.btn_all_reindex))

    section.add_widget(_make_separator())

    # Красные деструктивные — снизу.
    self.btn_all_reset_history = tr_set(QPushButton(), "Очистить историю ВСЕХ", "Clear ALL history")
    self.btn_all_reset_history.setProperty("actionTitle", "history_reset")
    tr_set(self.btn_all_reset_history, "Удалить историю всех персонажей без возможности восстановления",
          "Delete the history of all characters, cannot be undone", "setToolTip")
    self.btn_all_reset_history.setIcon(qta.icon('fa5s.trash-alt', color=THEME["text"]))
    self.btn_all_reset_history.setStyleSheet(_DANGER_QSS)
    self.btn_all_reset_history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _make_compact(self.btn_all_reset_history)
    section.add_widget(_btn_row(self.btn_all_reset_history))

    self.btn_all_purge = tr_set(QPushButton(), "Очистить удалённое (все)", "Purge deleted (all)")
    self.btn_all_purge.setProperty("actionTitle", "purge")
    tr_set(self.btn_all_purge, "Физически удалить is_deleted=1 записи для всех персонажей с резервной копией",
          "Physically delete is_deleted=1 records for all characters with backup", "setToolTip")
    self.btn_all_purge.setIcon(qta.icon('fa5s.fire-alt', color=THEME["text"]))
    self.btn_all_purge.setStyleSheet(_DANGER_QSS)
    self.btn_all_purge.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _make_compact(self.btn_all_purge)
    section.add_widget(_btn_row(self.btn_all_purge))

    return section


def build_character_settings_ui(self, parent_layout):
    container = CharacterWorkspace()
    container.setObjectName("CharacterSettingsWorkspace")
    container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    title = tr_set(QLabel(), "Настройки персонажей", "Characters Settings")
    title.setObjectName("CharacterSettingsTitle")
    layout.addWidget(title)
    splitter = CharacterWorkspaceSplitter()
    self.character_workspace_splitter = splitter
    layout.addWidget(splitter, 1)

    library = QFrame()
    library.setObjectName("CharacterLibrary")
    library.setMinimumWidth(240)
    left = QVBoxLayout(library)
    left.setContentsMargins(10, 10, 10, 10)
    left.setSpacing(6)
    heading = QHBoxLayout()
    heading.setContentsMargins(0, 0, 0, 0)
    title = tr_set(QLabel(), "Библиотека персонажей", "Character library")
    title.setObjectName("CharacterLibraryTitle")
    title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    heading.addWidget(title)
    heading.addStretch()
    self.character_count = QLabel()
    self.character_count.setObjectName("CharacterCount")
    heading.addWidget(self.character_count)
    left.addLayout(heading)
    self.character_search = QLineEdit()
    tr_set(self.character_search, "Поиск персонажей…", "Search characters…", "setPlaceholderText")
    self.character_search.setMinimumHeight(38)
    self.character_search.addAction(qta.icon("fa5s.search", color=THEME["muted"]), QLineEdit.ActionPosition.LeadingPosition)
    left.addWidget(self.character_search)
    self.character_library = QListWidget()
    self.character_library.setObjectName("CharacterList")
    register(self.character_library, retranslate_character_list)
    self.character_library.setItemDelegate(CharacterListDelegate(self.character_library))
    self.character_library.setSpacing(3)
    self.character_library.setMinimumHeight(0)
    self.character_library.setContentsMargins(0, 0, 0, 0)
    self.character_library.setFrameShape(QFrame.Shape.NoFrame)
    left.addWidget(self.character_library, 1)
    splitter.addWidget(library)

    detail = QFrame()
    detail.setObjectName("CharacterDetail")
    detail.setMinimumWidth(350)
    right = QVBoxLayout(detail)
    right.setContentsMargins(12, 12, 12, 12)
    right.setSpacing(14)
    header = QHBoxLayout()
    header.setSpacing(14)
    self.character_avatar = QLabel()
    self.character_avatar.setFixedSize(56, 56)
    self.character_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
    header.addWidget(self.character_avatar)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    name_row = QHBoxLayout()
    self.character_name = QLabel()
    self.character_name.setObjectName("CharacterName")
    register(self.character_name, lambda label: label.setText(character_display_name(label.property("characterId"), label.property("fallbackName"))))
    name_row.addWidget(self.character_name)
    name_row.addStretch()
    text.addLayout(name_row)
    self.character_id_label = QLabel()
    self.character_id_label.setObjectName("CharacterId")
    text.addWidget(self.character_id_label)
    header.addLayout(text, 1)
    right.addLayout(header)
    self._char_config_panel = _build_char_config_panel(self, 150)
    scroll, content_layout = tab_page()
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.addWidget(self._char_config_panel, 1)
    right.addWidget(scroll, 1)
    splitter.addWidget(detail)
    container.sections = [(self.character_prompt_section, True),
                          (self.character_provider_section, False),
                          (self.character_history_section, False),
                          (self.maintenance_section, False),
                          (self.character_danger_section, False)]
    for section, _expanded in container.sections:
        section.setProperty("rememberExpansion", False)
    parent_layout.addWidget(container, 1)
