from __future__ import annotations

from styles.main_styles import get_stylesheet as get_main_stylesheet
from styles.theme import get_theme
from utils import render_qss


AI_HUB_TEMPLATE = """
/* ===== AI Hub — rounded modal, sidebar, model cards, stat tiles ===== */

QDialog#AIHubDialog {
    background: transparent;
}

QFrame#AIHubRoot {
    background: {bg_root};
    border: none;
}

/* ---------- Header ---------- */
QLabel#AIHubTitle {
    color: {text};
    font-size: 22px;
    font-weight: 800;
}
QLabel#AIHubSubtitle {
    color: {muted};
    font-size: 12px;
}
QLabel#AIHubIconBadge {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba({accent_rgb}, 0.22),
        stop:1 rgba({accent_rgb}, 0.08));
    border-radius: 12px;
    border: 1px solid {accent_border};
}
/* ---------- Sidebar ---------- */
QFrame#AIHubSidebar {
    background: {sidebar_panel};
    border: 1px solid {outline};
    border-radius: 14px;
}
QLabel#AIHubSidebarHeader {
    color: {muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 4px;
}
QLabel#AIHubSidebarStatus {
    color: {muted};
    font-size: 10px;
    padding: 4px 6px;
}
QLabel#AIHubSectionHeader {
    color: {text};
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.4px;
    padding: 12px 2px 6px 2px;
    border-bottom: 1px solid {outline};
}
QLabel#AIHubSectionHeader[first="true"] {
    padding-top: 2px;
}
QFrame#AIHubActivityPanel {
    background: rgba(255,255,255,0.02);
    border: 1px solid {outline};
    border-radius: 12px;
}

QFrame#AIHubQueuePanel {
    background: rgba({accent_rgb}, 0.05);
    border: 1px solid {outline};
    border-radius: 10px;
}
QFrame#AIHubQueueRow {
    background: transparent;
    border: none;
}
QLabel#AIHubQueueRunning {
    color: {text};
    font-size: 11px;
    font-weight: 600;
}
QLabel#AIHubQueuePending {
    color: {muted};
    font-size: 11px;
}
QPushButton#AIHubQueueCancel {
    background: transparent;
    color: {muted};
    border: none;
    border-radius: 9px;
    font-size: 11px;
    font-weight: 700;
    padding: 0;
}
QPushButton#AIHubQueueCancel:hover {
    background: rgba({accent_rgb}, 0.15);
    color: {text};
}

QFrame#AIHubCategoryButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
}
QFrame#AIHubCategoryButton:hover {
    background: rgba(255,255,255,0.04);
}
QFrame#AIHubCategoryButton[selected="true"] {
    background: rgba({accent_rgb}, 0.10);
    border: 1px solid {accent_border};
}
QLabel#AIHubCategoryLabel {
    color: {muted};
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}
QFrame#AIHubCategoryButton[selected="true"] QLabel#AIHubCategoryLabel {
    color: {text};
    font-weight: 600;
}
QLabel#AIHubCategoryCount {
    color: {muted};
    background: rgba(255,255,255,0.06);
    border-radius: 10px;
    padding: 0px 0px;
    font-size: 10px;
    font-weight: 700;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
}
QFrame#AIHubCategoryButton[selected="true"] QLabel#AIHubCategoryCount {
    color: {accent};
    background: rgba({accent_rgb}, 0.18);
}

QPushButton#AIHubSidebarBtn {
    background: {panel_bg};
    color: {text};
    border: 1px solid {outline};
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
    font-size: 12px;
    text-align: left;
}
QPushButton#AIHubSidebarBtn:hover {
    background: rgba({accent_rgb}, 0.10);
    color: {text};
    border: 1px solid {accent_border};
}
QPushButton#AIHubSidebarBtn:disabled {
    background: #20212b;
    color: #77727c;
    border: 1px solid #30313a;
}

QFrame#AIHubHint {
    background: rgba({accent_rgb}, 0.06);
    border: 1px solid {accent_border};
    border-radius: 12px;
}
QLabel#AIHubHintTitle {
    color: {accent};
    font-size: 12px;
    font-weight: 700;
}
QLabel#AIHubHintBody {
    color: {muted};
    font-size: 11px;
}

/* ---------- Banner ---------- */
QFrame#AIHubBanner {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba({accent_rgb}, 0.14),
        stop:1 rgba(124, 58, 237, 0.08));
    border: 1px solid {accent_border};
    border-radius: 14px;
}
QLabel#AIHubBannerIcon {
    background: rgba({accent_rgb}, 0.16);
    border-radius: 10px;
}
QLabel#AIHubBannerTitle {
    color: {text};
    font-size: 13px;
    font-weight: 700;
}
QLabel#AIHubBannerBody {
    color: {muted};
    font-size: 11px;
}

/* ---------- Tabs (Install / Settings) ---------- */
QPushButton#AIHubTabBtn {
    background: transparent;
    color: {muted};
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 7px 18px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#AIHubTabBtn:hover {
    color: {text};
    background: rgba(255,255,255,0.04);
}
QPushButton#AIHubTabBtn[active="true"] {
    color: {text};
    background: rgba({accent_rgb}, 0.14);
    border: 1px solid {accent_border};
}

/* ---------- Backend filter pills ---------- */
QPushButton#AIHubFilterPill {
    background: {panel_bg};
    color: {muted};
    border: 1px solid {outline};
    border-radius: 14px;
    padding: 5px 12px;
    font-weight: 600;
    font-size: 11px;
}
QPushButton#AIHubFilterPill:hover {
    color: {text};
    border: 1px solid {accent_border};
}
QPushButton#AIHubFilterPill[active="true"] {
    color: white;
    background: {accent};
    border: 1px solid {accent};
}

/* ---------- Toolbar (search + sort) ---------- */
QLabel#AIHubSectionTitle {
    color: {text};
    font-size: 19px;
    font-weight: 700;
}
QLabel#AIHubToolbarLabel {
    color: {muted};
    font-size: 11px;
    font-weight: 600;
    padding-right: 2px;
}
QLineEdit#AIHubSearch {
    background: {panel_bg};
    color: {text};
    border: 1px solid {outline};
    border-radius: 10px;
    padding: 7px 12px 7px 32px;
    font-size: 12px;
}
QLineEdit#AIHubSearch:focus {
    border: 1px solid {accent_border};
    background: rgba({accent_rgb}, 0.04);
}

/* ---------- Model list ---------- */
QScrollArea#AIHubScroll {
    background: transparent;
    border: none;
}
QScrollArea#AIHubScroll > QWidget > QWidget { background: transparent; }
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: {scroll_handle};
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: rgba({accent_rgb}, 0.45); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QFrame#AIHubModelCard {
    background: {card_bg};
    border: 1px solid {outline};
    border-radius: 14px;
}
QFrame#AIHubModelCard:hover {
    background: {card_alt_bg};
    border: 1px solid {accent_border};
}
QFrame#AIHubModelCard[state="incompatible"] {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.04);
}
QFrame#AIHubModelCard[state="incompatible"] QLabel#AIHubCardTitle,
QFrame#AIHubModelCard[state="incompatible"] QLabel#AIHubCardDesc {
    color: rgba(243, 237, 246, 0.45);
}
QFrame#AIHubModelCard[state="installed"] {
    border: 1px solid rgba(127, 227, 140, 0.20);
}
QLabel#AIHubCardTitle {
    color: {text};
    font-size: 14px;
    font-weight: 700;
}
QLabel#AIHubCardDesc {
    color: {muted};
    font-size: 11px;
}

QLabel#AIHubChip {
    background: rgba(255,255,255,0.04);
    color: {text};
    border: 1px solid {outline};
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10px;
    font-weight: 500;
}
QLabel#AIHubChipBackend {
    background: rgba({accent_rgb}, 0.10);
    color: {accent};
    border: 1px solid {accent_border};
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#AIHubChipGpuOk {
    background: rgba(127, 227, 140, 0.08);
    color: {success};
    border: 1px solid rgba(127, 227, 140, 0.30);
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#AIHubChipMulti {
    background: rgba({accent_rgb}, 0.08);
    color: {accent};
    border: 1px solid {accent_border};
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#AIHubChipDanger {
    background: rgba(255, 123, 123, 0.10);
    color: {warn_text};
    border: 1px solid rgba(255, 123, 123, 0.40);
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#AIHubChipOnnx {
    background: rgba(245, 134, 64, 0.10);
    color: #f4a766;
    border: 1px solid rgba(245, 134, 64, 0.40);
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#AIHubChipNotRecommended {
    background: rgba(245, 166, 35, 0.10);
    color: #f0b45d;
    border: 1px solid rgba(245, 166, 35, 0.42);
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#AIHubStatusInstalled {
    color: {success};
    font-size: 11px;
    font-weight: 700;
    padding-right: 4px;
}

QLabel#AIHubStatusUpdate {
    color: {accent};
    font-size: 11px;
    font-weight: 700;
    padding-right: 4px;
}

QLabel#AIHubStatusPill {
    font-size: 11px;
    font-weight: 600;
}

QPushButton#AIHubCardPrimary {
    background: {accent};
    color: white;
    border: none;
    border-radius: 9px;
    padding: 7px 16px;
    font-weight: 700;
    font-size: 12px;
    min-width: 112px;
}
QPushButton#AIHubCardPrimary:hover { background: {accent_hover}; }
QPushButton#AIHubCardPrimary:pressed { background: {accent_pressed}; }
QPushButton#AIHubCardPrimary:disabled {
    background: #24252f;
    color: #77727c;
    border: 1px solid #34353f;
}
QPushButton#AIHubCardDanger {
    background: rgba(255,123,123,0.06);
    color: {warn_text};
    border: 1px solid rgba(255,123,123,0.22);
    border-radius: 9px;
    padding: 7px 16px;
    font-weight: 700;
    font-size: 12px;
    min-width: 112px;
}
QPushButton#AIHubCardDanger:hover { background: rgba(255,123,123,0.14); }

QPushButton#AIHubCardUnavailable {
    background: #24252f;
    color: #77727c;
    border: 1px solid #34353f;
    border-radius: 9px;
    padding: 7px 16px;
    font-weight: 700;
    font-size: 12px;
    min-width: 112px;
}

QPushButton#AIHubCardMenuBtn {
    background: {panel_bg};
    color: {text};
    border: 1px solid {outline};
    border-radius: 9px;
    font-size: 16px;
    font-weight: 700;
}
QPushButton#AIHubCardMenuBtn:hover {
    background: rgba({accent_rgb}, 0.12);
    border: 1px solid {accent_border};
}
QPushButton#AIHubCardMenuBtn:disabled {
    background: #24252f;
    color: #77727c;
    border: 1px solid #34353f;
}
QMenu#AIHubCardMenu {
    background: {sidebar_panel};
    color: {text};
    border: 1px solid {outline};
    padding: 4px;
}
QMenu#AIHubCardMenu::item {
    padding: 6px 14px 6px 24px;
    border-radius: 6px;
}
QMenu#AIHubCardMenu::item:selected {
    background: rgba({accent_rgb}, 0.16);
    color: {text};
}

/* Empty state */
QLabel#AIHubEmpty {
    color: {muted};
    font-size: 12px;
    padding: 40px 0;
}

/* ---------- Footer stats + actions ---------- */
QFrame#AIHubStat {
    background: {card_bg};
    border: 1px solid {outline};
    border-radius: 12px;
}
QLabel#AIHubStatIcon {
    background: rgba({accent_rgb}, 0.10);
    border-radius: 8px;
}
QLabel#AIHubStatLabel {
    color: {muted};
    font-size: 10px;
    font-weight: 500;
}
QLabel#AIHubStatValue {
    color: {text};
    font-size: 15px;
    font-weight: 700;
}
QLabel#AIHubStatSub {
    color: {muted};
    font-size: 10px;
}

QPushButton#AIHubPrimary {
    background: {accent};
    color: white;
    border: none;
    border-radius: 10px;
    padding: 9px 18px;
    font-weight: 700;
    font-size: 12px;
}
QPushButton#AIHubPrimary:hover { background: {accent_hover}; }
QPushButton#AIHubPrimary:pressed { background: {accent_pressed}; }
QPushButton#AIHubPrimary:disabled {
    background: {btn_disabled_bg};
    color: {btn_disabled_fg};
}
QPushButton#AIHubSecondary {
    background: {panel_bg};
    color: {text};
    border: 1px solid {outline};
    border-radius: 10px;
    padding: 9px 18px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton#AIHubSecondary:hover {
    background: rgba({accent_rgb}, 0.08);
    border: 1px solid {accent_border};
}
QPushButton#AIHubSecondary:disabled {
    background: #20212b;
    color: #77727c;
    border: 1px solid #30313a;
}

QFrame#AIHubCheckIndicator {
    background: rgba({accent_rgb}, 0.08);
    border: 1px solid rgba({accent_rgb}, 0.20);
    border-radius: 10px;
}
QPushButton#AIHubCheckSpinner:disabled {
    background: transparent;
    border: none;
    padding: 0;
}
QLabel#AIHubCheckText {
    color: {muted};
    font-size: 11px;
    font-weight: 600;
}

/* ---------- Settings panel ---------- */
QFrame#AIHubSettingsList {
    background: {sidebar_panel};
    border: 1px solid {outline};
    border-radius: 14px;
}
QLabel#AIHubSettingsListHeader {
    color: {muted};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.4px;
}
QListWidget#AIHubSettingsModelList {
    background: transparent;
    border: none;
    outline: 0;
    color: {text};
    font-size: 12px;
}
QListWidget#AIHubSettingsModelList::item {
    padding: 8px 10px;
    margin: 2px 0;
    border-radius: 8px;
}
QListWidget#AIHubSettingsModelList::item:hover {
    background: rgba(255,255,255,0.04);
}
QListWidget#AIHubSettingsModelList::item:selected {
    background: rgba({accent_rgb}, 0.16);
    color: {text};
}

QFrame#AIHubSettingsForm {
    background: {card_bg};
    border: 1px solid {outline};
    border-radius: 14px;
}
QLabel#AIHubSettingsTitle {
    color: {text};
    font-size: 17px;
    font-weight: 700;
}
QLabel#AIHubSettingsSubtitle {
    color: {muted};
    font-size: 11px;
}
QLabel#AIHubSettingsDirtyDot {
    color: {accent};
    font-size: 14px;
    font-weight: 700;
}
QLabel#AIHubSettingsStatus {
    color: {muted};
    font-size: 11px;
}
QLabel#AIHubSettingsEmpty {
    color: {muted};
    font-size: 12px;
}

QScrollArea#AIHubSettingsScroll {
    background: transparent;
    border: none;
}
QScrollArea#AIHubSettingsScroll > QWidget > QWidget { background: transparent; }

QFrame#AIHubSchemaForm {
    background: transparent;
}
QLabel#AIHubFormLabel {
    color: {text};
    font-size: 12px;
    font-weight: 600;
}
QLabel#AIHubFormHelp {
    color: {muted};
    font-size: 11px;
}
QLabel#AIHubFormError {
    color: {warn_text};
    font-size: 11px;
    font-weight: 600;
}

QFrame#AIHubSchemaForm QLineEdit,
QFrame#AIHubSchemaForm QComboBox,
QFrame#AIHubSchemaForm QSpinBox {
    background: {panel_bg};
    color: {text};
    border: 1px solid {outline};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
    min-height: 22px;
}
QFrame#AIHubSchemaForm QLineEdit:focus,
QFrame#AIHubSchemaForm QComboBox:focus,
QFrame#AIHubSchemaForm QSpinBox:focus {
    border: 1px solid {accent_border};
}
QFrame#AIHubSchemaForm QLineEdit[hasError="true"],
QFrame#AIHubSchemaForm QComboBox[hasError="true"],
QFrame#AIHubSchemaForm QSpinBox[hasError="true"] {
    border: 1px solid rgba(255,123,123,0.55);
    background: rgba(255,123,123,0.06);
}
QFrame#AIHubSchemaForm QCheckBox {
    background: transparent;
    border: none;
    color: {text};
    font-size: 12px;
    spacing: 6px;
    padding: 2px 0;
}

/* ---------- Нижняя плашка установки (Steam-style, #25) ---------- */
QFrame#AIHubInstallBar {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid {panel_border};
    border-radius: 12px;
}
QLabel#AIHubInstallBarTitle {
    color: {text};
    font-size: 12px;
    font-weight: 700;
}
QLabel#AIHubInstallBarDetail {
    color: {muted};
    font-size: 11px;
}
QProgressBar#AIHubInstallBarProgress {
    background: rgba(255, 255, 255, 0.06);
    border: none;
    border-radius: 4px;
}
QProgressBar#AIHubInstallBarProgress::chunk {
    background: {accent};
    border-radius: 4px;
}
/* Чип «+N в очереди» и кнопка возврата к логам — в нижней плашке. */
QLabel#AIHubInstallBarQueue {
    color: {muted};
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid {panel_border};
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#AIHubInstallBarLogsBtn {
    color: {text};
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {panel_border};
    border-radius: 9px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#AIHubInstallBarLogsBtn:hover {
    background: rgba({accent_rgb}, 0.14);
    border: 1px solid {accent_border};
}
"""


def get_stylesheet(overrides: dict | None = None) -> str:
    theme = get_theme()
    if overrides:
        theme.update(overrides)
    base = get_main_stylesheet(overrides)
    hub = render_qss(AI_HUB_TEMPLATE, theme)
    return base + "\n\n" + hub
