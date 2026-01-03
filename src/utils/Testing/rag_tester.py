# tools/rag_tester_gui.py
from __future__ import annotations

import os
import sys
import json
import datetime
from dataclasses import dataclass
from typing import Any, Optional

# --- make project root importable ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
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
    QGroupBox,
    QFormLayout,
    QDockWidget,
    QTabWidget,
    QScrollArea,
    QSizePolicy,
)

from styles.main_styles import get_stylesheet

from managers.database_manager import DatabaseManager
from managers.rag_manager import RAGManager
from managers.history_manager import HistoryManager
from managers.memory_manager import MemoryManager
from managers.settings_manager import SettingsManager


def _now_ts() -> str:
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _as_stripped(v: Any) -> str:
    return str(v or "").strip()


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


class SettingsOverride:
    """
    Временный override SettingsManager.get(key, default),
    чтобы тестировать RAG с разными весами без правок RAGManager.
    """
    def __init__(self, overrides: dict[str, Any]):
        self.overrides = dict(overrides or {})
        self._orig_get = None

    def __enter__(self):
        self._orig_get = getattr(SettingsManager, "get", None)
        orig = self._orig_get

        def wrapped_get(key: str, default=None):
            k = str(key) if key is not None else ""
            if k in self.overrides:
                return self.overrides[k]
            if callable(orig):
                return orig(key, default)
            return default

        try:
            setattr(SettingsManager, "get", staticmethod(wrapped_get))
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._orig_get is not None:
                setattr(SettingsManager, "get", self._orig_get)
        except Exception:
            pass
        return False


@dataclass
class Scenario:
    character_id: str
    context: list[dict]    # history.is_active=1
    history: list[dict]    # history.is_active=0
    memories: list[dict]   # memories

    @staticmethod
    def template(character_id: str = "RAG_TEST") -> "Scenario":
        now = _now_ts()
        cid = character_id or "RAG_TEST"
        return Scenario(
            character_id=cid,
            context=[
                {
                    "message_id": "in:demo-1",
                    "role": "user",
                    "speaker": "Player",
                    "sender": "Player",
                    "target": cid,
                    "participants": ["Player", cid],
                    "event_type": "chat",
                    "time": now,
                    "content": [{"type": "text", "text": "Привет! Напомни, что я говорил про поездку в Альпы?"}],
                },
                {
                    "message_id": "out:demo-1",
                    "role": "assistant",
                    "speaker": cid,
                    "sender": cid,
                    "target": "Player",
                    "participants": ["Player", cid],
                    "event_type": "chat",
                    "time": now,
                    "content": "Ты говорил, что хочешь в Альпы весной и уже выбирал маршрут.",
                },
            ],
            history=[
                {
                    "message_id": "in:old-1",
                    "role": "user",
                    "speaker": "Player",
                    "sender": "Player",
                    "target": cid,
                    "participants": ["Player", cid],
                    "event_type": "chat",
                    "time": "01.12.2025 12:00:00",
                    "content": [{"type": "text", "text": "Я люблю горы, особенно Альпы."}],
                },
                {
                    "message_id": "out:old-1",
                    "role": "assistant",
                    "speaker": cid,
                    "sender": cid,
                    "target": "Player",
                    "participants": ["Player", cid],
                    "event_type": "chat",
                    "time": "01.12.2025 12:01:00",
                    "content": "Ты говорил, что хочешь в Швейцарию весной.",
                },
            ],
            memories=[
                {
                    "content": "User prefers mountains; wants Alps/Switzerland trip in spring.",
                    "priority": "High",
                    "type": "fact",
                    "date_created": "01.12.2025 12:05:00",
                    "is_forgotten": 1,
                }
            ],
        )

    @staticmethod
    def from_json(obj: Any, fallback_character_id: str) -> "Scenario":
        if not isinstance(obj, dict):
            raise ValueError("Scenario JSON должен быть объектом (dict).")

        cid = _as_stripped(obj.get("character_id") or fallback_character_id or "RAG_TEST") or "RAG_TEST"
        context = obj.get("context") or []
        history = obj.get("history") or []
        memories = obj.get("memories") or []

        if not isinstance(context, list) or not isinstance(history, list) or not isinstance(memories, list):
            raise ValueError("context/history/memories должны быть списками.")

        def _norm_msgs(arr: list[Any]) -> list[dict]:
            out: list[dict] = []
            for it in arr:
                if not isinstance(it, dict):
                    continue
                it2 = dict(it)
                if "timestamp" not in it2 and "time" not in it2:
                    it2["time"] = _now_ts()
                it2.setdefault("role", "user")
                it2.setdefault("content", "")
                out.append(it2)
            return out

        def _norm_mems(arr: list[Any]) -> list[dict]:
            out: list[dict] = []
            for it in arr:
                if isinstance(it, str):
                    s = it.strip()
                    if not s:
                        continue
                    out.append({
                        "content": s,
                        "priority": "Normal",
                        "type": "fact",
                        "date_created": _now_ts(),
                        "is_forgotten": 1,
                    })
                    continue

                if not isinstance(it, dict):
                    continue

                content = _as_stripped(it.get("content") or it.get("text") or it.get("memory"))
                if not content:
                    continue

                it2 = dict(it)
                it2["content"] = content
                it2.setdefault("priority", "Normal")
                it2.setdefault("type", "fact")
                it2.setdefault("date_created", _now_ts())
                it2.setdefault("is_forgotten", 1)
                out.append(it2)

            return out

        return Scenario(
            character_id=cid,
            context=_norm_msgs(context),
            history=_norm_msgs(history),
            memories=_norm_mems(memories),
        )

    def to_pretty_json(self) -> str:
        return json.dumps(
            {
                "character_id": self.character_id,
                "context": self.context,
                "history": self.history,
                "memories": self.memories,
            },
            ensure_ascii=False,
            indent=2,
        )


class RagTesterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RAG Tester")

        self.db = DatabaseManager()

        self._build_actions()
        self._build_menu()
        self._build_central_ui()
        self._build_rag_settings_dock()
        self._wire_events()

        self.on_template()

    # ------------------------------------------------------------------
    # UI building
    # ------------------------------------------------------------------
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

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # ---------------------------
        # Left: tabs (Scenario / Data)
        # ---------------------------
        left_tabs = QTabWidget()
        splitter.addWidget(left_tabs)

        # Scenario tab
        tab_scn = QWidget()
        tab_scn_l = QVBoxLayout(tab_scn)

        row = QHBoxLayout()
        row.addWidget(QLabel("character_id:"))
        self.character_id_edit = QLineEdit("RAG_TEST")
        self.character_id_edit.setMaximumWidth(260)
        row.addWidget(self.character_id_edit)
        row.addStretch(1)

        self.btn_template = QPushButton("Шаблон")
        self.btn_load_file = QPushButton("Load…")
        self.btn_save_file = QPushButton("Save…")
        row.addWidget(self.btn_template)
        row.addWidget(self.btn_load_file)
        row.addWidget(self.btn_save_file)

        tab_scn_l.addLayout(row)

        self.scenario_edit = QTextEdit()
        self.scenario_edit.setAcceptRichText(False)
        tab_scn_l.addWidget(self.scenario_edit, 1)

        left_tabs.addTab(tab_scn, "Scenario")

        # Data tab
        tab_data = QWidget()
        tab_data_l = QVBoxLayout(tab_data)

        gb_db = QGroupBox("Database")
        gb_db_l = QGridLayout(gb_db)

        self.chk_clear_before = QCheckBox("Очистить перед заливкой (опасно)")
        self.chk_clear_before.setChecked(False)
        self.chk_embed_now = QCheckBox("Embed при заливке/импорте")
        self.chk_embed_now.setChecked(True)

        self.btn_apply = QPushButton("Залить scenario в БД")
        self.btn_load_from_db = QPushButton("Загрузить scenario из БД")

        self.db_hist_limit = QSpinBox()
        self.db_hist_limit.setRange(0, 200000)
        self.db_hist_limit.setValue(3000)
        self.db_hist_limit.setFixedWidth(120)

        self.db_mem_limit = QSpinBox()
        self.db_mem_limit.setRange(0, 200000)
        self.db_mem_limit.setValue(5000)
        self.db_mem_limit.setFixedWidth(120)

        gb_db_l.addWidget(self.btn_apply, 0, 0)
        gb_db_l.addWidget(self.btn_load_from_db, 0, 1)
        gb_db_l.addWidget(self.chk_clear_before, 1, 0, 1, 2)
        gb_db_l.addWidget(self.chk_embed_now, 2, 0, 1, 2)
        gb_db_l.addWidget(QLabel("history limit:"), 3, 0)
        gb_db_l.addWidget(self.db_hist_limit, 3, 1)
        gb_db_l.addWidget(QLabel("memories limit:"), 4, 0)
        gb_db_l.addWidget(self.db_mem_limit, 4, 1)

        tab_data_l.addWidget(gb_db)

        gb_import = QGroupBox("Import legacy JSON")
        gb_import_l = QGridLayout(gb_import)

        self.btn_import_old_history = QPushButton("Импорт history JSON…")
        self.btn_import_old_memories = QPushButton("Импорт memories JSON…")
        self.import_context_tail = QSpinBox()
        self.import_context_tail.setRange(0, 50)
        self.import_context_tail.setValue(2)
        self.import_context_tail.setFixedWidth(120)

        gb_import_l.addWidget(self.btn_import_old_history, 0, 0)
        gb_import_l.addWidget(self.btn_import_old_memories, 0, 1)
        gb_import_l.addWidget(QLabel("Tail->context:"), 1, 0)
        gb_import_l.addWidget(self.import_context_tail, 1, 1)

        tab_data_l.addWidget(gb_import)

        gb_index = QGroupBox("Indexing")
        gb_index_l = QHBoxLayout(gb_index)
        self.btn_index_missing = QPushButton("Index missing")
        self.btn_missing_count = QPushButton("Missing count")
        gb_index_l.addWidget(self.btn_index_missing)
        gb_index_l.addWidget(self.btn_missing_count)
        gb_index_l.addStretch(1)

        tab_data_l.addWidget(gb_index)
        tab_data_l.addStretch(1)

        left_tabs.addTab(tab_data, "Data")

        # ---------------------------
        # Right: Query + tabs (Results / Debug)
        # ---------------------------
        right = QWidget()
        right_l = QVBoxLayout(right)

        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("Query:"))
        self.query_edit = QLineEdit()
        qrow.addWidget(self.query_edit, 1)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 200)
        self.limit_spin.setValue(10)
        self.limit_spin.setFixedWidth(80)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-1.0, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.40)
        self.threshold_spin.setFixedWidth(90)

        qrow.addWidget(QLabel("limit"))
        qrow.addWidget(self.limit_spin)
        qrow.addWidget(QLabel("thr"))
        qrow.addWidget(self.threshold_spin)

        self.btn_search = QPushButton("Search")
        self.btn_preview_inject = QPushButton("Preview inject")
        qrow.addWidget(self.btn_search)
        qrow.addWidget(self.btn_preview_inject)

        right_l.addLayout(qrow)

        self.right_tabs = QTabWidget()
        right_l.addWidget(self.right_tabs, 1)

        # Results tab: table + details in vertical splitter
        tab_res = QWidget()
        tab_res_l = QVBoxLayout(tab_res)

        res_split = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["source", "id", "score", "type/role", "priority", "date", "speaker→target", "content"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        res_split.addWidget(self.table)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        res_split.addWidget(self.details)

        res_split.setStretchFactor(0, 3)
        res_split.setStretchFactor(1, 2)

        tab_res_l.addWidget(res_split, 1)
        self.right_tabs.addTab(tab_res, "Results")

        # Debug tab: effective query + injection preview
        tab_dbg = QWidget()
        tab_dbg_l = QVBoxLayout(tab_dbg)

        tab_dbg_l.addWidget(QLabel("Effective query (RAG build_query_from_recent):"))
        self.effective_query_view = QPlainTextEdit()
        self.effective_query_view.setReadOnly(True)
        self.effective_query_view.setMaximumBlockCount(2000)
        self.effective_query_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tab_dbg_l.addWidget(self.effective_query_view, 1)

        tab_dbg_l.addWidget(QLabel("Injection preview (<relevant_memories>/<past_context>):"))
        self.injection_preview = QPlainTextEdit()
        self.injection_preview.setReadOnly(True)
        self.injection_preview.setMaximumBlockCount(4000)
        self.injection_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tab_dbg_l.addWidget(self.injection_preview, 1)

        self.right_tabs.addTab(tab_dbg, "Debug")

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 880])

    def _build_rag_settings_dock(self) -> None:
        """
        Узкая скрываемая панель для overrides.
        """
        dock = QDockWidget("RAG Settings", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        wrap = QWidget()
        v = QVBoxLayout(wrap)

        self.chk_use_overrides = QCheckBox("Use overrides")
        self.chk_use_overrides.setChecked(True)
        v.addWidget(self.chk_use_overrides)

        form_box = QWidget()
        form = QFormLayout(form_box)

        self.k1 = QDoubleSpinBox(); self.k1.setRange(-10.0, 10.0); self.k1.setValue(1.0); self.k1.setSingleStep(0.1)
        self.k2 = QDoubleSpinBox(); self.k2.setRange(-10.0, 10.0); self.k2.setValue(1.0); self.k2.setSingleStep(0.1)
        self.k3 = QDoubleSpinBox(); self.k3.setRange(-10.0, 10.0); self.k3.setValue(1.0); self.k3.setSingleStep(0.1)
        self.k4 = QDoubleSpinBox(); self.k4.setRange(-10.0, 10.0); self.k4.setValue(0.5); self.k4.setSingleStep(0.1)

        self.decay = QDoubleSpinBox(); self.decay.setRange(0.0, 10.0); self.decay.setValue(0.15); self.decay.setSingleStep(0.05)
        self.noise = QDoubleSpinBox(); self.noise.setRange(0.0, 1.0); self.noise.setValue(0.05); self.noise.setSingleStep(0.01)

        self.memory_mode = QComboBox()
        self.memory_mode.addItems(["forgotten", "active", "all"])
        self.memory_mode.setCurrentText("forgotten")

        self.detailed_logs = QCheckBox("RAG_DETAILED_LOGS")
        self.detailed_logs.setChecked(True)

        self.include_forgotten = QCheckBox("RAG_INCLUDE_FORGOTTEN (не влияет в текущем коде)")
        self.include_forgotten.setChecked(False)
        self.forgotten_penalty = QDoubleSpinBox()
        self.forgotten_penalty.setRange(-5.0, 5.0)
        self.forgotten_penalty.setValue(-0.15)
        self.forgotten_penalty.setSingleStep(0.05)

        form.addRow("K1 similarity:", self.k1)
        form.addRow("K2 time:", self.k2)
        form.addRow("K3 priority:", self.k3)
        form.addRow("K4 entity:", self.k4)
        form.addRow("time decay:", self.decay)
        form.addRow("noise max:", self.noise)
        form.addRow("memory mode:", self.memory_mode)
        form.addRow(self.detailed_logs)
        form.addRow(self.include_forgotten)
        form.addRow("forgotten penalty:", self.forgotten_penalty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_box)

        v.addWidget(scroll, 1)
        dock.setWidget(wrap)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setVisible(False)
        dock.setMinimumWidth(320)
        dock.setMaximumWidth(420)

        self.settings_dock = dock

        # sync menu action
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

        self.table.itemSelectionChanged.connect(self.on_table_selection)

    # ------------------------------------------------------------------
    # Scenario I/O
    # ------------------------------------------------------------------
    def _parse_editor_scenario(self) -> Scenario:
        raw = self.scenario_edit.toPlainText().strip()
        if not raw:
            raise ValueError("Scenario JSON пустой.")
        obj = json.loads(raw)
        return Scenario.from_json(obj, fallback_character_id=self.character_id_edit.text().strip())

    def _set_editor_scenario(self, sc: Scenario) -> None:
        self.character_id_edit.setText(sc.character_id)
        self.scenario_edit.setPlainText(sc.to_pretty_json())

    def on_template(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        self._set_editor_scenario(Scenario.template(character_id=cid))

    def on_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load scenario JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.loads(f.read())
            sc = Scenario.from_json(obj, fallback_character_id=self.character_id_edit.text().strip())
            self._set_editor_scenario(sc)
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))

    def on_save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save scenario JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            sc = self._parse_editor_scenario()
            with open(path, "w", encoding="utf-8") as f:
                f.write(sc.to_pretty_json())
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------
    def _collect_overrides(self) -> dict[str, Any]:
        return {
            "RAG_WEIGHT_SIMILARITY": float(self.k1.value()),
            "RAG_WEIGHT_TIME": float(self.k2.value()),
            "RAG_WEIGHT_PRIORITY": float(self.k3.value()),
            "RAG_WEIGHT_ENTITY": float(self.k4.value()),
            "RAG_TIME_DECAY_RATE": float(self.decay.value()),
            "RAG_NOISE_MAX": float(self.noise.value()),
            "RAG_MEMORY_MODE": str(self.memory_mode.currentText() or "forgotten"),
            "RAG_DETAILED_LOGS": bool(self.detailed_logs.isChecked()),
            "RAG_INCLUDE_FORGOTTEN": bool(self.include_forgotten.isChecked()),
            "RAG_FORGOTTEN_PENALTY": float(self.forgotten_penalty.value()),
        }

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    def _table_cols(self, table: str) -> set[str]:
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            return set(r[1] for r in cur.fetchall() if r and len(r) > 1)
        except Exception:
            return set()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _clear_character_data(self, character_id: str) -> None:
        cid = str(character_id)

        hcols = self._table_cols("history")
        mcols = self._table_cols("memories")

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()

            if "is_deleted" in hcols:
                cur.execute("UPDATE history SET is_deleted=1 WHERE character_id=?", (cid,))
            else:
                cur.execute("DELETE FROM history WHERE character_id=?", (cid,))

            try:
                cur.execute("DELETE FROM variables WHERE character_id=?", (cid,))
            except Exception:
                pass

            if "is_deleted" in mcols:
                cur.execute("UPDATE memories SET is_deleted=1 WHERE character_id=?", (cid,))
            else:
                cur.execute("DELETE FROM memories WHERE character_id=?", (cid,))

            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _insert_memories(self, cid: str, memories: list[dict], embed_now: bool) -> int:
        if not memories:
            return 0

        _ = MemoryManager(cid)  # schema best-effort
        rag = RAGManager(cid)

        cols = self._table_cols("memories")
        has_is_forgotten = "is_forgotten" in cols
        has_is_deleted = "is_deleted" in cols

        inserted = 0
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT MAX(eternal_id) FROM memories WHERE character_id=?", (cid,))
            res = cur.fetchone()
            max_eid = int(res[0] or 0) if res else 0

            for it in memories:
                if not isinstance(it, dict):
                    continue
                content = _as_stripped(it.get("content"))
                if not content:
                    continue

                max_eid += 1
                priority = _as_stripped(it.get("priority") or "Normal") or "Normal"
                mtype = _as_stripped(it.get("type") or "fact") or "fact"
                date_created = _as_stripped(it.get("date_created") or _now_ts()) or _now_ts()
                participants = it.get("participants", None)
                is_forgotten = _safe_int(it.get("is_forgotten"), 0)
                is_deleted = _safe_int(it.get("is_deleted"), 0)

                insert_cols = ["character_id", "eternal_id", "content", "priority", "type", "date_created"]
                vals: list[Any] = [cid, max_eid, content, priority, mtype, date_created]

                if "participants" in cols:
                    insert_cols.append("participants")
                    vals.append(json.dumps(participants, ensure_ascii=False) if isinstance(participants, list) else participants)

                if has_is_deleted:
                    insert_cols.append("is_deleted")
                    vals.append(is_deleted)

                if has_is_forgotten:
                    insert_cols.append("is_forgotten")
                    vals.append(is_forgotten)

                placeholders = ",".join(["?"] * len(insert_cols))
                sql = f"INSERT INTO memories ({', '.join(insert_cols)}) VALUES ({placeholders})"
                cur.execute(sql, tuple(vals))
                inserted += 1

                if embed_now:
                    try:
                        rag.update_memory_embedding(max_eid, content)
                    except Exception:
                        pass

            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return inserted

    def _insert_history_messages(self, cid: str, msgs: list[dict], is_active: int, embed_now: bool) -> int:
        if not msgs:
            return 0

        hm = HistoryManager(character_name=cid, character_id=cid)
        rag = RAGManager(cid)

        inserted = 0
        for msg in msgs:
            if not isinstance(msg, dict):
                continue

            m2 = dict(msg)
            if "timestamp" not in m2 and "time" not in m2:
                m2["time"] = _now_ts()
            m2.setdefault("role", "user")
            m2.setdefault("content", "")

            row_id = hm._insert_history_row(msg=m2, is_active=int(is_active))
            if row_id:
                inserted += 1
                if embed_now:
                    try:
                        txt = hm._extract_text_for_embedding(m2.get("content"))
                        if txt:
                            rag.update_history_embedding(int(row_id), txt)
                    except Exception:
                        pass

        return inserted

    # ------------------------------------------------------------------
    # Load scenario from DB
    # ------------------------------------------------------------------
    def _load_from_db(self, cid: str, hist_limit: int, mem_limit: int) -> Scenario:
        cid = str(cid or "").strip() or "RAG_TEST"

        hm = HistoryManager(character_name=cid, character_id=cid)
        hm._ensure_history_schema()

        active = hm.load_history().get("messages", []) or []

        select_cols = hm._history_select_columns()
        cols_set = set(select_cols)

        hcols = hm._history_cols or set()
        where = "character_id=? AND is_active=0"
        if "is_deleted" in hcols:
            where += " AND is_deleted=0"

        sql = f"SELECT {', '.join(select_cols)} FROM history WHERE {where} ORDER BY id ASC"
        params: list[Any] = [cid]
        if hist_limit and hist_limit > 0:
            sql += " LIMIT ?"
            params.append(int(hist_limit))

        corpus: list[dict] = []
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        for row in rows:
            rd = dict(zip(select_cols, row))
            msg = hm._reconstruct_message_from_db(rd.get("role"), rd.get("content"), rd.get("meta_data"))
            msg["time"] = rd.get("timestamp") or ""

            for k in hm._HISTORY_DESIRED_COLUMNS.keys():
                if k in cols_set and rd.get(k) not in (None, ""):
                    msg[k] = rd.get(k)

            msg = hm._normalize_loaded_message(msg)
            corpus.append(msg)

        mcols = self._table_cols("memories")
        has_is_deleted = "is_deleted" in mcols
        has_is_forgotten = "is_forgotten" in mcols

        mem_select = ["content", "priority", "type", "date_created"]
        if "participants" in mcols:
            mem_select.append("participants")
        if has_is_forgotten:
            mem_select.append("is_forgotten")

        mem_where = "character_id=?"
        if has_is_deleted:
            mem_where += " AND is_deleted=0"

        mem_sql = f"SELECT {', '.join(mem_select)} FROM memories WHERE {mem_where} ORDER BY id ASC"
        mem_params: list[Any] = [cid]
        if mem_limit and mem_limit > 0:
            mem_sql += " LIMIT ?"
            mem_params.append(int(mem_limit))

        mems: list[dict] = []
        conn2 = self.db.get_connection()
        try:
            cur2 = conn2.cursor()
            cur2.execute(mem_sql, tuple(mem_params))
            mem_rows = cur2.fetchall() or []
        finally:
            try:
                conn2.close()
            except Exception:
                pass

        for r in mem_rows:
            i = 0
            content = r[i]; i += 1
            priority = r[i] if i < len(r) else "Normal"; i += 1
            mtype = r[i] if i < len(r) else "fact"; i += 1
            date_created = r[i] if i < len(r) else ""; i += 1

            participants = None
            if "participants" in mcols:
                participants = r[i] if i < len(r) else None
                i += 1

            is_forgotten = 1
            if has_is_forgotten:
                is_forgotten = _safe_int(r[i] if i < len(r) else 0, 0)

            d = {
                "content": content,
                "priority": priority,
                "type": mtype,
                "date_created": date_created,
                "is_forgotten": is_forgotten,
            }
            if participants is not None:
                d["participants"] = participants
            mems.append(d)

        return Scenario(character_id=cid, context=active, history=corpus, memories=mems)

    # ------------------------------------------------------------------
    # Import legacy JSON
    # ------------------------------------------------------------------
    def _read_json_file(self, path: str) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())

    def _ask_replace_or_merge(self) -> bool:
        """
        True = replace, False = merge
        """
        mb = QMessageBox(self)
        mb.setWindowTitle("Импорт")
        mb.setText("Как применить импорт?")
        replace_btn = mb.addButton("Заменить scenario", QMessageBox.ButtonRole.AcceptRole)
        merge_btn = mb.addButton("Смержить (добавить)", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = mb.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        mb.exec()
        clicked = mb.clickedButton()
        if clicked == cancel_btn:
            raise RuntimeError("cancelled")
        return clicked == replace_btn

    def _merge_scenario(self, base: Scenario, add: Scenario, *, replace: bool) -> Scenario:
        if replace:
            return Scenario(
                character_id=add.character_id or base.character_id,
                context=list(add.context),
                history=list(add.history),
                memories=list(add.memories),
            )

        cid = add.character_id or base.character_id
        return Scenario(
            character_id=cid,
            context=list(base.context) + list(add.context),
            history=list(base.history) + list(add.history),
            memories=list(base.memories) + list(add.memories),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def on_apply(self) -> None:
        try:
            sc = self._parse_editor_scenario()
            cid = sc.character_id
            self.character_id_edit.setText(cid)

            if self.chk_clear_before.isChecked():
                ok = QMessageBox.question(
                    self,
                    "Подтверждение",
                    f"Очистить данные для character_id='{cid}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ok != QMessageBox.StandardButton.Yes:
                    return
                self._clear_character_data(cid)

            embed_now = self.chk_embed_now.isChecked()

            n_ctx = self._insert_history_messages(cid, sc.context, is_active=1, embed_now=embed_now)
            n_hist = self._insert_history_messages(cid, sc.history, is_active=0, embed_now=embed_now)
            n_mem = self._insert_memories(cid, sc.memories, embed_now=embed_now)

            QMessageBox.information(
                self,
                "Готово",
                f"Заливка завершена для {cid}:\n"
                f"- context(active): {n_ctx}\n"
                f"- history(archived): {n_hist}\n"
                f"- memories: {n_mem}",
            )

        except Exception as e:
            QMessageBox.critical(self, "Apply failed", str(e))

    def on_load_from_db(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        try:
            sc = self._load_from_db(
                cid,
                hist_limit=int(self.db_hist_limit.value()),
                mem_limit=int(self.db_mem_limit.value()),
            )
            self._set_editor_scenario(sc)
            QMessageBox.information(
                self,
                "Loaded from DB",
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
            replace = self._ask_replace_or_merge()
            obj = self._read_json_file(path)

            messages = None
            if isinstance(obj, dict) and isinstance(obj.get("messages"), list):
                messages = obj.get("messages")
            elif isinstance(obj, list):
                messages = obj
            else:
                raise ValueError("Ожидаю list или dict с ключом 'messages'.")

            tail_n = max(0, int(self.import_context_tail.value()))

            msgs_norm: list[dict] = []
            for m in messages:
                if not isinstance(m, dict):
                    continue
                m2 = dict(m)
                if "timestamp" not in m2 and "time" not in m2:
                    m2["time"] = _now_ts()
                m2.setdefault("role", "user")
                m2.setdefault("content", "")
                msgs_norm.append(m2)

            if tail_n > 0:
                ctx = msgs_norm[-tail_n:] if len(msgs_norm) >= tail_n else list(msgs_norm)
                hist = msgs_norm[:-tail_n] if len(msgs_norm) > tail_n else []
            else:
                ctx, hist = [], msgs_norm

            cid = self.character_id_edit.text().strip() or "RAG_TEST"
            add = Scenario(character_id=cid, context=ctx, history=hist, memories=[])

            base = self._parse_editor_scenario()
            self._set_editor_scenario(self._merge_scenario(base, add, replace=replace))

        except RuntimeError:
            return
        except Exception as e:
            QMessageBox.critical(self, "Import history failed", str(e))

    def on_import_old_memories(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import old memories JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            replace = self._ask_replace_or_merge()
            obj = self._read_json_file(path)

            mem_list = None
            if isinstance(obj, dict) and isinstance(obj.get("memories"), list):
                mem_list = obj.get("memories")
            elif isinstance(obj, list):
                mem_list = obj
            else:
                raise ValueError("Ожидаю list или dict с ключом 'memories'.")

            mems: list[dict] = []
            for it in mem_list:
                if isinstance(it, str):
                    s = it.strip()
                    if s:
                        mems.append({
                            "content": s,
                            "priority": "Normal",
                            "type": "fact",
                            "date_created": _now_ts(),
                            "is_forgotten": 1,
                        })
                    continue
                if isinstance(it, dict):
                    content = _as_stripped(it.get("content") or it.get("text") or it.get("memory"))
                    if not content:
                        continue
                    d = dict(it)
                    d["content"] = content
                    d.setdefault("priority", "Normal")
                    d.setdefault("type", "fact")
                    d.setdefault("date_created", _now_ts())
                    d.setdefault("is_forgotten", 1)
                    mems.append(d)

            cid = self.character_id_edit.text().strip() or "RAG_TEST"
            add = Scenario(character_id=cid, context=[], history=[], memories=mems)

            base = self._parse_editor_scenario()
            self._set_editor_scenario(self._merge_scenario(base, add, replace=replace))

        except RuntimeError:
            return
        except Exception as e:
            QMessageBox.critical(self, "Import memories failed", str(e))

    def on_index_missing(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        try:
            rag = RAGManager(cid)
            updated = rag.index_all_missing(progress_callback=None)
            QMessageBox.information(self, "Index done", f"Обновлено записей: {updated}")
        except Exception as e:
            QMessageBox.critical(self, "Index failed", str(e))

    def on_missing_count(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        try:
            hm = HistoryManager(character_name=cid, character_id=cid)
            missing = hm.get_missing_embeddings_count()
            QMessageBox.information(self, "Missing embeddings", f"Missing embeddings count: {missing}")
        except Exception as e:
            QMessageBox.critical(self, "Failed", str(e))

    def _run_search(self, *, cid: str, query: str, limit: int, threshold: float) -> list[dict]:
        rag = RAGManager(cid)
        if self.chk_use_overrides.isChecked():
            with SettingsOverride(self._collect_overrides()):
                return rag.search_relevant(query=query, limit=limit, threshold=threshold)
        return rag.search_relevant(query=query, limit=limit, threshold=threshold)

    def on_search(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        query = self.query_edit.text()
        limit = int(self.limit_spin.value())
        threshold = float(self.threshold_spin.value())

        try:
            rag = RAGManager(cid)
            try:
                eq = rag._build_query_from_recent(query, tail=2)
            except Exception:
                eq = query
            self.effective_query_view.setPlainText(eq or "")

            res = self._run_search(cid=cid, query=query, limit=limit, threshold=threshold)

            self.table.setRowCount(0)
            for item in res:
                row = self.table.rowCount()
                self.table.insertRow(row)

                source = _as_stripped(item.get("source"))
                rid = str(item.get("id", ""))
                score = item.get("score", 0.0)
                score_str = f"{float(score):.4f}" if score is not None else ""

                type_or_role = _as_stripped(item.get("type") or item.get("role"))
                priority = _as_stripped(item.get("priority") or "")
                date = _as_stripped(item.get("date_created") or item.get("date") or "")

                sp = _as_stripped(item.get("speaker") or "")
                tg = _as_stripped(item.get("target") or "")
                st = f"{sp}→{tg}" if (sp and tg) else (sp or (f"→{tg}" if tg else ""))

                content_str = str(item.get("content") or "")
                clip = content_str.replace("\n", " ").strip()
                if len(clip) > 220:
                    clip = clip[:220] + "…"

                def _set(col: int, text: str, right: bool = False):
                    it = QTableWidgetItem(text)
                    if right:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, col, it)

                _set(0, source)
                _set(1, rid, right=True)
                _set(2, score_str, right=True)
                _set(3, type_or_role)
                _set(4, priority)
                _set(5, date)
                _set(6, st)
                _set(7, clip)

                self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)

            if res:
                self.table.selectRow(0)
                self.right_tabs.setCurrentIndex(0)  # Results
            else:
                self.details.setPlainText("")

        except Exception as e:
            QMessageBox.critical(self, "Search failed", str(e))

    def on_preview_inject(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        query = self.query_edit.text().strip()
        if not query:
            self.injection_preview.setPlainText("")
            return

        limit = int(self.limit_spin.value())
        threshold = float(self.threshold_spin.value())

        try:
            results = self._run_search(cid=cid, query=query, limit=limit, threshold=threshold)

            def _clip(s: Any, n: int = 700) -> str:
                t = str(s or "").strip()
                return (t[:n] + "…") if len(t) > n else t

            mem_lines: list[str] = []
            hist_lines: list[str] = []

            for r in results:
                if not isinstance(r, dict):
                    continue
                src = r.get("source")
                if src == "memory":
                    mem_lines.append(
                        f"- [{_safe_float(r.get('score'), 0.0):.3f}] "
                        f"({r.get('type')}, prio={r.get('priority')}, date={r.get('date_created')}) "
                        f"{_clip(r.get('content'))}"
                    )
                elif src == "history":
                    dt = r.get("date")
                    sp = r.get("speaker") or ""
                    tg = r.get("target") or ""
                    meta = f"{sp}→{tg}" if (sp and tg) else (sp or (f"→{tg}" if tg else ""))
                    meta_s = f" ({meta})" if meta else ""
                    hist_lines.append(
                        f"- [{_safe_float(r.get('score'), 0.0):.3f}] ({dt}){meta_s} {_clip(r.get('content'))}"
                    )

            blocks: list[str] = []
            if mem_lines:
                blocks.append("<relevant_memories>\n" + "\n".join(mem_lines) + "\n</relevant_memories>")
            if hist_lines:
                blocks.append("<past_context>\n" + "\n".join(hist_lines) + "\n</past_context>")

            self.injection_preview.setPlainText("\n\n".join(blocks))
            self.right_tabs.setCurrentIndex(1)  # Debug

        except Exception as e:
            QMessageBox.critical(self, "Preview failed", str(e))

    def on_table_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        r = rows[0].row()
        item0 = self.table.item(r, 0)
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
    w.resize(1280, 820)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())