# utils/Testing/rag_tester/tester_styles.py
#
# Дополнительный QSS для RAG Tester.
# Основной стиль проекта (main_styles.py) не покрывает QTableWidget,
# QPlainTextEdit, QSpinBox, QDoubleSpinBox, QDockWidget, QGroupBox,
# QStatusBar, QListWidget — здесь они стилизуются в той же палитре.

TESTER_QSS = """
/* ── PlainTextEdit (details, debug panes) ── */
QPlainTextEdit {
    background-color: rgba(18,18,22,0.92);
    color: #e6e6eb;
    border: 1px solid rgba(255,255,255,0.08);
    padding: 6px 10px;
    border-radius: 10px;
    selection-background-color: #8a2be2;
    selection-color: #ffffff;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9pt;
}
QPlainTextEdit:focus {
    border: 1px solid #8a2be2;
}

/* ── SpinBox / DoubleSpinBox ── */
QSpinBox, QDoubleSpinBox {
    background-color: rgba(18,18,22,0.92);
    color: #e6e6eb;
    border: 1px solid rgba(255,255,255,0.08);
    padding: 4px 8px;
    border-radius: 8px;
    min-height: 22px;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #8a2be2;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: rgba(255,255,255,0.06);
    border: none;
    width: 16px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: rgba(255,255,255,0.12);
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #e6e6eb;
    width: 0; height: 0;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #e6e6eb;
    width: 0; height: 0;
}

/* ── TableWidget (reuse QTableView rules) ── */
QTableWidget {
    background-color: rgba(18,18,22,0.92);
    alternate-background-color: rgba(255,255,255,0.03);
    color: #e6e6eb;
    border: 1px solid rgba(255,255,255,0.08);
    gridline-color: rgba(255,255,255,0.06);
    selection-background-color: rgba(138,43,226,0.25);
    selection-color: #ffffff;
    outline: 0;
    border-radius: 6px;
}
QTableWidget::item {
    padding: 4px 6px;
    border: none;
}
QTableWidget::item:hover {
    background-color: rgba(255,255,255,0.06);
}
QTableWidget::item:selected {
    background-color: rgba(138,43,226,0.35);
    color: #ffffff;
}

/* ── GroupBox ── */
QGroupBox {
    color: #e6e6eb;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px;
    color: #c8c8d0;
    background-color: rgba(24,24,28,0.95);
    border-radius: 6px;
}

/* ── DockWidget ── */
QDockWidget {
    color: #e6e6eb;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background-color: rgba(24,24,28,0.95);
    color: #e6e6eb;
    padding: 8px 12px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    font-weight: 700;
}
QDockWidget::close-button, QDockWidget::float-button {
    background-color: rgba(255,255,255,0.06);
    border: none;
    border-radius: 6px;
    padding: 2px;
}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {
    background-color: rgba(255,255,255,0.14);
}

/* ── ListWidget (query history) ── */
QListWidget {
    background-color: rgba(18,18,22,0.92);
    color: #e6e6eb;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 4px;
    outline: 0;
}
QListWidget::item {
    padding: 4px 8px;
    border-radius: 4px;
    color: #e6e6eb;
}
QListWidget::item:hover {
    background-color: rgba(255,255,255,0.06);
}
QListWidget::item:selected {
    background-color: rgba(138,43,226,0.30);
    color: #ffffff;
}

/* ── StatusBar ── */
QStatusBar {
    background-color: rgba(18,18,22,0.95);
    color: #9a9aa2;
    border-top: 1px solid rgba(255,255,255,0.08);
    padding: 2px 8px;
    font-size: 8.5pt;
}
QStatusBar QLabel {
    color: #9a9aa2;
    padding: 0 4px;
}

/* ── Splitter handles ── */
QSplitter::handle {
    background-color: rgba(255,255,255,0.06);
}
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }
QSplitter::handle:hover {
    background-color: rgba(138,43,226,0.40);
}

/* ── Menu bar ── */
QMenuBar {
    background-color: rgba(18,18,22,0.95);
    color: #e6e6eb;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}
QMenuBar::item {
    padding: 6px 12px;
    background: transparent;
}
QMenuBar::item:selected {
    background-color: rgba(138,43,226,0.30);
    border-radius: 6px;
}
QMenu {
    background-color: rgba(24,24,28,0.98);
    color: #e6e6eb;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 20px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: rgba(138,43,226,0.30);
}
QMenu::indicator:checked {
    background-color: #8a2be2;
    border-radius: 3px;
}
"""
