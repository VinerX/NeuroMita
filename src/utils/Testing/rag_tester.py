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
    Временный override SettingsManager.get(key, default), чтобы тестировать RAG
    с разными весами "как в проде", не меняя код RAGManager.
    """
    def __init__(self, overrides: dict[str, Any]):
        self.overrides = dict(overrides or {})
        self._orig_get = None

    def __enter__(self):
        self._orig_get = getattr(SettingsManager, "get", None)
        orig = self._orig_get

        def wrapped_get(key: str, default=None):
            try:
                k = str(key)
            except Exception:
                k = key
            if k in self.overrides:
                return self.overrides[k]
            if callable(orig):
                return orig(key, default)
            return default

        # делаем статикметод, чтобы не было привязки self/cls в неожиданных реализациях
        try:
            setattr(SettingsManager, "get", staticmethod(wrapped_get))
        except Exception:
            # если не вышло — просто оставим как есть
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
    history: list[dict]    # history.is_active=0 (корпус)
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
                    "is_forgotten": 1,  # чтобы участвовало при default RAG_MEMORY_MODE='forgotten'
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
                if "role" not in it2:
                    it2["role"] = "user"
                if "content" not in it2:
                    it2["content"] = ""
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
        self.setWindowTitle("RAG Tester (PyQt6)")

        self.db = DatabaseManager()

        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)

        # ------------------------------------------------------------------
        # Top controls
        # ------------------------------------------------------------------
        top = QWidget()
        top_layout = QGridLayout(top)

        self.character_id_edit = QLineEdit("RAG_TEST")
        top_layout.addWidget(QLabel("character_id:"), 0, 0)
        top_layout.addWidget(self.character_id_edit, 0, 1)

        self.btn_template = QPushButton("Шаблон")
        self.btn_load_file = QPushButton("Загрузить scenario JSON…")
        self.btn_save_file = QPushButton("Сохранить scenario JSON…")
        top_layout.addWidget(self.btn_template, 0, 2)
        top_layout.addWidget(self.btn_load_file, 0, 3)
        top_layout.addWidget(self.btn_save_file, 0, 4)

        self.chk_clear_before = QCheckBox("Очистить данные character_id перед заливкой (ОПАСНО)")
        self.chk_clear_before.setChecked(False)
        top_layout.addWidget(self.chk_clear_before, 1, 0, 1, 3)

        self.chk_embed_now = QCheckBox("Сразу построить эмбеддинги при заливке/импорте")
        self.chk_embed_now.setChecked(True)
        top_layout.addWidget(self.chk_embed_now, 1, 3, 1, 2)

        self.btn_apply = QPushButton("Залить scenario в БД")
        self.btn_load_from_db = QPushButton("Загрузить scenario из БД")
        top_layout.addWidget(self.btn_apply, 2, 0, 1, 2)
        top_layout.addWidget(self.btn_load_from_db, 2, 2, 1, 1)

        self.db_hist_limit = QSpinBox()
        self.db_hist_limit.setRange(0, 200000)
        self.db_hist_limit.setValue(3000)  # 0 = без лимита
        self.db_mem_limit = QSpinBox()
        self.db_mem_limit.setRange(0, 200000)
        self.db_mem_limit.setValue(5000)   # 0 = без лимита

        top_layout.addWidget(QLabel("DB history limit (0=all):"), 2, 3)
        top_layout.addWidget(self.db_hist_limit, 2, 4)

        top_layout.addWidget(QLabel("DB memories limit (0=all):"), 3, 3)
        top_layout.addWidget(self.db_mem_limit, 3, 4)

        self.btn_import_old_history = QPushButton("Импорт старого history JSON…")
        self.btn_import_old_memories = QPushButton("Импорт старого memories JSON…")
        top_layout.addWidget(self.btn_import_old_history, 3, 0, 1, 2)
        top_layout.addWidget(self.btn_import_old_memories, 3, 2, 1, 1)

        self.import_context_tail = QSpinBox()
        self.import_context_tail.setRange(0, 50)
        self.import_context_tail.setValue(2)
        top_layout.addWidget(QLabel("Tail->context при импорте history:"), 4, 0)
        top_layout.addWidget(self.import_context_tail, 4, 1)

        self.btn_index_missing = QPushButton("Индексировать missing embeddings")
        self.btn_missing_count = QPushButton("Показать missing count")
        top_layout.addWidget(self.btn_index_missing, 4, 2, 1, 1)
        top_layout.addWidget(self.btn_missing_count, 4, 3, 1, 1)

        main_layout.addWidget(top)

        # ------------------------------------------------------------------
        # RAG overrides group
        # ------------------------------------------------------------------
        overrides_group = QGroupBox("RAG overrides (опционально, 'как в проде', через SettingsManager.get override)")
        og = QFormLayout(overrides_group)

        self.chk_use_overrides = QCheckBox("Использовать overrides при поиске/превью инжекта")
        self.chk_use_overrides.setChecked(True)
        og.addRow(self.chk_use_overrides)

        self.k1 = QDoubleSpinBox(); self.k1.setRange(-10.0, 10.0); self.k1.setValue(1.0); self.k1.setSingleStep(0.1)
        self.k2 = QDoubleSpinBox(); self.k2.setRange(-10.0, 10.0); self.k2.setValue(1.0); self.k2.setSingleStep(0.1)
        self.k3 = QDoubleSpinBox(); self.k3.setRange(-10.0, 10.0); self.k3.setValue(1.0); self.k3.setSingleStep(0.1)
        self.k4 = QDoubleSpinBox(); self.k4.setRange(-10.0, 10.0); self.k4.setValue(0.5); self.k4.setSingleStep(0.1)

        og.addRow("RAG_WEIGHT_SIMILARITY (K1):", self.k1)
        og.addRow("RAG_WEIGHT_TIME (K2):", self.k2)
        og.addRow("RAG_WEIGHT_PRIORITY (K3):", self.k3)
        og.addRow("RAG_WEIGHT_ENTITY (K4):", self.k4)

        self.decay = QDoubleSpinBox(); self.decay.setRange(0.0, 10.0); self.decay.setValue(0.15); self.decay.setSingleStep(0.05)
        self.noise = QDoubleSpinBox(); self.noise.setRange(0.0, 1.0); self.noise.setValue(0.05); self.noise.setSingleStep(0.01)
        og.addRow("RAG_TIME_DECAY_RATE:", self.decay)
        og.addRow("RAG_NOISE_MAX:", self.noise)

        self.memory_mode = QComboBox()
        self.memory_mode.addItems(["forgotten", "active", "all"])
        self.memory_mode.setCurrentText("forgotten")
        og.addRow("RAG_MEMORY_MODE:", self.memory_mode)

        self.detailed_logs = QCheckBox("RAG_DETAILED_LOGS")
        self.detailed_logs.setChecked(True)
        og.addRow(self.detailed_logs)

        # NOTE: В текущем RAGManager эти два читаются, но штраф не применяется в формуле.
        self.include_forgotten = QCheckBox("RAG_INCLUDE_FORGOTTEN (сейчас не влияет в коде search_relevant)")
        self.include_forgotten.setChecked(False)
        og.addRow(self.include_forgotten)

        self.forgotten_penalty = QDoubleSpinBox()
        self.forgotten_penalty.setRange(-5.0, 5.0)
        self.forgotten_penalty.setValue(-0.15)
        self.forgotten_penalty.setSingleStep(0.05)
        og.addRow("RAG_FORGOTTEN_PENALTY (сейчас не влияет):", self.forgotten_penalty)

        main_layout.addWidget(overrides_group)

        # ------------------------------------------------------------------
        # Split: scenario editor / results
        # ------------------------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # left: scenario editor
        left = QWidget()
        left_layout = QVBoxLayout(left)

        left_layout.addWidget(QLabel("Scenario JSON:"))
        self.scenario_edit = QTextEdit()
        self.scenario_edit.setAcceptRichText(False)
        left_layout.addWidget(self.scenario_edit, 1)

        left_layout.addWidget(QLabel("Effective query (RAG build_query_from_recent + текущий запрос):"))
        self.effective_query_view = QPlainTextEdit()
        self.effective_query_view.setReadOnly(True)
        self.effective_query_view.setMaximumHeight(120)
        left_layout.addWidget(self.effective_query_view)

        left_layout.addWidget(QLabel("RAG injection preview (как process_rag: <relevant_memories>/<past_context>):"))
        self.injection_preview = QPlainTextEdit()
        self.injection_preview.setReadOnly(True)
        self.injection_preview.setMaximumHeight(160)
        left_layout.addWidget(self.injection_preview)

        splitter.addWidget(left)

        # right: query controls + table + details
        right = QWidget()
        right_layout = QVBoxLayout(right)

        query_box = QWidget()
        ql = QGridLayout(query_box)

        self.query_edit = QLineEdit()
        ql.addWidget(QLabel("Query:"), 0, 0)
        ql.addWidget(self.query_edit, 0, 1, 1, 5)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 200)
        self.limit_spin.setValue(10)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-1.0, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.40)

        self.btn_search = QPushButton("Search RAG")
        self.btn_preview_inject = QPushButton("Preview inject blocks")
        ql.addWidget(QLabel("limit:"), 1, 0)
        ql.addWidget(self.limit_spin, 1, 1)
        ql.addWidget(QLabel("threshold:"), 1, 2)
        ql.addWidget(self.threshold_spin, 1, 3)
        ql.addWidget(self.btn_search, 1, 4)
        ql.addWidget(self.btn_preview_inject, 1, 5)

        right_layout.addWidget(query_box)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["source", "id", "score", "type/role", "priority", "date", "speaker→target", "content"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        right_layout.addWidget(self.table, 1)

        right_layout.addWidget(QLabel("Selected item full JSON:"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(220)
        right_layout.addWidget(self.details)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)

        # ------------------------------------------------------------------
        # wire events
        # ------------------------------------------------------------------
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

        # init template
        self.on_template()

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
        sc = Scenario.template(character_id=cid)
        self._set_editor_scenario(sc)

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
    # Settings overrides
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

            # history
            if "is_deleted" in hcols:
                cur.execute("UPDATE history SET is_deleted=1 WHERE character_id=?", (cid,))
            else:
                cur.execute("DELETE FROM history WHERE character_id=?", (cid,))

            # variables
            try:
                cur.execute("DELETE FROM variables WHERE character_id=?", (cid,))
            except Exception:
                pass

            # memories
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

        # best-effort schema upgrade for is_forgotten
        _ = MemoryManager(cid)
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
                    # participants может быть list/str — как в HistoryManager, RAGManager умеет оба
                    vals.append(json.dumps(participants, ensure_ascii=False) if isinstance(participants, list) else participants)

                if has_is_deleted:
                    insert_cols.append("is_deleted")
                    vals.append(is_deleted)
                else:
                    # если нет колонки — нельзя корректно, но пропустим флаг
                    pass

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
            # нормализуем время (HistoryManager понимает time/timestamp)
            if "timestamp" not in m2 and "time" not in m2:
                m2["time"] = _now_ts()
            if "role" not in m2:
                m2["role"] = "user"
            if "content" not in m2:
                m2["content"] = ""

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

        # 1) context (active)
        active = hm.load_history().get("messages", []) or []

        # 2) archived history corpus (is_active=0)
        select_cols = hm._history_select_columns()  # includes role, content, meta_data, timestamp + desired cols if exist
        # ensure includes desired cols (hm._history_select_columns already does)
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
            msg = hm._reconstruct_message_from_db(
                rd.get("role"),
                rd.get("content"),
                rd.get("meta_data"),
            )
            msg["time"] = rd.get("timestamp") or ""

            # дополним из колонок, если они были в SELECT
            for k in hm._HISTORY_DESIRED_COLUMNS.keys():
                if k in cols_set and rd.get(k) not in (None, ""):
                    msg[k] = rd.get(k)

            msg = hm._normalize_loaded_message(msg)
            corpus.append(msg)

        # 3) memories
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

    def on_load_from_db(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        try:
            sc = self._load_from_db(cid, hist_limit=int(self.db_hist_limit.value()), mem_limit=int(self.db_mem_limit.value()))
            self._set_editor_scenario(sc)
            QMessageBox.information(
                self,
                "Loaded from DB",
                f"Загружено для {cid}:\n"
                f"- context(active): {len(sc.context)}\n"
                f"- history(archived corpus): {len(sc.history)}\n"
                f"- memories: {len(sc.memories)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Load from DB failed", str(e))

    # ------------------------------------------------------------------
    # Import old JSON
    # ------------------------------------------------------------------
    def _read_json_file(self, path: str) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())

    def _merge_scenario(self, base: Scenario, add: Scenario, *, replace: bool) -> Scenario:
        if replace:
            return Scenario(
                character_id=add.character_id or base.character_id,
                context=list(add.context),
                history=list(add.history),
                memories=list(add.memories),
            )

        # merge (append)
        cid = add.character_id or base.character_id
        return Scenario(
            character_id=cid,
            context=list(base.context) + list(add.context),
            history=list(base.history) + list(add.history),
            memories=list(base.memories) + list(add.memories),
        )

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

    def on_import_old_history(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import old history JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            replace = self._ask_replace_or_merge()
            obj = self._read_json_file(path)

            # old history formats:
            # - {"messages":[...], ...}
            # - [...]
            messages = None
            if isinstance(obj, dict) and isinstance(obj.get("messages"), list):
                messages = obj.get("messages")
            elif isinstance(obj, list):
                messages = obj
            else:
                raise ValueError("Не похоже на history JSON: ожидаю list или dict с ключом 'messages'.")

            # разложим: tail N -> context, остальное -> history corpus
            tail_n = int(self.import_context_tail.value())
            tail_n = max(0, tail_n)

            msgs_norm: list[dict] = []
            for m in messages:
                if not isinstance(m, dict):
                    continue
                m2 = dict(m)
                if "timestamp" not in m2 and "time" not in m2:
                    m2["time"] = _now_ts()
                if "role" not in m2:
                    m2["role"] = "user"
                if "content" not in m2:
                    m2["content"] = ""
                msgs_norm.append(m2)

            if tail_n > 0:
                ctx = msgs_norm[-tail_n:] if len(msgs_norm) >= tail_n else list(msgs_norm)
                hist = msgs_norm[:-tail_n] if len(msgs_norm) > tail_n else []
            else:
                ctx = []
                hist = msgs_norm

            cid = self.character_id_edit.text().strip() or "RAG_TEST"
            add = Scenario(character_id=cid, context=ctx, history=hist, memories=[])

            base = self._parse_editor_scenario()
            merged = self._merge_scenario(base, add, replace=replace)
            self._set_editor_scenario(merged)

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
                raise ValueError("Не похоже на memories JSON: ожидаю list или dict с ключом 'memories'.")

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
            merged = self._merge_scenario(base, add, replace=replace)
            self._set_editor_scenario(merged)

        except RuntimeError:
            return
        except Exception as e:
            QMessageBox.critical(self, "Import memories failed", str(e))

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
                    f"Очистить данные для character_id='{cid}'?\n"
                    f"Это повлияет на history/memories/variables этого персонажа.",
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
                f"- memories: {n_mem}\n\n"
                f"Если embed_now выключен — нажми 'Индексировать missing embeddings'.",
            )

        except Exception as e:
            QMessageBox.critical(self, "Apply failed", str(e))

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

            # effective query (контекст + текущий запрос)
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
                st = ""
                if sp and tg:
                    st = f"{sp}→{tg}"
                elif sp:
                    st = sp
                elif tg:
                    st = f"→{tg}"

                content = item.get("content", "")
                content_str = str(content or "")
                clip = content_str.replace("\n", " ").strip()
                if len(clip) > 220:
                    clip = clip[:220] + "…"

                def _set(col: int, text: str, align_right: bool = False):
                    it = QTableWidgetItem(text)
                    if align_right:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, col, it)

                _set(0, source)
                _set(1, rid, align_right=True)
                _set(2, score_str, align_right=True)
                _set(3, type_or_role)
                _set(4, priority)
                _set(5, date)
                _set(6, st)
                _set(7, clip)

                self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)

            if res:
                self.table.selectRow(0)
            else:
                self.details.setPlainText("")

        except Exception as e:
            QMessageBox.critical(self, "Search failed", str(e))

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

    def on_preview_inject(self) -> None:
        """
        Превью блоков как в твоём process_rag():
        <relevant_memories>...</relevant_memories>
        <past_context>...</past_context>
        """
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
                    meta = ""
                    if sp and tg:
                        meta = f"{sp}→{tg}"
                    elif sp:
                        meta = sp
                    elif tg:
                        meta = f"→{tg}"
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

        except Exception as e:
            QMessageBox.critical(self, "Preview failed", str(e))


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