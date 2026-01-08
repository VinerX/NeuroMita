# File: ui/dialogs/db_viewer.py
from __future__ import annotations

import os
from typing import Optional, Tuple, List

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QAction
from PyQt6.QtSql import QSqlDatabase, QSqlTableModel
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from main_logger import logger


def _sql_escape_literal(value: str) -> str:
    """Escape for SQL string literal inside single quotes (QSqlTableModel.setFilter uses raw SQL)."""
    return str(value).replace("'", "''")


def _sql_escape_like(value: str) -> str:
    """
    Escape for SQLite LIKE pattern; we'll use: LIKE '...%' ESCAPE '\'
    Escape backslash first, then % and _.
    """
    s = str(value).replace("\\", "\\\\")
    s = s.replace("%", "\\%").replace("_", "\\_")
    return s


class _AdvancedTablePage(QWidget):
    """
    One tab: filter area + QTableView backed by QSqlTableModel.
    Keeps its own filter state and preserves sorting on refresh.
    """

    OPERATORS = ["Contains", "Equals", "Starts With", "Is Empty"]

    def __init__(self, parent: QWidget, *, db: QSqlDatabase, table_name: str, character_id: Optional[str] = None):
        super().__init__(parent)
        self.db = db
        self.table_name = table_name
        self.character_id = character_id

        self._base_filter = self._build_base_filter()
        self._user_filter: str = ""

        self.model = QSqlTableModel(self, self.db)
        self.model.setTable(self.table_name)
        self.model.setEditStrategy(QSqlTableModel.EditStrategy.OnFieldChange)

        self.view = QTableView(self)
        self.view.setModel(self.model)

        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)

        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

        # Context menu
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._on_context_menu)

        # Filtering UI
        self.cmb_column = QComboBox(self)
        self.cmb_operator = QComboBox(self)
        self.cmb_operator.addItems(self.OPERATORS)

        self.txt_value = QLineEdit(self)
        self.txt_value.setPlaceholderText("Value...")

        self.btn_apply = QPushButton("Apply Filter", self)
        self.btn_clear = QPushButton("Clear Filter", self)

        self.lbl_filter_state = QLabel("Filter: OFF", self)
        self._set_filter_state(False)

        self.btn_apply.clicked.connect(self.apply_filter)
        self.btn_clear.clicked.connect(self.clear_filter)

        # Layout
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Column:", self))
        filter_row.addWidget(self.cmb_column, 2)
        filter_row.addWidget(QLabel("Operator:", self))
        filter_row.addWidget(self.cmb_operator, 1)
        filter_row.addWidget(QLabel("Value:", self))
        filter_row.addWidget(self.txt_value, 3)
        filter_row.addWidget(self.btn_apply)
        filter_row.addWidget(self.btn_clear)
        filter_row.addWidget(self.lbl_filter_state)

        root = QVBoxLayout(self)
        root.addLayout(filter_row)
        root.addWidget(self.view)

        # Initial load
        self.refresh()

    def cleanup(self) -> None:
        """Ensure models release the DB connection before dialog removes it."""
        try:
            self.view.setModel(None)
        except Exception:
            pass
        try:
            self.model.deleteLater()
        except Exception:
            pass

    def _build_base_filter(self) -> str:
        parts: List[str] = []
        if self.character_id is not None and str(self.character_id).strip() != "":
            cid = _sql_escape_literal(str(self.character_id))
            parts.append(f"character_id = '{cid}'")
        return " AND ".join(f"({p})" for p in parts)

    def _combined_filter(self) -> str:
        if self._base_filter and self._user_filter:
            return f"({self._base_filter}) AND ({self._user_filter})"
        if self._base_filter:
            return self._base_filter
        return self._user_filter or ""

    def _set_filter_state(self, active: bool) -> None:
        self.lbl_filter_state.setText("Filter: ON" if active else "Filter: OFF")
        # Simple, obvious visual hint without forcing app-wide stylesheet.
        self.lbl_filter_state.setStyleSheet(
            "font-weight: 600; color: #b00020;" if active else "font-weight: 600; color: #2e7d32;"
        )

    def _current_sort(self) -> Tuple[int, Qt.SortOrder]:
        header = self.view.horizontalHeader()
        return header.sortIndicatorSection(), header.sortIndicatorOrder()

    def _apply_sort(self, sort_column: int, sort_order: Qt.SortOrder) -> None:
        if sort_column is None or sort_column < 0:
            return
        try:
            self.model.setSort(sort_column, sort_order)
        except Exception:
            # Not fatal
            pass

    def _refresh_columns_combo(self) -> None:
        self.cmb_column.blockSignals(True)
        try:
            self.cmb_column.clear()

            rec = self.model.record()
            for i in range(rec.count()):
                field = rec.field(i)
                name = field.name() or f"col_{i}"
                # Avoid offering obvious blobs for filtering
                if name.lower() in {"embedding"}:
                    continue
                self.cmb_column.addItem(name, name)

            if self.cmb_column.count() == 0:
                # Fallback if record() is empty for some reason
                for i in range(self.model.columnCount()):
                    name = str(self.model.headerData(i, Qt.Orientation.Horizontal) or f"col_{i}")
                    if name.lower() == "embedding":
                        continue
                    self.cmb_column.addItem(name, name)
        finally:
            self.cmb_column.blockSignals(False)

    def _hide_large_columns_by_default(self) -> None:
        rec = self.model.record()
        for col in range(self.model.columnCount()):
            name = ""
            try:
                name = rec.field(col).name() or ""
            except Exception:
                name = str(self.model.headerData(col, Qt.Orientation.Horizontal) or "")

            lname = name.lower().strip()

            # Hide typical "huge" columns
            if lname in {"embedding"} or "embedding" in lname:
                self.view.hideColumn(col)
                continue

            # Also hide any ByteArray fields (BLOBs)
            try:
                f = rec.field(col)
                # QVariant.Type.ByteArray is typically used for BLOBs in Qt SQL
                if f.type() == f.type().ByteArray:  # robust enough in PyQt6
                    self.view.hideColumn(col)
            except Exception:
                # If introspection fails, ignore
                pass

    def refresh(self) -> None:
        sort_col, sort_order = self._current_sort()
        self.model.setFilter(self._combined_filter())
        self._apply_sort(sort_col, sort_order)

        if not self.model.select():
            err = self.model.lastError().text()
            logger.error(f"DB Viewer: select() failed for table '{self.table_name}': {err}")
            QMessageBox.critical(self, "Database Viewer", f"Failed to load table '{self.table_name}':\n{err}")

        self._refresh_columns_combo()
        self._hide_large_columns_by_default()

        # Initial auto-fit to contents, but keep interactive resizing.
        try:
            self.view.resizeColumnsToContents()
        except Exception:
            pass

        self._set_filter_state(bool(self._user_filter.strip()))

    def apply_filter(self) -> None:
        col = self.cmb_column.currentData()
        if not col:
            return

        op = self.cmb_operator.currentText()
        raw_value = self.txt_value.text()

        col_ident = '"' + str(col).replace('"', '""') + '"'

        if op == "Is Empty":
            self._user_filter = f"({col_ident} IS NULL OR TRIM({col_ident}) = '')"
        else:
            if raw_value is None or raw_value == "":
                QMessageBox.information(self, "Filter", "Enter a value or use the 'Is Empty' operator.")
                return

            if op == "Equals":
                v = _sql_escape_literal(raw_value)
                self._user_filter = f"{col_ident} = '{v}'"
            elif op == "Contains":
                v = _sql_escape_like(raw_value)
                self._user_filter = f"{col_ident} LIKE '%{v}%' ESCAPE '\\'"
            elif op == "Starts With":
                v = _sql_escape_like(raw_value)
                self._user_filter = f"{col_ident} LIKE '{v}%' ESCAPE '\\'"
            else:
                self._user_filter = ""

        self.refresh()

    def clear_filter(self) -> None:
        self._user_filter = ""
        self.txt_value.clear()
        self.refresh()

    def _selected_row_numbers(self) -> List[int]:
        sel = self.view.selectionModel()
        if not sel:
            return []
        rows = [idx.row() for idx in sel.selectedRows()]
        # unique + stable
        return sorted(set(rows))

    def _on_context_menu(self, pos: QPoint) -> None:
        index = self.view.indexAt(pos)
        model = self.model

        menu = QMenu(self)

        act_delete = QAction("Delete Selected Rows", self)
        act_delete.triggered.connect(self._delete_selected_rows)
        menu.addAction(act_delete)

        # Copy / batch edit only when a cell is targeted
        if index.isValid():
            col_name = str(model.headerData(index.column(), Qt.Orientation.Horizontal) or f"Column {index.column()}")

            act_copy = QAction("Copy Cell Content", self)
            act_copy.triggered.connect(lambda: self._copy_cell(index))
            menu.addAction(act_copy)

            # Batch edit action
            act_batch = QAction(f'Batch Edit "{col_name}"', self)
            act_batch.triggered.connect(lambda: self._batch_edit(index))
            menu.addAction(act_batch)

        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _copy_cell(self, index) -> None:
        try:
            text = self.model.data(index, Qt.ItemDataRole.DisplayRole)
            if text is None:
                text = ""
            QApplication.clipboard().setText(str(text))
        except Exception as e:
            logger.error(f"DB Viewer: copy failed: {e}", exc_info=True)

    def _delete_selected_rows(self) -> None:
        rows = self._selected_row_numbers()
        if not rows:
            return

        resp = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete {len(rows)} selected row(s) from '{self.table_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        # Remove from bottom to top
        rows_desc = sorted(rows, reverse=True)

        # Use manual submit to commit in one shot
        old_strategy = self.model.editStrategy()
        self.model.setEditStrategy(QSqlTableModel.EditStrategy.OnManualSubmit)

        ok = True
        try:
            for r in rows_desc:
                if not self.model.removeRow(r):
                    ok = False
                    break

            if ok:
                ok = self.model.submitAll()

            if not ok:
                err = self.model.lastError().text()
                logger.error(f"DB Viewer: delete failed on '{self.table_name}': {err}")
                QMessageBox.critical(self, "Delete Failed", f"Failed to delete rows:\n{err}")
                self.model.revertAll()
        except Exception as e:
            logger.error(f"DB Viewer: delete exception on '{self.table_name}': {e}", exc_info=True)
            QMessageBox.critical(self, "Delete Failed", f"Failed to delete rows:\n{e}")
            try:
                self.model.revertAll()
            except Exception:
                pass
        finally:
            try:
                self.model.setEditStrategy(old_strategy)
            except Exception:
                pass

        self.refresh()

    def _batch_edit(self, clicked_index) -> None:
        if not clicked_index.isValid():
            return

        col = clicked_index.column()
        col_name = str(self.model.headerData(col, Qt.Orientation.Horizontal) or f"Column {col}")
        lname = col_name.lower().strip()

        if "embedding" in lname:
            QMessageBox.information(self, "Batch Edit", f'Editing "{col_name}" is disabled (likely a large BLOB field).')
            return

        rows = self._selected_row_numbers()
        if not rows:
            return

        current_val = self.model.data(clicked_index, Qt.ItemDataRole.EditRole)
        if current_val is None:
            current_val = ""

        new_val, ok = QInputDialog.getText(
            self,
            "Batch Edit",
            f'Set "{col_name}" for {len(rows)} selected row(s):',
            text=str(current_val),
        )
        if not ok:
            return

        old_strategy = self.model.editStrategy()
        self.model.setEditStrategy(QSqlTableModel.EditStrategy.OnManualSubmit)

        try:
            for r in rows:
                idx = self.model.index(r, col)
                if not self.model.setData(idx, new_val, Qt.ItemDataRole.EditRole):
                    err = self.model.lastError().text()
                    logger.error(f"DB Viewer: setData failed for batch edit '{self.table_name}.{col_name}': {err}")
                    QMessageBox.critical(self, "Batch Edit Failed", f"Failed to update values:\n{err}")
                    self.model.revertAll()
                    return

            if not self.model.submitAll():
                err = self.model.lastError().text()
                logger.error(f"DB Viewer: submitAll failed for batch edit '{self.table_name}.{col_name}': {err}")
                QMessageBox.critical(self, "Batch Edit Failed", f"Failed to commit changes:\n{err}")
                self.model.revertAll()
                return

        except Exception as e:
            logger.error(f"DB Viewer: batch edit exception: {e}", exc_info=True)
            QMessageBox.critical(self, "Batch Edit Failed", f"Failed to update values:\n{e}")
            try:
                self.model.revertAll()
            except Exception:
                pass
        finally:
            try:
                self.model.setEditStrategy(old_strategy)
            except Exception:
                pass

        self.refresh()


