from __future__ import annotations

CHAT_WIDGETS_QSS = r"""
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
"""

CHAT_SCROLL_QSS = r"""
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

SANDBOX_PAGE_QSS = r"""
QWidget#SandboxPage,
QWidget#ChatWorkspace,
QWidget#SandboxInspector,
QWidget#SandboxLeftColumn {
    background: transparent;
    border: none;
}

QFrame#ChatToolbarCard,
QFrame#SandboxTitleCard,
QFrame#SandboxSelectorDeck,
QFrame#SandboxChatHost,
QFrame#SandboxInspector,
QFrame#ChatComposerCard {
    background-color: rgba(29, 12, 34, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.22);
    border-radius: 20px;
}

QFrame#SandboxSelectorCard,
QFrame#SandboxInspectorCard {
    background-color: rgba(24, 10, 32, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.18);
    border-radius: 22px;
}

QLabel#SandboxHeroBadge {
    color: #ffe7f4;
    background-color: rgba(255, 92, 168, 0.16);
    border: 1px solid rgba(255, 92, 168, 0.36);
    border-radius: 10px;
    padding: 3px 9px;
    font-size: 8pt;
    font-weight: 800;
    letter-spacing: 0.08em;
}

QLabel#ChatHeroTitle {
    font-size: 18pt;
    font-weight: 800;
    color: #fff1f9;
}

QLabel#ChatHeroSubtitle {
    color: #c5a8bf;
    font-size: 9pt;
}

QLabel#TokenCountLabel {
    color: #b89bb3;
    padding: 0 4px;
    background: transparent;
    border: none;
    font-size: 8pt;
}

QWidget#ChatCharacterHistoryGroup,
QWidget#ChatInputContainer {
    background-color: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
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

QLabel#SandboxInspectorTitle {
    color: #fff1f9;
    font-size: 11pt;
    font-weight: 800;
}

QLabel#SandboxInspectorLabel,
QLabel#SandboxSelectorLabel {
    color: #c39fb8;
    font-size: 8.5pt;
    font-weight: 700;
    text-transform: uppercase;
}

QLabel#SandboxInspectorValue,
QLabel#SandboxSelectorValue {
    color: #fff1f9;
    font-size: 10.5pt;
    font-weight: 700;
}

QLabel#SandboxSelectorHint,
QLabel#SandboxInspectorMeta {
    color: #c3a4ba;
    font-size: 9pt;
}

QLabel#SandboxSelectorHintAccent {
    color: #89f7b2;
    font-size: 9pt;
    font-weight: 700;
}

QPushButton#SandboxSelectorJump,
QPushButton#SandboxQuickAction {
    background-color: rgba(255, 255, 255, 0.04);
    color: #fff1f9;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 5px 10px;
    text-align: left;
    font-size: 10pt;
    font-weight: 600;
}

QPushButton#SandboxSelectorJump:hover,
QPushButton#SandboxQuickAction:hover {
    background-color: rgba(255, 92, 168, 0.16);
    border: 1px solid rgba(255, 92, 168, 0.36);
}

QPushButton#SandboxQuickAction:pressed {
    background-color: rgba(255, 92, 158, 0.24);
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
    top: 6px;
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

QPushButton#SandboxInspectorCollapseBtn {
    background: transparent;
    color: #ffd2ec;
    border: 1px solid rgba(255, 92, 158, 0.32);
    border-radius: 14px;
    min-width: 28px;
    min-height: 28px;
    max-width: 28px;
    max-height: 28px;
    font-size: 11pt;
    font-weight: 700;
    padding: 0;
}
QPushButton#SandboxInspectorCollapseBtn:hover {
    background-color: rgba(255, 92, 168, 0.16);
    border: 1px solid rgba(255, 92, 168, 0.52);
}
QPushButton#SandboxInspectorCollapseBtn:pressed {
    background-color: rgba(255, 92, 158, 0.24);
}

QLabel#SandboxCharacterAvatar {
    border-radius: 16px;
    min-width: 32px;
    min-height: 32px;
    max-width: 32px;
    max-height: 32px;
    background: transparent;
}

QLabel#SandboxSelectorIcon {
    background: transparent;
    border: none;
}

QCheckBox#SandboxCaptureToggle {
    color: #fff1f9;
    spacing: 8px;
    font-size: 10pt;
    background: transparent;
    border: none;
    padding: 2px 0;
}

QCheckBox#SandboxCaptureToggle::indicator {
    width: 14px;
    height: 14px;
    border-radius: 4px;
    border: 1px solid rgba(255, 92, 158, 0.36);
    background-color: rgba(255, 255, 255, 0.06);
}

QCheckBox#SandboxCaptureToggle::indicator:checked {
    background-color: #ff5ca8;
    border: 1px solid rgba(255, 92, 168, 0.85);
}
"""
