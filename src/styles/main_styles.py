# styles/main_styles.py
from utils import render_qss

THEME = {
    "bg_root": "#0d0713",
    "bg_window": "#09050f",
    "text": "#f4e7f1",
    "muted": "#b095ad",

    "panel_bg": "rgba(27,12,31,0.94)",
    "card_bg": "rgba(34,14,39,0.96)",
    "card_border": "rgba(255,120,181,0.18)",
    "border_soft": "rgba(255,255,255,0.10)",
    "outline": "rgba(255,255,255,0.06)",

    "accent": "#ff5c9e",
    "accent_hover": "#ff73ad",
    "accent_pressed": "#ef4b8f",
    "accent_border": "rgba(255,92,158,0.48)",

    "chip_bg": "rgba(255,255,255,0.05)",
    "chip_hover": "rgba(255,92,158,0.14)",
    "chip_pressed": "rgba(255,92,158,0.20)",

    "scroll_handle": "rgba(255,156,210,0.22)",

    "warn_bg": "rgba(255,120,120,0.08)",
    "warn_border": "rgba(255,120,120,0.25)",
    "warn_text": "#ffb4b4",

    "success": "#7fe38c",
    "success_hover": "#91eba0",
    "success_pressed": "#69d97a",

    "danger": "#d64545",
    "danger_hover": "#e25757",
    "danger_pressed": "#bf3838",

    "link": "#7bc6ff",

    "btn_disabled_bg": "#3a2236",
    "btn_disabled_fg": "#7e6178",
}

def get_theme():
    return THEME.copy()

