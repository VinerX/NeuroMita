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
QWidget#SandboxLeftColumn,
QWidget#SandboxInspectorTabCorner {
    background: transparent;
    border: none;
}

QFrame#SandboxWorkspaceShell {
    background-color: rgba(8, 12, 23, 0.97);
    border: 1px solid rgba(92, 84, 146, 0.34);
    border-radius: 24px;
}

QFrame#SandboxWorkspaceHeader {
    background: transparent;
    border: none;
}

QFrame#SandboxSelectorDeck,
QFrame#SandboxChatHost,
QFrame#SandboxInspector,
QFrame#ChatComposerCard {
    background-color: rgba(12, 17, 31, 0.92);
    border: 1px solid rgba(81, 94, 158, 0.20);
    border-radius: 20px;
}

QFrame#ChatToolbarCard,
QFrame#SandboxSelectorCard {
    background-color: rgba(16, 22, 38, 0.96);
    border: 1px solid rgba(90, 103, 166, 0.22);
    border-radius: 18px;
}

QFrame#SandboxInspectorCard {
    background-color: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.045);
    border-radius: 16px;
}

QLabel#SandboxHeroIcon {
    background: transparent;
    border: none;
}

QLabel#SandboxHeroBadge {
    color: #ffe8f4;
    background-color: rgba(255, 109, 183, 0.10);
    border: 1px solid rgba(255, 109, 183, 0.30);
    border-radius: 10px;
    padding: 3px 9px;
    font-size: 8pt;
    font-weight: 800;
    letter-spacing: 0.08em;
}

QLabel#ChatHeroTitle {
    font-size: 18pt;
    font-weight: 800;
    color: #f3efff;
}

QLabel#ChatHeroSubtitle {
    color: #9da5c7;
    font-size: 9pt;
}

QLabel#TokenCountLabel {
    color: #7e86a7;
    padding: 0 4px;
    background: transparent;
    border: none;
    font-size: 8pt;
}

QWidget#ChatCharacterHistoryGroup,
QWidget#ChatInputContainer {
    background-color: rgba(18, 23, 38, 0.94);
    border: 1px solid rgba(83, 96, 158, 0.20);
    border-radius: 14px;
}

QCheckBox#StatusIndicator {
    color: #bcc4e4;
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
    background-color: rgba(13, 18, 31, 0.95);
    border: 1px solid rgba(80, 94, 154, 0.15);
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
    color: #bcc4e4;
    font-size: 9pt;
    font-weight: 600;
}

QLabel#StatusIndicatorText[active="true"] {
    color: #f5f2ff;
}

QLabel#SandboxInspectorTitle {
    color: #f2efff;
    font-size: 10.5pt;
    font-weight: 800;
}

QLabel#SandboxInspectorLabel,
QLabel#SandboxSelectorLabel {
    color: #8f97bb;
    font-size: 8.5pt;
    font-weight: 700;
    text-transform: uppercase;
}

QLabel#SandboxInspectorValue,
QLabel#SandboxSelectorValue {
    color: #f5f2ff;
    font-size: 10.5pt;
    font-weight: 700;
}

QLabel#SandboxSelectorHint,
QLabel#SandboxInspectorMeta {
    color: #9aa2c3;
    font-size: 9pt;
}

QLabel#SandboxSelectorHintAccent {
    color: #89f7b2;
    font-size: 9pt;
    font-weight: 700;
}

QPushButton#SandboxSelectorJump,
QPushButton#SandboxQuickAction {
    background-color: rgba(18, 24, 40, 0.90);
    color: #eff0ff;
    border: 1px solid rgba(86, 99, 163, 0.18);
    border-radius: 8px;
    padding: 5px 10px;
    text-align: left;
    font-size: 9.5pt;
    font-weight: 600;
}

QPushButton#SandboxSelectorJump:hover,
QPushButton#SandboxQuickAction:hover {
    background-color: rgba(255, 109, 183, 0.10);
    border: 1px solid rgba(255, 109, 183, 0.28);
}

QPushButton#SandboxQuickAction:pressed {
    background-color: rgba(255, 109, 183, 0.18);
}

QFrame#ChatConversationStrip {
    background-color: rgba(14, 19, 34, 0.78);
    border: 1px solid rgba(81, 94, 158, 0.16);
    border-radius: 14px;
}

QLabel#ChatStripTitle {
    color: #eef1ff;
    font-size: 10pt;
    font-weight: 700;
}

QLabel#ChatStripMeta {
    color: #97a0c4;
    font-size: 9pt;
}

QLabel#ChatStripSeparator {
    color: rgba(255, 109, 183, 0.45);
    font-size: 10pt;
}

QPushButton#ChatStripGhostButton {
    background-color: rgba(18, 24, 40, 0.68);
    color: #ebedff;
    border: 1px solid rgba(85, 99, 165, 0.16);
    border-radius: 12px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 600;
}

QPushButton#ChatStripGhostButton:hover {
    background-color: rgba(255, 109, 183, 0.10);
    border: 1px solid rgba(255, 109, 183, 0.28);
}

QFrame#SandboxInspectorTabHeader,
QWidget#SandboxInspectorTabHost,
QStackedWidget#SandboxInspectorStack,
QWidget#SandboxInspectorTabPage {
    background: transparent;
}

QPushButton#SandboxInspectorTabButton {
    background: transparent;
    color: #9ba3c6;
    border: none;
    border-radius: 14px;
    padding: 8px 16px;
    font-size: 9.5pt;
    font-weight: 700;
    text-align: center;
}

QPushButton#SandboxInspectorTabButton:hover {
    color: #eef1ff;
    background-color: rgba(255, 255, 255, 0.03);
}

QPushButton#SandboxInspectorTabButton[active="true"] {
    color: #f5f2ff;
    background-color: rgba(255, 109, 183, 0.10);
    border-bottom: 2px solid #ff6db7;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}

QPushButton#SandboxInspectorCollapseBtn {
    background-color: rgba(255, 109, 183, 0.12);
    color: #ffd6ee;
    border: none;
    border-radius: 17px;
    min-width: 34px;
    min-height: 34px;
    max-width: 34px;
    max-height: 34px;
    font-weight: 700;
    padding: 0;
}
QPushButton#SandboxInspectorCollapseBtn:hover {
    background-color: rgba(255, 109, 183, 0.18);
}
QPushButton#SandboxInspectorCollapseBtn:pressed {
    background-color: rgba(255, 109, 183, 0.24);
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
    color: #eef1ff;
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
    border: 1px solid rgba(89, 103, 166, 0.34);
    background-color: rgba(255, 255, 255, 0.06);
}

QCheckBox#SandboxCaptureToggle::indicator:checked {
    background-color: #ff6db7;
    border: 1px solid rgba(255, 109, 183, 0.82);
}
"""
