from __future__ import annotations

CHAT_WIDGETS_QSS = r"""
/* ========= Chat widgets ========= */
QWidget#ChatInputContainer {
    background: transparent;
    border: none;
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
QPushButton#ChatIconMini:hover { background-color: rgba({accent_rgb}, 0.24); }
QPushButton#ChatIconMini:pressed { background-color: rgba({accent_rgb}, 0.36); }

QPushButton#ChatComposerIconBtn {
    background-color: transparent;
    border: none;
    border-radius: 10px;
    padding: 4px;
}
QPushButton#ChatComposerIconBtn:hover { background-color: rgba({accent_rgb}, 0.14); }
QPushButton#ChatComposerIconBtn:pressed { background-color: rgba({accent_rgb}, 0.26); }

QPushButton#ChatSendButtonCircle {
    background-color: {accent};
    border: 0px; border-radius: 14px; padding: 5px;
}
QPushButton#ChatSendButtonCircle:hover { background-color: {accent_hover}; }
QPushButton#ChatSendButtonCircle:pressed { background-color: {accent_pressed}; }
QPushButton#ChatSendButtonCircle:disabled {
    background-color: {btn_disabled_bg}; color: {btn_disabled_fg};
}

QPushButton#ChatSendButtonPill {
    background-color: {accent};
    border: 0px;
    border-radius: 14px;
    padding: 5px;
}
QPushButton#ChatSendButtonPill:hover { background-color: {accent_hover}; }
QPushButton#ChatSendButtonPill:pressed { background-color: {accent_pressed}; }
QPushButton#ChatSendButtonPill:disabled {
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
    background-color: rgba({sandbox_bg_rgb}, 0.995);
    border: none;
}

QFrame#SandboxWorkspaceHeader {
    background: transparent;
    border: none;
}

QFrame#SandboxSelectorDeck,
QFrame#SandboxChatHost {
    background-color: rgba({settings_panel_rgb}, 0.97);
    border: 1px solid rgba({accent_rgb}, 0.16);
    border-radius: 20px;
}

QWidget#ChatComposerWrapper {
    background: transparent;
    border: none;
}

QFrame#ChatComposerBar {
    background-color: rgba({settings_panel_rgb}, 0.97);
    border: 1px solid rgba({accent_rgb}, 0.22);
    border-radius: 20px;
}

QFrame#SandboxInspector {
    background-color: rgba({sandbox_bg_rgb}, 0.94);
    border: 1px solid rgba({accent_rgb}, 0.12);
    border-radius: 20px;
}

QFrame#ChatToolbarCard,
QFrame#SandboxSelectorCard {
    background-color: rgba({settings_panel_rgb}, 0.985);
    border: 1px solid rgba({accent_rgb}, 0.18);
    border-radius: 18px;
}

QFrame#SandboxInspectorCard {
    background-color: rgba({settings_panel_rgb}, 0.95);
    border: 1px solid rgba({accent_rgb}, 0.14);
    border-radius: 16px;
}

QLabel#SandboxHeroIcon {
    background: transparent;
    border: none;
}

QLabel#SandboxHeroBadge {
    color: #ffe8f4;
    background-color: rgba({accent_rgb}, 0.10);
    border: 1px solid rgba({accent_rgb}, 0.30);
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
    color: {muted};
    font-size: 9pt;
}

QPushButton#SandboxHeaderButton,
QPushButton#SandboxHeaderPrimaryButton {
    padding: 10px 16px;
    border-radius: 12px;
    font-weight: 700;
}

QPushButton#SandboxHeaderButton {
    background-color: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    color: {text};
}

QPushButton#SandboxHeaderButton:hover {
    background-color: rgba({accent_rgb}, 0.12);
    border: 1px solid rgba({accent_rgb}, 0.24);
}

QPushButton#SandboxHeaderButton:pressed {
    background-color: rgba({accent_rgb}, 0.20);
}

QPushButton#SandboxHeaderPrimaryButton {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba({accent_rgb_alt}, 0.94),
        stop: 1 rgba({slider_progress_rgb}, 0.98)
    );
    border: 1px solid rgba({accent_rgb_alt}, 0.70);
    color: #ffffff;
}

QPushButton#SandboxHeaderPrimaryButton:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba({accent_rgb_alt}, 0.98),
        stop: 1 rgba({accent_rgb}, 0.98)
    );
}

QPushButton#SandboxHeaderPrimaryButton:pressed {
    background-color: rgba({slider_progress_rgb}, 0.90);
}

QLabel#TokenCountLabel {
    color: {muted};
    padding: 0 4px;
    background: transparent;
    border: none;
    font-size: 8pt;
}

QWidget#ChatCharacterHistoryGroup {
    background-color: rgba({settings_panel_rgb}, 0.97);
    border: 1px solid rgba({accent_rgb}, 0.14);
    border-radius: 14px;
}

QCheckBox#StatusIndicator {
    color: {muted};
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
    background-color: rgba({settings_panel_rgb}, 0.95);
    border: 1px solid rgba({accent_rgb}, 0.14);
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
    color: {muted};
    font-size: 9pt;
    font-weight: 600;
}

QLabel#StatusIndicatorText[active="true"] {
    color: {text};
}

QLabel#SandboxInspectorTitle {
    color: {text};
    font-size: 10.5pt;
    font-weight: 800;
}

QLabel#SandboxInspectorLabel,
QLabel#SandboxSelectorLabel {
    color: {muted};
    font-size: 8.5pt;
    font-weight: 700;
    text-transform: uppercase;
}

QLabel#SandboxInspectorValue,
QLabel#SandboxSelectorValue {
    color: {text};
    font-size: 10.5pt;
    font-weight: 700;
}

QLabel#SandboxSelectorHint,
QLabel#SandboxInspectorMeta {
    color: {muted};
    font-size: 9pt;
}

QLabel#SandboxSelectorHintAccent {
    color: #89f7b2;
    font-size: 9pt;
    font-weight: 700;
}

QPushButton#SandboxSelectorJump,
QPushButton#SandboxQuickAction {
    background-color: rgba({sandbox_bg_rgb}, 0.72);
    color: {text};
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    padding: 5px 10px;
    text-align: left;
    font-size: 9.5pt;
    font-weight: 600;
}

QPushButton#SandboxSelectorJump:hover,
QPushButton#SandboxQuickAction:hover {
    background-color: rgba({accent_rgb}, 0.10);
    border: 1px solid rgba({accent_rgb}, 0.28);
}

QPushButton#SandboxQuickAction:pressed {
    background-color: rgba({accent_rgb}, 0.18);
}

QPushButton#SandboxQuickAction[danger="true"] {
    color: #ffd1dc;
    border: 1px solid rgba(255, 110, 140, 0.35);
}

QPushButton#SandboxQuickAction[danger="true"]:hover {
    background-color: rgba(255, 90, 120, 0.18);
    border: 1px solid rgba(255, 110, 140, 0.55);
}

/* ── Character state panel ── */
QLabel#CharacterStatLabel {
    color: {muted};
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 0.3px;
}

QLabel#CharacterStatValue {
    color: {text};
    font-size: 9pt;
    font-weight: 700;
}


QLabel#CharacterStateBadge {
    color: #ffd1dc;
    background-color: rgba(255, 90, 120, 0.18);
    border: 1px solid rgba(255, 110, 140, 0.45);
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 9pt;
    font-weight: 700;
}

QLabel#CharacterStateBadge[kind="active"] {
    color: #d6ffe3;
    background-color: rgba(110, 220, 150, 0.18);
    border: 1px solid rgba(110, 220, 150, 0.45);
}

QLabel#CharacterStateBadge[kind="neutral"] {
    color: {muted};
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.10);
}

QToolButton#SandboxInspectorToggle {
    background: transparent;
    border: none;
    color: {muted};
    font-size: 9pt;
    font-weight: 600;
    padding: 2px 4px;
}

QToolButton#SandboxInspectorToggle:hover {
    color: {text};
}

QPlainTextEdit#SandboxInspectorMonoText {
    background-color: rgba(8, 8, 18, 0.82);
    color: {text};
    border: 1px solid rgba({accent_rgb}, 0.14);
    border-radius: 10px;
    padding: 8px 10px;
    font-family: "Consolas", "Cascadia Mono", "Courier New", monospace;
    font-size: 8.5pt;
    selection-background-color: rgba({accent_rgb}, 0.30);
}

QScrollArea#SandboxInspectorScroll {
    background: transparent;
    border: none;
}

QFrame#ChatConversationStrip {
    background-color: rgba({settings_panel_rgb}, 0.95);
    border: 1px solid rgba({accent_rgb}, 0.14);
    border-radius: 14px;
}

QLabel#ChatStripTitle {
    color: {text};
    font-size: 10pt;
    font-weight: 700;
}

QLabel#ChatStripMeta {
    color: {muted};
    font-size: 9pt;
}

QLabel#ChatStripSeparator {
    color: rgba({accent_rgb}, 0.45);
    font-size: 10pt;
}

QPushButton#ChatStripGhostButton {
    background-color: rgba({sandbox_bg_rgb}, 0.62);
    color: {text};
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 600;
}

QPushButton#ChatStripGhostButton:hover {
    background-color: rgba({accent_rgb}, 0.10);
    border: 1px solid rgba({accent_rgb}, 0.28);
}

QFrame#SandboxInspectorTabHeader,
QWidget#SandboxInspectorTabHost,
QStackedWidget#SandboxInspectorStack,
QWidget#SandboxInspectorTabPage {
    background: transparent;
}

QFrame#SandboxInspectorTabHeader {
    border-bottom: 1px solid rgba(255,255,255,0.05);
    padding-bottom: 6px;
}

QPushButton#SandboxInspectorTabButton {
    background: transparent;
    color: {muted};
    border: none;
    border-radius: 14px;
    padding: 8px 16px;
    font-size: 9.5pt;
    font-weight: 700;
    text-align: center;
}

QPushButton#SandboxInspectorTabButton:hover {
    color: {text};
    background-color: rgba(255, 255, 255, 0.03);
}

QPushButton#SandboxInspectorTabButton[active="true"] {
    color: {text};
    background-color: rgba({accent_rgb}, 0.10);
    border-bottom: 2px solid {accent_alt};
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}

QPushButton#SandboxInspectorCollapseBtn {
    background-color: rgba({accent_rgb}, 0.12);
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
    background-color: rgba({accent_rgb}, 0.18);
}
QPushButton#SandboxInspectorCollapseBtn:pressed {
    background-color: rgba({accent_rgb}, 0.24);
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
    color: {text};
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
    border: 1px solid rgba(255,255,255,0.12);
    background-color: rgba(255, 255, 255, 0.06);
}

QCheckBox#SandboxCaptureToggle::indicator:checked {
    background-color: {accent_alt};
    border: 1px solid rgba({accent_rgb}, 0.82);
}
"""
