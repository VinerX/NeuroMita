from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LauncherShellPalette:
    root_bg: str = "#07050d"
    panel_bg: str = "rgba(12, 10, 20, 0.985)"
    panel_soft: str = "rgba(18, 14, 30, 0.96)"
    card_bg: str = "rgba(24, 16, 38, 0.90)"
    card_alt_bg: str = "rgba(20, 13, 31, 0.94)"
    border: str = "rgba(255, 120, 188, 0.16)"
    border_strong: str = "rgba(255, 120, 188, 0.30)"
    text: str = "#f5e8f7"
    muted: str = "#c8aac6"
    accent: str = "#ff5ca8"
    accent_soft: str = "rgba(255, 92, 168, 0.14)"
    accent_hover: str = "#ff74b8"
    accent_pressed: str = "#ea4c96"
    success: str = "#89f7b2"
    warning: str = "#ffcf7d"
    danger: str = "#ff7a98"
    link: str = "#89dbff"


PALETTE = LauncherShellPalette()


def resolve_launcher_asset(name: str) -> str | None:
    asset_path = Path("assets") / "launcher_ui" / name
    return str(asset_path) if asset_path.exists() else None


def get_launcher_shell_stylesheet() -> str:
    p = PALETTE
    bg_rule = """
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #160b1c,
            stop: 0.36 #0e0915,
            stop: 1 #050409
        );
    """
    return f"""
    QWidget#LauncherShellRoot {{
        background: transparent;
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
    }}
    QWidget#LauncherShellPage {{
        background: transparent;
    }}
    QFrame#LauncherShellBackdrop {{
        {bg_rule}
        border-radius: 28px;
        border: 1px solid rgba(255, 255, 255, 0.04);
    }}
    QScrollArea#LauncherShellScrollArea,
    QScrollArea#LauncherShellScrollArea > QWidget,
    QScrollArea#LauncherShellScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QFrame#LauncherShellPage,
    QFrame#LauncherShellSectionCard,
    QFrame#LauncherShellPromoCard,
    QFrame#LauncherShellStatusCard,
    QFrame#LauncherShellSocialCard,
    QFrame#LauncherShellHeroCard,
    QFrame#LauncherShellMetricCard,
    QFrame#LauncherShellNewsCard,
    QFrame#LauncherShellLogCard {{
        background-color: {p.card_bg};
        border: 1px solid {p.border};
        border-radius: 22px;
    }}
    QFrame#LauncherShellSidebar {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 rgba(15, 11, 24, 0.99),
            stop: 1 rgba(10, 8, 18, 0.995)
        );
        border: none;
        border-right: 1px solid rgba(255, 120, 188, 0.14);
        border-radius: 0px;
    }}
    QFrame#LauncherShellNavHost,
    QFrame#LauncherShellBrandRow,
    QFrame#LauncherShellDivider {{
        background: transparent;
        border: none;
        border-radius: 0px;
    }}
    QFrame#LauncherShellDivider {{
        min-height: 1px;
        max-height: 1px;
        background-color: rgba(255, 255, 255, 0.12);
    }}
    QLabel#LauncherShellEyebrow {{
        color: {p.accent_hover};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellTitle {{
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 26px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellSubtitle,
    QLabel#LauncherShellMeta,
    QLabel#LauncherShellHint,
    QLabel#LauncherShellBody {{
        color: {p.muted};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 13px;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellSectionTitle {{
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellSectionValue {{
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 17px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellStatusDot {{
        min-width: 10px;
        max-width: 10px;
        min-height: 10px;
        max-height: 10px;
        border-radius: 5px;
        background-color: {p.success};
    }}
    QPushButton#LauncherShellNavButton {{
        background-color: transparent;
        color: {p.muted};
        border: 1px solid transparent;
        border-radius: 16px;
        padding: 13px 14px;
        font-family: "Segoe UI", "Arial", sans-serif;
        text-align: left;
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellNavButton:hover {{
        background-color: rgba(255, 255, 255, 0.03);
        border: 1px solid transparent;
        color: {p.text};
    }}
    QPushButton#LauncherShellNavButton[active="true"] {{
        background-color: rgba(255, 92, 168, 0.72);
        border: 1px solid {p.border_strong};
        color: {p.text};
    }}
    QPushButton#LauncherShellActionButton,
    QPushButton#LauncherShellPromoButton {{
        background-color: {p.accent};
        color: white;
        border: 1px solid rgba(255, 92, 168, 0.42);
        border-radius: 14px;
        padding: 10px 14px;
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellActionButton:hover,
    QPushButton#LauncherShellPromoButton:hover {{
        background-color: {p.accent_hover};
    }}
    QPushButton#LauncherShellActionButton:pressed,
    QPushButton#LauncherShellPromoButton:pressed {{
        background-color: {p.accent_pressed};
    }}
    QPushButton#LauncherShellGhostButton,
    QPushButton#LauncherShellChipButton {{
        background-color: rgba(255, 255, 255, 0.04);
        color: {p.text};
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px;
        padding: 9px 12px;
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellGhostButton:hover,
    QPushButton#LauncherShellChipButton:hover {{
        background-color: {p.accent_soft};
        border: 1px solid {p.border};
    }}
    QPushButton#LauncherShellSocialButton {{
        background: transparent;
        border: none;
        border-radius: 10px;
        padding: 4px;
    }}
    QPushButton#LauncherShellSocialButton:hover {{
        background-color: {p.accent_soft};
    }}
    QWidget#LauncherShellSocialBlock,
    QWidget#LauncherShellFooterBlock {{
        background: transparent;
    }}
    QFrame#LauncherShellSocialIconCard {{
        background-color: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 16px;
        padding: 6px;
    }}
    QFrame#LauncherShellBrandRow {{
        background: transparent;
        border: none;
    }}
    QLabel#LauncherShellBrandTitle {{
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 16px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellBrandSubtitle {{
        color: {p.muted};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellLangPill {{
        background-color: rgba(255, 255, 255, 0.02);
        color: {p.text};
        border: 1px solid rgba(255, 120, 188, 0.26);
        border-radius: 12px;
        padding: 0;
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellLangPill:hover {{
        background-color: {p.accent_soft};
        color: {p.text};
        border: 1px solid {p.border};
    }}
    QPushButton#LauncherShellLangPill[active="true"] {{
        background-color: {p.accent};
        color: white;
        border: 1px solid rgba(255, 92, 168, 0.42);
    }}
    QLabel#LauncherShellVersionLabel {{
        color: {p.muted};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 11px;
        letter-spacing: 0px;
    }}
    QScrollArea#LauncherShellScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        width: 10px;
        background: transparent;
        margin: 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255, 167, 214, 0.22);
        border-radius: 5px;
        min-height: 28px;
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0px;
    }}
    """
