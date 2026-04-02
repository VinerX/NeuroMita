# styles/main_styles.py
from utils import render_qss

THEME = {
    "bg_root": "#1b1d22",
    "bg_window": "#17181d",
    "text": "#e6e6eb",
    "muted": "#9a9aa2",

    "panel_bg": "rgba(18,18,22,0.92)",
    "card_bg": "rgba(24,24,28,0.95)",
    "card_border": "rgba(255,255,255,0.08)",
    "border_soft": "rgba(255,255,255,0.08)",
    "outline": "rgba(255,255,255,0.06)",

    "accent": "#8a2be2",
    "accent_hover": "#9b47ea",
    "accent_pressed": "#7a1fda",
    "accent_border": "rgba(138,43,226,0.35)",

    "chip_bg": "rgba(255,255,255,0.06)",
    "chip_hover": "rgba(255,255,255,0.10)",
    "chip_pressed": "rgba(255,255,255,0.14)",

    "scroll_handle": "rgba(255,255,255,0.12)",

    "warn_bg": "rgba(255,120,120,0.08)",
    "warn_border": "rgba(255,120,120,0.25)",
    "warn_text": "#ffb4b4",

    "success": "#3da66e",
    "success_hover": "#49b57b",
    "success_pressed": "#349a69",

    "danger": "#d64545",
    "danger_hover": "#e25757",
    "danger_pressed": "#bf3838",

    "link": "#3498db",

    "btn_disabled_bg": "#4a4a4a",
    "btn_disabled_fg": "#666666",
}

def get_theme():
    return THEME.copy()

style_template = """
/* ========= Base ========= */
QWidget {
    background-color: {bg_root};
    color: {text};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 9pt;
    border-radius: 0px;
}
QMainWindow { background-color: {bg_window}; }
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
    background-color: rgba(12,12,16,0.92);
    border-radius: 10px;
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
    background-color: #3a3a3f;
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
    border: 1px solid {accent};
}

QPushButton:disabled {
    background-color: #3a3a3f;
    color: {muted};
    border: 1px solid {outline};
}

/* ========= Labels ========= */
QLabel { background-color: transparent; padding: 0px; }
QLabel#TokenCountLabel {
    font-size: 8pt;
    color: #b8b8c2;
    padding: 2px 6px;
    border-radius: 6px;
    background-color: {chip_bg};
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
    background-color: rgba(24,24,28,1);
}
QCheckBox::indicator:hover { border-color: {accent}; }
QCheckBox::indicator:checked {
    background-color: {accent};
    border: 1px solid #a270ff;
}
QCheckBox::indicator:checked:disabled {
    background-color: {accent};
    border: 1px solid #a270ff;
}
QCheckBox:disabled { color: {muted}; }
QCheckBox::indicator:disabled {
    border: 1px solid {outline};
    background: {chip_bg};
    image: none;
}

/* ========= Scrolls ========= */
QScrollArea { background-color: transparent; border: none; }
QScrollBar:vertical {
    border: none; background: transparent; width: 10px; margin: 0;
}
QScrollBar::handle:vertical {
    background: {scroll_handle};
    min-height: 26px; border-radius: 6px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.18); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

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

/* ========= Settings Sidebar ========= */
QWidget#SettingsSidebar {
    background-color: {card_bg};
    border-right: 1px solid {card_border};
}

/* ========= API Presets ========= */
QFrame#PresetsPanel {
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 12px;
}
QListWidget#PresetsList {
    background: {panel_bg};
    border: 1px solid {border_soft};
    border-radius: 10px;
    padding: 6px;
    color: {text};
    outline: 0;
}
QListWidget#PresetsList::item { padding: 6px 6px; color: {text}; }
QListWidget#PresetsList::item:hover { background: {chip_bg}; border-radius: 6px; }
QListWidget#PresetsList::item:selected { background: {chip_hover}; border-radius: 6px; color: #ffffff; }

QPushButton#AddPresetButton,
QPushButton#RemovePresetButton,
QPushButton#MoveUpButton,
QPushButton#MoveDownButton {
    background-color: {chip_bg};
    border: 1px solid {outline};
    color: {text};
    padding: 0px;
    min-width: 28px; min-height: 28px;
    border-radius: 8px;
}
QPushButton#AddPresetButton:hover,
QPushButton#RemovePresetButton:hover,
QPushButton#MoveUpButton:hover,
QPushButton#MoveDownButton:hover {
    background-color: {chip_hover};
}
QPushButton#AddPresetButton:pressed,
QPushButton#RemovePresetButton:pressed,
QPushButton#MoveUpButton:pressed,
QPushButton#MoveDownButton:pressed {
    background-color: {chip_pressed};
}
QPushButton#RemovePresetButton:disabled { color: {muted}; border-color: {outline}; }

/* ========= Chat widgets ========= */
QWidget#ChatInputContainer {
    background-color: {panel_bg};
    border: 1px solid {border_soft};
    border-radius: 12px;
}

QPushButton#GuideButtonSmall {
    background-color: {accent};
    color: #ffffff;
    border: 1px solid {accent_border};
    padding: 5px;
    border-radius: 8px;
}
QPushButton#GuideButtonSmall:hover { background-color: {accent_hover}; }
QPushButton#GuideButtonSmall:pressed { background-color: {accent_pressed}; }

QPushButton#ChatIconMini {
    background-color: {chip_bg};
    border: 0px; border-radius: 10px;
    padding: 3px;
}
QPushButton#ChatIconMini:hover { background-color: rgba(138,43,226,0.3); }
QPushButton#ChatIconMini:pressed { background-color: rgba(138,43,226,0.5); }

QPushButton#ChatSendButtonCircle {
    background-color: {accent};
    border: 0px; border-radius: 14px; padding: 5px;
}
QPushButton#ChatSendButtonCircle:hover { background-color: {accent_hover}; }
QPushButton#ChatSendButtonCircle:pressed { background-color: {accent_pressed}; }
QPushButton#ChatSendButtonCircle:disabled {
    background-color: {btn_disabled_bg}; color: {btn_disabled_fg};
}

QPushButton#ScrollToBottomButton {
    border:none; border-radius:17px; background-color:{accent};
}
QPushButton#ScrollToBottomButton:hover { background-color:{accent_hover}; }
QPushButton#ScrollToBottomButton:focus { outline:none; border:none; }

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
QProgressBar::chunk { background-color: {accent}; border-radius: 8px; }

/* ========= Disabled ========= */
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    background-color: rgba(14,14,18,0.85);
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

/* ========= Chat scroll area (widget-based) ========= */
QScrollArea#ChatScrollArea {
    background-color: {panel_bg};
    border: none;
    border-radius: 10px;
}
QScrollArea#ChatScrollArea::viewport {
    background-color: {panel_bg};
    border: none;
}
QWidget#ChatContainer {
    background-color: {panel_bg};
}
"""

def get_stylesheet(overrides: dict | None = None) -> str:
    theme = THEME.copy()
    if overrides:
        theme.update(overrides)
    return render_qss(style_template, theme)

