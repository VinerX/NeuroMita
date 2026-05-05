from __future__ import annotations

COMPONENTS_QSS = r"""
/* ========= Loading / Progress ========= */
QDialog#LoadingDialog {
    border: 1px solid {border_soft};
    border-radius: 12px;
    background-color: {card_bg};
}
QProgressBar {
    border: 1px solid {border_soft};
    border-radius: 10px;
    text-align: center;
    background-color: {chip_bg};
    color: {text};
    height: 20px;
    padding: 2px;
}
QProgressBar::chunk { background-color: {slider_progress}; border-radius: 8px; }

/* ========= Disabled ========= */
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    background-color: rgba({sandbox_bg_rgb}, 0.85);
    color: #8d8d96;
    border: 1px solid {outline};
}
QLabel:disabled { color: #7d7d86; }

/* ========= Overlay internals ========= */
QWidget#SettingsOverlay QStackedWidget > QWidget > QWidget { background-color: transparent; }

/* ========= ToolTip ========= */
QToolTip {
    color: #ffffff;
    background-color: {card_bg};
    border: 1px solid {card_border};
    padding: 6px 10px;
    border-radius: 8px;
}

/* ========== Danger Zone =========== */
QPushButton#SecondaryButton[dangerHover="true"] {
    /* базовый стиль наследуется от SecondaryButton */
}
QPushButton#SecondaryButton[dangerHover="true"]:hover {
    background-color: rgba(214, 69, 69, 0.16);   /* мягкое заливание */
    border: 1px solid rgba(214, 69, 69, 0.45);
}
QPushButton#SecondaryButton[dangerHover="true"]:pressed {
    background-color: rgba(214, 69, 69, 0.26);   /* чуть сильнее при нажатии */
}

/* ========= Tables ========= */
QTableView {
    background-color: {panel_bg};
    alternate-background-color: rgba(255,255,255,0.03);
    color: {text};

    border: 1px solid {border_soft};
    gridline-color: {outline};

    selection-background-color: rgba({accent_rgb}, 0.25);
    selection-color: #ffffff;

    outline: 0;
}

QTableView::item {
    padding: 6px 8px;
    border: none;
}

QTableView::item:hover {
    background-color: rgba(255,255,255,0.06);
}

QTableView::item:selected:active {
    background-color: rgba({accent_rgb}, 0.35);
    color: #ffffff;
}

QTableView::item:selected:!active {
    background-color: rgba({accent_rgb}, 0.22);
    color: #ffffff;
}

QHeaderView::section {
    background-color: {chip_bg};
    color: {text};

    padding: 6px 8px;
    font-weight: 700;

    border: none;
    border-bottom: 1px solid {border_soft};
    border-right: 1px solid {outline};
}

QHeaderView::section:horizontal:last {
    border-right: none;
}

QTableCornerButton::section {
    background-color: {chip_bg};
    border: none;
    border-bottom: 1px solid {border_soft};
    border-right: 1px solid {outline};
}

/* ========= Tabs ========= */
QTabWidget::pane {
    border: 1px solid {border_soft};
    background-color: {card_bg};
    border-radius: 12px;
    top: -1px; /* чтобы стык с табами был аккуратнее */
}

QTabBar {
    background: transparent;
}

QTabBar::tab {
    background-color: {chip_bg};
    color: {text};
    border: 1px solid {outline};
    padding: 8px 12px;
    margin-right: 6px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}

QTabBar::tab:hover {
    background-color: {chip_hover};
    border: 1px solid {border_soft};
}

QTabBar::tab:selected {
    background-color: {panel_bg};
    border: 1px solid {border_soft};
    border-bottom-color: {panel_bg}; /* визуально “сливаем” с pane */
    font-weight: 700;
}

QTabBar::tab:disabled {
    color: {muted};
    background-color: rgba(255,255,255,0.03);
    border: 1px solid {outline};
}
"""
