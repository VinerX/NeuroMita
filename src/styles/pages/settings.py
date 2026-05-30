from __future__ import annotations

SETTINGS_PAGE_QSS = r"""
/* ========= API Presets ========= */
QFrame#PresetsPanel {
    background-color: rgba({settings_panel_rgb}, 0.82);
    border: 1px solid rgba({accent_rgb}, 0.14);
    border-radius: 16px;
}
QListWidget#PresetsList {
    background: rgba({sandbox_bg_rgb}, 0.88);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 6px;
    color: {text};
    outline: 0;
}
QListWidget#PresetsList::item { padding: 6px 6px; color: {text}; }
QListWidget#PresetsList::item:hover {
    background: rgba({accent_rgb}, 0.10);
    border-radius: 8px;
}
QListWidget#PresetsList::item:selected {
    background: rgba({accent_rgb}, 0.18);
    border-radius: 8px;
    color: #ffffff;
}

QPushButton#AddPresetButton,
QPushButton#RemovePresetButton,
QPushButton#MoveUpButton,
QPushButton#MoveDownButton {
    background-color: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    color: {text};
    padding: 0px;
    min-width: 28px;
    min-height: 28px;
    border-radius: 8px;
}
QPushButton#AddPresetButton:hover,
QPushButton#RemovePresetButton:hover,
QPushButton#MoveUpButton:hover,
QPushButton#MoveDownButton:hover {
    background-color: rgba({accent_rgb}, 0.16);
    border: 1px solid rgba({accent_rgb}, 0.24);
}
QPushButton#AddPresetButton:pressed,
QPushButton#RemovePresetButton:pressed,
QPushButton#MoveUpButton:pressed,
QPushButton#MoveDownButton:pressed {
    background-color: rgba({accent_rgb}, 0.24);
}
QPushButton#RemovePresetButton:disabled {
    color: {muted};
    border-color: {outline};
}

/* ========= Settings Page ========= */
QWidget#SettingsPageRoot,
QWidget#SettingsRail,
QWidget#SettingsWorkspaceContent {
    background: transparent;
    border: none;
}

QFrame#SettingsWorkspacePanel,
QFrame#SettingsTabsCard,
QFrame#SettingsStatusRailCard,
QFrame#SettingsQuickActionsCard,
QFrame#SettingsNoteCard {
    background-color: rgba({settings_panel_rgb}, 0.94);
    border: 1px solid rgba({accent_rgb}, 0.14);
    border-radius: 16px;
}

QFrame#SettingsWorkspaceRootShell {
    background-color: rgba({sandbox_bg_rgb}, 0.98);
    border: none;
}

QFrame#SettingsWorkspaceHeader {
    background: transparent;
    border: none;
}

QFrame#SettingsWorkspacePanel {
    background-color: rgba({sandbox_bg_rgb}, 0.92);
}

QLabel#SettingsHeroIcon {
    background: transparent;
    border: none;
}

QLabel#SettingsHeroTitle {
    font-size: 18pt;
    font-weight: 800;
    color: {text};
}

QLabel#SettingsHeroSubtitle {
    color: {muted};
    font-size: 9pt;
}

QPushButton#SettingsHeaderButton,
QPushButton#SettingsHeaderPrimaryButton {
    padding: 10px 16px;
    border-radius: 12px;
    font-weight: 700;
}
QPushButton#SettingsHeaderButton {
    background-color: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    color: {text};
}
QPushButton#SettingsHeaderButton:hover {
    background-color: rgba({accent_rgb}, 0.12);
    border: 1px solid rgba({accent_rgb}, 0.24);
}
QPushButton#SettingsHeaderButton:pressed {
    background-color: rgba({accent_rgb}, 0.20);
}
QPushButton#SettingsHeaderPrimaryButton {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba({accent_rgb_alt}, 0.94),
        stop: 1 rgba({slider_progress_rgb}, 0.98)
    );
    border: 1px solid rgba({accent_rgb_alt}, 0.70);
    color: #ffffff;
}
QPushButton#SettingsHeaderPrimaryButton:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba({accent_rgb_alt}, 0.98),
        stop: 1 rgba({accent_rgb}, 0.98)
    );
}
QPushButton#SettingsHeaderPrimaryButton:pressed {
    background-color: rgba({slider_progress_rgb}, 0.90);
}

QWidget#SettingsRail {
    min-width: 308px;
}

QLabel#SettingsRailTitle,
QLabel#SettingsRailBrandTitle {
    color: {text};
    font-size: 11.5pt;
    font-weight: 800;
}

QLabel#SettingsRailLabel {
    color: {muted};
    font-size: 8.5pt;
    font-weight: 700;
    text-transform: uppercase;
}

QLabel#SettingsRailValue {
    color: {text};
    font-size: 10pt;
    font-weight: 700;
}

QLabel#SettingsRailBrandMeta,
QLabel#SettingsRailBrandHint,
QLabel#SettingsNoteText {
    color: {muted};
    font-size: 9pt;
}

QLabel#SettingsRailBrandState {
    color: #82e996;
    font-size: 9pt;
    font-weight: 800;
}

QLabel#SettingsRailBrandIcon {
    min-width: 64px;
    min-height: 64px;
    border-radius: 18px;
    background-color: rgba({accent_rgb}, 0.08);
    border: 1px solid rgba({accent_rgb}, 0.16);
}

QPushButton#SettingsQuickActionButton {
    background-color: rgba(255,255,255,0.035);
    color: {text};
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 10px 12px;
    text-align: left;
    font-weight: 700;
}
QPushButton#SettingsQuickActionButton:hover {
    background-color: rgba({accent_rgb}, 0.13);
    border: 1px solid rgba({accent_rgb}, 0.26);
}
QPushButton#SettingsQuickActionButton:pressed {
    background-color: rgba({accent_rgb}, 0.20);
}

QScrollArea#SettingsWorkspaceScroll,
QScrollArea#SettingsWorkspaceScroll > QWidget,
QScrollArea#SettingsWorkspaceScroll > QWidget > QWidget,
QScrollArea#SettingsTabsScroll,
QScrollArea#SettingsTabsScroll > QWidget,
QScrollArea#SettingsTabsScroll > QWidget > QWidget,
QScrollArea#SettingsSectionPageScroll,
QScrollArea#SettingsSectionPageScroll > QWidget,
QScrollArea#SettingsSectionPageScroll > QWidget > QWidget,
QStackedWidget#SettingsWorkspaceStack,
QWidget#SettingsTabsHost,
QFrame#SettingsSectionPage,
QWidget#SettingsSectionPageContent {
    background: transparent;
    border: none;
}

QFrame#SettingsSectionPageHeader {
    background-color: rgba({settings_panel_rgb}, 0.94);
    border: 1px solid rgba({accent_rgb}, 0.18);
    border-radius: 16px;
}

QLabel#SettingsSectionPageTitle {
    color: {text};
    font-size: 15pt;
    font-weight: 800;
}

QFrame#SettingsSectionPageBody {
    background: transparent;
    border: none;
}

QFrame#SettingsSectionCard {
    background-color: rgba({settings_panel_rgb}, 0.94);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 22px;
}
QFrame#SettingsSectionCard[expanded="true"] {
    background-color: rgba({settings_panel_rgb}, 0.98);
    border: 1px solid rgba({accent_rgb}, 0.24);
}

QFrame#SettingsSectionHeader {
    background: transparent;
    border-radius: 22px;
}
QFrame#SettingsSectionHeader[expanded="true"] {
    background-color: rgba(255,255,255,0.015);
}

QLabel#SettingsSectionIcon {
    background-color: rgba({accent_rgb}, 0.10);
    border: 1px solid rgba({accent_rgb}, 0.22);
    border-radius: 12px;
}

QLabel#SettingsSectionTitle {
    color: {text};
    font-size: 12pt;
    font-weight: 800;
}

QLabel#SettingsSectionSubtitle {
    color: {muted};
    font-size: 9pt;
}

QLabel#SettingsSectionBadge {
    color: #f7dceb;
    background-color: rgba({accent_rgb}, 0.10);
    border: 1px solid rgba({accent_rgb}, 0.22);
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 8.5pt;
    font-weight: 800;
}

QFrame#SettingsSectionBody {
    background: transparent;
    border-top: 1px solid rgba(255,255,255,0.06);
}

QFrame#SettingsSectionBodyHost {
    background: transparent;
}

/* ========= Inner Groups / Rows ========= */
QWidget#SettingsSubsectionHeader {
    background: transparent;
}

QLabel#SettingsSubsectionTitle {
    color: #ffe8f4;
    font-size: 10pt;
    font-weight: 800;
}

QFrame#SettingsSubsectionLine {
    background-color: rgba(255,255,255,0.08);
    border-radius: 1px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleSection {
    background-color: rgba({settings_panel_rgb}, 0.70);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleHeader {
    background: transparent;
    border: none;
    border-radius: 0px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleHeader:hover {
    background: transparent;
    border: none;
}

QWidget#SettingsPageRoot QWidget#InnerCollapsibleHeader {
    background: transparent;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding-bottom: 6px;
}

QWidget#SettingsPageRoot QLabel#CollapsibleArrow,
QWidget#SettingsPageRoot QLabel#CollapsibleTitle {
    color: {text};
    font-weight: 800;
    padding: 8px 2px 4px 2px;
}

QWidget#SettingsPageRoot QLabel#CollapsibleArrow {
    max-width: 0px;
    min-width: 0px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleContent {
    background: transparent;
    padding-top: 4px;
}

QWidget#SettingsPageRoot QWidget#SettingRow {
    background: transparent;
    border: none;
    border-radius: 0px;
    padding: 2px 0px;
}

QWidget#SettingsPageRoot QLabel#SeparatorLabel {
    margin-top: 10px;
    padding: 8px 2px 6px 2px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    font-weight: 800;
    color: {text};
}

QWidget#SettingsPageRoot QLineEdit,
QWidget#SettingsPageRoot QTextEdit,
QWidget#SettingsPageRoot QPlainTextEdit,
QWidget#SettingsPageRoot QComboBox,
QWidget#SettingsPageRoot QSpinBox,
QWidget#SettingsPageRoot QDoubleSpinBox,
QWidget#SettingsPageRoot QListWidget,
QWidget#SettingsPageRoot QTreeWidget {
    background-color: rgba({settings_panel_rgb}, 0.85);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    color: {text};
    padding: 7px 10px;
    selection-background-color: rgba({accent_rgb}, 0.30);
}

QWidget#SettingsPageRoot QLineEdit:focus,
QWidget#SettingsPageRoot QTextEdit:focus,
QWidget#SettingsPageRoot QPlainTextEdit:focus,
QWidget#SettingsPageRoot QComboBox:focus,
QWidget#SettingsPageRoot QSpinBox:focus,
QWidget#SettingsPageRoot QDoubleSpinBox:focus,
QWidget#SettingsPageRoot QListWidget:focus,
QWidget#SettingsPageRoot QTreeWidget:focus {
    border: 1px solid rgba({accent_rgb}, 0.24);
}

QWidget#SettingsPageRoot QComboBox::drop-down {
    border: none;
    width: 26px;
}

QWidget#SettingsPageRoot QCheckBox {
    background: transparent;
    border: none;
    color: {text};
    spacing: 8px;
    padding: 2px 0;
}

QWidget#SettingsPageRoot QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: none;
    background-color: rgba(255,255,255,0.08);
}

QWidget#SettingsPageRoot QCheckBox::indicator:hover {
    background-color: rgba({accent_rgb}, 0.14);
}

QWidget#SettingsPageRoot QCheckBox::indicator:checked {
    border: none;
    background-color: {accent_alt};
}

QWidget#SettingsPageRoot QCheckBox::indicator:disabled {
    border: none;
    background-color: rgba(255,255,255,0.04);
}

QWidget#SettingsPageRoot QPushButton#SecondaryButton,
QWidget#SettingsPageRoot QPushButton#CancelButton {
    border-radius: 10px;
}
"""
