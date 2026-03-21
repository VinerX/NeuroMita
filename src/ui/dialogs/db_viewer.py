from __future__ import annotations

import os
from typing import Optional, Tuple, List

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtSql import QSqlDatabase, QSqlQuery, QSqlTableModel
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
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


def _q_ident(ident: str) -> str:
    """Safely quote SQLite identifiers (table/column names)."""
    return '"' + str(ident).replace('"', '""') + '"'


def _is_empty_value(v) -> bool:
    if v is None:
        return True
    try:
        if isinstance(v, str):
            return v.strip() == ""
    except Exception:
        pass
    return False


def _is_blob_value(v) -> bool:
    # PyQt can return QByteArray; in python it may look like 'QByteArray' type.
    if v is None:
        return False
    if isinstance(v, (bytes, bytearray, memoryview)):
        return len(v) > 0
    tname = type(v).__name__
    if tname == "QByteArray":
        try:
            return not v.isEmpty()
        except Exception:
            return True
    return False


class _PrettySqlTableModel(QSqlTableModel):
    """
    QSqlTableModel with nicer display:
    - BLOB columns: show ✓ / ✗ instead of bytes
    - bool-ish int columns (is_deleted/is_active/is_forgotten): show ✓ / ✗
    - disable editing for BLOB columns
    """

    BOOLISH_COLUMNS = {"is_deleted", "is_active", "is_forgotten"}
    # treat these as blob-like by name even if type introspection is flaky
    BLOBISH_NAME_PARTS = {"embedding"}

    def _col_name(self, col: int) -> str:
        try:
            name = self.headerData(col, Qt.Orientation.Horizontal)
            return str(name or "")
        except Exception:
            return ""

    def _is_blob_column(self, col: int) -> bool:
        name = self._col_name(col).lower().strip()
        if any(p in name for p in self.BLOBISH_NAME_PARTS):
            return True

        # Best-effort: check record type (may fail depending on driver state)
        try:
            rec = self.record()
            if rec and col < rec.count():
                f = rec.field(col)
                # If driver exposes ByteArray type, it often indicates BLOB.
                # We avoid hard enum dependency; instead look at returned value at runtime.
                return False
        except Exception:
            pass
        return False

    def flags(self, index):
        f = super().flags(index)
        if index.isValid() and self._is_blob_column(index.column()):
            # disable editing for blob columns
            return f & ~Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return super().data(index, role)

        col = index.column()
        col_name = self._col_name(col).lower().strip()

        # Use raw value from EditRole for decisions (DisplayRole might be already prettified somewhere else).
        raw = super().data(index, Qt.ItemDataRole.EditRole)

        if role == Qt.ItemDataRole.DisplayRole:
            # BLOB (embedding etc.)
            if self._is_blob_column(col) or "embedding" in col_name:
                has = _is_blob_value(raw)
                return "✓" if has else "✗"

            # bool-ish ints
            if col_name in self.BOOLISH_COLUMNS:
                try:
                    v = 0 if raw is None else int(raw)
                    return "✓" if v != 0 else "✗"
                except Exception:
                    return "✗" if _is_empty_value(raw) else "✓"

        return super().data(index, role)


