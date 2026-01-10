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

    self.history_section = InnerCollapsibleSection(_("История и очистка", "History & cleanup"), parent=self)
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

    history_row = QWidget()
    hr_h = QHBoxLayout(history_row)
    hr_h.setContentsMargins(0, 0, 0, 0)
    hr_h.setSpacing(6)

    def _mark_danger_hover(btn: QPushButton):
        btn.setObjectName("SecondaryButton")
        btn.setProperty("dangerHover", True)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    def _make_compact(btn: QPushButton):
        """
        Делает кнопку более "ужимаемой" в рядах по 2 кнопки.
        - compact property: под QSS (если добавишь правило QPushButton[compact="true"])
        - Ignored/minWidth: чтобы layout не раздувал панель из-за minimumSizeHint()
        """
        btn.setProperty("compact", True)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    # -------- Подсекция: для выбранного персонажа --------
    char_tools_title = QLabel(_("Для выбранного персонажа", "For selected character"))
    char_tools_title.setStyleSheet("font-weight: 600;")
    self.history_section.add_widget(char_tools_title)

    # Кнопки (персонаж)
    self.btn_clear_history = QPushButton(_("Очистить", "Clear"))
    self.btn_clear_history.setToolTip(
        _("Очистить историю выбранного персонажа",
          "Clear history for selected character")
    )
    self.btn_clear_history.setIcon(qta.icon('fa5s.trash', color='#ffffff'))
    _mark_danger_hover(self.btn_clear_history)
    _make_compact(self.btn_clear_history)

    self.btn_migrate_db = QPushButton(_("Миграция", "Migrate"))
    self.btn_migrate_db.setToolTip(
        _("Перенести старую файловую историю в базу данных",
          "Migrate old file history to database")
    )
    self.btn_migrate_db.setIcon(qta.icon('fa5s.database', color='#ffffff'))
    self.btn_migrate_db.setObjectName("SecondaryButton")
    _make_compact(self.btn_migrate_db)

    row_char_1 = QWidget()
    row_char_1_l = QHBoxLayout(row_char_1)
    row_char_1_l.setContentsMargins(0, 0, 0, 0)
    row_char_1_l.setSpacing(6)
    row_char_1_l.addWidget(self.btn_clear_history, 1)
    row_char_1_l.addWidget(self.btn_migrate_db, 1)
    self.history_section.add_widget(row_char_1)

    self.btn_reindex = QPushButton(_("Индекс", "Index"))
    self.btn_reindex.setToolTip(_("Заполнить пустые вектора для RAG", "Fill missing vectors for RAG"))
    self.btn_reindex.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_reindex.setObjectName("SecondaryButton")

    self.btn_db_viewer = QPushButton(_("БД", "DB"))
    self.btn_db_viewer.setToolTip(
        _("Просмотр базы данных (для выбранного персонажа)",
          "Database viewer (selected character)")
    )
    self.btn_db_viewer.setIcon(qta.icon('fa5s.table', color='#ffffff'))
    self.btn_db_viewer.setObjectName("SecondaryButton")
    _make_compact(self.btn_db_viewer)

    row_char_2 = QWidget()
    row_char_2_l = QHBoxLayout(row_char_2)
    row_char_2_l.setContentsMargins(0, 0, 0, 0)
    row_char_2_l.setSpacing(6)
    row_char_2_l.addWidget(self.btn_reindex, 1)
    row_char_2_l.addWidget(self.btn_db_viewer, 1)
    self.history_section.add_widget(row_char_2)

    self.btn_dedupe_history = QPushButton(_("Дубли", "Dups"))
    self.btn_dedupe_history.setToolTip(_(
        "Удалить дубли истории по ключу (message_id + timestamp) для выбранного персонажа",
        "Remove history duplicates by (message_id + timestamp) for selected character"
    ))
    self.btn_dedupe_history.setIcon(qta.icon('fa5s.broom', color='#ffffff'))
    self.btn_dedupe_history.setObjectName("SecondaryButton")
    _make_compact(self.btn_dedupe_history)

    # Отдельная кнопка: переиндексировать ВСЁ (все строки выбранного персонажа)
    self.btn_reindex_all = QPushButton(_("Индекс всё", "Index ALL"))
    self.btn_reindex_all.setToolTip(_(
        "Пересоздать вектора для всех строк выбранного персонажа (history + memories).",
        "Regenerate embeddings for all rows of selected character (history + memories)."
    ))
    self.btn_reindex_all.setIcon(qta.icon('fa5s.sync-alt', color='#ffffff'))
    self.btn_reindex_all.setObjectName("SecondaryButton")
    _make_compact(self.btn_reindex_all)

    row_char_3 = QWidget()
    row_char_3_l = QHBoxLayout(row_char_3)
    row_char_3_l.setContentsMargins(0, 0, 0, 0)
    row_char_3_l.setSpacing(6)
    row_char_3_l.addWidget(self.btn_dedupe_history, 1)
    row_char_3_l.addWidget(self.btn_reindex_all, 1)
    self.history_section.add_widget(row_char_3)

    # -------- Разделитель --------
    sep = QWidget()
    sep.setFixedHeight(1)
    sep.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.12);")
    self.history_section.add_widget(sep)

    # -------- Подсекция: для всех персонажей --------
    global_tools_title = QLabel(_("Для всех персонажей", "For all characters"))
    global_tools_title.setStyleSheet("font-weight: 600;")
    self.history_section.add_widget(global_tools_title)

    # Кнопки (все персонажи)
    self.btn_clear_all_histories = QPushButton(_("Очистить всё", "Clear ALL"))
    self.btn_clear_all_histories.setToolTip(
        _("Очистить истории всех персонажей",
          "Clear histories for all characters")
    )
    self.btn_clear_all_histories.setIcon(qta.icon('fa5s.trash-alt', color='#ffffff'))
    _mark_danger_hover(self.btn_clear_all_histories)
    _make_compact(self.btn_clear_all_histories)

    # Новые “глобальные” кнопки (UI). Логику/сигналы подключишь там же, где подключаешь остальные.
    self.btn_migrate_db_all = QPushButton(_("Миграция", "Migrate"))
    self.btn_migrate_db_all.setToolTip(_(
        "Миграция истории всех персонажей из JSON файлов в БД",
        "Migrate file JSON-histories of all characters into DB"
    ))
    self.btn_migrate_db_all.setIcon(qta.icon('fa5s.database', color='#ffffff'))
    self.btn_migrate_db_all.setObjectName("SecondaryButton")

    row_all_1 = QWidget()
    row_all_1_l = QHBoxLayout(row_all_1)
    row_all_1_l.setContentsMargins(0, 0, 0, 0)
    row_all_1_l.setSpacing(6)
    row_all_1_l.addWidget(self.btn_clear_all_histories, 1)
    row_all_1_l.addWidget(self.btn_migrate_db_all, 1)
    self.history_section.add_widget(row_all_1)

    self.btn_reindex_global = QPushButton(_("Индекс всё", "Index ALL"))
    self.btn_reindex_global.setToolTip(_(
        "Заполнить пустые вектора для RAG по всем персонажам",
        "Fill missing vectors for RAG for all characters"
    ))
    self.btn_reindex_global.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_reindex_global.setObjectName("SecondaryButton")
    _make_compact(self.btn_reindex_global)

    self.btn_db_viewer_global = QPushButton(_("БД (общ.)", "DB (Global)"))
    self.btn_db_viewer_global.setToolTip(_(
        "Открыть просмотр базы данных (общий режим)",
        "Open database viewer (global mode)"
    ))
    self.btn_db_viewer_global.setIcon(qta.icon('fa5s.table', color='#ffffff'))
    self.btn_db_viewer_global.setObjectName("SecondaryButton")
    _make_compact(self.btn_db_viewer_global)

    row_all_2 = QWidget()
    row_all_2_l = QHBoxLayout(row_all_2)
    row_all_2_l.setContentsMargins(0, 0, 0, 0)
    row_all_2_l.setSpacing(6)
    row_all_2_l.addWidget(self.btn_reindex_global, 1)
    row_all_2_l.addWidget(self.btn_db_viewer_global, 1)
    self.history_section.add_widget(row_all_2)

    container_lay.addWidget(root)
    parent_layout.addWidget(container)