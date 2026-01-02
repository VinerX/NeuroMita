# File: ui/dialogs/db_viewer.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QTableView,
    QPushButton, QHeaderView, QAbstractItemView
)
from PyQt6.QtSql import QSqlDatabase, QSqlTableModel
import os

from main_logger import logger


class DbViewerDialog(QDialog):
    def __init__(self, parent=None, character_id=None):
        super().__init__(parent)
        self.setWindowTitle("Database Viewer (World.db)")
        self.resize(900, 600)
        self.character_id = character_id

        # Стиль НЕ дергаем тут вообще: диалог унаследует общий stylesheet приложения/родителя.

        # Инициализируем соединение с БД для QtSql (глобальное для приложения)
        self._init_sql_connection()

        self.layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        # Tabs
        self.history_tab = self._create_table_view("history")
        self.memories_tab = self._create_table_view("memories")
        self.variables_tab = self._create_table_view("variables")

        self.tabs.addTab(self.history_tab, "History")
        self.tabs.addTab(self.memories_tab, "Memories")
        self.tabs.addTab(self.variables_tab, "Variables")

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_all)
        self.btn_delete = QPushButton("Delete Selected Row")
        self.btn_delete.clicked.connect(self.delete_current_row)

        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_delete)
        self.layout.addLayout(btn_layout)

    def _init_sql_connection(self):
        # Проверяем, добавлена ли БД в пул Qt
        if QSqlDatabase.contains("qt_sql_default_connection"):
            self.db = QSqlDatabase.database("qt_sql_default_connection")
            if not self.db.isOpen():
                if not self.db.open():
                    logger.error(f"Failed to open existing Qt DB connection: {self.db.lastError().text()}")
            return

        self.db = QSqlDatabase.addDatabase("QSQLITE")
        db_path = os.path.join("Histories", "world.db")
        self.db.setDatabaseName(db_path)
        if not self.db.open():
            logger.error(f"Failed to open DB for viewer: {self.db.lastError().text()}")

    def _create_table_view(self, table_name: str) -> QTableView:
        view = QTableView()
        model = QSqlTableModel(self, self.db)
        model.setTable(table_name)

        # Фильтр по персонажу, если передан
        if self.character_id:
            # минимально экранируем одинарные кавычки для SQL-строки
            cid = str(self.character_id).replace("'", "''")
            model.setFilter(f"character_id = '{cid}'")

        model.setEditStrategy(QSqlTableModel.EditStrategy.OnFieldChange)
        model.select()

        view.setModel(model)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setAlternatingRowColors(True)
        view.setSortingEnabled(True)

        view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        view.horizontalHeader().setStretchLastSection(True)

        # Скрываем колонку embedding (она огромная и бинарная)
        emb_idx = model.fieldIndex("embedding")
        if emb_idx != -1:
            view.hideColumn(emb_idx)

        return view

    def refresh_all(self):
        for tab in (self.history_tab, self.memories_tab, self.variables_tab):
            model = tab.model()
            if model:
                model.select()

    def delete_current_row(self):
        current_view = self.tabs.currentWidget()
        if not isinstance(current_view, QTableView):
            return

        selection = current_view.selectionModel().selectedRows()
        if not selection:
            return

        model = current_view.model()
        for index in selection:
            model.removeRow(index.row())

        model.submitAll()
        model.select()