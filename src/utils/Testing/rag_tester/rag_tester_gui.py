from __future__ import annotations

import os
import sys
import json
from typing import Any

# --- make project root importable ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QFont
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
    QStatusBar,
    QProgressBar,
)

from styles.main_styles import get_stylesheet
from rag_tester_core import (
    RagTesterService, Scenario, TestSuite, TestCase, BatchResult,
)
from tester_styles import TESTER_QSS


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
        self._build_status_bar()
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

    def _build_status_bar(self) -> None:
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label, 1)
        self.db_stats_label = QLabel("")
        self.status_bar.addPermanentWidget(self.db_stats_label)

    def _update_status(self, text: str) -> None:
        self.status_label.setText(text)
        QApplication.processEvents()

    def _update_db_stats(self) -> None:
        cid = self.current_cid()
        try:
            stats = self.svc.db_stats(cid)
            self.db_stats_label.setText(
                f"[{cid}] hist: {stats.get('history_archived', '?')} "
                f"(emb: {stats.get('history_embedded', '?')}) | "
                f"mem: {stats.get('memories_total', '?')} "
                f"(emb: {stats.get('memories_embedded', '?')}) | "
                f"ctx: {stats.get('history_active', '?')}"
            )
        except Exception:
            self.db_stats_label.setText(f"[{cid}] DB stats unavailable")

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
        self.btn_refresh_stats = QPushButton("Refresh stats")
        db_btns.addWidget(self.btn_apply)
        db_btns.addWidget(self.btn_load_from_db)
        db_btns.addWidget(self.btn_refresh_stats)
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

        # ── Batch Test Tab ───────────────────────────────────────────────────
        tab_batch = QWidget()
        tab_batch_l = QVBoxLayout(tab_batch)
        tab_batch_l.setContentsMargins(15, 15, 15, 15)
        tab_batch_l.setSpacing(10)

        batch_top = QHBoxLayout()
        self.btn_batch_template = QPushButton("Шаблон suite")
        self.btn_batch_load = QPushButton("Load suite…")
        self.btn_batch_save = QPushButton("Save suite…")
        batch_top.addWidget(self.btn_batch_template)
        batch_top.addWidget(self.btn_batch_load)
        batch_top.addWidget(self.btn_batch_save)
        batch_top.addStretch(1)
        tab_batch_l.addLayout(batch_top)

        self.batch_edit = QTextEdit()
        self.batch_edit.setAcceptRichText(False)
        self.batch_edit.setPlaceholderText("Test suite JSON — загрузите шаблон или файл")
        tab_batch_l.addWidget(self.batch_edit, 2)

        batch_run_row = QHBoxLayout()
        self.btn_batch_run = QPushButton("Run Batch Test")
        self.btn_batch_run.setMinimumHeight(36)
        font = self.btn_batch_run.font()
        font.setBold(True)
        self.btn_batch_run.setFont(font)
        batch_run_row.addWidget(self.btn_batch_run)
        batch_run_row.addStretch(1)
        tab_batch_l.addLayout(batch_run_row)

        self.batch_results_view = QPlainTextEdit()
        self.batch_results_view.setReadOnly(True)
        self.batch_results_view.setPlaceholderText("Результаты batch-теста")
        tab_batch_l.addWidget(self.batch_results_view, 3)
        left_tabs.addTab(tab_batch, "Batch Test")

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
        self.threshold_spin.setSingleStep(0.05)

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

        def dspin(lo=-10.0, hi=10.0, val=1.0, step=0.1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setValue(val)
            s.setSingleStep(step)
            s.setFixedWidth(90)
            return s

        def ispin(lo=0, hi=1000, val=0):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(val)
            s.setFixedWidth(90)
            return s

        # ── Weights ──────────────────────────────────────────────────────────
        gb_w = QGroupBox("Weights")
        form_w = QFormLayout(gb_w)
        form_w.setVerticalSpacing(6)

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

        self.tail_messages = ispin(0, 20, 2)
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
        self.combine_mode_combo.addItems(["union", "vector_only", "intersect", "intersect2", "intersect_n", "two_stage"])
        self.combine_mode_combo.setCurrentText("union")
        form_r.addRow("combine mode:", self.combine_mode_combo)

        self.vector_top_k = ispin(0, 500, 0)
        form_r.addRow("vector_top_k:", self.vector_top_k)

        self.intersect_min_methods = ispin(1, 5, 2)
        form_r.addRow("intersect min:", self.intersect_min_methods)

        self.intersect_require_vector = QCheckBox("require vector")
        self.intersect_require_vector.setChecked(True)
        form_r.addRow(self.intersect_require_vector)

        self.intersect_fallback_union = QCheckBox("fallback union")
        self.intersect_fallback_union.setChecked(True)
        form_r.addRow(self.intersect_fallback_union)

        self.two_stage_fallback_union = QCheckBox("2-stage fallback")
        self.two_stage_fallback_union.setChecked(True)
        form_r.addRow(self.two_stage_fallback_union)

        scroll_layout.addWidget(gb_r)

        # ── Keyword search ────────────────────────────────────────────────────
        gb_kw = QGroupBox("Keyword Search")
        form_kw = QFormLayout(gb_kw)
        form_kw.setVerticalSpacing(6)

        self.kw_enabled = QCheckBox("enabled")
        self.kw_enabled.setChecked(False)
        form_kw.addRow(self.kw_enabled)

        self.kw_max_terms = ispin(1, 50, 8)
        form_kw.addRow("max terms:", self.kw_max_terms)

        self.kw_min_score = dspin(lo=0.0, hi=1.0, val=0.34, step=0.05)
        form_kw.addRow("min score:", self.kw_min_score)

        self.kw_sql_limit = ispin(1, 5000, 250)
        form_kw.addRow("SQL limit:", self.kw_sql_limit)

        self.kw_min_len = ispin(1, 20, 3)
        form_kw.addRow("min len:", self.kw_min_len)

        self.kw_lemmatization = QCheckBox("lemmatization")
        self.kw_lemmatization.setChecked(True)
        form_kw.addRow(self.kw_lemmatization)

        scroll_layout.addWidget(gb_kw)

        # ── FTS ───────────────────────────────────────────────────────────────
        gb_fts = QGroupBox("FTS (Full-Text Search)")
        form_fts = QFormLayout(gb_fts)
        form_fts.setVerticalSpacing(6)

        self.use_fts = QCheckBox("enabled")
        self.use_fts.setChecked(False)
        form_fts.addRow(self.use_fts)

        self.fts_top_k_hist = ispin(1, 500, 50)
        form_fts.addRow("top_k history:", self.fts_top_k_hist)

        self.fts_top_k_mem = ispin(1, 500, 50)
        form_fts.addRow("top_k memories:", self.fts_top_k_mem)

        self.fts_max_terms = ispin(1, 50, 10)
        form_fts.addRow("max terms:", self.fts_max_terms)

        self.fts_min_len = ispin(1, 20, 3)
        form_fts.addRow("min len:", self.fts_min_len)

        scroll_layout.addWidget(gb_fts)

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

        self.log_top_n = ispin(0, 100, 10)
        form_m.addRow("log top N:", self.log_top_n)

        self.log_bottom_n = ispin(0, 100, 5)
        form_m.addRow("log bottom N:", self.log_bottom_n)

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
        self.btn_refresh_stats.clicked.connect(self._update_db_stats)

        self.btn_import_old_history.clicked.connect(self.on_import_old_history)
        self.btn_import_old_memories.clicked.connect(self.on_import_old_memories)

        self.btn_index_missing.clicked.connect(self.on_index_missing)
        self.btn_missing_count.clicked.connect(self.on_missing_count)

        self.btn_search.clicked.connect(self.on_search)
        self.query_edit.returnPressed.connect(self.on_search)
        self.btn_preview_inject.clicked.connect(self.on_preview_inject)
        self.btn_export_json.clicked.connect(self.on_export_json)

        self.btn_toggle_history.toggled.connect(self._on_toggle_history)
        self.history_list.itemClicked.connect(self._on_history_item_clicked)

        self.table.itemSelectionChanged.connect(self.on_table_selection)

        # batch
        self.btn_batch_template.clicked.connect(self.on_batch_template)
        self.btn_batch_load.clicked.connect(self.on_batch_load)
        self.btn_batch_save.clicked.connect(self.on_batch_save)
        self.btn_batch_run.clicked.connect(self.on_batch_run)

        # update stats when character changes
        self.character_id_edit.editingFinished.connect(self._update_db_stats)

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
            # always enabled in tester
            "RAG_ENABLED":              True,
            # weights
            "RAG_WEIGHT_SIMILARITY":    float(self.k1.value()),
            "RAG_WEIGHT_TIME":          float(self.k2.value()),
            "RAG_WEIGHT_PRIORITY":      float(self.k3.value()),
            "RAG_WEIGHT_ENTITY":        float(self.k4.value()),
            "RAG_WEIGHT_KEYWORDS":      float(self.k5.value()),
            "RAG_WEIGHT_LEXICAL":       float(self.k6.value()),
            "RAG_TIME_DECAY_RATE":      float(self.decay.value()),
            "RAG_NOISE_MAX":            float(self.noise.value()),
            # query
            "RAG_QUERY_TAIL_MESSAGES":  int(self.tail_messages.value()),
            "RAG_SEARCH_MEMORY":        bool(self.search_memory.isChecked()),
            "RAG_SEARCH_HISTORY":       bool(self.search_history.isChecked()),
            "RAG_MEMORY_MODE":          str(self.memory_mode.currentText() or "forgotten"),
            # retrieval
            "RAG_COMBINE_MODE":         str(self.combine_mode_combo.currentText()),
            "RAG_VECTOR_TOP_K":         int(self.vector_top_k.value()),
            "RAG_INTERSECT_MIN_METHODS": int(self.intersect_min_methods.value()),
            "RAG_INTERSECT_REQUIRE_VECTOR": bool(self.intersect_require_vector.isChecked()),
            "RAG_INTERSECT_FALLBACK_UNION": bool(self.intersect_fallback_union.isChecked()),
            "RAG_TWO_STAGE_FALLBACK_UNION": bool(self.two_stage_fallback_union.isChecked()),
            # keyword
            "RAG_KEYWORD_SEARCH":       bool(self.kw_enabled.isChecked()),
            "RAG_KEYWORDS_MAX_TERMS":   int(self.kw_max_terms.value()),
            "RAG_KEYWORD_MIN_SCORE":    float(self.kw_min_score.value()),
            "RAG_KEYWORD_SQL_LIMIT":    int(self.kw_sql_limit.value()),
            "RAG_KEYWORDS_MIN_LEN":     int(self.kw_min_len.value()),
            "RAG_LEMMATIZATION":        bool(self.kw_lemmatization.isChecked()),
            # fts
            "RAG_USE_FTS":              bool(self.use_fts.isChecked()),
            "RAG_FTS_TOP_K_HISTORY":    int(self.fts_top_k_hist.value()),
            "RAG_FTS_TOP_K_MEMORIES":   int(self.fts_top_k_mem.value()),
            "RAG_FTS_MAX_TERMS":        int(self.fts_max_terms.value()),
            "RAG_FTS_MIN_LEN":          int(self.fts_min_len.value()),
            # misc
            "RAG_DETAILED_LOGS":        bool(self.detailed_logs.isChecked()),
            "RAG_INCLUDE_FORGOTTEN":    bool(self.include_forgotten.isChecked()),
            "RAG_FORGOTTEN_PENALTY":    float(self.forgotten_penalty.value()),
            "RAG_LOG_LIST_TOP_N":       int(self.log_top_n.value()),
            "RAG_LOG_LIST_BOTTOM_N":    int(self.log_bottom_n.value()),
        }

    def _reset_settings_defaults(self) -> None:
        # weights
        self.k1.setValue(1.0);  self.k2.setValue(0.3);  self.k3.setValue(0.5)
        self.k4.setValue(0.5);  self.k5.setValue(0.6);  self.k6.setValue(0.3)
        self.decay.setValue(0.05);  self.noise.setValue(0.02)
        # query
        self.tail_messages.setValue(2)
        self.search_memory.setChecked(True)
        self.search_history.setChecked(True)
        self.memory_mode.setCurrentText("all")
        # retrieval
        self.combine_mode_combo.setCurrentText("union")
        self.vector_top_k.setValue(0)
        self.intersect_min_methods.setValue(2)
        self.intersect_require_vector.setChecked(True)
        self.intersect_fallback_union.setChecked(True)
        self.two_stage_fallback_union.setChecked(True)
        # keyword
        self.kw_enabled.setChecked(True)
        self.kw_max_terms.setValue(8)
        self.kw_min_score.setValue(0.34)
        self.kw_sql_limit.setValue(250)
        self.kw_min_len.setValue(3)
        self.kw_lemmatization.setChecked(True)
        # fts
        self.use_fts.setChecked(True)
        self.fts_top_k_hist.setValue(50)
        self.fts_top_k_mem.setValue(50)
        self.fts_max_terms.setValue(10)
        self.fts_min_len.setValue(3)
        # misc
        self.detailed_logs.setChecked(True)
        self.include_forgotten.setChecked(False)
        self.forgotten_penalty.setValue(-0.15)
        self.log_top_n.setValue(10)
        self.log_bottom_n.setValue(5)

    def _push_query_history(self, query: str) -> None:
        q = query.strip()
        if not q:
            return
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
            if not feat_str or all(v == 0.0 for v in features.values()):
                feat_item.setForeground(_CLR_GREY)
            self.table.setItem(row, _COL_FEAT, feat_item)

            self.table.setItem(row, _COL_TYPE,    cell(type_or_role))
            self.table.setItem(row, _COL_PRIO,    cell(priority))
            self.table.setItem(row, _COL_DATE,    cell(date))
            self.table.setItem(row, _COL_SP_TG,   cell(st))
            self.table.setItem(row, _COL_CONTENT, cell(clip))

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
            self._update_status(f"Loaded scenario from {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))

    def on_save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save scenario JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            sc = self.parse_editor_scenario()
            self.svc.save_scenario_file(sc, path)
            self._update_status(f"Saved to {os.path.basename(path)}")
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
            self._update_status("Загрузка в БД...")
            counts = self.svc.apply_scenario_to_db(sc, clear_before=clear_before, embed_now=embed_now)
            self._update_db_stats()
            self._update_status(
                f"Залито: ctx={counts['context']}, hist={counts['history']}, mem={counts['memories']}"
            )
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
            self._update_status(f"Loading from DB for {cid}...")
            sc = self.svc.load_scenario_from_db(
                cid,
                hist_limit=int(self.db_hist_limit.value()),
                mem_limit=int(self.db_mem_limit.value()),
            )
            self.set_editor_scenario(sc)
            self._update_db_stats()
            self._update_status(
                f"Loaded: ctx={len(sc.context)}, hist={len(sc.history)}, mem={len(sc.memories)}"
            )
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
            self._update_status(f"Imported history: {len(add.history)} archived, {len(add.context)} context")
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
            self._update_status(f"Imported {len(add.memories)} memories")
        except RuntimeError:
            return
        except Exception as e:
            QMessageBox.critical(self, "Import memories failed", str(e))

    def on_index_missing(self) -> None:
        cid = self.current_cid()
        try:
            self._update_status(f"Indexing {cid}...")
            updated = self.svc.index_missing(cid)
            self._update_db_stats()
            self._update_status(f"Indexed {updated} rows")
            QMessageBox.information(self, "Index done", f"Обновлено записей: {updated}")
        except Exception as e:
            QMessageBox.critical(self, "Index failed", str(e))

    def on_missing_count(self) -> None:
        cid = self.current_cid()
        try:
            missing = self.svc.missing_count(cid)
            self._update_status(f"Missing embeddings: {missing}")
            QMessageBox.information(self, "Missing embeddings", f"Missing embeddings count: {missing}")
        except Exception as e:
            QMessageBox.critical(self, "Failed", str(e))

    def on_search(self) -> None:
        cid   = self.current_cid()
        query = self.query_edit.text()
        if not query.strip():
            return
        limit = int(self.limit_spin.value())
        thr   = float(self.threshold_spin.value())

        try:
            self._update_status("Searching...")
            eq = self.svc.build_effective_query(cid, query, tail=int(self.tail_messages.value()))
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

            self._update_status(f"Found {len(res)} results")

            if res:
                self.table.selectRow(0)
                self.right_tabs.setCurrentIndex(0)
            else:
                self.details.setPlainText("(no results)")

        except Exception as e:
            self._update_status(f"Search error: {e}")
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
            self._update_status(f"Exported {len(self._last_results)} results")
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

    # ─────────────────── batch test actions ─────────────────────────────────

    def on_batch_template(self) -> None:
        suite = TestSuite.template()
        suite.character_id = self.current_cid()
        self.batch_edit.setPlainText(suite.to_json())

    def on_batch_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load test suite", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            suite = TestSuite.from_json(text)
            self.batch_edit.setPlainText(suite.to_json())
            self._update_status(f"Loaded suite: {suite.name} ({len(suite.cases)} cases)")
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))

    def on_batch_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save test suite", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            text = self.batch_edit.toPlainText().strip()
            suite = TestSuite.from_json(text)
            with open(path, "w", encoding="utf-8") as f:
                f.write(suite.to_json())
            self._update_status(f"Saved suite to {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def on_batch_run(self) -> None:
        try:
            text = self.batch_edit.toPlainText().strip()
            if not text:
                QMessageBox.warning(self, "Batch", "Загрузите или создайте test suite.")
                return
            suite = TestSuite.from_json(text)
            if not suite.cases:
                QMessageBox.warning(self, "Batch", "Suite пустой — добавьте test cases.")
                return

            limit = int(self.limit_spin.value())
            thr = float(self.threshold_spin.value())
            use_overrides = bool(self.chk_use_overrides.isChecked())
            overrides = self.collect_overrides()

            self._update_status(f"Running batch: {len(suite.cases)} queries...")
            self.batch_results_view.setPlainText("Running...")
            QApplication.processEvents()

            def on_progress(idx, total, query):
                self._update_status(f"Batch [{idx+1}/{total}]: {query[:40]}...")
                QApplication.processEvents()

            result = self.svc.run_batch(
                suite,
                limit=limit,
                threshold=thr,
                use_overrides=use_overrides,
                overrides=overrides,
                progress_callback=on_progress,
            )

            self.batch_results_view.setPlainText(result.summary_text())
            self._update_status(
                f"Batch done: P={result.mean_precision:.3f} R={result.mean_recall:.3f} "
                f"MRR={result.mrr:.3f} nDCG={result.mean_ndcg:.3f}"
            )

        except Exception as e:
            self._update_status(f"Batch error: {e}")
            QMessageBox.critical(self, "Batch failed", str(e))


def main() -> int:
    app = QApplication(sys.argv)
    try:
        base_qss = get_stylesheet()
        app.setStyleSheet(base_qss + "\n" + TESTER_QSS)
    except Exception:
        try:
            app.setStyleSheet(TESTER_QSS)
        except Exception:
            pass

    w = RagTesterWindow()
    w.resize(1400, 860)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
