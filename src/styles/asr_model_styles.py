# src/styles/asr_model_styles.py
from styles.main_styles import get_stylesheet as get_main_stylesheet, get_theme
from utils import render_qss

ASR_TEMPLATE = """
QSplitter::handle {
    background: {outline};
    width: 4px;
    border-radius: 2px;
}

QListWidget#ModelsList {
    background: {panel_bg};
    border: 1px solid {border_soft};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}
QListWidget#ModelsList::item {
    border: none;
    padding: 0px;
    margin: 1px 0px;
    border-radius: 4px;
    background: transparent;
}
QListWidget#ModelsList::item:hover { background: rgba(138, 43, 226, 0.08); }
QListWidget#ModelsList::item:selected { background: rgba(138, 43, 226, 0.15); }

QLineEdit#SearchBox { border-radius: 10px; }

QFrame#ModelPanel {
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 6px;
}
QLabel#TitleLabel {
    color: {text};
    font-weight: 700;
    font-size: 14pt;
}
QLabel#Subtle { color: {muted}; }
QLabel#Warn { color: {warn_text}; font-weight: 700; }

QLabel#ChipOk {
    background-color: rgba(61,166,110,0.16);
    border: 1px solid rgba(61,166,110,0.45);
    color: #9be2bc;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 8pt;
    font-weight: 600;
}
QLabel#ChipWarn {
    background-color: {warn_bg};
    border: 1px solid {warn_border};
    color: {warn_text};
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 8pt;
    font-weight: 600;
}
QLabel#ChipInfo {
    background-color: {chip_bg};
    border: 1px solid {outline};
    color: {text};
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 8pt;
    font-weight: 600;
}

QLabel#Tag {
    background-color: {chip_bg};
    color: {text};
    border: 1px solid {outline};
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 8pt;
    min-height: 20px;
    max-height: 20px;
}
QLabel#TagMore {
    background-color: transparent;
    color: {muted};
    border: 1px dashed {outline};
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 8pt;
    font-weight: 600;
}
QLabel#TagMore:hover {
    color: {text};
    border-color: {border_soft};
}

/* Detail tabs (chrome-like) */
QTabWidget#DetailTabs::pane {
    border: 1px solid {card_border};
    border-radius: 6px;
    background: {card_bg};
    top: -1px;
}

QTabBar::tab {
    background: transparent;
    color: {muted};
    border: 1px solid transparent;
    border-bottom: 1px solid transparent;
    padding: 6px 10px;
    padding-right: 30px;          /* reserve space for badge */
    margin-right: 6px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    font-weight: 600;
}
QTabBar::tab:hover { color: {text}; }
QTabBar::tab:selected {
    color: {text};
    background: {card_bg};
    border: 1px solid {card_border};
    border-bottom: 1px solid {card_bg};
}

/* Dependencies badge on tab (circle with number) */
QLabel#DepsBadge {
    border-radius: 8px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    font-size: 8pt;
    font-weight: 800;
    color: #ffffff;
    qproperty-alignment: AlignCenter;
}
QLabel#DepsBadge[state="ok"] { background: rgba(61,166,110,1); }
QLabel#DepsBadge[state="warn"] { background: rgba(214,69,69,1); }

/* Compact settings rows */
QFrame#SettingRow { margin: 0px; }
QFrame#SettingLabel {
    background-color: {chip_bg};
    border: 1px solid {border_soft};
    border-radius: 4px;
    padding: 0px 10px;
    min-height: 26px;
    max-height: 26px;
}
QFrame#SettingWidget {
    background-color: transparent;
    padding: 0px;
    min-height: 28px;
    max-height: 28px;
}
QFrame#SettingWidget QLineEdit,
QFrame#SettingWidget QComboBox {
    min-height: 26px;
    max-height: 26px;
    padding: 0px 8px;
    margin: 0px;
    border-radius: 4px;
    font-size: 9pt;
}
QFrame#SettingWidget QComboBox::drop-down {
    width: 20px;
    border: none;
    padding: 0px;
    margin: 0px;
}
QFrame#SettingWidget QCheckBox {
    min-height: 28px;
    max-height: 28px;
    padding-left: 6px;
}

QFrame#DepRow {
    background-color: {panel_bg};
    border: 1px solid {border_soft};
    border-radius: 6px;
}

QPushButton#InstallButton {
    border-radius: 4px;
    min-height: 22px;
    padding: 2px 10px;
}
"""

def get_asr_stylesheet(overrides: dict | None = None) -> str:
    theme = get_theme()
    if overrides:
        theme.update(overrides)

    base_qss = get_main_stylesheet(overrides)
    asr_qss = render_qss(ASR_TEMPLATE, theme)
    return base_qss + "\n\n" + asr_qss