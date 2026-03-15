from __future__ import annotations

import os
import sys
import json
from typing import Any

# --- make project root importable ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QComboBox,
    QFormLayout,
    QDockWidget,
    QTabWidget,
    QScrollArea,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
)

from styles.main_styles import get_stylesheet
from rag_tester_core import RagTesterService, Scenario


def as_stripped(v: Any) -> str:
    return str(v or "").strip()


# ── score colour thresholds ──────────────────────────────────────────────────
_CLR_GREEN  = QColor(60, 160, 60)
_CLR_YELLOW = QColor(200, 160, 0)
_CLR_RED    = QColor(180, 60, 60)
_CLR_GREY   = QColor(130, 130, 130)

def _score_color(score: float) -> QColor:
    if score >= 0.7:
        return _CLR_GREEN
    if score >= 0.4:
        return _CLR_YELLOW
    return _CLR_RED


def _fmt_features(features: dict) -> str:
    """Compact one-liner: s=0.82 k=0.00 l=0.00 t=0.60 e=1.0 p=0.5"""
    if not features:
        return ""
    mapping = [("sim", "s"), ("kw", "k"), ("lex", "l"), ("time", "t"), ("entity", "e"), ("prio", "p")]
    parts = []
    for key, abbr in mapping:
        v = features.get(key)
        if v is not None:
            parts.append(f"{abbr}={float(v):.2f}")
    # include any unexpected keys
    known = {k for k, _ in mapping}
    for k, v in features.items():
        if k not in known:
            parts.append(f"{k[:3]}={float(v):.2f}")
    return " ".join(parts)


# ── history list cap ─────────────────────────────────────────────────────────
_HISTORY_MAX = 25

# ── table column indices ─────────────────────────────────────────────────────
_COL_SOURCE  = 0
_COL_ID      = 1
_COL_SCORE   = 2
_COL_FEAT    = 3
_COL_TYPE    = 4
_COL_PRIO    = 5
_COL_DATE    = 6
_COL_SP_TG   = 7
_COL_CONTENT = 8


class RagTesterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RAG Tester")

        self.svc = RagTesterService()
        self._query_history: list[str] = []
        self._last_results: list[dict] = []

        self._build_actions()
        self._build_menu()
        self._build_central_ui()
        self._build_settings_dock()
        self._wire_events()

        self.on_template()

    # ─────────────────────────── UI builders ────────────────────────────────

    def _build_actions(self) -> None:
        self.act_toggle_settings = QAction("RAG Settings", self)
        self.act_toggle_settings.setCheckable(True)
        self.act_toggle_settings.setChecked(False)

    def _build_menu(self) -> None:
        view = self.menuBar().addMenu("View")
        view.addAction(self.act_toggle_settings)

    def _build_central_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(15)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # ═══ LEFT TABS ═══════════════════════════════════════════════════════
        left_tabs = QTabWidget()
        splitter.addWidget(left_tabs)

        # ── Scenario Tab ─────────────────────────────────────────────────────
        tab_scn = QWidget()
        tab_scn_l = QVBoxLayout(tab_scn)
        tab_scn_l.setContentsMargins(15, 15, 15, 15)
        tab_scn_l.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("character_id:"))
        self.character_id_edit = QLineEdit("RAG_TEST")
        self.character_id_edit.setFixedWidth(200)
        top_row.addWidget(self.character_id_edit)
        top_row.addStretch(1)

        self.btn_template = QPushButton("Шаблон")
        self.btn_load_file = QPushButton("Load…")
        self.btn_save_file = QPushButton("Save…")
        top_row.addWidget(self.btn_template)
        top_row.addWidget(self.btn_load_file)
        top_row.addWidget(self.btn_save_file)

        tab_scn_l.addLayout(top_row)
        self.scenario_edit = QTextEdit()
        self.scenario_edit.setAcceptRichText(False)
        tab_scn_l.addWidget(self.scenario_edit, 1)
        left_tabs.addTab(tab_scn, "Scenario")

        # ── Data Tab ─────────────────────────────────────────────────────────
        tab_data = QWidget()
        tab_data_l = QVBoxLayout(tab_data)
        tab_data_l.setContentsMargins(15, 20, 15, 15)
        tab_data_l.setSpacing(25)

        gb_db = QGroupBox("Database")
        gb_db_l = QVBoxLayout(gb_db)
        gb_db_l.setSpacing(15)
        gb_db_l.setContentsMargins(12, 20, 12, 12)

        db_btns = QHBoxLayout()
        self.btn_apply = QPushButton("Залить scenario в БД")
        self.btn_load_from_db = QPushButton("Загрузить scenario из БД")
        db_btns.addWidget(self.btn_apply)
        db_btns.addWidget(self.btn_load_from_db)
        gb_db_l.addLayout(db_btns)

        chk_l = QVBoxLayout()
        chk_l.setSpacing(8)
        self.chk_clear_before = QCheckBox("Очистить перед заливкой (опасно)")
        self.chk_embed_now = QCheckBox("Embed при заливке/импорте")
        self.chk_embed_now.setChecked(True)
        chk_l.addWidget(self.chk_clear_before)
        chk_l.addWidget(self.chk_embed_now)
        gb_db_l.addLayout(chk_l)

        db_form = QFormLayout()
        db_form.setVerticalSpacing(12)
        self.db_hist_limit = QSpinBox()
        self.db_hist_limit.setRange(0, 200000)
        self.db_hist_limit.setValue(3000)
        self.db_mem_limit = QSpinBox()
        self.db_mem_limit.setRange(0, 200000)
        self.db_mem_limit.setValue(4997)
        self.db_hist_limit.setFixedWidth(120)
        self.db_mem_limit.setFixedWidth(120)
        db_form.addRow("history limit:", self.db_hist_limit)
        db_form.addRow("memories limit:", self.db_mem_limit)
        gb_db_l.addLayout(db_form)
        tab_data_l.addWidget(gb_db)

        gb_import = QGroupBox("Import legacy JSON")
        gb_import_l = QVBoxLayout(gb_import)
        gb_import_l.setSpacing(15)
        gb_import_l.setContentsMargins(12, 20, 12, 12)

        imp_btns = QHBoxLayout()
        self.btn_import_old_history = QPushButton("Импорт history JSON…")
        self.btn_import_old_memories = QPushButton("Импорт memories JSON…")
        imp_btns.addWidget(self.btn_import_old_history)
        imp_btns.addWidget(self.btn_import_old_memories)
        gb_import_l.addLayout(imp_btns)

        imp_form = QFormLayout()
        self.import_context_tail = QSpinBox()
        self.import_context_tail.setRange(0, 50)
        self.import_context_tail.setValue(2)
        self.import_context_tail.setFixedWidth(120)
        imp_form.addRow("Tail -> context:", self.import_context_tail)
        gb_import_l.addLayout(imp_form)
        tab_data_l.addWidget(gb_import)

        gb_index = QGroupBox("Indexing")
        gb_index_l = QHBoxLayout(gb_index)
        gb_index_l.setContentsMargins(12, 20, 12, 12)
        gb_index_l.setSpacing(10)
        self.btn_index_missing = QPushButton("Index missing")
        self.btn_missing_count = QPushButton("Missing count")
        gb_index_l.addWidget(self.btn_index_missing)
        gb_index_l.addWidget(self.btn_missing_count)
        gb_index_l.addStretch(1)
        tab_data_l.addWidget(gb_index)

        tab_data_l.addStretch(1)
        left_tabs.addTab(tab_data, "Data")

        # ═══ RIGHT PANEL (SEARCH) ════════════════════════════════════════════
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(8)

        # ── Query history (collapsible) ───────────────────────────────────────
        self._history_visible = False
        self.btn_toggle_history = QPushButton("▸ History")
        self.btn_toggle_history.setFixedHeight(24)
        self.btn_toggle_history.setCheckable(True)
        right_l.addWidget(self.btn_toggle_history)

        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(120)
        self.history_list.setVisible(False)
        right_l.addWidget(self.history_list)

        # ── Query row ────────────────────────────────────────────────────────
        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("Query:"))
        self.query_edit = QLineEdit()
        qrow.addWidget(self.query_edit, 1)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 200)
        self.limit_spin.setValue(10)
        self.limit_spin.setFixedWidth(60)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-1.0, 1.0)
        self.threshold_spin.setValue(0.40)
        self.threshold_spin.setFixedWidth(70)

        qrow.addWidget(QLabel("limit"))
        qrow.addWidget(self.limit_spin)
        qrow.addWidget(QLabel("thr"))
        qrow.addWidget(self.threshold_spin)

        self.btn_search = QPushButton("Search")
        self.btn_preview_inject = QPushButton("Preview")
        self.btn_export_json = QPushButton("Export JSON")
        qrow.addWidget(self.btn_search)
        qrow.addWidget(self.btn_preview_inject)
        qrow.addWidget(self.btn_export_json)
        right_l.addLayout(qrow)

        self.right_tabs = QTabWidget()
        right_l.addWidget(self.right_tabs, 1)

        # ── Results tab ───────────────────────────────────────────────────────
        tab_res = QWidget()
        tab_res_l = QVBoxLayout(tab_res)
        tab_res_l.setContentsMargins(0, 0, 0, 0)
        res_split = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["source", "id", "score", "features", "type/role", "priority", "date", "speaker→target", "content"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(_COL_SOURCE, 60)
        self.table.setColumnWidth(_COL_ID, 45)
        self.table.setColumnWidth(_COL_SCORE, 60)
        self.table.setColumnWidth(_COL_FEAT, 220)
        self.table.setColumnWidth(_COL_TYPE, 70)
        self.table.setColumnWidth(_COL_PRIO, 65)
        self.table.setColumnWidth(_COL_DATE, 130)
        self.table.setColumnWidth(_COL_SP_TG, 110)
        res_split.addWidget(self.table)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        res_split.addWidget(self.details)
        res_split.setStretchFactor(0, 3)
        res_split.setStretchFactor(1, 1)
        tab_res_l.addWidget(res_split)
        self.right_tabs.addTab(tab_res, "Results")

        # ── Debug tab ─────────────────────────────────────────────────────────
        tab_dbg = QWidget()
        tab_dbg_l = QVBoxLayout(tab_dbg)
        tab_dbg_l.setSpacing(10)
        tab_dbg_l.addWidget(QLabel("Effective query:"))
        self.effective_query_view = QPlainTextEdit()
        self.effective_query_view.setReadOnly(True)
        tab_dbg_l.addWidget(self.effective_query_view, 1)
        tab_dbg_l.addWidget(QLabel("Injection preview:"))
        self.injection_preview = QPlainTextEdit()
        self.injection_preview.setReadOnly(True)
        tab_dbg_l.addWidget(self.injection_preview, 2)
        self.right_tabs.addTab(tab_dbg, "Debug")

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 880])

    def _build_settings_dock(self) -> None:
        dock = QDockWidget("RAG Settings", self)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setSpacing(8)

        self.chk_use_overrides = QCheckBox("Use overrides")
        self.chk_use_overrides.setChecked(True)
        v.addWidget(self.chk_use_overrides)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(10)

        # ── Weights ──────────────────────────────────────────────────────────
        gb_w = QGroupBox("Weights")
        form_w = QFormLayout(gb_w)
        form_w.setVerticalSpacing(6)

        def dspin(lo=-10.0, hi=10.0, val=1.0, step=0.1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setValue(val)
            s.setSingleStep(step)
            s.setFixedWidth(90)
            return s

        self.k1 = dspin(val=1.0);  form_w.addRow("K1 similarity:", self.k1)
        self.k2 = dspin(val=1.0);  form_w.addRow("K2 time:", self.k2)
        self.k3 = dspin(val=1.0);  form_w.addRow("K3 priority:", self.k3)
        self.k4 = dspin(val=0.5);  form_w.addRow("K4 entity:", self.k4)
        self.k5 = dspin(val=0.6);  form_w.addRow("K5 keywords:", self.k5)
        self.k6 = dspin(val=0.3);  form_w.addRow("K6 lexical:", self.k6)
        self.decay = dspin(lo=0.0, hi=10.0, val=0.15, step=0.05)
        form_w.addRow("time decay:", self.decay)
        self.noise = dspin(lo=0.0, hi=1.0, val=0.05, step=0.01)
        form_w.addRow("noise max:", self.noise)
        scroll_layout.addWidget(gb_w)

        # ── Query ─────────────────────────────────────────────────────────────
        gb_q = QGroupBox("Query")
        form_q = QFormLayout(gb_q)
        form_q.setVerticalSpacing(6)

        self.tail_messages = QSpinBox()
        self.tail_messages.setRange(0, 20)
        self.tail_messages.setValue(2)
        self.tail_messages.setFixedWidth(90)
        form_q.addRow("tail messages:", self.tail_messages)

        self.search_memory = QCheckBox("search_memory")
        self.search_memory.setChecked(False)
        form_q.addRow(self.search_memory)

        self.search_history = QCheckBox("search_history")
        self.search_history.setChecked(True)
        form_q.addRow(self.search_history)

        self.memory_mode = QComboBox()
        self.memory_mode.addItems(["forgotten", "active", "all"])
        self.memory_mode.setCurrentText("forgotten")
        form_q.addRow("memory mode:", self.memory_mode)
        scroll_layout.addWidget(gb_q)

        # ── Retrieval ─────────────────────────────────────────────────────────
        gb_r = QGroupBox("Retrieval")
        form_r = QFormLayout(gb_r)
        form_r.setVerticalSpacing(6)

        self.combine_mode_combo = QComboBox()
        self.combine_mode_combo.addItems(["union", "vector_only", "intersect", "two_stage"])
        self.combine_mode_combo.setCurrentText("union")
        form_r.addRow("combine mode:", self.combine_mode_combo)

        self.kw_enabled = QCheckBox("keyword search")
        self.kw_enabled.setChecked(False)
        form_r.addRow(self.kw_enabled)

        self.use_fts = QCheckBox("FTS search")
        self.use_fts.setChecked(False)
        form_r.addRow(self.use_fts)
        scroll_layout.addWidget(gb_r)

        # ── Misc ──────────────────────────────────────────────────────────────
        gb_m = QGroupBox("Misc")
        form_m = QFormLayout(gb_m)
        form_m.setVerticalSpacing(6)

        self.detailed_logs = QCheckBox("RAG_DETAILED_LOGS")
        self.detailed_logs.setChecked(True)
        form_m.addRow(self.detailed_logs)

        self.include_forgotten = QCheckBox("RAG_INCLUDE_FORGOTTEN")
        self.include_forgotten.setChecked(False)
        form_m.addRow(self.include_forgotten)

        self.forgotten_penalty = dspin(lo=-5.0, hi=5.0, val=-0.15, step=0.05)
        form_m.addRow("forgotten penalty:", self.forgotten_penalty)
        scroll_layout.addWidget(gb_m)

        scroll_layout.addStretch(1)

        btn_reset = QPushButton("Reset defaults")
        btn_reset.clicked.connect(self._reset_settings_defaults)
        scroll_layout.addWidget(btn_reset)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(scroll_widget)
        v.addWidget(scroll, 1)

        dock.setWidget(wrap)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setVisible(False)
        dock.setMinimumWidth(320)
        dock.setMaximumWidth(440)

        self.settings_dock = dock
        self.act_toggle_settings.toggled.connect(self.settings_dock.setVisible)
        self.settings_dock.visibilityChanged.connect(self.act_toggle_settings.setChecked)

    def _wire_events(self) -> None:
        self.btn_template.clicked.connect(self.on_template)
        self.btn_load_file.clicked.connect(self.on_load_file)
        self.btn_save_file.clicked.connect(self.on_save_file)

        self.btn_apply.clicked.connect(self.on_apply)
        self.btn_load_from_db.clicked.connect(self.on_load_from_db)

        self.btn_import_old_history.clicked.connect(self.on_import_old_history)
        self.btn_import_old_memories.clicked.connect(self.on_import_old_memories)

        self.btn_index_missing.clicked.connect(self.on_index_missing)
        self.btn_missing_count.clicked.connect(self.on_missing_count)

        self.btn_search.clicked.connect(self.on_search)
        self.btn_preview_inject.clicked.connect(self.on_preview_inject)
        self.btn_export_json.clicked.connect(self.on_export_json)

        self.btn_toggle_history.toggled.connect(self._on_toggle_history)
        self.history_list.itemClicked.connect(self._on_history_item_clicked)

        self.table.itemSelectionChanged.connect(self.on_table_selection)

    # ─────────────────────────── helpers ────────────────────────────────────

    def current_cid(self) -> str:
        return self.character_id_edit.text().strip() or "RAG_TEST"

    def parse_editor_scenario(self) -> Scenario:
        raw = self.scenario_edit.toPlainText().strip()
        if not raw:
            raise ValueError("Scenario JSON пустой.")
        obj = json.loads(raw)
        return Scenario.from_json(obj, fallback_character_id=self.current_cid())

    def set_editor_scenario(self, sc: Scenario) -> None:
        self.character_id_edit.setText(sc.character_id)
        self.scenario_edit.setPlainText(sc.to_pretty_json())

    def ask_replace_or_merge(self) -> bool:
        mb = QMessageBox(self)
        mb.setWindowTitle("Импорт")
        mb.setText("Как применить импорт?")
        replace_btn = mb.addButton("Заменить scenario", QMessageBox.ButtonRole.AcceptRole)
        merge_btn   = mb.addButton("Смержить (добавить)", QMessageBox.ButtonRole.ActionRole)
        cancel_btn  = mb.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        mb.exec()
        clicked = mb.clickedButton()
        if clicked == cancel_btn:
            raise RuntimeError("cancelled")
        return clicked == replace_btn

    def collect_overrides(self) -> dict[str, Any]:
        return {
            "RAG_WEIGHT_SIMILARITY":    float(self.k1.value()),
            "RAG_WEIGHT_TIME":          float(self.k2.value()),
            "RAG_WEIGHT_PRIORITY":      float(self.k3.value()),
            "RAG_WEIGHT_ENTITY":        float(self.k4.value()),
            "RAG_WEIGHT_KEYWORDS":      float(self.k5.value()),
            "RAG_WEIGHT_LEXICAL":       float(self.k6.value()),
            "RAG_TIME_DECAY_RATE":      float(self.decay.value()),
            "RAG_NOISE_MAX":            float(self.noise.value()),
            "RAG_MEMORY_MODE":          str(self.memory_mode.currentText() or "forgotten"),
            "RAG_DETAILED_LOGS":        bool(self.detailed_logs.isChecked()),
            "RAG_INCLUDE_FORGOTTEN":    bool(self.include_forgotten.isChecked()),
            "RAG_FORGOTTEN_PENALTY":    float(self.forgotten_penalty.value()),
            "RAG_QUERY_TAIL_MESSAGES":  int(self.tail_messages.value()),
            "RAG_SEARCH_MEMORY":        bool(self.search_memory.isChecked()),
            "RAG_SEARCH_HISTORY":       bool(self.search_history.isChecked()),
            "RAG_COMBINE_MODE":         str(self.combine_mode_combo.currentText()),
            "RAG_KEYWORD_SEARCH":       bool(self.kw_enabled.isChecked()),
            "RAG_USE_FTS":              bool(self.use_fts.isChecked()),
        }

    def _reset_settings_defaults(self) -> None:
        self.k1.setValue(1.0);  self.k2.setValue(1.0);  self.k3.setValue(1.0)
        self.k4.setValue(0.5);  self.k5.setValue(0.6);  self.k6.setValue(0.3)
        self.decay.setValue(0.15);  self.noise.setValue(0.05)
        self.memory_mode.setCurrentText("forgotten")
        self.tail_messages.setValue(2)
        self.search_memory.setChecked(False)
        self.search_history.setChecked(True)
        self.combine_mode_combo.setCurrentText("union")
        self.kw_enabled.setChecked(False)
        self.use_fts.setChecked(False)
        self.detailed_logs.setChecked(True)
        self.include_forgotten.setChecked(False)
        self.forgotten_penalty.setValue(-0.15)

    def _push_query_history(self, query: str) -> None:
        q = query.strip()
        if not q:
            return
        # remove duplicate if present
        self._query_history = [x for x in self._query_history if x != q]
        self._query_history.insert(0, q)
        self._query_history = self._query_history[:_HISTORY_MAX]
        self._refresh_history_list()

    def _refresh_history_list(self) -> None:
        self.history_list.blockSignals(True)
        self.history_list.clear()
        for q in self._query_history:
            item = QListWidgetItem(q)
            self.history_list.addItem(item)
        self.history_list.blockSignals(False)

    def _on_toggle_history(self, checked: bool) -> None:
        self.history_list.setVisible(checked)
        self.btn_toggle_history.setText("▾ History" if checked else "▸ History")

    def _on_history_item_clicked(self, item: QListWidgetItem) -> None:
        self.query_edit.setText(item.text())

    def _populate_table(self, res: list[dict]) -> None:
        self.table.setRowCount(0)
        for item in res:
            row = self.table.rowCount()
            self.table.insertRow(row)

            source    = as_stripped(item.get("source"))
            rid       = str(item.get("id", ""))
            score     = item.get("score", 0.0)
            score_val = float(score) if score is not None else 0.0
            score_str = f"{score_val:.4f}"
            features  = item.get("features") or {}
            feat_str  = _fmt_features(features)

            type_or_role = as_stripped(item.get("type") or item.get("role"))
            priority     = as_stripped(item.get("priority") or "")
            date         = as_stripped(item.get("date_created") or item.get("date") or "")

            sp = as_stripped(item.get("speaker") or "")
            tg = as_stripped(item.get("target") or "")
            st = f"{sp}→{tg}" if (sp and tg) else (sp or (f"→{tg}" if tg else ""))

            content_str = str(item.get("content") or "")
            clip = content_str.replace("\n", " ").strip()
            if len(clip) > 220:
                clip = clip[:220] + "…"

            def cell(text: str, right: bool = False) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                if right:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                return it

            self.table.setItem(row, _COL_SOURCE,  cell(source))
            self.table.setItem(row, _COL_ID,       cell(rid, right=True))

            score_item = cell(score_str, right=True)
            score_item.setForeground(_score_color(score_val))
            self.table.setItem(row, _COL_SCORE, score_item)

            feat_item = cell(feat_str)
            # dim zero-only feature cells
            if not feat_str or all(v == 0.0 for v in features.values()):
                feat_item.setForeground(_CLR_GREY)
            self.table.setItem(row, _COL_FEAT, feat_item)

            self.table.setItem(row, _COL_TYPE,    cell(type_or_role))
            self.table.setItem(row, _COL_PRIO,    cell(priority))
            self.table.setItem(row, _COL_DATE,    cell(date))
            self.table.setItem(row, _COL_SP_TG,   cell(st))
            self.table.setItem(row, _COL_CONTENT, cell(clip))

            # store full payload for details pane and export
            self.table.item(row, _COL_SOURCE).setData(Qt.ItemDataRole.UserRole, item)

    # ─────────────────────────── actions ────────────────────────────────────

    def on_template(self) -> None:
        sc = Scenario.template(character_id=self.current_cid())
        self.set_editor_scenario(sc)

    def on_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load scenario JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            sc = self.svc.load_scenario_file(path, fallback_character_id=self.current_cid())
            self.set_editor_scenario(sc)
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))

    def on_save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save scenario JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            sc = self.parse_editor_scenario()
            self.svc.save_scenario_file(sc, path)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def on_apply(self) -> None:
        try:
            sc = self.parse_editor_scenario()
            clear_before = bool(self.chk_clear_before.isChecked())
            if clear_before:
                ok = QMessageBox.question(
                    self, "Подтверждение",
                    f"Очистить данные для character_id='{sc.character_id}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ok != QMessageBox.StandardButton.Yes:
                    return
            embed_now = bool(self.chk_embed_now.isChecked())
            counts = self.svc.apply_scenario_to_db(sc, clear_before=clear_before, embed_now=embed_now)
            QMessageBox.information(
                self, "Готово",
                f"Заливка завершена для {sc.character_id}:\n"
                f"- context(active): {counts['context']}\n"
                f"- history(archived): {counts['history']}\n"
                f"- memories: {counts['memories']}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Apply failed", str(e))

    def on_load_from_db(self) -> None:
        cid = self.current_cid()
        try:
            sc = self.svc.load_scenario_from_db(
                cid,
                hist_limit=int(self.db_hist_limit.value()),
                mem_limit=int(self.db_mem_limit.value()),
            )
            self.set_editor_scenario(sc)
            QMessageBox.information(
                self, "Loaded",
                f"{cid}:\n"
                f"- context(active): {len(sc.context)}\n"
                f"- history(archived): {len(sc.history)}\n"
                f"- memories: {len(sc.memories)}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Load from DB failed", str(e))

    def on_import_old_history(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import old history JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            replace = self.ask_replace_or_merge()
            with open(path, "r", encoding="utf-8") as f:
                obj = json.loads(f.read())
            add = self.svc.import_old_history_obj(
                obj, character_id=self.current_cid(),
                tail_to_context=int(self.import_context_tail.value()),
            )
            base = self.parse_editor_scenario()
            merged = self.svc.merge_scenarios(base, add, replace=replace)
            self.set_editor_scenario(merged)
        except RuntimeError:
            return
        except Exception as e:
            QMessageBox.critical(self, "Import history failed", str(e))

    def on_import_old_memories(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import old memories JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            replace = self.ask_replace_or_merge()
            with open(path, "r", encoding="utf-8") as f:
                obj = json.loads(f.read())
            add = self.svc.import_old_memories_obj(obj, character_id=self.current_cid())
            base = self.parse_editor_scenario()
            merged = self.svc.merge_scenarios(base, add, replace=replace)
            self.set_editor_scenario(merged)
        except RuntimeError:
            return
        except Exception as e:
            QMessageBox.critical(self, "Import memories failed", str(e))

    def on_index_missing(self) -> None:
        cid = self.current_cid()
        try:
            updated = self.svc.index_missing(cid)
            QMessageBox.information(self, "Index done", f"Обновлено записей: {updated}")
        except Exception as e:
            QMessageBox.critical(self, "Index failed", str(e))

    def on_missing_count(self) -> None:
        cid = self.current_cid()
        try:
            missing = self.svc.missing_count(cid)
            QMessageBox.information(self, "Missing embeddings", f"Missing embeddings count: {missing}")
        except Exception as e:
            QMessageBox.critical(self, "Failed", str(e))

    def on_search(self) -> None:
        cid   = self.current_cid()
        query = self.query_edit.text()
        limit = int(self.limit_spin.value())
        thr   = float(self.threshold_spin.value())

        try:
            eq = self.svc.build_effective_query(cid, query, tail=2)
            self.effective_query_view.setPlainText(eq or "")

            use_overrides = bool(self.chk_use_overrides.isChecked())
            overrides = self.collect_overrides()

            res = self.svc.search(
                cid=cid, query=query, limit=limit, threshold=thr,
                use_overrides=use_overrides, overrides=overrides,
            )
            self._last_results = res

            self._populate_table(res)
            self._push_query_history(query)

            if res:
                self.table.selectRow(0)
                self.right_tabs.setCurrentIndex(0)
            else:
                self.details.setPlainText("(no results)")

        except Exception as e:
            QMessageBox.critical(self, "Search failed", str(e))

    def on_preview_inject(self) -> None:
        cid   = self.current_cid()
        query = self.query_edit.text().strip()
        if not query:
            self.injection_preview.setPlainText("")
            return

        limit = int(self.limit_spin.value())
        thr   = float(self.threshold_spin.value())

        try:
            use_overrides = bool(self.chk_use_overrides.isChecked())
            overrides = self.collect_overrides()

            res = self.svc.search(
                cid=cid, query=query, limit=limit, threshold=thr,
                use_overrides=use_overrides, overrides=overrides,
            )
            self._last_results = res
            self._populate_table(res)
            preview = self.svc.build_injection_preview(res)
            self.injection_preview.setPlainText(preview)
            self.right_tabs.setCurrentIndex(1)
        except Exception as e:
            QMessageBox.critical(self, "Preview failed", str(e))

    def on_export_json(self) -> None:
        if not self._last_results:
            QMessageBox.information(self, "Export", "Нет результатов для экспорта.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export results JSON", "rag_results.json", "JSON (*.json);;All (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._last_results, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Export", f"Сохранено {len(self._last_results)} записей в:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def on_table_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        r = rows[0].row()
        item0 = self.table.item(r, _COL_SOURCE)
        if not item0:
            return
        payload = item0.data(Qt.ItemDataRole.UserRole) or {}
        try:
            self.details.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            self.details.setPlainText(str(payload))


def main() -> int:
    app = QApplication(sys.argv)
    try:
        app.setStyleSheet(get_stylesheet())
    except Exception:
        pass

    w = RagTesterWindow()
    w.resize(1400, 860)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