class _AdvancedTablePage(QWidget):
    """
    One tab: filter area + search area + QTableView backed by QSqlTableModel.
    Keeps its own filter/search state and preserves sorting on refresh.
    """

    OPERATORS = ["Contains", "Equals", "Starts With", "Is Empty"]
    SEARCH_OPERATORS = ["Contains", "Starts With", "Equals"]

    # Default visible columns (non-extended mode). Missing columns are ignored.
    DEFAULT_VISIBLE = {
        "history": {
            "id",
            "timestamp",
            "role",
            "speaker",
            "target",
            "event_type",
            "participants",
            "tags",
            "content",
            "is_active",
            "is_deleted",
        },
        "memories": {
            "id",
            "date_created",
            "type",
            "priority",
            "tags",
            "participants",
            "content",
            "is_deleted",
            "is_forgotten",
        },
        "variables": {
            "character_id",
            "key",
            "value",
        },
        "graph_entities": {
            "id",
            "character_id",
            "name",
            "entity_type",
            "mention_count",
            "first_seen",
            "last_seen",
        },
        "graph_relations": {
            "id",
            "character_id",
            "subject_id",
            "predicate",
            "object_id",
            "confidence",
            "created_at",
        },
    }
    # Preferred widths for long-text columns (so they don't become huge).
    # With "Wrap text + auto row height" enabled, text fits by increasing row height.
    PREFERRED_TEXT_COL_WIDTH = {
        "history": {"content": 420},
        "memories": {"content": 420},
        "variables": {"value": 420},
        "graph_relations": {"predicate": 300},
    }

    def __init__(self, parent: QWidget, *, db: QSqlDatabase, table_name: str, character_id: Optional[str] = None):
        super().__init__(parent)
        self.db = db
        self.table_name = table_name
        self.character_id = character_id

        self._base_filter = self._build_base_filter()
        self._user_filter: str = ""
        self._search_filter: str = ""
        self._extended_columns: bool = False
        self._hscroll_before_click: Optional[int] = None
        self._vscroll_before_click: Optional[int] = None

        self.model = _PrettySqlTableModel(self, self.db)
        self.model.setTable(self.table_name)
        self.model.setEditStrategy(QSqlTableModel.EditStrategy.OnFieldChange)

        self.view = QTableView(self)
        self.view.setModel(self.model)

        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)
        # Disable inline editors (QLineEdit) to avoid:
        # - horizontal scrollbar "jump" after click/edit on long text cells
        # - single-line editing for multi-line fields like "content"
        # Editing/viewing is provided via a dedicated multi-line dialog on double click.
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Preserve scroll position on click (prevents delayed scroll "jump" to the clicked cell).
        self.view.pressed.connect(self._remember_scroll_pos)
        self.view.clicked.connect(self._restore_scroll_pos_later)
        self.view.doubleClicked.connect(self._open_cell_dialog)

        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

        # Row height / wrap support (toggled from the dialog).
        self._default_row_height = int(self.view.verticalHeader().defaultSectionSize())
        self._auto_row_height: bool = False

        self._row_resize_timer = QTimer(self)
        self._row_resize_timer.setSingleShot(True)
        self._row_resize_timer.setInterval(150)
        self._row_resize_timer.timeout.connect(self._resize_rows_to_contents_if_needed)

        # When wrapping is enabled, column width changes affect row height (line breaks).
        header.sectionResized.connect(lambda *_: self._queue_row_resize())

        # Context menu
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._on_context_menu)

        # Keyboard: Delete -> delete selected rows
        self._act_delete_shortcut = QAction("Delete Selected Rows", self.view)
        self._act_delete_shortcut.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        self._act_delete_shortcut.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self._act_delete_shortcut.triggered.connect(self._delete_selected_rows)
        self.view.addAction(self._act_delete_shortcut)

        # --- Filtering UI ---
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

        # --- Search UI ---
        self.cmb_search_column = QComboBox(self)
        self.cmb_search_operator = QComboBox(self)
        self.cmb_search_operator.addItems(self.SEARCH_OPERATORS)

        self.txt_search = QLineEdit(self)
        self.txt_search.setPlaceholderText("Search... (filters rows)")

        self.chk_search_case = QCheckBox("Case sensitive", self)
        self.btn_clear_search = QPushButton("Clear Search", self)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._apply_search_from_ui)

        self.txt_search.textChanged.connect(lambda: self._search_timer.start())
        self.cmb_search_column.currentIndexChanged.connect(lambda: self._search_timer.start())
        self.cmb_search_operator.currentIndexChanged.connect(lambda: self._search_timer.start())
        self.chk_search_case.toggled.connect(lambda: self._search_timer.start())
        self.btn_clear_search.clicked.connect(self.clear_search)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:", self))
        search_row.addWidget(self.txt_search, 4)
        search_row.addWidget(QLabel("In:", self))
        search_row.addWidget(self.cmb_search_column, 2)
        search_row.addWidget(QLabel("Op:", self))
        search_row.addWidget(self.cmb_search_operator, 1)
        search_row.addWidget(self.chk_search_case)
        search_row.addWidget(self.btn_clear_search)

        # Layout
        root = QVBoxLayout(self)
        root.addLayout(filter_row)
        root.addLayout(search_row)
        root.addWidget(self.view)

        # Initial load
        self.refresh()

    def set_extended_columns(self, enabled: bool) -> None:
        self._extended_columns = bool(enabled)
        self._apply_column_visibility()

    def set_auto_row_height(self, enabled: bool) -> None:
        """Enable/disable word-wrap + auto row height (ResizeToContents)."""
        self._auto_row_height = bool(enabled)
        self._apply_row_height_mode()

    def _apply_row_height_mode(self) -> None:
        try:
            vh = self.view.verticalHeader()
            self.view.setWordWrap(self._auto_row_height)
            self.view.setTextElideMode(
                Qt.TextElideMode.ElideNone if self._auto_row_height else Qt.TextElideMode.ElideRight
            )

            if self._auto_row_height:
                vh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
                self._queue_row_resize()
            else:
                vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
                vh.setDefaultSectionSize(self._default_row_height)
        except Exception:
            pass

    def _queue_row_resize(self) -> None:
        if not self._auto_row_height:
            return
        try:
            self._row_resize_timer.start()
        except Exception:
            pass

    def _resize_rows_to_contents_if_needed(self) -> None:
        if not self._auto_row_height:
            return
        try:
            self.view.resizeRowsToContents()
        except Exception:
            pass

    def _apply_preferred_text_column_widths(self) -> None:
        prefs = self.PREFERRED_TEXT_COL_WIDTH.get(self.table_name, {})
        if not prefs:
            return
        try:
            name_to_idx = {str(n).lower().strip(): i for i, n in self._iter_columns()}
            for col_name, width in prefs.items():
                idx = name_to_idx.get(col_name.lower().strip())
                if idx is None:
                    continue
                if self.view.isColumnHidden(idx):
                    continue
                self.view.setColumnWidth(idx, int(width))
        except Exception:
            pass

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
        parts = []
        if self._base_filter.strip():
            parts.append(f"({self._base_filter})")
        if self._user_filter.strip():
            parts.append(f"({self._user_filter})")
        if self._search_filter.strip():
            parts.append(f"({self._search_filter})")
        return " AND ".join(parts)

    def _set_filter_state(self, active: bool) -> None:
        self.lbl_filter_state.setText("Filter: ON" if active else "Filter: OFF")
        self.lbl_filter_state.setToolTip(self._combined_filter() or "(no filter)")
        self.lbl_filter_state.setStyleSheet(
            "font-weight: 600; color: #b00020;" if active else "font-weight: 600; color: #2e7d32;"
        )

    def _current_sort(self) -> Tuple[int, Qt.SortOrder]:
        header = self.view.horizontalHeader()
        try:
            # If user never sorted, avoid forcing sort on refresh.
            if not header.isSortIndicatorShown():
                return -1, Qt.SortOrder.AscendingOrder
        except Exception:
            pass
        return header.sortIndicatorSection(), header.sortIndicatorOrder()

    def _apply_sort(self, sort_column: int, sort_order: Qt.SortOrder) -> None:
        if sort_column is None or sort_column < 0:
            return
        try:
            self.model.setSort(sort_column, sort_order)
        except Exception:
            pass

    def _iter_columns(self) -> List[Tuple[int, str]]:
        out: List[Tuple[int, str]] = []
        for i in range(self.model.columnCount()):
            name = str(self.model.headerData(i, Qt.Orientation.Horizontal) or f"col_{i}")
            out.append((i, name))
        return out

    def _is_embeddingish(self, name: str) -> bool:
        lname = (name or "").lower().strip()
        return "embedding" in lname

    def _is_searchable_column(self, name: str) -> bool:
        if not name:
            return False
        # don't search blobs by default
        if self._is_embeddingish(name):
            return False
        return True

    def _refresh_columns_combos(self) -> None:
        # Filter column combo
        self.cmb_column.blockSignals(True)
        self.cmb_search_column.blockSignals(True)
        try:
            self.cmb_column.clear()
            self.cmb_search_column.clear()

            # Search column: "All"
            self.cmb_search_column.addItem("All columns", None)

            for _, name in self._iter_columns():
                if self._is_embeddingish(name):
                    # still allow filtering by embedding presence via context menu; UI combo can skip
                    continue
                self.cmb_column.addItem(name, name)

                if self._is_searchable_column(name):
                    self.cmb_search_column.addItem(name, name)
        finally:
            self.cmb_column.blockSignals(False)
            self.cmb_search_column.blockSignals(False)

    def _apply_column_visibility(self) -> None:
        cols = self._iter_columns()

        if self._extended_columns:
            for i, _ in cols:
                self.view.showColumn(i)
            return

        visible = self.DEFAULT_VISIBLE.get(self.table_name, set())

        for i, name in cols:
            lname = (name or "").lower().strip()

            # Always hide obvious huge blob columns in non-extended mode
            if self._is_embeddingish(lname):
                self.view.hideColumn(i)
                continue

            # hide everything not in "visible allowlist" (if allowlist exists)
            if visible:
                if lname in visible:
                    self.view.showColumn(i)
                else:
                    self.view.hideColumn(i)
            else:
                # fallback heuristic (if table not in DEFAULT_VISIBLE)
                if lname in {"rag_id", "req_id", "task_uid", "meta_data", "embedding_id"}:
                    self.view.hideColumn(i)

    def refresh(self) -> None:
        sort_col, sort_order = self._current_sort()

        self.model.setFilter(self._combined_filter())
        self._apply_sort(sort_col, sort_order)

        if not self.model.select():
            err = self.model.lastError().text()
            logger.error(f"DB Viewer: select() failed for table '{self.table_name}': {err}")
            QMessageBox.critical(self, "Database Viewer", f"Failed to load table '{self.table_name}':\n{err}")

        self._refresh_columns_combos()
        self._apply_column_visibility()

        try:
            self.view.resizeColumnsToContents()
        except Exception:
            pass

        # Keep long-text columns from becoming too wide.
        self._apply_preferred_text_column_widths()
        # Apply current row-height mode (wrap + auto height if enabled).
        self._apply_row_height_mode()

        active = bool(self._user_filter.strip() or self._search_filter.strip())
        self._set_filter_state(active)

    # -------- Filter building helpers --------
    def _set_user_filter_expr(self, expr: str, *, append_and: bool = False) -> None:
        expr = (expr or "").strip()
        if not expr:
            return
        if append_and and self._user_filter.strip():
            self._user_filter = f"({self._user_filter}) AND ({expr})"
        else:
            self._user_filter = expr
        self.refresh()

    def _expr_equals(self, col_name: str, raw_value) -> str:
        col_ident = _q_ident(col_name)
        if raw_value is None:
            return f"{col_ident} IS NULL"
        if isinstance(raw_value, (int, float)):
            return f"{col_ident} = {raw_value}"
        v = _sql_escape_literal(str(raw_value))
        return f"{col_ident} = '{v}'"

    def _expr_contains(self, col_name: str, raw_value) -> str:
        col_ident = _q_ident(col_name)
        if raw_value is None or str(raw_value) == "":
            return f"({col_ident} IS NULL OR TRIM({col_ident}) = '')"
        v = _sql_escape_like(str(raw_value))
        return f"{col_ident} LIKE '%{v}%' ESCAPE '\\'"

    def _expr_is_empty(self, col_name: str) -> str:
        col_ident = _q_ident(col_name)
        return f"({col_ident} IS NULL OR TRIM({col_ident}) = '')"

    def _expr_has_value(self, col_name: str) -> str:
        col_ident = _q_ident(col_name)
        # for BLOB/embedding this also works as "has any bytes"
        if self._is_embeddingish(col_name):
            return f"({col_ident} IS NOT NULL AND LENGTH({col_ident}) > 0)"
        return f"({col_ident} IS NOT NULL AND TRIM({col_ident}) != '')"

    # -------- Filtering UI actions --------
    def apply_filter(self) -> None:
        col = self.cmb_column.currentData()
        if not col:
            return

        op = self.cmb_operator.currentText()
        raw_value = self.txt_value.text()

        col_ident = _q_ident(str(col))

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

    # -------- Search --------
    def _apply_search_from_ui(self) -> None:
        text = (self.txt_search.text() or "").strip()
        col = self.cmb_search_column.currentData()  # None means "All columns"
        op = self.cmb_search_operator.currentText()
        case_sensitive = bool(self.chk_search_case.isChecked())

        if not text:
            self._search_filter = ""
            self.refresh()
            return

        pattern = _sql_escape_like(text)

        def like_expr(col_name: str) -> str:
            c = _q_ident(col_name)
            if op == "Equals":
                v = _sql_escape_literal(text)
                expr = f"{c} = '{v}'"
            elif op == "Starts With":
                expr = f"CAST({c} AS TEXT) LIKE '{pattern}%' ESCAPE '\\'"
            else:  # Contains
                expr = f"CAST({c} AS TEXT) LIKE '%{pattern}%' ESCAPE '\\'"

            if not case_sensitive and op != "Equals":
                # Note: SQLite NOCASE is ASCII-only by default, but still useful.
                expr = f"({expr}) COLLATE NOCASE"
            return expr

        if col:
            self._search_filter = like_expr(str(col))
        else:
            # All columns (except blob-ish)
            cols = [name for _, name in self._iter_columns() if self._is_searchable_column(name)]
            if not cols:
                self._search_filter = ""
            else:
                self._search_filter = " OR ".join(f"({like_expr(c)})" for c in cols)

        self.refresh()

    def clear_search(self) -> None:
        self._search_filter = ""
        self.txt_search.clear()
        self.refresh()

    # -------- Selection helpers --------
    def _selected_row_numbers(self) -> List[int]:
        sel = self.view.selectionModel()
        if not sel:
            return []
        rows = [idx.row() for idx in sel.selectedRows()]
        return sorted(set(rows))

    # -------- Context menu --------
    def _on_context_menu(self, pos: QPoint) -> None:
        index = self.view.indexAt(pos)
        model = self.model

        menu = QMenu(self)

        if index.isValid():
            col_name = str(model.headerData(index.column(), Qt.Orientation.Horizontal) or f"Column {index.column()}")
            raw = model.data(index, Qt.ItemDataRole.EditRole)

            # Quick filter submenu
            sub_filter = menu.addMenu(f'Filter by "{col_name}"')

            act_eq = QAction("Equals this value (replace)", self)
            act_eq.triggered.connect(lambda: self._set_user_filter_expr(self._expr_equals(col_name, raw), append_and=False))
            sub_filter.addAction(act_eq)

            act_eq_and = QAction("Equals this value (AND)", self)
            act_eq_and.triggered.connect(lambda: self._set_user_filter_expr(self._expr_equals(col_name, raw), append_and=True))
            sub_filter.addAction(act_eq_and)

            act_contains = QAction("Contains this value (replace)", self)
            act_contains.triggered.connect(
                lambda: self._set_user_filter_expr(self._expr_contains(col_name, raw), append_and=False)
            )
            sub_filter.addAction(act_contains)

            act_contains_and = QAction("Contains this value (AND)", self)
            act_contains_and.triggered.connect(
                lambda: self._set_user_filter_expr(self._expr_contains(col_name, raw), append_and=True)
            )
            sub_filter.addAction(act_contains_and)

            sub_filter.addSeparator()

            act_empty = QAction("Is Empty (replace)", self)
            act_empty.triggered.connect(lambda: self._set_user_filter_expr(self._expr_is_empty(col_name), append_and=False))
            sub_filter.addAction(act_empty)

            act_empty_and = QAction("Is Empty (AND)", self)
            act_empty_and.triggered.connect(lambda: self._set_user_filter_expr(self._expr_is_empty(col_name), append_and=True))
            sub_filter.addAction(act_empty_and)

            act_has = QAction("Has Value (replace)", self)
            act_has.triggered.connect(lambda: self._set_user_filter_expr(self._expr_has_value(col_name), append_and=False))
            sub_filter.addAction(act_has)

            act_has_and = QAction("Has Value (AND)", self)
            act_has_and.triggered.connect(lambda: self._set_user_filter_expr(self._expr_has_value(col_name), append_and=True))
            sub_filter.addAction(act_has_and)

            menu.addSeparator()

            # Quick search actions
            act_search_col = QAction(f'Search this value in "{col_name}"', self)
            act_search_col.triggered.connect(lambda: self._search_from_cell(col_name, raw))
            menu.addAction(act_search_col)

            act_search_all = QAction("Search this value in all columns", self)
            act_search_all.triggered.connect(lambda: self._search_from_cell(None, raw))
            menu.addAction(act_search_all)

            menu.addSeparator()

            # Column visibility quick actions
            act_hide_col = QAction(f'Hide column "{col_name}"', self)
            act_hide_col.triggered.connect(lambda: self.view.hideColumn(index.column()))
            menu.addAction(act_hide_col)

            act_show_all_cols = QAction("Show all columns (this tab)", self)
            act_show_all_cols.triggered.connect(self._show_all_columns_temp)
            menu.addAction(act_show_all_cols)

            act_reset_cols = QAction("Reset columns to default", self)
            act_reset_cols.triggered.connect(self._apply_column_visibility)
            menu.addAction(act_reset_cols)

            menu.addSeparator()

            # Copy / batch edit
            act_copy = QAction("Copy Cell Content", self)
            act_copy.triggered.connect(lambda: self._copy_cell(index))
            menu.addAction(act_copy)

            act_batch = QAction(f'Batch Edit "{col_name}"', self)
            act_batch.triggered.connect(lambda: self._batch_edit(index))
            menu.addAction(act_batch)

            menu.addSeparator()

        # Delete is always available
        act_delete = QAction("Delete Selected Rows", self)
        act_delete.triggered.connect(self._delete_selected_rows)
        menu.addAction(act_delete)

        # Clear helpers
        menu.addSeparator()
        act_clear_filters = QAction("Clear Filter (keep base)", self)
        act_clear_filters.triggered.connect(self.clear_filter)
        menu.addAction(act_clear_filters)

        act_clear_search = QAction("Clear Search", self)
        act_clear_search.triggered.connect(self.clear_search)
        menu.addAction(act_clear_search)

        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _show_all_columns_temp(self) -> None:
        # Show all for this tab without touching the global "extended output" checkbox.
        for i in range(self.model.columnCount()):
            self.view.showColumn(i)

    def _search_from_cell(self, col_name: Optional[str], raw_value) -> None:
        if raw_value is None:
            text = ""
        else:
            # for blobs we search "has value" via filter, not via text search
            if _is_blob_value(raw_value):
                # if user clicked on blob cell: set search text empty and add a "has value" filter
                if col_name:
                    self._set_user_filter_expr(self._expr_has_value(col_name), append_and=True)
                return
            text = str(raw_value)

        self.txt_search.setText(text)
        if col_name is None:
            self.cmb_search_column.setCurrentIndex(0)  # All columns
        else:
            # Find column item
            for i in range(self.cmb_search_column.count()):
                if self.cmb_search_column.itemData(i) == col_name:
                    self.cmb_search_column.setCurrentIndex(i)
                    break
        self._apply_search_from_ui()

    def _copy_cell(self, index) -> None:
        try:
            text = self.model.data(index, Qt.ItemDataRole.DisplayRole)
            if text is None:
                text = ""
            QApplication.clipboard().setText(str(text))
        except Exception as e:
            logger.error(f"DB Viewer: copy failed: {e}", exc_info=True)

    def _remember_scroll_pos(self, _index) -> None:
        try:
            self._hscroll_before_click = int(self.view.horizontalScrollBar().value())
            self._vscroll_before_click = int(self.view.verticalScrollBar().value())
        except Exception:
            self._hscroll_before_click = None
            self._vscroll_before_click = None

    def _restore_scroll_pos_later(self, _index) -> None:
        """
        QTableView may auto-scroll to the current index after the click is processed.
        Restore previous scroll position to prevent the horizontal scrollbar "jump".
        """
        h = self._hscroll_before_click
        v = self._vscroll_before_click
        if h is None and v is None:
            return

        hbar = self.view.horizontalScrollBar()
        vbar = self.view.verticalScrollBar()

        def restore():
            try:
                if h is not None:
                    hbar.setValue(h)
                if v is not None:
                    vbar.setValue(v)
            except Exception:
                pass

        # Do it twice: immediately after event loop and a tiny bit later
        # (covers delayed scrollTo/ensureVisible triggered by the view/editor).
        QTimer.singleShot(0, restore)
        QTimer.singleShot(50, restore)

        self._hscroll_before_click = None
        self._vscroll_before_click = None

    def _open_cell_dialog(self, index) -> None:
        """Multi-line viewer/editor for cell content (replaces single-line inline editor)."""
        if not index.isValid():
            return

        col_name = str(self.model.headerData(index.column(), Qt.Orientation.Horizontal) or f"Column {index.column()}")
        lname = col_name.lower().strip()

        # Don't open huge/opaque blobs in a text editor.
        if "embedding" in lname:
            QMessageBox.information(
                self,
                "View Cell",
                f'"{col_name}" looks like a BLOB/embedding field.\n'
                f"Inline viewing/editing is disabled for this column.",
            )
            return

        raw = self.model.data(index, Qt.ItemDataRole.EditRole)
        text = "" if raw is None else str(raw)

        editable = bool(self.model.flags(index) & Qt.ItemFlag.ItemIsEditable)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.table_name}.{col_name} (row {index.row() + 1})")
        dlg.resize(900, 520)

        root = QVBoxLayout(dlg)
        editor = QPlainTextEdit(dlg)
        editor.setPlainText(text)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setReadOnly(not editable)
        root.addWidget(editor, 1)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton("Copy", dlg)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(editor.toPlainText()))
        btn_row.addWidget(btn_copy)

        btn_row.addStretch(1)

        btn_save = None
        if editable:
            btn_save = QPushButton("Save", dlg)
            btn_row.addWidget(btn_save)

        btn_close = QPushButton("Close", dlg)
        btn_close.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        if editable and btn_save is not None:
            def do_save() -> None:
                new_val = editor.toPlainText()
                col_name_save = str(self.model.headerData(index.column(), Qt.Orientation.Horizontal) or "")
                if not col_name_save:
                    QMessageBox.critical(self, "Save Failed", "Could not determine column name.")
                    return

                rec = self.model.record(index.row())
                pk = rec.value("id")
                if pk is None:
                    QMessageBox.critical(self, "Save Failed", "Could not determine row ID (no 'id' column?).")
                    return

                try:
                    db = self.model.database()
                    q = QSqlQuery(db)
                    q.prepare(f'UPDATE "{self.table_name}" SET "{col_name_save}" = ? WHERE id = ?')
                    q.addBindValue(new_val)
                    q.addBindValue(pk)
                    if not q.exec():
                        err = q.lastError().text()
                        logger.error(f"DB Viewer: cell save failed for '{self.table_name}.{col_name_save}': {err}")
                        QMessageBox.critical(self, "Save Failed", f"Failed to commit change:\n{err}")
                        return
                except Exception as e:
                    logger.error(f"DB Viewer: cell save exception: {e}", exc_info=True)
                    QMessageBox.critical(self, "Save Failed", f"Failed to commit change:\n{e}")
                    return

                self.refresh()
                dlg.accept()

            btn_save.clicked.connect(do_save)

        dlg.exec()

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

        # Collect IDs first, then write via direct SQL (same reason as batch edit:
        # avoids QSqlTableModel.submitAll() "database is locked" on QSQLITE).
        row_ids = []
        for r in rows:
            rec = self.model.record(r)
            pk = rec.value("id")
            if pk is not None:
                row_ids.append(pk)

        if not row_ids:
            QMessageBox.warning(self, "Delete Failed", "Could not determine row IDs (no 'id' column?).")
            return

        try:
            ids_literal = ",".join(str(int(pk)) for pk in row_ids)
            db = self.model.database()
            q = QSqlQuery(db)
            if not q.exec(f'DELETE FROM "{self.table_name}" WHERE id IN ({ids_literal})'):
                err = q.lastError().text()
                logger.error(f"DB Viewer: delete failed on '{self.table_name}': {err}")
                QMessageBox.critical(self, "Delete Failed", f"Failed to delete rows:\n{err}")
                return
        except Exception as e:
            logger.error(f"DB Viewer: delete exception on '{self.table_name}': {e}", exc_info=True)
            QMessageBox.critical(self, "Delete Failed", f"Failed to delete rows:\n{e}")
            return

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

        # Collect primary key values for selected rows (avoids QSqlTableModel.submitAll()
        # which can fail with "database is locked" due to Qt keeping a SELECT cursor open
        # on the same connection while trying to re-fetch rows after each UPDATE).
        row_ids = []
        for r in rows:
            rec = self.model.record(r)
            pk = rec.value("id")
            if pk is not None:
                row_ids.append(pk)

        if not row_ids:
            QMessageBox.warning(self, "Batch Edit", "Could not determine row IDs (no 'id' column?).")
            return

        # Direct SQL via QSqlQuery — bypasses model's submitAll() fetch-back loop.
        db = self.model.database()
        try:
            ids_literal = ",".join(str(int(pk)) for pk in row_ids)
            q = QSqlQuery(db)
            q.prepare(f'UPDATE "{self.table_name}" SET "{col_name}" = ? WHERE id IN ({ids_literal})')
            q.addBindValue(new_val)
            if not q.exec():
                err = q.lastError().text()
                logger.error(f"DB Viewer: direct UPDATE failed for batch edit '{self.table_name}.{col_name}': {err}")
                QMessageBox.critical(self, "Batch Edit Failed", f"Failed to commit changes:\n{err}")
                return
        except Exception as e:
            logger.error(f"DB Viewer: batch edit exception: {e}", exc_info=True)
            QMessageBox.critical(self, "Batch Edit Failed", f"Failed to update values:\n{e}")
            return

        self.refresh()


