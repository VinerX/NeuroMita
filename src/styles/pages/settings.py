from __future__ import annotations

SETTINGS_PAGE_QSS = r"""
QWidget#CharacterSettingsWorkspace, QWidget#CharacterSettingsWorkspace QLabel,
QWidget#CharacterSettingsWorkspace QLineEdit, QWidget#CharacterSettingsWorkspace QComboBox,
QWidget#CharacterSettingsWorkspace QPushButton, QWidget#CharacterSettingsWorkspace QListWidget,
QWidget#CharacterSettingsWorkspace QTabBar {
    font-family: "Segoe UI"; letter-spacing: 0px;
}
QLabel#CharacterSettingsTitle { font-size: 22px; font-weight: 700; }
QWidget#CharacterSettingsWorkspace QLabel#SeparatorLabel { color: {muted}; font-weight: 400; }
QFrame#CharacterLibrary, QFrame#CharacterDetail {
    background: {settings_panel_bg}; border: 1px solid {panel_border}; border-radius: 12px;
}
QFrame#CharacterSection {
    background: {settings_panel_bg}; border: 1px solid {panel_border}; border-radius: 10px;
}
QWidget#CharacterSettingsWorkspace QWidget#CollapsibleSection,
QWidget#CharacterSettingsWorkspace QWidget#CollapsibleHeader,
QWidget#CharacterSettingsWorkspace QFrame#CollapsibleContent {
    background: {settings_panel_bg};
}
QWidget#CharacterSettingsWorkspace QWidget#CollapsibleSection {
    border: 1px solid {panel_border}; border-radius: 10px;
}
QWidget#CharacterSettingsWorkspace QWidget#CollapsibleHeader {
    border: none; border-radius: 10px;
}
QWidget#CharacterSettingsWorkspace QLabel#CharacterLibraryTitle,
QLabel#CharacterCount { margin: 0px; padding: 0px; border: none; }
QLabel#CharacterCount { color: {muted}; }
QWidget#CharacterSettingsWorkspace QWidget#CharacterActionRow {
    border-bottom: 1px solid {panel_border};
}
QLabel#CharacterActionTitle { font-weight: 600; }
QListWidget#CharacterList { background: transparent; border: none; outline: none; padding: 0px; }
QListWidget#CharacterList::item {
    background: {settings_panel_bg}; border: 1px solid {panel_border}; border-radius: 9px;
    padding: 3px 8px; font-size: 14px; font-weight: 600;
}
QListWidget#CharacterList::item:selected {
    background: {settings_panel_bg}; border: 1px solid {muted};
}
QListWidget#CharacterList::item:hover { border: 1px solid {muted}; }
QLabel#CharacterName { font-size: 20px; font-weight: 700; }
QLabel#CharacterId { color: {muted}; font-size: 12px; font-weight: 400; }
QWidget#CharacterSettingsWorkspace QLabel#CharacterActionDescription {
    color: {muted}; font-weight: 400; font-size: 12px;
}
QWidget#CharacterSettingsWorkspace QWidget#CollapsibleSection[danger="true"] {
    border: 1px solid {warn_border}; border-radius: 10px;
}
QLabel#CharacterLibraryTitle { font-size: 14px; font-weight: 600; }
QLabel#CharacterActiveBadge {
    background: rgba({accent_rgb}, 0.18); color: {text}; border-radius: 6px; padding: 5px 9px;
}
/* ========= API workspace ========= */
QWidget#ApiSettingsWorkspace { background: transparent; }
QWidget#ApiSettingsWorkspace, QWidget#ApiSettingsWorkspace QLabel,
QWidget#ApiSettingsWorkspace QLineEdit, QWidget#ApiSettingsWorkspace QComboBox,
QWidget#ApiSettingsWorkspace QPushButton, QWidget#ApiSettingsWorkspace QCheckBox {
    font-family: "Segoe UI"; letter-spacing: 0px;
}
QLabel#ApiSettingsTitle { font-size: 22px; font-weight: 700; color: {text}; }
QLabel#ApiEditorTitle { font-size: 13px; font-weight: 600; color: {text}; }
QLabel#ApiPresetName { font-size: 18px; font-weight: 700; color: {text}; }
QLabel#ApiSettingsSubtitle { color: {muted}; font-size: 12px; }
QLabel#ApiParameterKey { color: {muted}; font-size: 11px; }
QFrame#ApiWorkspacePanel {
    background: transparent; border: none;
}
QFrame#ApiPresetSidebar { background: {settings_panel_bg}; border: 1px solid {panel_border}; border-radius: 12px; }
QFrame#ApiEditorPanel { background: transparent; border: none; }
QLineEdit#ApiPresetSearch { background: {bg_root}; border: 1px solid {panel_border}; border-radius: 8px; padding: 6px; }
QSplitter#ApiWorkspaceSplitter { background: transparent; }
QSplitter#ApiWorkspaceSplitter::handle {
    background: transparent;
}
QSplitter#ApiWorkspaceSplitter::handle:hover { border-left: 1px solid {text}; }
QFrame#ApiEditorHeader, QFrame#ApiConfigurationHeader {
    background: {bg_root}; border: 1px solid {panel_border}; border-radius: 10px;
}
QFrame#ApiConfigurationHeader { border: 1px solid {panel_border}; border-radius: 8px; }
QLabel#ApiActiveTag {
    background: {chip_bg}; color: {success}; border: 1px solid {border_soft};
    border-radius: 9px; padding: 3px 9px; font-size: 11px; font-weight: 600;
}
QFrame#ApiConnectionCard { background: {settings_panel_bg}; border: 1px solid {panel_border}; border-radius: 12px; }
QTabWidget#ApiEditorTabs::pane { border: none; background: {settings_panel_bg}; }
QLabel#ApiReserveCount { background: {chip_bg}; color: {text}; border: 1px solid {panel_border}; border-radius: 7px; padding: 6px 10px; }
QTabWidget#ApiEditorTabs QTabBar { background: transparent; }
QTabWidget#ApiEditorTabs QTabBar::tab {
    background: {bg_root}; color: {muted}; border: none;
    border-bottom: 2px solid transparent; padding: 14px 22px; font-weight: 600;
}
QTabWidget#ApiEditorTabs QTabBar::tab:selected {
    background: {chip_bg}; color: {text}; border-bottom: 2px solid {accent};
}
QTabWidget#ApiEditorTabs QTabBar::tab:hover { color: {text}; }
QTabWidget#ApiEditorTabs QTabBar::tab:first { border-top-left-radius: 11px; }
QComboBox#ApiArrowCombo { padding-right: 30px; }
QComboBox#ApiArrowCombo::drop-down { width: 30px; border: none; background: transparent; }

QListWidget#ApiPresetCards, QScrollArea#ApiEditorScroll, QScrollArea#ApiConfigurationScroll, QWidget#ApiEditorContent {
    background: transparent; border: none; padding: 0; outline: 0;
}
QListWidget#ApiPresetCards::item { padding: 0; border: none; background: transparent; }
QListWidget#ModelParameterFields { background: {bg_root}; border: 1px solid {panel_border}; border-radius: 10px; padding: 6px; }
QListWidget#ModelParameterFields::item { padding: 8px; border-radius: 6px; color: {text}; }
QListWidget#ModelParameterFields::item:selected { background: rgba({accent_rgb}, 0.18); color: {text}; }
QWidget#ApiSettingsWorkspace QPushButton { padding: 0px 14px; border-radius: 8px; font-weight: 600; }
QPushButton#ApiAddPresetButton, QPushButton#ApiSaveButton {
    background: {accent}; color: {text}; border: 1px solid {accent_border}; font-weight: 600;
}
QPushButton#ApiAddPresetButton:hover, QPushButton#ApiSaveButton:hover { background: {accent_hover}; }
QPushButton#ApiSaveButton:disabled { background: {btn_disabled_bg}; color: {btn_disabled_fg}; border-color: {panel_border}; }
QPushButton#ApiCheckButton { background: transparent; border: 1px solid {panel_border}; color: {text}; }
QPushButton#ApiCheckButton:hover { background: rgba({accent_rgb}, 0.12); border-color: {accent}; }
QWidget#ApiEditorContent QLineEdit, QWidget#ApiEditorContent QComboBox {
    background: {bg_root}; border: 1px solid {panel_border};
    border-radius: 7px; padding: 8px 11px;
}
QWidget#ApiEditorContent QLineEdit { placeholder-text-color: {muted}; }
QWidget#ApiEditorContent QLineEdit:disabled {
    color: {muted}; placeholder-text-color: {muted};
    background: {bg_root}; border-color: {panel_border};
}
QWidget#ApiEditorContent QComboBox:disabled { color: {muted}; }
QWidget#ApiEditorContent QLineEdit:focus, QWidget#ApiEditorContent QComboBox:focus { border-color: {accent}; }
QWidget#ApiEditorContent QLabel[dirty="true"] { color: {link}; }
QWidget#ApiEditorContent QLineEdit[invalid="true"],
QWidget#ApiEditorContent QLineEdit[invalid="true"]:focus,
QWidget#ApiEditorContent QComboBox[invalid="true"],
QWidget#ApiEditorContent QComboBox[invalid="true"]:focus {
    border: 1px solid {danger};
}
QWidget#ApiSettingsWorkspace QWidget#CollapsibleHeader {
    background: {bg_root}; border: 1px solid {panel_border}; border-radius: 8px;
}

QWidget#ApiSettingsWorkspace QWidget#CollapsibleHeader QLabel#CollapsibleTitle { font-size: 14px; font-weight: 600; }
QWidget#ApiSettingsWorkspace QWidget#CollapsibleHeader QLabel#CollapsibleSubtitle { color: {muted}; font-size: 12px; }
QWidget#ApiSettingsWorkspace QLabel#CollapsibleIcon {
    background: {chip_bg}; border: 1px solid {panel_border}; border-radius: 9px;
}
/* ========= Settings Page ========= */
QWidget#SettingsPageRoot,
QWidget#SettingsWorkspaceContent {
    background: transparent;
    border: none;
}

QFrame#SettingsWorkspacePanel {
    background-color: rgba({settings_panel_rgb}, 0.98);
    border: 1px solid {panel_border};
    border-radius: 16px;
}

QFrame#SettingsTabsCard {
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    border-radius: 0px;
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
    background-color: rgba({settings_panel_rgb}, 0.98);
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

QFrame#SettingsSectionPageBody {
    background: transparent;
    border: none;
}

QFrame#SettingsSectionCard {
    background-color: rgba(9, 10, 22, 0.74);
    border: 1px solid {panel_border};
    border-radius: 22px;
}
QFrame#SettingsSectionCard[expanded="true"] {
    background-color: rgba(9, 10, 22, 0.86);
    border: 1px solid {panel_border};
}

QFrame#SettingsSectionHeader {
    background: transparent;
    border-radius: 22px;
}
QFrame#SettingsSectionHeader[expanded="true"] {
    background-color: rgba(255,255,255,0.015);
}

QLabel#SettingsSectionTitle {
    color: {text};
    font-size: 12pt;
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

QWidget#SettingsSubsectionHeader[hero="true"] QLabel#SettingsSubsectionTitle {
    color: {text};
    font-size: 17pt;
    font-weight: 800;
}

QWidget#SettingsSubsectionHeader[hero="true"] QLabel#SettingsSubsectionSubtitle {
    color: {muted};
    font-size: 9.5pt;
    font-weight: 500;
}

QFrame#SettingsSubsectionLine {
    background-color: rgba(255,255,255,0.08);
    border-radius: 1px;
}

QWidget#SettingsSubsectionHeader[hero="true"] QFrame#SettingsSubsectionLine {
    background-color: rgba(255,255,255,0.11);
}

QWidget#SettingsPageRoot QWidget#CollapsibleSection {
    background-color: rgba(9, 10, 22, 0.72);
    border: 1px solid {panel_border};
    border-radius: 14px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleSection[inner="true"] {
    background: transparent;
    border: none;
    border-radius: 0px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleHeader {
    background: transparent;
    border: none;
    border-radius: 14px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleHeader[expanded="true"] {
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleHeader:hover {
    background-color: rgba(255,255,255,0.025);
}

QWidget#SettingsPageRoot QWidget#CollapsibleContent[expanded="true"] {
    background-color: rgba(8, 9, 19, 0.42);
    border-left: none;
    border-right: none;
    border-bottom: none;
    border-bottom-left-radius: 14px;
    border-bottom-right-radius: 14px;
}

QWidget#SettingsPageRoot QWidget#InnerCollapsibleHeader {
    background: transparent;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    border-radius: 0px;
    padding-bottom: 6px;
}

QWidget#SettingsPageRoot QWidget#InnerCollapsibleHeader:hover {
    background: transparent;
}

QWidget#SettingsPageRoot QLabel#CollapsibleTitle {
    color: {text};
    font-weight: 800;
    padding: 0px;
}

QWidget#SettingsPageRoot QLabel#CollapsibleSubtitle {
    color: {muted};
    font-size: 8.8pt;
    font-weight: 500;
}

QWidget#SettingsPageRoot QLabel#CollapsibleArrow {
    padding: 0px;
    background: transparent;
}

QWidget#SettingsPageRoot QLabel#CollapsibleIcon {
    padding: 0px;
    background-color: rgba({accent_rgb}, 0.10);
    border: 1px solid rgba({accent_rgb}, 0.20);
    border-radius: 9px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleContent {
    background: transparent;
    padding-top: 4px;
}

QWidget#SettingsPageRoot QWidget#CollapsibleContent[inner="true"] {
    background: transparent;
    border: none;
    padding-top: 4px;
}

QWidget#SettingsPageRoot QWidget#SettingRow {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 3px 0px;
}

QWidget#SettingsPageRoot QWidget#SettingRow[disabled="true"] {
    background: transparent;
    border: none;
    padding: 3px 0px;
}

QWidget#SettingsPageRoot QWidget#SettingRow[disabled="true"] QLabel {
    color: rgba(188,169,187,0.34);
}

QWidget#SettingsPageRoot QWidget#SettingRow[disabled="true"] QLabel#SettingRowDescription {
    color: rgba(188,169,187,0.26);
}

QWidget#SettingsPageRoot QLabel#SeparatorLabel {
    margin-top: 10px;
    padding: 8px 2px 6px 2px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    font-weight: 800;
    color: {text};
}

QWidget#SettingsPageRoot QLabel#SettingRowDescription {
    color: {muted};
    font-size: 8.5pt;
    font-weight: 500;
}

QWidget#SettingsPageRoot QLineEdit,
QWidget#SettingsPageRoot QTextEdit,
QWidget#SettingsPageRoot QPlainTextEdit,
QWidget#SettingsPageRoot QComboBox,
QWidget#SettingsPageRoot QSpinBox,
QWidget#SettingsPageRoot QDoubleSpinBox,
QWidget#SettingsPageRoot QListWidget,
QWidget#SettingsPageRoot QTreeWidget {
    background-color: rgba(9, 10, 22, 0.88);
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

QWidget#SettingsPageRoot QWidget#NumberStepper {
    background-color: rgba(9, 10, 22, 0.88);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
}

QWidget#SettingsPageRoot QSpinBox#NumberStepperValue {
    min-width: 54px;
    min-height: 36px;
    padding: 0 8px;
    background: transparent;
    border: none;
    border-radius: 0;
    color: {text};
    font-weight: 700;
}

QWidget#SettingsPageRoot QToolButton#NumberStepperDecrease,
QWidget#SettingsPageRoot QToolButton#NumberStepperIncrease {
    min-width: 36px;
    max-width: 36px;
    min-height: 38px;
    max-height: 38px;
    padding: 0;
    background: rgba(255,255,255,0.035);
    border: none;
    color: {muted};
    font-size: 13pt;
    font-weight: 500;
}

QWidget#SettingsPageRoot QToolButton#NumberStepperDecrease {
    border-right: 1px solid rgba(255,255,255,0.08);
    border-top-left-radius: 9px;
    border-bottom-left-radius: 9px;
}

QWidget#SettingsPageRoot QToolButton#NumberStepperIncrease {
    border-left: 1px solid rgba(255,255,255,0.08);
    border-top-right-radius: 9px;
    border-bottom-right-radius: 9px;
}

QWidget#SettingsPageRoot QToolButton#NumberStepperDecrease:hover,
QWidget#SettingsPageRoot QToolButton#NumberStepperIncrease:hover {
    background: rgba({accent_rgb}, 0.16);
    color: {text};
}

QWidget#SettingsPageRoot QToolButton#NumberStepperDecrease:pressed,
QWidget#SettingsPageRoot QToolButton#NumberStepperIncrease:pressed {
    background: rgba({accent_rgb}, 0.28);
}

QWidget#SettingsPageRoot QCheckBox {
    background: transparent;
    border: none;
    color: {text};
    spacing: 8px;
    padding: 2px 0;
}

QWidget#SettingsPageRoot QCheckBox::indicator {
    /* Жёсткий квадрат с рамкой: с `border: none` Qt в этой сборке растягивал
       фон индикатора в «пилюлю/слайдер» (фидбэк Артёма «это просто галка»).
       Рамка + min/max-size фиксируют чекбокс как квадрат. */
    width: 16px;
    height: 16px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.22);
    background-color: rgba(255,255,255,0.06);
}

QWidget#SettingsPageRoot QCheckBox::indicator:hover {
    border: 1px solid rgba({accent_rgb}, 0.55);
    background-color: rgba({accent_rgb}, 0.14);
}

QWidget#SettingsPageRoot QCheckBox::indicator:checked {
    border: 1px solid {accent_alt};
    background-color: {accent_alt};
    image: url(assets/launcher_ui/check.svg);
}

QWidget#SettingsPageRoot QCheckBox::indicator:disabled {
    border: 1px solid rgba(255,255,255,0.10);
    background-color: rgba(255,255,255,0.04);
}

QWidget#SettingsPageRoot QPushButton#SecondaryButton {
    background-color: rgba(255,255,255,0.045);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
}

QWidget#SettingsPageRoot QPushButton#SecondaryButton:hover {
    background-color: rgba(255,255,255,0.075);
    border: 1px solid {panel_border};
}

QWidget#SettingsPageRoot QPushButton#CancelButton {
    border-radius: 10px;
}

/* ========= Scope toggle (Characters: Selected / All) ========= */
QWidget#SettingsPageRoot QFrame#ScopeToggle {
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid {panel_border};
    border-radius: 9px;
}
QWidget#SettingsPageRoot QPushButton#ScopeToggleButton {
    background: rgba(255, 255, 255, 0.04);
    border: none;
    border-radius: 7px;
    padding: 5px 14px;
    color: {muted};
    font-weight: 600;
}
QWidget#SettingsPageRoot QPushButton#ScopeToggleButton:hover[active="false"] {
    background: rgba({accent_rgb}, 0.16);
    color: {text};
}
QWidget#SettingsPageRoot QPushButton#ScopeToggleButton[active="true"] {
    background: {accent};
    color: #ffffff;
}

/* ========= AI Engine settings ========= */
QWidget#SettingsPageRoot QFrame#AIEngineHardwarePanel,
QWidget#SettingsPageRoot QFrame#AIEngineHubPanel,
QWidget#SettingsPageRoot QFrame#AIEngineModePanel {
    background-color: #111321;
    border: 1px solid #292738;
    border-radius: 16px;
}
QWidget#SettingsPageRoot QLabel#AIEngineCardIcon {
    background-color: rgba({accent_rgb}, 0.10);
    border: 1px solid rgba({accent_rgb}, 0.22);
    border-radius: 12px;
}
QWidget#SettingsPageRoot QLabel#AIEngineCardTitle {
    color: {text};
    font-size: 11pt;
    font-weight: 750;
}
QWidget#SettingsPageRoot QLabel#AIEngineEyebrow {
    color: {muted};
    font-size: 8.5pt;
    font-weight: 700;
}
QWidget#SettingsPageRoot QLabel#AIEngineCardSubtitle,
QWidget#SettingsPageRoot QLabel#AIEngineLoadingText,
QWidget#SettingsPageRoot QLabel#AIEngineMaintenanceHint {
    color: {muted};
    font-size: 9pt;
}
QWidget#SettingsPageRoot QPushButton#AIEngineLoadingSpinner:disabled {
    background: transparent;
    border: none;
    padding: 0px;
}
QWidget#SettingsPageRoot QPushButton#AIEngineIconButton {
    background-color: #191b2a;
    border: 1px solid #302e3e;
    border-radius: 9px;
    padding: 0px;
}
QWidget#SettingsPageRoot QPushButton#AIEngineIconButton:hover {
    background-color: rgba({accent_rgb}, 0.13);
    border-color: rgba({accent_rgb}, 0.30);
}
QWidget#SettingsPageRoot QLabel#AIEngineChip,
QWidget#SettingsPageRoot QLabel#AIEngineChipCuda,
QWidget#SettingsPageRoot QLabel#AIEngineChipOnnx,
QWidget#SettingsPageRoot QLabel#AIEngineChipGpu,
QWidget#SettingsPageRoot QLabel#AIEngineChipWarning,
QWidget#SettingsPageRoot QLabel#AIEngineChipSuccess {
    padding: 3px 8px;
    border-radius: 7px;
    font-size: 8.5pt;
    font-weight: 650;
}
QWidget#SettingsPageRoot QLabel#AIEngineChip {
    color: {text};
    background-color: rgba(255,255,255,0.055);
    border: 1px solid rgba(255,255,255,0.09);
}
QWidget#SettingsPageRoot QLabel#AIEngineChipGpu,
QWidget#SettingsPageRoot QLabel#AIEngineChipSuccess {
    color: #a8f0c6;
    background-color: rgba(67, 190, 119, 0.12);
    border: 1px solid rgba(80, 210, 135, 0.24);
}
QWidget#SettingsPageRoot QLabel#AIEngineChipCuda {
    color: #b9cfff;
    background-color: rgba(74, 117, 230, 0.14);
    border: 1px solid rgba(91, 139, 255, 0.28);
}
QWidget#SettingsPageRoot QLabel#AIEngineChipOnnx {
    color: #d5b8ff;
    background-color: rgba(143, 88, 220, 0.14);
    border: 1px solid rgba(168, 111, 242, 0.25);
}
QWidget#SettingsPageRoot QLabel#AIEngineChipWarning {
    color: #f3bd74;
    background-color: rgba(220, 145, 58, 0.12);
    border: 1px solid rgba(240, 166, 74, 0.26);
}
QWidget#SettingsPageRoot QLabel#AIEngineModeDescription {
    color: {muted};
    background: transparent;
    border: none;
    padding: 3px 1px 1px 1px;
}
QWidget#SettingsPageRoot QLabel#AIEngineModeWarning {
    color: #f0a64a;
    background-color: rgba(230, 139, 45, 0.08);
    border: 1px solid rgba(240, 166, 74, 0.20);
    border-radius: 9px;
    padding: 9px 11px;
}
QWidget#SettingsPageRoot QFrame#AIEngineBackendNotice[severity="warning"] {
    background-color: rgba(230, 139, 45, 0.08);
    border: 1px solid rgba(240, 166, 74, 0.20);
    border-radius: 9px;
}
QWidget#SettingsPageRoot QFrame#AIEngineBackendNotice[severity="info"] {
    background-color: rgba(88, 135, 220, 0.08);
    border: 1px solid rgba(116, 160, 235, 0.20);
    border-radius: 9px;
}
QWidget#SettingsPageRoot QFrame#AIEngineBackendNotice[severity="warning"] QLabel#AIEngineBackendNoticeText {
    color: #f0a64a;
}
QWidget#SettingsPageRoot QFrame#AIEngineBackendNotice[severity="info"] QLabel#AIEngineBackendNoticeText {
    color: #9cc3ff;
}
QWidget#SettingsPageRoot QPushButton#AIEngineApplyButton[dirty="true"] {
    color: #ffffff;
    font-weight: 700;
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba({accent_rgb_alt}, 0.96),
        stop: 1 rgba({slider_progress_rgb}, 0.98)
    );
    border: 1px solid rgba({accent_rgb_alt}, 0.70);
    border-radius: 10px;
    padding: 7px 14px;
}
QWidget#SettingsPageRoot QPushButton#AIEngineApplyButton[dirty="true"]:hover {
    background-color: rgba({accent_rgb}, 0.96);
}
QWidget#SettingsPageRoot QPushButton#AIEngineApplyButton:disabled {
    color: #746f7b;
    background-color: #222330;
    border: 1px solid #343340;
    border-radius: 10px;
    padding: 7px 14px;
}
QWidget#SettingsPageRoot QLabel#AIEngineEnvironmentPath {
    color: {muted};
    background-color: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: 8px 10px;
}
QWidget#SettingsPageRoot QLabel#AIEngineMaintenanceStatus {
    color: {text};
    font-weight: 600;
}
"""
