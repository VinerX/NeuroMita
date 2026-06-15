from __future__ import annotations

BASE_QSS = r"""
/* ========= Base ========= */
QWidget {
    background-color: {bg_root};
    color: {text};
    font-family: "Segoe UI Variable", "Segoe UI", Arial, sans-serif;
    font-size: 9pt;
    border-radius: 0px;
}
QMainWindow { background-color: {bg_window}; }
QWidget#LauncherRoot {
    background-color: {app_bg};
}
QDialog { background-color: {bg_root}; }
QFrame { border: none; background: transparent; }

/* ========= Inputs ========= */
QTextEdit, QLineEdit {
    background-color: {panel_bg};
    color: {text};
    border: 1px solid {border_soft};
    padding: 6px 10px;
    border-radius: 10px;
    selection-background-color: {accent};
    selection-color: #ffffff;
    min-height: 22px;
}
QTextEdit:focus, QLineEdit:focus {
    border: 1px solid {accent};
    background-color: {panel_bg};
    outline: none;
}
QTextEdit#DebugWindow {
    font-family: "Consolas", "Courier New", monospace;
    font-size: 8pt;
    min-height: 80px;
    background-color: rgba({sandbox_bg_rgb}, 0.92);
    border-radius: 10px;
}

/* ========= SpinBox ========= */
QSpinBox, QDoubleSpinBox {
    background-color: {panel_bg};
    color: {text};
    border: 1px solid {border_soft};
    border-radius: 4px;
    padding: 2px 6px;
    min-height: 22px;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid {accent};
}
QSpinBox:disabled, QDoubleSpinBox:disabled {
    background-color: rgba({sandbox_bg_rgb}, 0.85);
    color: #8d8d96;
}

/* ========= ComboBox ========= */
QComboBox {
    background-color: {panel_bg};
    color: {text};
    border: 1px solid {border_soft};
    padding: 4px 10px;
    min-height: 22px;
    border-radius: 10px;
}
QComboBox:focus, QComboBox:on { border: 1px solid {accent}; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {border_soft};
    margin-left: 6px;
}
QComboBox QAbstractItemView {
    background-color: {panel_bg};
    border: 1px solid {accent};
    selection-background-color: {accent};
    selection-color: #ffffff;
    color: {text};
    padding: 6px;
    border-radius: 8px;
}

/* ========= Buttons ========= */
QPushButton {
    background-color: {accent};
    color: #ffffff;
    border: 1px solid {accent_border};
    padding: 7px 14px;
    font-weight: 600;
    border-radius: 10px;
}
QPushButton:hover { background-color: {accent_hover}; }
QPushButton:pressed { background-color: {accent_pressed}; }
QPushButton:disabled {
    background-color: {btn_disabled_bg};
    color: {muted};
    border: 1px solid {outline};
}
QPushButton#CancelButton {
    background-color: {danger};
    border: 1px solid rgba(214,69,69,0.35);
}
QPushButton#CancelButton:hover { background-color: {danger_hover}; }
QPushButton#CancelButton:pressed { background-color: {danger_pressed}; }
QPushButton#SecondaryButton {
    background-color: {chip_bg};
    color: {text};
    border: 1px solid {outline};
}
/* Compact buttons (for tight rows like History & cleanup) */
QPushButton[compact="true"] {
    padding: 4px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}
QPushButton#SecondaryButton:hover { background-color: {chip_hover}; }
QPushButton#SecondaryButton:pressed { background-color: {chip_pressed}; }

QPushButton#DangerButton {
    background-color: {danger};
    color: #ffffff;
    border: 1px solid rgba(214,69,69,0.35);
}
QPushButton#DangerButton:hover { background-color: {danger_hover}; }
QPushButton#DangerButton:pressed { background-color: {danger_pressed}; }

QPushButton:focus {
    outline: none;
}

QPushButton:disabled {
    background-color: {btn_disabled_bg};
    color: {muted};
    border: 1px solid {outline};
}

/* ========= Labels ========= */
QLabel { background-color: transparent; padding: 0px; }
QLabel#TokenCountLabel {
    font-size: 8pt;
    color: {muted};
    padding: 0 4px;
    background: transparent;
    border: none;
}
QLabel#SeparatorLabel {
    margin-top: 8px;
    padding: 6px 0;
    border-bottom: 1px solid {border_soft};
    font-weight: 700;
    color: #f5f5f7;
}
QLabel#WarningIcon { color: #ffcc00; }
QLabel#LinkLabel { color: {link}; }

QFrame#SeparatorH {
    background-color: {border_soft};
    max-height: 1px;
    border-radius: 1px;
    margin: 0 10px;
}

#TritonWarningLabel {
    background-color: {warn_bg};
    color: {warn_text};
    font-weight: 600;
    padding: 6px 8px;
    border: 1px solid {warn_border};
    border-radius: 10px;
}

/* ========= CheckBox ========= */
QCheckBox { spacing: 8px; color: {text}; padding: 2px 0; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid rgba(255,255,255,0.18);
    background-color: rgba({sidebar_panel_rgb}, 0.96);
}
QCheckBox::indicator:hover { border-color: {accent}; }
QCheckBox::indicator:checked {
    background-color: {accent};
    border: 1px solid {accent_alt};
}
QCheckBox::indicator:checked:disabled {
    background-color: {accent};
    border: 1px solid {accent_alt};
}
QCheckBox:disabled { color: {muted}; }
QCheckBox::indicator:disabled {
    border: 1px solid {outline};
    background: {chip_bg};
    image: none;
}

/* ========= Scrolls ========= */
QScrollArea {
    background-color: transparent;
    border: none;
}

/* общий сброс */
QScrollBar {
    background: transparent;
}

/* Vertical */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: {scroll_handle};
    min-height: 26px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: rgba({accent_rgb}, 0.34);
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

/* Horizontal */
QScrollBar:horizontal {
    border: none;
    background: transparent;
    height: 10px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: {scroll_handle};
    min-width: 26px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba({accent_rgb}, 0.34);
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
/* ========= Collapsible ========= */
QWidget#CollapsibleHeader {
    background-color: {chip_bg};
    border-radius: 10px;
}
QWidget#CollapsibleHeader:hover { background-color: {chip_hover}; }
QWidget#InnerCollapsibleHeader {
    background: transparent;
    border-bottom: 1px solid {border_soft};
    padding-bottom: 4px;
}
QLabel#CollapsibleArrow, QLabel#CollapsibleTitle {
    font-weight: 700; color: #f5f5f7; padding: 3px;
}
QWidget#CollapsibleContent { background-color: transparent; padding-top: 6px; }
QWidget#CollapsibleSection { background-color: transparent; background: transparent; }
QWidget#SettingsBodyWidget { background-color: transparent; background: transparent; }
QWidget#SettingRow { background-color: transparent; background: transparent; }
"""