class DbViewerDialog(QDialog):
    """
    Advanced Database Viewer:
    - Unique QtSql connection name
    - Per-tab filtering UI
    - Multi-row selection, sorting, interactive resizing
    - Context menu: delete rows, batch edit column, copy cell
    - Hides large blob columns (embedding) by default
    """

    def __init__(self, parent=None, character_id: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Advanced Database Viewer (World.db)")
        self.resize(1100, 700)
        self.character_id = character_id

        self._connection_name = f"db_viewer_connection_{id(self)}"
        self.db = self._init_sql_connection()

        layout = QVBoxLayout(self)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self.history_page = _AdvancedTablePage(self, db=self.db, table_name="history", character_id=self.character_id)
        self.memories_page = _AdvancedTablePage(self, db=self.db, table_name="memories", character_id=self.character_id)
        self.variables_page = _AdvancedTablePage(self, db=self.db, table_name="variables", character_id=self.character_id)

        self.tabs.addTab(self.history_page, "History")
        self.tabs.addTab(self.memories_page, "Memories")
        self.tabs.addTab(self.variables_page, "Variables")

        # Bottom buttons
        btn_row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh", self)
        self.btn_refresh.clicked.connect(self.refresh_all)
        btn_row.addWidget(self.btn_refresh)

        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _init_sql_connection(self) -> QSqlDatabase:
        db_path = os.path.join("Histories", "world.db")

        db = QSqlDatabase.addDatabase("QSQLITE", self._connection_name)
        db.setDatabaseName(db_path)

        # Also set Qt-side busy timeout (connection-level)
        db.setConnectOptions("QSQLITE_BUSY_TIMEOUT=5000")

        if not db.open():
            err = db.lastError().text()
            logger.error(f"DB Viewer: failed to open Qt DB connection: {err}")
            QMessageBox.critical(self, "Database Viewer", f"Failed to open database:\n{err}")
            return db

        # Enforce WAL + busy_timeout on this Qt connection too (WAL persists, busy_timeout is per-connection).
        try:
            db.exec("PRAGMA journal_mode=WAL;")
            db.exec("PRAGMA busy_timeout = 5000;")
        except Exception as e:
            logger.error(f"DB Viewer: failed to apply PRAGMAs via Qt connection: {e}", exc_info=True)

        return db

    def refresh_all(self) -> None:
        self.history_page.refresh()
        self.memories_page.refresh()
        self.variables_page.refresh()

    def closeEvent(self, event) -> None:
        # Release models before removing the connection name.
        try:
            self.history_page.cleanup()
            self.memories_page.cleanup()
            self.variables_page.cleanup()
        except Exception:
            pass

        try:
            if self.db and self.db.isOpen():
                self.db.close()
        except Exception:
            pass

        # Remove the named connection to avoid accumulating stale connections.
        try:
            name = self._connection_name
            self.db = None  # drop reference before removing
            QSqlDatabase.removeDatabase(name)
        except Exception:
            pass

        super().closeEvent(event)