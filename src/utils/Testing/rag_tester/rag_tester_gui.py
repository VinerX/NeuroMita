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
    QFormLayout,
    QDockWidget,
    QTabWidget,
    QScrollArea,
    QSizePolicy,
    QGroupBox,
)

from styles.main_styles import get_stylesheet
from rag_tester_core import RagTesterService, Scenario


def as_stripped(v: Any) -> str:
    return str(v or "").strip()


class RagTesterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RAG Tester")

        self.svc = RagTesterService()

        self._build_actions()
        self._build_menu()
        self._build_central_ui()
        self._build_settings_dock()
        self._wire_events()

        self.on_template()

    # ---------------- UI ----------------
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
        root.setSpacing(15)  # Общее расстояние между крупными блоками

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # === ЛЕВАЯ ЧАСТЬ (TABS) ===
        left_tabs = QTabWidget()
        splitter.addWidget(left_tabs)

        # --- Scenario Tab ---
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

        # --- Data Tab ---
        tab_data = QWidget()
        tab_data_l = QVBoxLayout(tab_data)
        tab_data_l.setContentsMargins(15, 20, 15, 15)
        tab_data_l.setSpacing(25)  # Большое расстояние между группами (Database, Import, Indexing)

        # 1. Database Group
        gb_db = QGroupBox("Database")
        gb_db_l = QVBoxLayout(gb_db)
        gb_db_l.setSpacing(15)  # Расстояние внутри группы
        gb_db_l.setContentsMargins(12, 20, 12, 12)

        # Ряд кнопок
        db_btns = QHBoxLayout()
        self.btn_apply = QPushButton("Залить scenario в БД")
        self.btn_load_from_db = QPushButton("Загрузить scenario из БД")
        db_btns.addWidget(self.btn_apply)
        db_btns.addWidget(self.btn_load_from_db)
        gb_db_l.addLayout(db_btns)

        # Чекбоксы
        chk_l = QVBoxLayout()
        chk_l.setSpacing(8)
        self.chk_clear_before = QCheckBox("Очистить перед заливкой (опасно)")
        self.chk_embed_now = QCheckBox("Embed при заливке/импорте")
        self.chk_embed_now.setChecked(True)
        chk_l.addWidget(self.chk_clear_before)
        chk_l.addWidget(self.chk_embed_now)
        gb_db_l.addLayout(chk_l)

        # Параметры (выравнивание через FormLayout)
        db_form = QFormLayout()
        db_form.setVerticalSpacing(12)  # Вертикальный зазор между строками
        self.db_hist_limit = QSpinBox();
        self.db_hist_limit.setRange(0, 200000);
        self.db_hist_limit.setValue(3000)
        self.db_mem_limit = QSpinBox();
        self.db_mem_limit.setRange(0, 200000);
        self.db_mem_limit.setValue(4997)
        self.db_hist_limit.setFixedWidth(120)
        self.db_mem_limit.setFixedWidth(120)
        db_form.addRow("history limit:", self.db_hist_limit)
        db_form.addRow("memories limit:", self.db_mem_limit)
        gb_db_l.addLayout(db_form)
        tab_data_l.addWidget(gb_db)

        # 2. Import Group
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
        self.import_context_tail.setRange(0, 50);
        self.import_context_tail.setValue(2)
        self.import_context_tail.setFixedWidth(120)
        imp_form.addRow("Tail -> context:", self.import_context_tail)
        gb_import_l.addLayout(imp_form)
        tab_data_l.addWidget(gb_import)

        # 3. Indexing Group
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

        # === ПРАВАЯ ЧАСТЬ (SEARCH) ===
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(12)

        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("Query:"))
        self.query_edit = QLineEdit()
        qrow.addWidget(self.query_edit, 1)

        self.limit_spin = QSpinBox();
        self.limit_spin.setRange(1, 200);
        self.limit_spin.setValue(10);
        self.limit_spin.setFixedWidth(60)
        self.threshold_spin = QDoubleSpinBox();
        self.threshold_spin.setRange(-1.0, 1.0);
        self.threshold_spin.setValue(0.40);
        self.threshold_spin.setFixedWidth(70)

        qrow.addWidget(QLabel("limit"))
        qrow.addWidget(self.limit_spin)
        qrow.addWidget(QLabel("thr"))
        qrow.addWidget(self.threshold_spin)

        self.btn_search = QPushButton("Search")
        self.btn_preview_inject = QPushButton("Preview")
        qrow.addWidget(self.btn_search)
        qrow.addWidget(self.btn_preview_inject)
        right_l.addLayout(qrow)

        self.right_tabs = QTabWidget()
        right_l.addWidget(self.right_tabs, 1)

        # Results tab
        tab_res = QWidget()
        tab_res_l = QVBoxLayout(tab_res)
        tab_res_l.setContentsMargins(0, 0, 0, 0)
        res_split = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["source", "id", "score", "type/role", "priority", "date", "speaker→target", "content"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        res_split.addWidget(self.table)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        res_split.addWidget(self.details)
        res_split.setStretchFactor(0, 3)
        res_split.setStretchFactor(1, 1)
        tab_res_l.addWidget(res_split)
        self.right_tabs.addTab(tab_res, "Results")

        # Debug tab
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

        # NB: в текущем search_relevant эти два ключа читаются, но штраф не применяется.
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

    # ---------------- helpers ----------------
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

    def collect_overrides(self) -> dict[str, Any]:
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

    # ---------------- actions ----------------
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
                    self,
                    "Подтверждение",
                    f"Очистить данные для character_id='{sc.character_id}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ok != QMessageBox.StandardButton.Yes:
                    return

            embed_now = bool(self.chk_embed_now.isChecked())
            counts = self.svc.apply_scenario_to_db(sc, clear_before=clear_before, embed_now=embed_now)

            QMessageBox.information(
                self,
                "Готово",
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
                self,
                "Loaded",
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
                obj,
                character_id=self.current_cid(),
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
        cid = self.current_cid()
        query = self.query_edit.text()
        limit = int(self.limit_spin.value())
        thr = float(self.threshold_spin.value())

        try:
            eq = self.svc.build_effective_query(cid, query, tail=2)
            self.effective_query_view.setPlainText(eq or "")

            use_overrides = bool(self.chk_use_overrides.isChecked())
            overrides = self.collect_overrides()

            res = self.svc.search(
                cid=cid,
                query=query,
                limit=limit,
                threshold=thr,
                use_overrides=use_overrides,
                overrides=overrides,
            )

            self.table.setRowCount(0)
            for item in res:
                row = self.table.rowCount()
                self.table.insertRow(row)

                source = as_stripped(item.get("source"))
                rid = str(item.get("id", ""))
                score = item.get("score", 0.0)
                score_str = f"{float(score):.4f}" if score is not None else ""

                type_or_role = as_stripped(item.get("type") or item.get("role"))
                priority = as_stripped(item.get("priority") or "")
                date = as_stripped(item.get("date_created") or item.get("date") or "")

                sp = as_stripped(item.get("speaker") or "")
                tg = as_stripped(item.get("target") or "")
                st = f"{sp}→{tg}" if (sp and tg) else (sp or (f"→{tg}" if tg else ""))

                content_str = str(item.get("content") or "")
                clip = content_str.replace("\n", " ").strip()
                if len(clip) > 220:
                    clip = clip[:220] + "…"

                def set_cell(col: int, text: str, right: bool = False):
                    it = QTableWidgetItem(text)
                    if right:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, col, it)

                set_cell(0, source)
                set_cell(1, rid, right=True)
                set_cell(2, score_str, right=True)
                set_cell(3, type_or_role)
                set_cell(4, priority)
                set_cell(5, date)
                set_cell(6, st)
                set_cell(7, clip)

                self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)

            if res:
                self.table.selectRow(0)
                self.right_tabs.setCurrentIndex(0)  # Results
            else:
                self.details.setPlainText("")

        except Exception as e:
            QMessageBox.critical(self, "Search failed", str(e))

    def on_preview_inject(self) -> None:
        cid = self.current_cid()
        query = self.query_edit.text().strip()
        if not query:
            self.injection_preview.setPlainText("")
            return

        limit = int(self.limit_spin.value())
        thr = float(self.threshold_spin.value())

        try:
            use_overrides = bool(self.chk_use_overrides.isChecked())
            overrides = self.collect_overrides()

            res = self.svc.search(
                cid=cid,
                query=query,
                limit=limit,
                threshold=thr,
                use_overrides=use_overrides,
                overrides=overrides,
            )
            preview = self.svc.build_injection_preview(res)
            self.injection_preview.setPlainText(preview)
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