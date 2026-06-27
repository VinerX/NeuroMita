# File: src/ui/settings/character_settings/ui.py

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QSizePolicy, QStyle
)
import qtawesome as qta

from ui.gui_templates import create_section_header, SettingsBodyWidget
from ui.widgets.tr_combobox import TRQComboBox
from managers.settings_manager import InnerCollapsibleSection
from utils import getTranslationVariant as _
from localization.live import register_if_tr, tr_set


def _make_row(label_text: str, field_widget: QWidget, label_w: int) -> QWidget:
    row = SettingsBodyWidget()
    row.setObjectName("SettingRow")
    hl = QHBoxLayout(row)
    hl.setContentsMargins(8, 4, 8, 4)
    hl.setSpacing(6)

    lbl = QLabel(label_text)
    register_if_tr(lbl, label_text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    lbl.setFixedWidth(label_w)
    hl.addWidget(lbl, 0)

    hl.addWidget(field_widget, 1)
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


def build_character_settings_ui(self, parent_layout):
    try:
        scrollbar_guard = max(12, self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
    except Exception:
        scrollbar_guard = 14

    sidebar_w = getattr(self, "SETTINGS_SIDEBAR_WIDTH", 50)
    right_pad = max(scrollbar_guard, min(18, int(sidebar_w * 0.25)))

    container = SettingsBodyWidget()
    container_lay = QVBoxLayout(container)
    container_lay.setContentsMargins(0, 0, right_pad, 0)
    container_lay.setSpacing(6)

    create_section_header(container_lay, _("Настройки персонажей", "Characters Settings"))

    overlay_w = getattr(self, "SETTINGS_PANEL_WIDTH", 400)
    label_w = max(90, min(120, int(overlay_w * 0.3)))
    self.mic_label_width = label_w

    root = SettingsBodyWidget()
    lay = QVBoxLayout(root)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)

    character_field = SettingsBodyWidget()
    ch_h = QHBoxLayout(character_field)
    ch_h.setContentsMargins(0, 0, 0, 0)
    ch_h.setSpacing(6)

    self.character_combobox = TRQComboBox()
    self.character_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    ch_h.addWidget(self.character_combobox, 1)
    lay.addWidget(_make_row(_("Персонажи", "Characters"), character_field, label_w))

    prompt_field = SettingsBodyWidget()
    pr_h = QHBoxLayout(prompt_field)
    pr_h.setContentsMargins(0, 0, 0, 0)
    pr_h.setSpacing(6)

    self.prompt_pack_combobox = TRQComboBox()
    self.prompt_pack_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    pr_h.addWidget(self.prompt_pack_combobox, 1)
    lay.addWidget(_make_row(_("Набор промптов", "Prompt set"), prompt_field, label_w))

    provider_field = SettingsBodyWidget()
    pv_h = QHBoxLayout(provider_field)
    pv_h.setContentsMargins(0, 0, 0, 0)
    pv_h.setSpacing(6)

    self.char_provider_combobox = TRQComboBox()
    self.char_provider_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    pv_h.addWidget(self.char_provider_combobox, 1)
    lay.addWidget(_make_row(_("Провайдер для персонажа", "Provider for character"), provider_field, label_w))

    sub_title1 = tr_set(QLabel(), "Управление персонажем", "Character management")
    sub_title1.setStyleSheet("font-weight: 600;")
    lay.addWidget(sub_title1)

    self.btn_reload_character_data = tr_set(QPushButton(), "Перезагрузить", "Reload")
    self.btn_reload_character_data.setObjectName("SecondaryButton")
    self.btn_reload_character_data.setIcon(qta.icon('fa5s.sync', color='#ffffff'))
    self.btn_reload_character_data.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    lay.addWidget(self.btn_reload_character_data)

    mgmt_row = SettingsBodyWidget()
    mg_h = QHBoxLayout(mgmt_row)
    mg_h.setContentsMargins(0, 0, 0, 0)
    mg_h.setSpacing(6)

    self.btn_open_character_folder = tr_set(QPushButton(), "Открыть папку набора", "Open prompt set folder")
    self.btn_open_character_folder.setObjectName("SecondaryButton")
    self.btn_open_character_folder.setIcon(qta.icon('fa5s.folder-open', color='#ffffff'))
    mg_h.addWidget(self.btn_open_character_folder, 1)

    self.btn_open_history_folder = tr_set(QPushButton(), "Папку истории", "History folder")
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
        _make_info_row(_("Автор:", "Author:"), _make_info_value_label(self, "author"))
    )
    self.prompt_info_section.add_widget(
        _make_info_row(_("Версия:", "Version:"), _make_info_value_label(self, "version"))
    )

    desc_title = tr_set(QLabel(), "Описание:", "Description:")
    desc_title.setStyleSheet("font-weight: 600;")
    self.prompt_info_section.add_widget(desc_title)

    self.prompt_info_section.add_widget(_make_info_value_label(self, "description"))

    lay.addSpacing(6)

    # ══════════════════════════════════════════════════════
    # История и обслуживание — единый набор действий с переключателем области
    # (вариант A+B: тумблер «Выбранный / Все» убирает дублирование, плюс
    #  визуальная иерархия и сворачиваемое «Обслуживание»)
    # ══════════════════════════════════════════════════════

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
        r = SettingsBodyWidget()
        r.setObjectName("SettingRow")
        rl = QHBoxLayout(r)
        rl.setContentsMargins(8, 4, 8, 4)
        rl.setSpacing(6)
        for w in widgets:
            rl.addWidget(w, 1)
        return r

    # -------- Переключатель области: выбранный персонаж / все --------
    scope_row = SettingsBodyWidget()
    scope_row.setObjectName("SettingRow")
    scope_l = QHBoxLayout(scope_row)
    scope_l.setContentsMargins(8, 4, 8, 4)
    scope_l.setSpacing(8)

    scope_caption = tr_set(QLabel(), "Область:", "Scope:")
    scope_caption.setStyleSheet("font-weight: 600;")
    scope_l.addWidget(scope_caption, 0)

    scope_toggle = SettingsBodyWidget()
    scope_toggle.setObjectName("ScopeToggle")
    st_l = QHBoxLayout(scope_toggle)
    st_l.setContentsMargins(2, 2, 2, 2)
    st_l.setSpacing(2)

    self._scope_btn_current = tr_set(QPushButton(), "Выбранный", "Selected")
    self._scope_btn_current.setObjectName("ScopeToggleButton")
    self._scope_btn_current.setCheckable(True)
    self._scope_btn_current.setCursor(Qt.CursorShape.PointingHandCursor)

    self._scope_btn_all = tr_set(QPushButton(), "Все персонажи", "All characters")
    self._scope_btn_all.setObjectName("ScopeToggleButton")
    self._scope_btn_all.setCheckable(True)
    self._scope_btn_all.setCursor(Qt.CursorShape.PointingHandCursor)

    st_l.addWidget(self._scope_btn_current, 1)
    st_l.addWidget(self._scope_btn_all, 1)
    scope_l.addWidget(scope_toggle, 1)

    self._char_history_scope = "current"

    def _set_history_scope(scope: str):
        scope = "all" if scope == "all" else "current"
        self._char_history_scope = scope
        for key, btn in (("current", self._scope_btn_current), ("all", self._scope_btn_all)):
            active = key == scope
            btn.setChecked(active)
            btn.setProperty("active", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        # «Обновить формат» имеет смысл только для выбранного персонажа
        if hasattr(self, "btn_maint_update_format"):
            sel = scope == "current"
            self.btn_maint_update_format.setEnabled(sel)
            self.btn_maint_update_format.setToolTip(
                _("Конвертировать JSON-файл истории в новый structured формат (создаёт резервную копию)",
                  "Convert JSON history file to the new structured format (creates a backup)")
                if sel else
                _("Доступно только для выбранного персонажа",
                  "Available only for the selected character")
            )

    self._set_history_scope = _set_history_scope
    self._scope_btn_current.clicked.connect(lambda: _set_history_scope("current"))
    self._scope_btn_all.clicked.connect(lambda: _set_history_scope("all"))

    lay.addWidget(scope_row)

    # -------- Действия с историей (зависят от области) --------
    hist_title = tr_set(QLabel(), "История", "History")
    hist_title.setStyleSheet("font-weight: 600;")
    lay.addWidget(hist_title)

    self.btn_history_view = tr_set(QPushButton(), "Открыть", "Open")
    tr_set(self.btn_history_view, "Просмотр базы данных истории", "View the history database", "setToolTip")
    self.btn_history_view.setIcon(qta.icon('fa5s.table', color='#ffffff'))
    self.btn_history_view.setObjectName("SecondaryButton")
    _make_compact(self.btn_history_view)

    self.btn_history_export = tr_set(QPushButton(), "Выгрузить", "Export")
    tr_set(self.btn_history_export, "Выгрузить данные из БД в файл", "Export data from DB to file", "setToolTip")
    self.btn_history_export.setIcon(qta.icon('fa5s.file-export', color='#ffffff'))
    self.btn_history_export.setObjectName("SecondaryButton")
    _make_compact(self.btn_history_export)

    self.btn_history_import = tr_set(QPushButton(), "Загрузить", "Import")
    tr_set(self.btn_history_import, "Загрузить данные из файла в БД", "Import data from file to DB", "setToolTip")
    self.btn_history_import.setIcon(qta.icon('fa5s.file-import', color='#ffffff'))
    self.btn_history_import.setObjectName("SecondaryButton")
    _make_compact(self.btn_history_import)

    self.btn_history_reset = tr_set(QPushButton(), "Сбросить", "Reset")
    tr_set(self.btn_history_reset, "Сбросить историю", "Reset history", "setToolTip")
    self.btn_history_reset.setIcon(qta.icon('fa5s.undo-alt', color='#ffffff'))
    _mark_danger_hover(self.btn_history_reset)
    _make_compact(self.btn_history_reset)

    lay.addWidget(_btn_row(self.btn_history_view, self.btn_history_export))
    lay.addWidget(_btn_row(self.btn_history_import, self.btn_history_reset))

    lay.addSpacing(4)

    # -------- Обслуживание (свёрнуто по умолчанию) --------
    self.maintenance_section = InnerCollapsibleSection(_("Обслуживание", "Maintenance"), parent=self)
    lay.addWidget(self.maintenance_section)

    try:
        self.maintenance_section.content_layout.setContentsMargins(16, 8, 12, 8)
        self.maintenance_section.content_layout.setSpacing(8)
    except Exception:
        pass

    maint_hint = tr_set(QLabel(),
        "Действия применяются к выбранной области (переключатель выше).",
        "Actions apply to the selected scope (toggle above).")
    maint_hint.setObjectName("SeparatorLabel")
    maint_hint.setWordWrap(True)
    self.maintenance_section.add_widget(maint_hint)

    self.btn_maint_files_db = tr_set(QPushButton(), "Файлы → БД", "Files → DB")
    tr_set(self.btn_maint_files_db, "Перенести историю из JSON-файлов в базу данных SQLite",
          "Import history from JSON files into the SQLite database", "setToolTip")
    self.btn_maint_files_db.setIcon(qta.icon('fa5s.database', color='#ffffff'))
    self.btn_maint_files_db.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_files_db)

    self.btn_maint_tags = tr_set(QPushButton(), "Теги → данные", "Tags → data")
    tr_set(self.btn_maint_tags, "Перенести теги из поля content в колонку structured_data",
          "Move inline tags from the content field into the structured_data column", "setToolTip")
    self.btn_maint_tags.setIcon(qta.icon('fa5s.exchange-alt', color='#ffffff'))
    self.btn_maint_tags.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_tags)

    self.maintenance_section.add_widget(_btn_row(self.btn_maint_files_db, self.btn_maint_tags))

    self.btn_maint_index_new = tr_set(QPushButton(), "Индекс нового", "Index new")
    tr_set(self.btn_maint_index_new, "Заполнить отсутствующие векторы для RAG", "Fill missing embedding vectors for RAG", "setToolTip")
    self.btn_maint_index_new.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_maint_index_new.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_index_new)

    self.btn_maint_reindex = tr_set(QPushButton(), "Переиндексация", "Reindex")
    tr_set(self.btn_maint_reindex, "Пересоздать все векторы для RAG (медленно)", "Regenerate ALL embedding vectors for RAG (slow)", "setToolTip")
    self.btn_maint_reindex.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_maint_reindex.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_reindex)

    self.maintenance_section.add_widget(_btn_row(self.btn_maint_index_new, self.btn_maint_reindex))

    self.btn_maint_dedupe = tr_set(QPushButton(), "Удалить дубли", "Remove duplicates")
    tr_set(self.btn_maint_dedupe, "Удалить дубликаты сообщений", "Remove duplicate messages", "setToolTip")
    self.btn_maint_dedupe.setIcon(qta.icon('fa5s.broom', color='#ffffff'))
    self.btn_maint_dedupe.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_dedupe)

    self.btn_maint_update_format = tr_set(QPushButton(), "Обновить формат", "Update format")
    self.btn_maint_update_format.setIcon(qta.icon('fa5s.file-code', color='#ffffff'))
    self.btn_maint_update_format.setObjectName("SecondaryButton")
    _make_compact(self.btn_maint_update_format)

    self.maintenance_section.add_widget(_btn_row(self.btn_maint_dedupe, self.btn_maint_update_format))

    # -------- Разделитель + деструктивное действие (всегда «все») --------
    self.maintenance_section.add_widget(_make_separator())

    self.btn_purge_deleted = tr_set(QPushButton(), "Очистить удалённое (все)", "Purge deleted (all)")
    tr_set(self.btn_purge_deleted, "Физически удалить is_deleted=1 записи для всех персонажей с резервной копией",
          "Physically delete is_deleted=1 records for all characters with backup", "setToolTip")
    self.btn_purge_deleted.setIcon(qta.icon('fa5s.fire-alt', color='#ffffff'))
    self.btn_purge_deleted.setStyleSheet(
        "QPushButton { background-color: #8b1a1a; color: #ffffff; border-radius: 4px; }"
        "QPushButton:hover { background-color: #b22222; }"
        "QPushButton:pressed { background-color: #6a0f0f; }"
    )
    self.btn_purge_deleted.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _make_compact(self.btn_purge_deleted)
    self.maintenance_section.add_widget(self.btn_purge_deleted)

    # Инициализируем активное состояние тумблера (после создания всех кнопок)
    _set_history_scope("current")

    container_lay.addWidget(root)
    parent_layout.addWidget(container)
