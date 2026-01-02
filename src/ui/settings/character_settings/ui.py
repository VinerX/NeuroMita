from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QSizePolicy, QFrame, QCheckBox, QStyle
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


def build_character_settings_ui(self, parent_layout):
    # Резерв под вертикальный скролл, чтобы при его появлении ширина не «прыгала»
    try:
        scrollbar_guard = max(12, self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
    except Exception:
        scrollbar_guard = 14

    # Контейнер с правым отступом (защита от перекрытия сайдбаром + запас под скролл)
    base_right_pad = getattr(self, "SETTINGS_SIDEBAR_WIDTH", 50) + 8
    right_pad = base_right_pad + scrollbar_guard

    container = QWidget()
    container_lay = QVBoxLayout(container)
    container_lay.setContentsMargins(0, 0, right_pad, 0)
    container_lay.setSpacing(6)

    # Заголовок секции
    create_section_header(container_lay, _("Настройки персонажей", "Characters Settings"))

    # Расчёт ширины колонки меток
    overlay_w = getattr(self, "SETTINGS_PANEL_WIDTH", 400)
    label_w = max(90, min(120, int(overlay_w * 0.3)))
    self.mic_label_width = label_w

    root = QWidget()
    lay = QVBoxLayout(root)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)

    # --- Персонажи
    character_field = QWidget()
    ch_h = QHBoxLayout(character_field)
    ch_h.setContentsMargins(0, 0, 0, 0)
    ch_h.setSpacing(6)

    self.character_combobox = QComboBox()
    self.character_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    ch_h.addWidget(self.character_combobox, 1)

    lay.addWidget(_make_row(_("Персонажи", "Characters"), character_field, label_w))

    # --- Набор промтов (+ индикатор)
    prompt_field = QWidget()
    pr_h = QHBoxLayout(prompt_field)
    pr_h.setContentsMargins(0, 0, 0, 0)
    pr_h.setSpacing(6)

    self.prompt_pack_combobox = QComboBox()
    self.prompt_pack_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    pr_h.addWidget(self.prompt_pack_combobox, 1)

    self.prompt_sync_label = QLabel("●")
    self.prompt_sync_label.setToolTip(_("Индикатор соответствия промптов", "Prompts sync indicator"))
    self.prompt_sync_label.setStyleSheet("color: #bdc3c7; font-size: 16px;")
    pr_h.addWidget(self.prompt_sync_label, 0, Qt.AlignmentFlag.AlignVCenter)

    lay.addWidget(_make_row(_("Набор промтов", "Prompt set"), prompt_field, label_w))

    # --- Провайдер для персонажа
    provider_field = QWidget()
    pv_h = QHBoxLayout(provider_field)
    pv_h.setContentsMargins(0, 0, 0, 0)
    pv_h.setSpacing(6)

    self.char_provider_combobox = QComboBox()
    self.char_provider_combobox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    pv_h.addWidget(self.char_provider_combobox, 1)

    lay.addWidget(_make_row(_("Провайдер для персонажа", "Provider for character"), provider_field, label_w))

    # --- Показ логов сравнения промптов
    self.show_prompt_sync_logs_check = QCheckBox(_("Показывать логи сравнения промптов", "Show prompt comparison logs"))
    lay.addWidget(_make_row(_("Логи", "Logs"), self.show_prompt_sync_logs_check, label_w))

    # --- Управление персонажем (подзаголовок)
    sub_title1 = QLabel(_("Управление персонажем", "Character management"))
    sub_title1.setStyleSheet("font-weight: 600;")
    lay.addWidget(sub_title1)

    mgmt_row = QWidget()
    mg_h = QHBoxLayout(mgmt_row)
    mg_h.setContentsMargins(0, 0, 0, 0)
    mg_h.setSpacing(6)

    self.btn_open_character_folder = QPushButton(_("Открыть папку персонажа", "Open character folder"))
    self.btn_open_character_folder.setObjectName("SecondaryButton")
    self.btn_open_character_folder.setIcon(qta.icon('fa5s.folder-open', color='#ffffff'))
    mg_h.addWidget(self.btn_open_character_folder, 1)

    self.btn_open_history_folder = QPushButton(_("Папку истории", "History folder"))
    self.btn_open_history_folder.setObjectName("SecondaryButton")
    self.btn_open_history_folder.setIcon(qta.icon('fa5s.clock', color='#ffffff'))
    mg_h.addWidget(self.btn_open_history_folder, 1)

    lay.addWidget(mgmt_row)

    # Небольшой визуальный отступ перед внутренней секцией
    lay.addSpacing(6)

    # --- История и очистка (внутренняя секция)
    self.history_section = InnerCollapsibleSection(_("История и очистка", "History & cleanup"), parent=self)
    lay.addWidget(self.history_section)

    # На старте — всегда закрыта. Сохраняем состояние только при клике.
    try:
        orig_toggle = self.history_section.toggle

        def _toggle_and_save(_=None):
            orig_toggle()
            # сохраняем состояние, но не читаем его при старте — секция всегда закрыта на открытие окна
            if hasattr(self, "settings"):
                self.settings.set("SHOW_HISTORY_RESET_SECTION", not self.history_section.is_collapsed)

        self.history_section.header.mousePressEvent = _toggle_and_save
    except Exception:
        pass

    # Чуть меньше левый отступ, чтобы выглядело аккуратнее и не давало лишней ширины
    try:
        self.history_section.content_layout.setContentsMargins(16, 8, 12, 8)
        self.history_section.content_layout.setSpacing(8)
    except Exception:
        pass

    # Группа кнопок: очистка истории и всех историй
    history_row = QWidget()
    hr_h = QHBoxLayout(history_row)
    hr_h.setContentsMargins(0, 0, 0, 0)
    hr_h.setSpacing(6)

    def _mark_danger_hover(btn: QPushButton):
        # Серый стиль + красный hover через глобальный QSS
        btn.setObjectName("SecondaryButton")
        btn.setProperty("dangerHover", True)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    self.btn_clear_history = QPushButton(_("Очистить историю", "Clear history"))
    self.btn_clear_history.setIcon(qta.icon('fa5s.trash', color='#ffffff'))
    _mark_danger_hover(self.btn_clear_history)
    hr_h.addWidget(self.btn_clear_history, 1)

    self.btn_clear_all_histories = QPushButton(_("Очистить все истории", "Clear all histories"))
    self.btn_clear_all_histories.setIcon(qta.icon('fa5s.trash-alt', color='#ffffff'))
    _mark_danger_hover(self.btn_clear_all_histories)
    hr_h.addWidget(self.btn_clear_all_histories, 1)

    self.history_section.add_widget(history_row)

    # Отдельной строкой — перекачка промптов (тоже с danger-hover)
    self.btn_reload_prompts = QPushButton(_("Перекачать промпты", "Reload prompts"))
    self.btn_reload_prompts.setIcon(qta.icon('fa5s.download', color='#ffffff'))
    self.btn_reload_prompts.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _mark_danger_hover(self.btn_reload_prompts)
    self.history_section.add_widget(self.btn_reload_prompts)


    self.btn_migrate_db = QPushButton(_("Миграция JSON -> SQLite", "Migrate JSON -> SQLite"))
    self.btn_migrate_db.setToolTip(
        _("Перенести старую файловую историю в базу данных", "Migrate old file history to database"))
    self.btn_migrate_db.setIcon(qta.icon('fa5s.database', color='#ffffff'))
    self.btn_migrate_db.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.btn_migrate_db.setObjectName("SecondaryButton")
    self.history_section.add_widget(self.btn_migrate_db)

    self.db_tools_row = QWidget()
    dbt_h = QHBoxLayout(self.db_tools_row)
    dbt_h.setContentsMargins(0, 0, 0, 0)
    dbt_h.setSpacing(6)

    self.btn_db_viewer = QPushButton(_("Просмотр БД", "DB Viewer"))
    self.btn_db_viewer.setIcon(qta.icon('fa5s.table', color='#ffffff'))
    self.btn_db_viewer.setObjectName("SecondaryButton")
    dbt_h.addWidget(self.btn_db_viewer, 1)

    self.btn_dedupe_history = QPushButton(_("Очистить дубли", "Remove duplicates"))
    self.btn_dedupe_history.setToolTip(_("Удалить дубли истории по ключу (message_id + timestamp) для выбранного персонажа",
                                         "Remove history duplicates by (message_id + timestamp) for selected character"))
    self.btn_dedupe_history.setIcon(qta.icon('fa5s.broom', color='#ffffff'))
    self.btn_dedupe_history.setObjectName("SecondaryButton")
    dbt_h.addWidget(self.btn_dedupe_history, 1)

    self.btn_reindex = QPushButton(_("Переиндексация", "Re-index Knowledge"))
    self.btn_reindex.setToolTip(_("Заполнить пустые вектора для RAG", "Fill missing vectors for RAG"))
    self.btn_reindex.setIcon(qta.icon('fa5s.brain', color='#ffffff'))
    self.btn_reindex.setObjectName("SecondaryButton")
    dbt_h.addWidget(self.btn_reindex, 1)

    # Добавляем сохраненный виджет
    self.history_section.add_widget(self.db_tools_row)

    container_lay.addWidget(root)
    parent_layout.addWidget(container)