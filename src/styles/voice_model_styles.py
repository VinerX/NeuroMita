# styles/voice_model_styles.py
from styles.main_styles import get_stylesheet as get_main_stylesheet, get_theme
from utils import render_qss

VOICE_TEMPLATE = """
/* ===== Voice Models window — tweaks on top of main theme ===== */

/* Splitter */
QSplitter::handle {
    background: {outline};
    width: 4px;
    border-radius: 2px;
}

/* Top description card */
QFrame#DescriptionFrame {
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 6px;  /* Уменьшено с 12px */
}

/* Model profile card (right) */
QFrame#ModelPanel {
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 6px;  /* Уменьшено с 12px */
}

/* Компактные настройки */
QFrame#SettingRow {
    margin: 0px;
}

QFrame#SettingLabel {
    background-color: {chip_bg};
    border: 1px solid {border_soft};
    border-radius: 4px;  /* Маленькое скругление */
    padding: 0px 10px;   /* Убран вертикальный padding */
    min-height: 26px;    /* Единая высота */
    max-height: 26px;
}

QFrame#SettingWidget {
    background-color: transparent;
    padding: 0px;
    min-height: 28px;    /* Та же высота */
    max-height: 28px;
}

/* Инпуты - компактные */
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

QFrame#SettingWidget QLineEdit[dirty="true"],
QFrame#SettingWidget QComboBox[dirty="true"] {
    border: 1px solid rgba(230, 200, 80, 0.85);
    background-color: rgba(230, 200, 80, 0.08);
}

QFrame#ModelPanel QPushButton#PrimaryButton[dirty="true"] {
    border: 1px solid rgba(230, 200, 80, 0.85);
}

/* Чекбоксы */
QFrame#SettingWidget QCheckBox { 
    min-height: 28px;
    max-height: 28px;
    padding-left: 6px;
}

/* Role labels */
QLabel#TitleLabel {
    color: {text};
    font-weight: 700;
    font-size: 12pt;     /* Базовый размер заголовков */
}
/* Увеличиваем заголовок модели только внутри правой панели */
QFrame#ModelPanel QLabel#TitleLabel {
    font-size: 14pt;     /* +2pt относительно базового */
}
QLabel#Subtle { color: {muted}; }
QLabel#Warn {
    color: {warn_text};
    font-weight: 700;
}
QLabel#RTX {
    font-size: 7pt;
    font-weight: 700;
}
QLabel#Link {
    color: {link};
    font-weight: 600;
    text-decoration: underline;
}

/* Tags (languages, chips) */
QLabel#Tag {
    background-color: {chip_bg};
    color: {text};
    border: 1px solid {outline};
    border-radius: 4px;          /* Маленькое скругление */
    padding: 1px 6px;            /* Чуть компактнее по вертикали */
    font-size: 8pt;
    min-height: 20px;            /* Единая компактная высота */
    max-height: 20px;
}

/* Свёрнутый “+N” для длинных списков языков */
QLabel#TagMore {
    background-color: transparent;
    color: {muted};
    border: 1px dashed {outline};
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 8pt;
    font-weight: 600;            /* Чуть активнее визуально */
}
QLabel#TagMore:hover {
    color: {text};
    border-color: {border_soft};
}

/* Compact section title */
QLabel#SectionLabel {
    color: #f5f5f7;
    font-weight: 600;
    margin-top: 2px;
}

/* Chips with states */
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
}

/* Buttons - НЕ ТРОГАЕМ стили главных кнопок, только для этого окна */
QFrame#ModelPanel QPushButton#PrimaryButton,
QFrame#ModelPanel QPushButton#SecondaryButton,
QFrame#ModelPanel QPushButton#DangerButton {
    border-radius: 4px;  /* Только для кнопок внутри панели модели */
    min-height: 26px;
}
/* Установка — компактнее по высоте */
QFrame#ModelPanel QPushButton#SecondaryButton {
    min-height: 22px;
    padding: 2px 10px;
}
/* Удаление — тоже компактнее по высоте */
QFrame#ModelPanel QPushButton#DangerButton {
    min-height: 22px;
    padding: 2px 10px;
}

/* Models list (left) */
QListWidget {
    background: {panel_bg};
    border: 1px solid {border_soft};
    border-radius: 6px;  /* Умеренное скругление */
    padding: 4px;
    outline: 0;
}
QListWidget::item {
    padding: 6px 8px;
    border-radius: 3px;  /* Маленькое скругление */
}
QListWidget::item:hover { background: {chip_bg}; }
QListWidget::item:selected {
    background: {chip_hover};
    color: #ffffff;
}

/* Selected item (active) */
QListView::item:selected:active { background: {chip_hover}; }

/* ===== Remove focus outlines globally where possible ===== */
QWidget:focus { outline: none; }
QAbstractItemView:focus { outline: none; }
QListView:focus, QTreeView:focus, QTableView:focus, QListWidget:focus { outline: none; }
QScrollArea:focus { outline: none; }
QTabBar::tab:focus { outline: none; }
QComboBox:focus { outline: none; }
QLineEdit:focus { outline: none; }
QPushButton:focus { outline: none; }

/* Minimal Models list */
QListWidget {
    background: {panel_bg};
    border: 1px solid {border_soft};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}

QListWidget::item {
    border: none;
    padding: 0px;
    margin: 1px 0px;
    border-radius: 4px;
    background: transparent;
}

QListWidget::item:hover {
    background: rgba(138, 43, 226, 0.08);
}

QListWidget::item:selected {
    background: rgba(138, 43, 226, 0.15);
}

"""

def get_stylesheet(overrides: dict | None = None) -> str:
    theme = get_theme()
    if overrides:
        theme.update(overrides)

    base_qss = get_main_stylesheet(overrides)
    voice_qss = render_qss(VOICE_TEMPLATE, theme)

    return base_qss + "\n\n" + voice_qss