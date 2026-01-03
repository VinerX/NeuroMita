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
    QPlainTextEdit,
)

from styles.main_styles import get_stylesheet

from managers.database_manager import DatabaseManager
from managers.rag_manager import RAGManager
from managers.history_manager import HistoryManager
from managers.memory_manager import MemoryManager


def _now_ts() -> str:
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _as_stripped(s: Any) -> str:
    return str(s or "").strip()


@dataclass
class Scenario:
    character_id: str
    context: list[dict]          # active messages (is_active=1)
    history: list[dict]          # archived corpus (is_active=0)
    memories: list[dict]         # memories corpus

    @staticmethod
    def template(character_id: str = "RAG_TEST") -> "Scenario":
        now = _now_ts()
        return Scenario(
            character_id=character_id,

            # ACTIVE: именно это влияет на _build_query_from_recent + ctx_actors (speaker/target/participants)
            context=[
                {
                    "message_id": "in:demo-1",
                    "role": "user",
                    "speaker": "Player",
                    "sender": "Player",
                    "target": character_id,
                    "participants": ["Player", character_id],
                    "event_type": "chat",
                    "time": now,
                    "content": [
                        {"type": "text", "text": "Привет! Напомни, что я говорил про поездку в Альпы?"},
                    ],
                },
                {
                    "message_id": "out:demo-1",
                    "role": "assistant",
                    "speaker": character_id,
                    "sender": character_id,
                    "target": "Player",
                    "participants": ["Player", character_id],
                    "event_type": "chat",
                    "time": now,
                    "content": "Ты говорил, что хочешь в Альпы весной и уже выбирал маршрут.",
                },
            ],

            # ARCHIVED CORPUS: только is_active=0 участвует в history-поиске RAG
            history=[
                {
                    "message_id": "in:old-1",
                    "role": "user",
                    "speaker": "Player",
                    "sender": "Player",
                    "target": character_id,
                    "participants": ["Player", character_id],
                    "event_type": "chat",
                    "time": "01.12.2025 12:00:00",
                    "content": [{"type": "text", "text": "Я люблю горы, особенно Альпы."}],
                },
                {
                    "message_id": "out:old-1",
                    "role": "assistant",
                    "speaker": character_id,
                    "sender": character_id,
                    "target": "Player",
                    "participants": ["Player", character_id],
                    "event_type": "chat",
                    "time": "01.12.2025 12:01:00",
                    "content": "Ты говорил, что хочешь в Швейцарию весной.",
                },
                {
                    "message_id": "in:old-2",
                    "role": "user",
                    "speaker": "Player",
                    "sender": "Player",
                    "target": character_id,
                    "participants": ["Player", character_id],
                    "event_type": "chat",
                    "time": "01.12.2025 12:02:00",
                    "content": [
                        {"type": "text", "text": "У меня есть красный рюкзак и треккинговые ботинки."},
                        # можно оставить без реальной картинки — формат важнее
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA..."}},
                    ],
                },
            ],

            # MEMORIES: чтобы точно участвовали при дефолтном RAG_MEMORY_MODE="forgotten" — ставим is_forgotten=1
            memories=[
                {
                    "content": "User prefers mountains; wants Alps/Switzerland trip in spring.",
                    "priority": "High",
                    "type": "fact",
                    "date_created": "01.12.2025 12:05:00",
                    "is_forgotten": 1
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

        # normalize items to dict
        def _norm_msgs(arr: list[Any]) -> list[dict]:
            out: list[dict] = []
            for it in arr:
                if not isinstance(it, dict):
                    continue
                role = _as_stripped(it.get("role"))
                if role and role not in ("user", "assistant", "system", "developer", "tool", "other"):
                    # не валим — просто оставим как есть
                    pass
                if "timestamp" not in it and "time" not in it:
                    it = dict(it)
                    it["time"] = _now_ts()
                out.append(it)
            return out

        def _norm_mems(arr: list[Any]) -> list[dict]:
            out: list[dict] = []
            for it in arr:
                if not isinstance(it, dict):
                    continue
                if not _as_stripped(it.get("content")):
                    continue
                it2 = dict(it)
                if "priority" not in it2:
                    it2["priority"] = "Normal"
                if "type" not in it2:
                    it2["type"] = "fact"
                if "date_created" not in it2:
                    it2["date_created"] = _now_ts()
                if "is_forgotten" not in it2:
                    it2["is_forgotten"] = 1  # чтобы попадало в RAG при default memory_mode="forgotten"
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

        # --- Top controls ---
        top = QWidget()
        top_layout = QGridLayout(top)

        self.character_id_edit = QLineEdit("RAG_TEST")
        top_layout.addWidget(QLabel("character_id:"), 0, 0)
        top_layout.addWidget(self.character_id_edit, 0, 1)

        self.btn_load_file = QPushButton("Загрузить JSON…")
        self.btn_save_file = QPushButton("Сохранить JSON…")
        self.btn_template = QPushButton("Шаблон")
        top_layout.addWidget(self.btn_load_file, 0, 2)
        top_layout.addWidget(self.btn_save_file, 0, 3)
        top_layout.addWidget(self.btn_template, 0, 4)

        self.chk_clear_before = QCheckBox("Очистить данные character_id перед заливкой (ОПАСНО)")
        self.chk_clear_before.setChecked(False)
        top_layout.addWidget(self.chk_clear_before, 1, 0, 1, 3)

        self.chk_embed_now = QCheckBox("Сразу построить эмбеддинги при заливке")
        self.chk_embed_now.setChecked(True)
        top_layout.addWidget(self.chk_embed_now, 1, 3, 1, 2)

        self.btn_apply = QPushButton("Залить сценарий в БД")
        top_layout.addWidget(self.btn_apply, 2, 0, 1, 2)

        self.btn_index_missing = QPushButton("Индексировать missing embeddings")
        top_layout.addWidget(self.btn_index_missing, 2, 2, 1, 2)

        self.btn_missing_count = QPushButton("Показать missing count")
        top_layout.addWidget(self.btn_missing_count, 2, 4, 1, 1)

        main_layout.addWidget(top)

        # --- Split: scenario editor / results ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # left: scenario editor + logs/info
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
        ql.addWidget(QLabel("limit:"), 1, 0)
        ql.addWidget(self.limit_spin, 1, 1)
        ql.addWidget(QLabel("threshold:"), 1, 2)
        ql.addWidget(self.threshold_spin, 1, 3)
        ql.addWidget(self.btn_search, 1, 5)

        right_layout.addWidget(query_box)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["source", "id", "score", "type/role", "priority", "date", "content"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        right_layout.addWidget(self.table, 1)

        right_layout.addWidget(QLabel("Selected item full content:"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(200)
        right_layout.addWidget(self.details)

        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)

        # --- wire events ---
        self.btn_template.clicked.connect(self.on_template)
        self.btn_load_file.clicked.connect(self.on_load_file)
        self.btn_save_file.clicked.connect(self.on_save_file)
        self.btn_apply.clicked.connect(self.on_apply)
        self.btn_index_missing.clicked.connect(self.on_index_missing)
        self.btn_missing_count.clicked.connect(self.on_missing_count)
        self.btn_search.clicked.connect(self.on_search)
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
        try:
            obj = json.loads(raw)
        except Exception as e:
            raise ValueError(f"Невалидный JSON: {e}")
        return Scenario.from_json(obj, fallback_character_id=self.character_id_edit.text().strip())

    def on_template(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        sc = Scenario.template(character_id=cid)
        self.scenario_edit.setPlainText(sc.to_pretty_json())

    def on_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load scenario JSON", "", "JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            obj = json.loads(raw)
            sc = Scenario.from_json(obj, fallback_character_id=self.character_id_edit.text().strip())
            self.character_id_edit.setText(sc.character_id)
            self.scenario_edit.setPlainText(sc.to_pretty_json())
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
        """
        Осторожная очистка только по character_id.
        - history: если есть is_deleted -> soft delete, иначе DELETE
        - memories: is_deleted=1 (если колонка есть), иначе DELETE
        """
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

            # variables (опционально, но обычно логично чистить для теста)
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
        """
        Вставляем memories напрямую в БД:
        - сохраняем is_forgotten, если колонка есть
        - eternal_id авто-инкрементируем как MAX+1
        - (опционально) эмбеддим через RAGManager.update_memory_embedding
        """
        if not memories:
            return 0

        mm = MemoryManager(cid)  # гарантирует схему is_forgotten (best-effort)
        rag = RAGManager(cid)

        cols = self._table_cols("memories")
        has_is_forgotten = "is_forgotten" in cols

        inserted = 0
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()

            # starting eternal_id
            cur.execute("SELECT MAX(eternal_id) FROM memories WHERE character_id=?", (cid,))
            res = cur.fetchone()
            max_eid = int(res[0] or 0) if res else 0

            for it in memories:
                content = _as_stripped(it.get("content"))
                if not content:
                    continue

                max_eid += 1
                priority = _as_stripped(it.get("priority") or "Normal") or "Normal"
                mtype = _as_stripped(it.get("type") or "fact") or "fact"
                date_created = _as_stripped(it.get("date_created") or _now_ts()) or _now_ts()
                is_deleted = int(it.get("is_deleted") or 0)
                is_forgotten = int(it.get("is_forgotten") or 0)

                insert_cols = ["character_id", "eternal_id", "content", "priority", "type", "date_created", "is_deleted"]
                vals: list[Any] = [cid, max_eid, content, priority, mtype, date_created, is_deleted]

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
                        # не валим заливку
                        pass

            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # чтобы mm не удалился “без дела”
        _ = mm
        return inserted

    def _insert_history_messages(self, cid: str, msgs: list[dict], is_active: int, embed_now: bool) -> int:
        """
        Вставляем сообщения через HistoryManager._insert_history_row (у вас уже есть dedupe/динамика по схеме).
        Если embed_now=True, то сразу считаем эмбеддинги (для content любых типов через _extract_text_for_embedding).
        """
        if not msgs:
            return 0

        hm = HistoryManager(character_name=cid, character_id=cid)
        rag = RAGManager(cid)

        inserted = 0
        for msg in msgs:
            if not isinstance(msg, dict):
                continue

            # нормализуем timestamp
            m2 = dict(msg)
            if "timestamp" not in m2 and "time" not in m2:
                m2["timestamp"] = _now_ts()

            # роль/контент
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
    # Actions
    # ------------------------------------------------------------------
    def on_apply(self) -> None:
        try:
            sc = self._parse_editor_scenario()
            cid = sc.character_id
            self.character_id_edit.setText(cid)

            if self.chk_clear_before.isChecked():
                # маленькое “страхование от случайного клика”
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
            # простой синхронный прогон (да, UI подвиснет на больших объёмах)
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

    def on_search(self) -> None:
        cid = self.character_id_edit.text().strip() or "RAG_TEST"
        query = self.query_edit.text()
        limit = int(self.limit_spin.value())
        threshold = float(self.threshold_spin.value())

        try:
            rag = RAGManager(cid)

            # покажем, какой текст реально пойдёт в эмбеддинг запроса (контекст + текущий query)
            try:
                eq = rag._build_query_from_recent(query, tail=2)  # да, private — но это тестер
            except Exception:
                eq = query
            self.effective_query_view.setPlainText(eq or "")

            res = rag.search_relevant(query=query, limit=limit, threshold=threshold)

            self.table.setRowCount(0)
            for item in res:
                row = self.table.rowCount()
                self.table.insertRow(row)

                source = _as_stripped(item.get("source"))
                rid = str(item.get("id", ""))
                score = item.get("score", 0.0)
                score_str = f"{float(score):.4f}" if score is not None else ""

                # unify fields
                type_or_role = _as_stripped(item.get("type") or item.get("role"))
                priority = _as_stripped(item.get("priority") or "")
                date = _as_stripped(item.get("date_created") or item.get("date") or "")

                content = item.get("content", "")
                content_str = str(content or "")
                clip = content_str.replace("\n", " ").strip()
                if len(clip) > 220:
                    clip = clip[:220] + "…"

                def _set(col: int, text: str):
                    it = QTableWidgetItem(text)
                    if col in (1, 2):
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, col, it)

                _set(0, source)
                _set(1, rid)
                _set(2, score_str)
                _set(3, type_or_role)
                _set(4, priority)
                _set(5, date)
                _set(6, clip)

                # full payload into user role for selection details
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


def main() -> int:
    app = QApplication(sys.argv)
    try:
        app.setStyleSheet(get_stylesheet())
    except Exception:
        # если stylesheet не загрузился — не валим тестер
        pass
    w = RagTesterWindow()
    w.resize(1280, 780)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())