class DbViewerDialog(QDialog):
    """
    Advanced Database Viewer:
    - Unique QtSql connection name
    - Per-tab filtering + search
    - Quick right-click filter by cell value
    - Default column hiding + global "Extended output" checkbox
    - BLOB (embedding) rendered as ✓/✗ instead of bytes
    """

    def __init__(self, parent=None, character_id: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Advanced Database Viewer (World.db)")
        self.resize(1200, 740)
        self.character_id = character_id

        self._connection_name = f"db_viewer_connection_{id(self)}"
        self.db = self._init_sql_connection()

        layout = QVBoxLayout(self)

        # Global "extended output" checkbox (affects all tabs)
        top_row = QHBoxLayout()
        self.chk_extended = QCheckBox("Extended output (show all columns)", self)
        self.chk_extended.setChecked(False)
        top_row.addWidget(self.chk_extended)
        self.chk_auto_row_height = QCheckBox("Wrap text + auto row height", self)
        self.chk_auto_row_height.setChecked(False)
        top_row.addWidget(self.chk_auto_row_height)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self.history_page = _AdvancedTablePage(self, db=self.db, table_name="history", character_id=self.character_id)
        self.memories_page = _AdvancedTablePage(self, db=self.db, table_name="memories", character_id=self.character_id)
        self.variables_page = _AdvancedTablePage(self, db=self.db, table_name="variables", character_id=self.character_id)

        self.tabs.addTab(self.history_page, "History")
        self.tabs.addTab(self.memories_page, "Memories")
        self.tabs.addTab(self.variables_page, "Variables")

        # Graph tables (only if they exist in the database).
        self._graph_pages: list[_AdvancedTablePage] = []
        for tbl_name, tab_label in [("graph_entities", "Graph: Entities"), ("graph_relations", "Graph: Relations")]:
            if self._table_exists(tbl_name):
                page = _AdvancedTablePage(self, db=self.db, table_name=tbl_name, character_id=self.character_id)
                self.tabs.addTab(page, tab_label)
                self._graph_pages.append(page)

        self.chk_extended.toggled.connect(self._apply_extended_to_all)
        self._apply_extended_to_all(self.chk_extended.isChecked())
        self.chk_auto_row_height.toggled.connect(self._apply_auto_row_height_to_all)
        self._apply_auto_row_height_to_all(self.chk_auto_row_height.isChecked())
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

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        if not self.db or not self.db.isOpen():
            return False
        q = QSqlQuery(self.db)
        q.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?")
        q.addBindValue(table_name)
        if q.exec() and q.next():
            return True
        return False

    @property
    def _all_pages(self) -> list:
        pages = [self.history_page, self.memories_page, self.variables_page]
        pages.extend(self._graph_pages)
        return pages

    def _apply_extended_to_all(self, enabled: bool) -> None:
        try:
            for page in self._all_pages:
                page.set_extended_columns(enabled)
        except Exception:
            pass

    def _apply_auto_row_height_to_all(self, enabled: bool) -> None:
        try:
            for page in self._all_pages:
                page.set_auto_row_height(enabled)
        except Exception:
            pass

    def _init_sql_connection(self) -> QSqlDatabase:
        db_path = os.path.join("Histories", "world.db")

        db = QSqlDatabase.addDatabase("QSQLITE", self._connection_name)
        db.setDatabaseName(db_path)
        db.setConnectOptions("QSQLITE_BUSY_TIMEOUT=5000")

        if not db.open():
            err = db.lastError().text()
            logger.error(f"DB Viewer: failed to open Qt DB connection: {err}")
            QMessageBox.critical(self, "Database Viewer", f"Failed to open database:\n{err}")
            # Remove orphaned connection to prevent leak
            db = QSqlDatabase()
            QSqlDatabase.removeDatabase(self._connection_name)
            return db

        try:
            db.exec("PRAGMA journal_mode=WAL;")
            db.exec("PRAGMA busy_timeout = 5000;")
        except Exception as e:
            logger.error(f"DB Viewer: failed to apply PRAGMAs via Qt connection: {e}", exc_info=True)

        return db

    def refresh_all(self) -> None:
        for page in self._all_pages:
            page.refresh()

    def closeEvent(self, event) -> None:
        try:
            for page in self._all_pages:
                page.cleanup()
        except Exception:
            pass

        try:
            if self.db and self.db.isOpen():
                self.db.close()
        except Exception:
            pass

        try:
            name = self._connection_name
            self.db = None
            QSqlDatabase.removeDatabase(name)
        except Exception:
            pass

        super().closeEvent(event)