style_template = """
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
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #140913,
        stop: 0.45 #0c0813,
        stop: 1 #07060d
    );
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
    background-color: rgba(12,12,16,0.92);
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
    background-color: rgba(14,14,18,0.85);
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
    background: rgba(255,255,255,0.18);
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
    background: rgba(255,255,255,0.18);
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

QPushButton#ChatTopIconButton {
    background-color: {chip_bg};
    color: #ffffff;
    border: 1px solid {outline};
    padding: 4px;
    border-radius: 8px;
}
QPushButton#ChatTopIconButton:hover { background-color: {chip_hover}; }
QPushButton#ChatTopIconButton:pressed { background-color: {chip_pressed}; }

QComboBox#ChatCharacterCombo {
    min-height: 20px;
    padding: 4px 8px;
    border-radius: 8px;
}

QWidget#InlineStatusIndicators {
    background-color: transparent;
}

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

/* ========= Tables ========= */
QTableView {
    background-color: {panel_bg};
    alternate-background-color: rgba(255,255,255,0.03);
    color: {text};

    border: 1px solid {border_soft};
    gridline-color: {outline};

    selection-background-color: rgba(138,43,226,0.25); /* на всякий случай */
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
    background-color: rgba(138,43,226,0.35);
    color: #ffffff;
}

QTableView::item:selected:!active {
    background-color: rgba(138,43,226,0.22);
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

/* ========= Launcher Shell ========= */
QWidget#SettingsSidebar {
    background-color: rgba(11, 7, 18, 0.98);
    border-right: 1px solid rgba(255, 92, 158, 0.18);
}

QFrame#LauncherBrandCard,
QFrame#LauncherFooterCard,
QFrame#ChatToolbarCard,
QFrame#ChatComposerCard,
QFrame#SettingsHeroCard {
    background-color: rgba(29, 12, 34, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.22);
    border-radius: 20px;
}

QFrame#LauncherBrandCard {
    background-color: rgba(34, 13, 36, 0.98);
}

QLabel#LauncherBrandTitle {
    font-size: 17pt;
    font-weight: 800;
    color: #fff1f9;
}

QLabel#LauncherBrandSubtitle,
QLabel#LauncherFooterHint,
QLabel#ChatHeroSubtitle,
QLabel#SettingsHeroSubtitle {
    color: #c5a8bf;
    font-size: 9pt;
}

QLabel#SettingsSidebarTitle,
QLabel#LauncherFooterStatus {
    color: #ff84bd;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

QLabel#ChatHeroTitle,
QLabel#SettingsHeroTitle {
    font-size: 18pt;
    font-weight: 800;
    color: #fff1f9;
}

QLabel#TokenCountLabel {
    color: #d6b3c7;
    padding: 4px 10px;
    border-radius: 999px;
    background-color: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.05);
}

QWidget#ChatCharacterHistoryGroup,
QWidget#ChatInputContainer {
    background-color: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
}

QPushButton#ChatTopIconButton,
QPushButton#GuideButtonSmall {
    background-color: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
}

QPushButton#ChatTopIconButton:hover,
QPushButton#GuideButtonSmall:hover {
    background-color: rgba(255,92,158,0.16);
    border: 1px solid rgba(255,92,158,0.24);
}

QPushButton#ChatSendButtonCircle {
    background-color: {accent};
    border: 1px solid rgba(255, 180, 216, 0.55);
    border-radius: 14px;
}

QPushButton#ChatIconMini {
    background-color: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px;
}

QCheckBox#StatusIndicator {
    color: #dcbfd3;
    spacing: 6px;
    padding: 2px 6px 2px 0;
}

QCheckBox#StatusIndicator::indicator {
    width: 12px;
    height: 12px;
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.12);
    background-color: rgba(255,255,255,0.08);
}

QCheckBox#StatusIndicator::indicator:checked {
    background-color: #79e78c;
    border: 1px solid rgba(121, 231, 140, 0.85);
}

QWidget#StatusIndicatorStrip,
QWidget#InlineStatusIndicators {
    background-color: rgba(22, 10, 26, 0.96);
    border: 1px solid rgba(255, 92, 158, 0.14);
    border-radius: 18px;
}

QWidget#StatusIndicatorChip {
    background: transparent;
}

QLabel#StatusIndicatorDot {
    border-radius: 7px;
    background-color: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.14);
}

QLabel#StatusIndicatorDot[active="true"] {
    background-color: #79e78c;
    border: 1px solid rgba(121,231,140,0.88);
}

QLabel#StatusIndicatorText {
    color: #d7b6c6;
    font-size: 9pt;
    font-weight: 600;
}

QLabel#StatusIndicatorText[active="true"] {
    color: #fff0f8;
}

QFrame#LauncherContentHost,
QStackedWidget#MainPageStack,
QStackedWidget#MainPageStack > QWidget,
QWidget#SandboxPage,
QWidget#SettingsPageRoot,
QWidget#SettingsRail {
    background: transparent;
    border: none;
}

QFrame#LauncherSpotlightCard,
QFrame#SettingsTabsCard,
QFrame#SettingsStatusRailCard,
QFrame#SettingsQuickActionsCard,
QFrame#SandboxSelectorCard,
QFrame#SandboxInspectorCard {
    background-color: rgba(24, 10, 32, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.18);
    border-radius: 22px;
}

QLabel#LauncherSpotlightArt {
    min-width: 240px;
    min-height: 170px;
    border-radius: 18px;
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    color: #fff1f9;
    font-size: 18pt;
    font-weight: 800;
}

QWidget#SettingsRail {
    min-width: 300px;
}

QLabel#SettingsRailTitle,
QLabel#SandboxInspectorTitle {
    color: #fff1f9;
    font-size: 11pt;
    font-weight: 800;
}

QLabel#SettingsRailLabel,
QLabel#SandboxInspectorLabel,
QLabel#SandboxSelectorLabel {
    color: #c39fb8;
    font-size: 8.5pt;
    font-weight: 700;
    text-transform: uppercase;
}

QLabel#SettingsRailValue,
QLabel#SandboxInspectorValue,
QLabel#SandboxSelectorValue {
    color: #fff1f9;
    font-size: 10.5pt;
    font-weight: 700;
}

QLabel#SandboxSelectorHint,
QLabel#SettingsOverviewText,
QLabel#SettingsRailBrandHint,
QLabel#SettingsRailBrandMeta,
QLabel#SandboxInspectorMeta {
    color: #c3a4ba;
    font-size: 9pt;
}

QLabel#SandboxSelectorHintAccent,
QLabel#SettingsRailBrandState {
    color: #89f7b2;
    font-size: 9pt;
    font-weight: 700;
}

QPushButton#SandboxSelectorJump {
    background-color: rgba(255, 255, 255, 0.04);
    color: #fff1f9;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 5px 10px;
    text-align: left;
    font-size: 10pt;
    font-weight: 600;
}

QPushButton#SandboxSelectorJump:hover {
    background-color: rgba(255, 92, 168, 0.16);
    border: 1px solid rgba(255, 92, 168, 0.36);
}

QFrame#ChatConversationStrip {
    background-color: rgba(28, 12, 36, 0.72);
    border: 1px solid rgba(255, 92, 158, 0.16);
    border-radius: 14px;
}

QLabel#ChatStripTitle {
    color: #fff1f9;
    font-size: 10pt;
    font-weight: 700;
}

QLabel#ChatStripMeta {
    color: #c39fb8;
    font-size: 9pt;
}

QLabel#ChatStripSeparator {
    color: rgba(255, 92, 158, 0.55);
    font-size: 10pt;
}

QPushButton#ChatStripGhostButton {
    background: transparent;
    color: #ffd2ec;
    border: 1px solid rgba(255, 92, 158, 0.24);
    border-radius: 12px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 600;
}

QPushButton#ChatStripGhostButton:hover {
    background-color: rgba(255, 92, 158, 0.14);
    border: 1px solid rgba(255, 92, 158, 0.42);
}

QTabWidget#SandboxInspectorTabs::pane {
    border: none;
    background: transparent;
    top: 4px;
}
QTabWidget#SandboxInspectorTabs QTabBar::tab {
    background: transparent;
    color: #c39fb8;
    padding: 8px 14px;
    margin-right: 6px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 10pt;
    font-weight: 600;
}
QTabWidget#SandboxInspectorTabs QTabBar::tab:hover {
    color: #fff1f9;
}
QTabWidget#SandboxInspectorTabs QTabBar::tab:selected {
    color: #fff1f9;
    border-bottom: 2px solid #ff5ca8;
}
QWidget#SandboxInspectorTabPage {
    background: transparent;
}

QLabel#SettingsOverviewTitle,
QLabel#SettingsRailBrandTitle {
    color: #fff1f9;
    font-size: 12pt;
    font-weight: 800;
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

QFrame#SettingsOverviewCard {
    background-color: rgba(29, 12, 34, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.22);
    border-radius: 20px;
}

QPushButton#SettingsQuickActionButton,
QPushButton#SettingsOverviewShortcut,
QPushButton#SandboxQuickAction {
    background-color: rgba(255, 255, 255, 0.04);
    color: #fff1f9;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    padding: 10px 12px;
    text-align: left;
    font-weight: 700;
}

QPushButton#SettingsQuickActionButton:hover,
QPushButton#SettingsOverviewShortcut:hover,
QPushButton#SandboxQuickAction:hover {
    background-color: rgba(255, 92, 158, 0.16);
    border: 1px solid rgba(255, 92, 158, 0.28);
}

QPushButton#SettingsQuickActionButton:pressed,
QPushButton#SettingsOverviewShortcut:pressed,
QPushButton#SandboxQuickAction:pressed {
    background-color: rgba(255, 92, 158, 0.24);
}

QWidget#SandboxInspector {
    background: transparent;
}

QWidget#ChatWorkspace {
    background: transparent;
}

QWidget#SettingsPageOverlay QStackedWidget,
QWidget#SettingsPageOverlay QStackedWidget > QWidget,
QWidget#SettingsPageOverlay QScrollArea,
QWidget#SettingsPageOverlay QScrollArea > QWidget,
QWidget#SettingsPageOverlay QScrollArea > QWidget > QWidget,
QWidget#SettingsPageOverlay QAbstractScrollArea,
QWidget#SettingsPageOverlay QAbstractScrollArea > QWidget,
QWidget#SettingsPageOverlay QAbstractScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}

/* Контейнеры страниц настроек, рендерящихся внутри SettingsOverlay,
   не должны рисовать собственный тёмный квадрат — без этого правила
   при переключении категорий иногда мелькала подложка. */
QWidget[objectName^="ContentWidget_"],
QScrollArea[objectName^="ScrollArea_"],
QScrollArea[objectName^="ScrollArea_"] > QWidget,
QScrollArea[objectName^="ScrollArea_"] > QWidget > QWidget {
    background: transparent;
    border: none;
}

QWidget#LauncherHomeBackground,
QWidget#LauncherHomeLogoZone {
    background: transparent;
    border: none;
    font-family: "Segoe UI", "Arial", sans-serif;
}

QLabel#LauncherHomeTitle,
QLabel#LauncherHomeSubtitle,
QLabel#LauncherHomeFootnote,
QLabel#LauncherHomeUpdateText,
QLabel#LauncherHomeStatusEyebrow,
QLabel#LauncherHomeNewsTitle,
QLabel#LauncherHomeCardTitle,
QLabel#LauncherHomeStatusValue,
QLabel#LauncherHomeNewsItemTitle,
QLabel#LauncherHomeNewsItemBody,
QLabel#LauncherHomeNewsDate,
QLabel#LauncherHomeNewsBadge,
QPushButton#LauncherHomeLinkButton,
QPushButton#LauncherHomePrimaryButton,
QPushButton#LauncherHomeMenuButton,
QPushButton#LauncherHomeVerifyButton {
    font-family: "Segoe UI", "Arial", sans-serif;
}

QLabel#LauncherHomeTitle {
    color: #ffffff;
    font-size: 30pt;
    font-weight: 800;
    letter-spacing: 0px;
}

QLabel#LauncherHomeSubtitle,
QLabel#LauncherHomeFootnote {
    color: #e2bccb;
    font-size: 12pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeFootnote {
    font-size: 9pt;
    color: #c39aab;
}

QProgressBar#LauncherHomeProgressBar {
    background-color: rgba(20, 8, 13, 0.78);
    border: 1px solid rgba(255, 92, 158, 0.30);
    border-radius: 5px;
    text-align: center;
}
QProgressBar#LauncherHomeProgressBar::chunk {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #ff80a9,
        stop: 1 #c81663
    );
    border-radius: 5px;
}

QLabel#LauncherHomeProgressLabel {
    color: #ffd2ec;
    font-size: 9pt;
    font-weight: 600;
}

QFrame#LauncherHomeUpdateChip,
QFrame#LauncherHomeNewsPanel,
QFrame#LauncherHomeStatusCard {
    background-color: rgba(20, 8, 13, 0.78);
    border: 1px solid rgba(255, 92, 158, 0.30);
    border-radius: 14px;
}

QFrame#LauncherHomeNewsItem {
    background: transparent;
    border: none;
    border-radius: 0;
}

QLabel#LauncherHomeLogo {
    min-height: 240px;
    background: transparent;
}

QLabel#LauncherHomeUpdateDot {
    border-radius: 5px;
    background-color: #ffd06b;
}

QLabel#LauncherHomeUpdateText {
    color: #f5e2e8;
    font-size: 10pt;
    letter-spacing: 0px;
}

QPushButton#LauncherHomeLinkButton {
    background: transparent;
    border: none;
    color: #ff80a9;
    font-size: 10pt;
    font-weight: 600;
    letter-spacing: 0px;
    padding: 0;
}

QPushButton#LauncherHomeLinkButton:hover {
    color: #ff9ec0;
}

QLabel#LauncherHomeStatusEyebrow,
QLabel#LauncherHomeNewsTitle,
QLabel#LauncherHomeCardTitle {
    color: #f5c9d4;
    font-size: 8.5pt;
    font-weight: 800;
    letter-spacing: 0px;
    text-transform: uppercase;
}

QLabel#LauncherHomeStatusValue {
    color: #ffffff;
    font-size: 14pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QPushButton#LauncherHomePrimaryButton {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #ff4d8a,
        stop: 1 #c81663
    );
    border: 1px solid rgba(255, 179, 212, 0.42);
    border-radius: 16px;
    color: #ffffff;
    padding: 16px 22px;
    font-size: 16pt;
    font-weight: 800;
    letter-spacing: 0px;
}

QPushButton#LauncherHomePrimaryButton:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #ff73a8,
        stop: 1 #dd3a76
    );
}

QPushButton#LauncherHomeMenuButton {
    min-width: 56px;
    min-height: 56px;
    background-color: rgba(34, 16, 26, 0.96);
    border: 1px solid rgba(255, 92, 158, 0.22);
    border-radius: 16px;
    color: #ffd6e1;
    font-size: 16pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QPushButton#LauncherHomeMenuButton:hover,
QPushButton#LauncherHomeVerifyButton:hover {
    background-color: rgba(42, 16, 25, 0.96);
    border: 1px solid rgba(255, 92, 158, 0.32);
}

QPushButton#LauncherHomeVerifyButton {
    min-height: 46px;
    background-color: rgba(28, 10, 18, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.18);
    border-radius: 14px;
    color: #f5c9d4;
    text-align: left;
    padding: 12px 14px;
    font-size: 10pt;
    font-weight: 600;
    letter-spacing: 0px;
}

QFrame#LauncherHomeDivider {
    background-color: rgba(90, 34, 51, 1);
}

QLabel#LauncherHomeNewsItemTitle {
    color: #ffffff;
    font-size: 10pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsItemBody {
    color: #b08a96;
    font-size: 8.5pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsDate {
    color: #8a6271;
    font-size: 8pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsBadge {
    background-color: #ff4d8a;
    border-radius: 8px;
    color: #ffffff;
    padding: 2px 8px;
    font-size: 7.5pt;
    font-weight: 800;
    letter-spacing: 0px;
}
"""

def get_stylesheet(overrides: dict | None = None) -> str:
    theme = THEME.copy()
    if overrides:
        theme.update(overrides)
    return render_qss(style_template, theme)

