from styles.theme import get_theme
from utils import render_qss

_QSS = r"""
QAbstractItemView#CompletionPopup {
    background-color: {control_bg};
    color: {text};
    font-family: "Segoe UI Variable", "Segoe UI", Arial, sans-serif;
    font-size: 9pt;
    border: 1px solid {border_soft};
    border-radius: 8px;
    outline: none;
    selection-background-color: {accent};
    selection-color: #ffffff;
}
QAbstractItemView#CompletionPopup::item {
    padding: 5px 8px;
    min-height: 20px;
    border-radius: 4px;
}
QAbstractItemView#CompletionPopup::item:selected {
    background-color: {accent};
    color: #ffffff;
}
QScrollBar:vertical {
    background: {control_bg};
    width: 8px;
    margin: 2px 0;
    border: none;
}
QScrollBar::handle:vertical {
    background: {muted};
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
"""


def get_completion_popup_stylesheet() -> str:
    return render_qss(_QSS, get_theme())
