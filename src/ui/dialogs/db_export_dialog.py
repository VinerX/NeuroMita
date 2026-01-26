import os
import json
from datetime import datetime

from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QGroupBox,
    QRadioButton, QDateTimeEdit, QLineEdit, QPushButton, QFileDialog,
    QPlainTextEdit, QMessageBox, QScrollArea, QWidget, QSizePolicy,QToolButton
)

from utils import getTranslationVariant as _


class DbExportDialog(QDialog):
    """
    Диалог настроек экспорта из SQLite (Histories/world.db) в JSON.
    Возвращает настройки через get_settings() после accept().
    """
    def __init__(self, parent, *, character_id: str | None):
        super().__init__(parent)
        self._character_id = str(character_id or "").strip() or None

        self.setWindowTitle(_("Выгрузка из БД", "Export from DB"))
        self.setMinimumSize(560, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ========== Scroll area (чтобы ничего не наезжало при маленьком окне) ==========
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)

        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(10)

        def _gb_layout(gb: QGroupBox) -> QVBoxLayout:
            # Важно: верхний отступ > 0, чтобы контент не попадал под заголовок groupbox
            lay = QVBoxLayout(gb)
            lay.setContentsMargins(12, 20, 12, 12)  # <- "отступ между заголовком и выбором"
            lay.setSpacing(8)
            return lay

        # =========================
        # 1) Что выгрузить (в одну строку)
        # =========================
        g_what = QGroupBox(_("Что выгрузить", "What to export"))
        v_what = _gb_layout(g_what)

        self.cb_history = QCheckBox(_("История", "History"))
        self.cb_memories = QCheckBox(_("Память", "Memories"))
        self.cb_variables = QCheckBox(_("Переменные", "Variables"))
        self.cb_history.setChecked(True)
        self.cb_memories.setChecked(True)
        self.cb_variables.setChecked(True)

        what_row = QHBoxLayout()
        what_row.setContentsMargins(0, 0, 0, 0)
        what_row.setSpacing(14)
        what_row.addWidget(self.cb_history)
        what_row.addWidget(self.cb_memories)
        what_row.addWidget(self.cb_variables)
        what_row.addStretch(1)
        v_what.addLayout(what_row)

        content_lay.addWidget(g_what)

        # =========================
        # 2) Статусы (в одну строку)
        # =========================
        g_status = QGroupBox(_("Статусы (история/память)", "Statuses (history/memories)"))
        v_status = _gb_layout(g_status)

        self.cb_active = QCheckBox(_("Активную", "Active"))
        self.cb_forgotten = QCheckBox(_("Забытую", "Forgotten"))
        self.cb_deleted = QCheckBox(_("Удалённую", "Deleted"))
        self.cb_active.setChecked(True)
        self.cb_forgotten.setChecked(True)
        self.cb_deleted.setChecked(False)

        st_row = QHBoxLayout()
        st_row.setContentsMargins(0, 0, 0, 0)
        st_row.setSpacing(14)
        st_row.addWidget(self.cb_active)
        st_row.addWidget(self.cb_forgotten)
        st_row.addWidget(self.cb_deleted)
        st_row.addStretch(1)
        v_status.addLayout(st_row)

        content_lay.addWidget(g_status)

        # =========================
        # 3) Период (режимы в одну строку + даты в одну строку)
        # =========================
        g_date = QGroupBox(_("Период", "Date range"))
        v_date = _gb_layout(g_date)

        self.rb_all = QRadioButton(_("Вся", "All"))
        self.rb_from = QRadioButton(_("От даты", "From date"))
        self.rb_range = QRadioButton(_("За период", "Range"))
        self.rb_all.setChecked(True)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(14)
        mode_row.addWidget(self.rb_all)
        mode_row.addWidget(self.rb_from)
        mode_row.addWidget(self.rb_range)
        mode_row.addStretch(1)
        v_date.addLayout(mode_row)

        self.dt_from = QDateTimeEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_from.setDateTime(QDateTime.currentDateTime().addDays(-7))

        self.dt_to = QDateTimeEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_to.setDateTime(QDateTime.currentDateTime())

        dt_row = QHBoxLayout()
        dt_row.setContentsMargins(0, 0, 0, 0)
        dt_row.setSpacing(10)

        lab_from = QLabel(_("С:", "From:"))
        lab_from.setMinimumWidth(22)
        dt_row.addWidget(lab_from)
        dt_row.addWidget(self.dt_from, 1)

        lab_to = QLabel(_("По:", "To:"))
        lab_to.setMinimumWidth(28)
        dt_row.addWidget(lab_to)
        dt_row.addWidget(self.dt_to, 1)

        v_date.addLayout(dt_row)

        def _update_dt_enabled():
            self.dt_from.setEnabled(self.rb_from.isChecked() or self.rb_range.isChecked())
            self.dt_to.setEnabled(self.rb_range.isChecked())

        self.rb_all.toggled.connect(_update_dt_enabled)
        self.rb_from.toggled.connect(_update_dt_enabled)
        self.rb_range.toggled.connect(_update_dt_enabled)
        _update_dt_enabled()

        content_lay.addWidget(g_date)

        # =========================
        # 4) Кастом-фильтры (раскрываемый блок)
        # =========================
        g_filters = QGroupBox(_("Доп. отборы (JSON)", "Extra filters (JSON)"))
        v_f = _gb_layout(g_filters)

        # Header row with toggle
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        self.btn_filters_toggle = QToolButton()
        self.btn_filters_toggle.setCheckable(True)
        self.btn_filters_toggle.setChecked(False)
        self.btn_filters_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.btn_filters_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_filters_toggle.setText(_("Показать", "Show"))
        header_row.addWidget(self.btn_filters_toggle)
        header_row.addStretch(1)

        v_f.addLayout(header_row)

        # Collapsible content
        self.filters_container = QWidget()
        fc_l = QVBoxLayout(self.filters_container)
        fc_l.setContentsMargins(0, 0, 0, 0)
        fc_l.setSpacing(6)

        self.filters_edit = QPlainTextEdit()
        self.filters_edit.setPlaceholderText(
            _(
                "Пример:\n"
                "{\n"
                "  \"history\": {\"role\": [\"user\", \"assistant\"], \"speaker\": {\"like\": \"Alice%\"}},\n"
                "  \"memories\": {\"type\": \"fact\"},\n"
                "  \"variables\": {\"key\": {\"like\": \"quest_%\"}}\n"
                "}\n",
                "Example:\n"
                "{\n"
                "  \"history\": {\"role\": [\"user\", \"assistant\"], \"speaker\": {\"like\": \"Alice%\"}},\n"
                "  \"memories\": {\"type\": \"fact\"},\n"
                "  \"variables\": {\"key\": {\"like\": \"quest_%\"}}\n"
                "}\n",
            )
        )
        self.filters_edit.setMinimumHeight(140)
        self.filters_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        fc_l.addWidget(self.filters_edit)

        self.filters_container.setVisible(False)
        v_f.addWidget(self.filters_container)

        def _toggle_filters(on: bool):
            self.filters_container.setVisible(bool(on))
            self.btn_filters_toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
            self.btn_filters_toggle.setText(_("Скрыть", "Hide") if on else _("Показать", "Show"))

        self.btn_filters_toggle.toggled.connect(_toggle_filters)

        content_lay.addWidget(g_filters)

        # =========================
        # 5) Файл (путь в одну строку, имя в одну строку)
        # =========================
        g_out = QGroupBox(_("Файл", "File"))
        v_out = _gb_layout(g_out)

        self.out_dir = QLineEdit()
        self.out_dir.setText(os.getcwd())

        self.out_name = QLineEdit()
        default_name = f"db_export_{self._character_id or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self.out_name.setText(default_name)

        row_dir = QHBoxLayout()
        row_dir.setContentsMargins(0, 0, 0, 0)
        row_dir.setSpacing(10)
        row_dir.addWidget(QLabel(_("Путь:", "Path:")))
        row_dir.addWidget(self.out_dir, 1)
        btn_browse_dir = QPushButton(_("Обзор...", "Browse..."))
        row_dir.addWidget(btn_browse_dir)
        v_out.addLayout(row_dir)

        row_name = QHBoxLayout()
        row_name.setContentsMargins(0, 0, 0, 0)
        row_name.setSpacing(10)
        row_name.addWidget(QLabel(_("Имя файла:", "File name:")))
        row_name.addWidget(self.out_name, 1)
        v_out.addLayout(row_name)

        def _browse_dir():
            d = QFileDialog.getExistingDirectory(self, _("Выберите папку", "Select folder"), self.out_dir.text().strip() or os.getcwd())
            if d:
                self.out_dir.setText(d)

        btn_browse_dir.clicked.connect(_browse_dir)
        content_lay.addWidget(g_out)

        # добиваем низ (чтобы кнопки не прилипали к контенту)
        content_lay.addStretch(1)

        # ========== Кнопки снизу (вне скролла) ==========
        row_btn = QHBoxLayout()
        row_btn.setContentsMargins(0, 0, 0, 0)
        row_btn.addStretch(1)

        self.btn_cancel = QPushButton(_("Отмена", "Cancel"))
        self.btn_ok = QPushButton(_("Выгрузить", "Export"))
        self.btn_ok.setDefault(True)

        row_btn.addWidget(self.btn_cancel)
        row_btn.addWidget(self.btn_ok)
        root.addLayout(row_btn)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._validate_and_accept)

    def _validate_and_accept(self):
        if not (self.cb_history.isChecked() or self.cb_memories.isChecked() or self.cb_variables.isChecked()):
            QMessageBox.warning(self, _("Ошибка", "Error"), _("Выберите что выгружать.", "Select what to export."))
            return

        if (self.cb_history.isChecked() or self.cb_memories.isChecked()) and not (
            self.cb_active.isChecked() or self.cb_forgotten.isChecked() or self.cb_deleted.isChecked()
        ):
            QMessageBox.warning(self, _("Ошибка", "Error"), _("Выберите хотя бы один статус.", "Select at least one status."))
            return

        out_dir = self.out_dir.text().strip()
        out_name = self.out_name.text().strip()
        if not out_dir:
            QMessageBox.warning(self, _("Ошибка", "Error"), _("Укажите путь сохранения.", "Select output directory."))
            return
        if not out_name:
            QMessageBox.warning(self, _("Ошибка", "Error"), _("Укажите имя файла.", "Enter file name."))
            return

        txt = self.filters_edit.toPlainText().strip()
        if txt:
            try:
                obj = json.loads(txt)
                if not isinstance(obj, dict):
                    raise ValueError("filters must be an object")
            except Exception as e:
                QMessageBox.warning(
                    self, _("Ошибка", "Error"),
                    _("Некорректный JSON фильтров:\n{e}", "Invalid JSON filters:\n{e}").format(e=str(e))
                )
                return

        self.accept()

    def get_settings(self) -> dict:
        filters_txt = self.filters_edit.toPlainText().strip()
        filters_obj = None
        if filters_txt:
            try:
                filters_obj = json.loads(filters_txt)
            except Exception:
                filters_obj = None

        date_mode = "all"
        if self.rb_from.isChecked():
            date_mode = "from"
        elif self.rb_range.isChecked():
            date_mode = "range"

        date_from = self.dt_from.dateTime().toString(Qt.DateFormat.ISODate)
        date_to = self.dt_to.dateTime().toString(Qt.DateFormat.ISODate)

        out_dir = self.out_dir.text().strip()
        out_name = self.out_name.text().strip()
        if not out_name.lower().endswith(".json"):
            out_name += ".json"
        out_path = os.path.join(out_dir, out_name)

        return {
            "character_id": self._character_id,  # None => all characters
            "include_history": self.cb_history.isChecked(),
            "include_memories": self.cb_memories.isChecked(),
            "include_variables": self.cb_variables.isChecked(),
            "status_active": self.cb_active.isChecked(),
            "status_forgotten": self.cb_forgotten.isChecked(),
            "status_deleted": self.cb_deleted.isChecked(),
            "date_mode": date_mode,              # all/from/range
            "date_from": date_from,
            "date_to": date_to,
            "column_filters": filters_obj,        # dict or None
            "out_path": out_path,
        }