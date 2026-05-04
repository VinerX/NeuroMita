from __future__ import annotations

SETTINGS_PAGE_QSS = r"""
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

QWidget#SettingsPageRoot,
QWidget#SettingsRail {
    background: transparent;
    border: none;
}

QFrame#SettingsHeroCard {
    background-color: rgba(29, 12, 34, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.22);
    border-radius: 20px;
}

QLabel#SettingsHeroTitle {
    font-size: 18pt;
    font-weight: 800;
    color: #fff1f9;
}

QLabel#SettingsHeroSubtitle {
    color: #c5a8bf;
    font-size: 9pt;
}

QFrame#SettingsTabsCard,
QFrame#SettingsStatusRailCard,
QFrame#SettingsQuickActionsCard,
QFrame#SettingsOverviewCard {
    background-color: rgba(24, 10, 32, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.18);
    border-radius: 22px;
}

QWidget#SettingsRail {
    min-width: 300px;
}

QLabel#SettingsRailTitle,
QLabel#SettingsOverviewTitle,
QLabel#SettingsRailBrandTitle {
    color: #fff1f9;
    font-size: 12pt;
    font-weight: 800;
}

QLabel#SettingsRailLabel {
    color: #c39fb8;
    font-size: 8.5pt;
    font-weight: 700;
    text-transform: uppercase;
}

QLabel#SettingsRailValue {
    color: #fff1f9;
    font-size: 10.5pt;
    font-weight: 700;
}

QLabel#SettingsRailBrandHint,
QLabel#SettingsRailBrandMeta,
QLabel#SettingsOverviewText {
    color: #c3a4ba;
    font-size: 9pt;
}

QLabel#SettingsRailBrandState {
    color: #89f7b2;
    font-size: 9pt;
    font-weight: 700;
}

QLabel#SettingsRailBrandIcon {
    min-width: 64px;
    min-height: 64px;
    border-radius: 18px;
    background-color: rgba(255, 92, 158, 0.10);
    border: 1px solid rgba(255, 92, 158, 0.18);
}

QWidget#SettingsOverviewPage {
    background: transparent;
}

QPushButton#SettingsQuickActionButton,
QPushButton#SettingsOverviewShortcut {
    background-color: rgba(255, 255, 255, 0.04);
    color: #fff1f9;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    padding: 10px 12px;
    text-align: left;
    font-weight: 700;
}

QPushButton#SettingsQuickActionButton:hover,
QPushButton#SettingsOverviewShortcut:hover {
    background-color: rgba(255, 92, 158, 0.16);
    border: 1px solid rgba(255, 92, 158, 0.28);
}

QPushButton#SettingsQuickActionButton:pressed,
QPushButton#SettingsOverviewShortcut:pressed {
    background-color: rgba(255, 92, 158, 0.24);
}

QWidget#SettingsPageOverlay QStackedWidget,
QWidget#SettingsPageOverlay QStackedWidget > QWidget,
QWidget#SettingsPageOverlay QScrollArea,
QWidget#SettingsPageOverlay QScrollArea > QWidget,
QWidget#SettingsPageOverlay QScrollArea > QWidget > QWidget,
QWidget#SettingsPageOverlay QAbstractScrollArea,
QWidget#SettingsPageOverlay QAbstractScrollArea > QWidget,
QWidget#SettingsPageOverlay QAbstractScrollArea > QWidget > QWidget,
QWidget[objectName^="ContentWidget_"],
QScrollArea[objectName^="ScrollArea_"],
QScrollArea[objectName^="ScrollArea_"] > QWidget,
QScrollArea[objectName^="ScrollArea_"] > QWidget > QWidget {
    background: transparent;
    border: none;
}

QWidget[objectName^="ContentWidget_"] QWidget,
QWidget#SettingsPageOverlay QStackedWidget QWidget {
    background-color: transparent;
}

QWidget[objectName^="ContentWidget_"] QLineEdit,
QWidget[objectName^="ContentWidget_"] QTextEdit,
QWidget[objectName^="ContentWidget_"] QPlainTextEdit,
QWidget[objectName^="ContentWidget_"] QComboBox,
QWidget[objectName^="ContentWidget_"] QPushButton,
QWidget[objectName^="ContentWidget_"] QSpinBox,
QWidget[objectName^="ContentWidget_"] QDoubleSpinBox,
QWidget[objectName^="ContentWidget_"] QListWidget,
QWidget[objectName^="ContentWidget_"] QTreeWidget,
QWidget#SettingsPageOverlay QStackedWidget QLineEdit,
QWidget#SettingsPageOverlay QStackedWidget QTextEdit,
QWidget#SettingsPageOverlay QStackedWidget QPlainTextEdit,
QWidget#SettingsPageOverlay QStackedWidget QComboBox,
QWidget#SettingsPageOverlay QStackedWidget QPushButton,
QWidget#SettingsPageOverlay QStackedWidget QSpinBox,
QWidget#SettingsPageOverlay QStackedWidget QDoubleSpinBox,
QWidget#SettingsPageOverlay QStackedWidget QListWidget,
QWidget#SettingsPageOverlay QStackedWidget QTreeWidget {
    background-color: {panel_bg};
}

QWidget[objectName^="ContentWidget_"] QPushButton,
QWidget#SettingsPageOverlay QStackedWidget QPushButton {
    background-color: {accent};
}

QWidget#CollapsibleHeader {
    background-color: {chip_bg};
}
"""
