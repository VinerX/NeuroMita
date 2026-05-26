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
    border: 1px solid {border_soft};
    border-radius: 18px;
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
QPushButton#AIHubClose {
    background: rgba(255,255,255,0.04);
    border: 1px solid {border_soft};
    border-radius: 10px;
}
QPushButton#AIHubClose:hover {
    background: rgba(255,123,123,0.12);
    border: 1px solid rgba(255,123,123,0.30);
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
    letter-spacing: 1.4px;
    padding: 2px 4px;
}
QLabel#AIHubSidebarStatus {
    color: {muted};
    font-size: 10.5px;
    padding: 4px 6px;
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
    font-size: 12.5px;
    font-weight: 500;
    background: transparent;
}
QFrame#AIHubCategoryButton[selected="true"] QLabel#AIHubCategoryLabel {
    color: {text};
    font-weight: 600;
}
QLabel#AIHubCategoryCount {
    color: {muted};
    background: rgba(255,255,255,0.05);
    padding: 1px 8px;
    border-radius: 8px;
    font-size: 10.5px;
    font-weight: 600;
    min-width: 14px;
}
QFrame#AIHubCategoryButton[selected="true"] QLabel#AIHubCategoryCount {
    color: {accent};
    background: rgba({accent_rgb}, 0.15);
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
    font-size: 13.5px;
    font-weight: 700;
}
QLabel#AIHubBannerBody {
    color: {muted};
    font-size: 11.5px;
}

/* ---------- Toolbar (search + sort) ---------- */
QLabel#AIHubSectionTitle {
    color: {text};
    font-size: 16px;
    font-weight: 700;
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
QComboBox#AIHubSort {
    background: {panel_bg};
    color: {text};
    border: 1px solid {outline};
    border-radius: 10px;
    padding: 6px 30px 6px 12px;
    font-size: 12px;
}
QComboBox#AIHubSort:hover {
    border: 1px solid {accent_border};
}
QComboBox#AIHubSort::drop-down {
    border: none;
    width: 24px;
}
QComboBox#AIHubSort QAbstractItemView {
    background: {sidebar_panel};
    color: {text};
    selection-background-color: rgba({accent_rgb}, 0.18);
    border: 1px solid {outline};
    outline: none;
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
QLabel#AIHubCardTitle {
    color: {text};
    font-size: 14.5px;
    font-weight: 700;
}
QLabel#AIHubCardDesc {
    color: {muted};
    font-size: 11.5px;
}

QLabel#AIHubChip {
    background: rgba(255,255,255,0.04);
    color: {text};
    border: 1px solid {outline};
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10.5px;
    font-weight: 500;
}
QLabel#AIHubChipBackend {
    background: rgba({accent_rgb}, 0.10);
    color: {accent};
    border: 1px solid {accent_border};
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10.5px;
    font-weight: 600;
}
QLabel#AIHubChipGpuOk {
    background: rgba(127, 227, 140, 0.08);
    color: {success};
    border: 1px solid rgba(127, 227, 140, 0.30);
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 10.5px;
    font-weight: 600;
}

QLabel#AIHubStatusPill {
    font-size: 11.5px;
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

/* Empty state */
QLabel#AIHubEmpty {
    color: {muted};
    font-size: 12.5px;
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
    font-size: 10.5px;
    font-weight: 500;
}
QLabel#AIHubStatValue {
    color: {text};
    font-size: 15px;
    font-weight: 700;
}
QLabel#AIHubStatSub {
    color: {muted};
    font-size: 10.5px;
}

QPushButton#AIHubPrimary {
    background: {accent};
    color: white;
    border: none;
    border-radius: 10px;
    padding: 9px 18px;
    font-weight: 700;
    font-size: 12.5px;
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
    font-size: 12.5px;
}
QPushButton#AIHubSecondary:hover {
    background: rgba({accent_rgb}, 0.08);
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
