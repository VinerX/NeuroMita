# src/styles/asr_model_styles.py
from styles.main_styles import get_stylesheet as get_main_stylesheet, get_theme
from utils import render_qss

ASR_TEMPLATE = """
/* ===== ASR Glossary Window ===== */

/* Splitter */
QSplitter::handle {
    background: {outline};
    width: 2px;
}

/* List Widget (Left) */
QListWidget {
    background: {panel_bg};
    border: none;
    outline: 0;
    padding: 6px;
}

QListWidget::item {
    background: transparent;
    border-radius: 6px;
    padding: 2px; 
    margin-bottom: 4px;
    border: 1px solid transparent;
}

QListWidget::item:hover {
    background: {chip_bg};
}

QListWidget::item:selected {
    background: {chip_hover};
    border: 1px solid {accent_border};
}

/* Right Panel */
QFrame#DetailPanel {
    background-color: {card_bg};
    border-left: 1px solid {card_border};
}

/* Settings Row - Clean (No underlines) */
QFrame#SettingRow {
    background-color: transparent;
    margin-bottom: 6px;
    padding-bottom: 0px;
    border: none;
}

QLabel#SettingLabel {
    color: {text};
    font-size: 9pt;
    font-weight: 500;
}

/* Inputs */
QLineEdit, QComboBox {
    background-color: {panel_bg};
    border: 1px solid {border_soft};
    border-radius: 6px;
    padding: 4px 10px;
    min-height: 28px;
    font-size: 9pt;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid {accent};
}

QCheckBox {
    spacing: 8px;
}

/* Chips / Status */
QLabel#StatusChip {
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 8pt;
    font-weight: 600;
}

/* Header */
QLabel#ModelTitle {
    font-size: 16pt;
    font-weight: 700;
    color: {text};
}

/* Dependencies Area */
QFrame#DepsPanel {
    background-color: {chip_bg}; 
    border-radius: 8px;
    border: 1px solid {outline};
}

/* Dependency Item (Chip) */
QFrame#DepChip {
    background-color: {panel_bg};
    border: 1px solid {border_soft};
    border-radius: 6px;
}
"""

def get_asr_stylesheet(overrides: dict | None = None) -> str:
    theme = get_theme()
    if overrides:
        theme.update(overrides)

    base_qss = get_main_stylesheet(overrides)
    asr_qss = render_qss(ASR_TEMPLATE, theme)

    return base_qss + "\n\n" + asr_qss