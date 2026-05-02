from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import QWidget


@dataclass(frozen=True)
class LauncherShellPalette:
    root_bg: str = "#07050d"
    panel_bg: str = "rgba(18, 10, 28, 0.96)"
    panel_soft: str = "rgba(31, 16, 43, 0.94)"
    card_bg: str = "rgba(29, 13, 40, 0.92)"
    card_alt_bg: str = "rgba(24, 10, 34, 0.94)"
    border: str = "rgba(255, 120, 188, 0.20)"
    border_strong: str = "rgba(255, 120, 188, 0.34)"
    text: str = "#faedf7"
    muted: str = "#b89bb3"
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
    bg_path = resolve_launcher_asset("bg.jpg")
    bg_rule = (
        f"border-image: url({bg_path.replace('\\', '/')}) 0 0 0 0 stretch stretch;"
        if bg_path
        else """
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #160b1c,
            stop: 0.36 #0e0915,
            stop: 1 #050409
        );
        """
    )
    return f"""
    QWidget#LauncherShellRoot {{
        background-color: {p.root_bg};
        color: {p.text};
        font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
    }}
    QFrame#LauncherShellBackdrop {{
        {bg_rule}
        border-radius: 28px;
        border: 1px solid rgba(255, 255, 255, 0.04);
    }}
    QFrame#LauncherShellSidebar,
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
        background-color: {p.panel_bg};
    }}
    QLabel#LauncherShellEyebrow {{
        color: {p.accent_hover};
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#LauncherShellTitle {{
        color: {p.text};
        font-size: 26px;
        font-weight: 700;
    }}
    QLabel#LauncherShellSubtitle,
    QLabel#LauncherShellMeta,
    QLabel#LauncherShellHint,
    QLabel#LauncherShellBody {{
        color: {p.muted};
        font-size: 13px;
    }}
    QLabel#LauncherShellSectionTitle {{
        color: {p.text};
        font-size: 15px;
        font-weight: 700;
    }}
    QLabel#LauncherShellSectionValue {{
        color: {p.text};
        font-size: 17px;
        font-weight: 700;
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
        border-radius: 18px;
        padding: 12px 14px;
        text-align: left;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton#LauncherShellNavButton:hover {{
        background-color: {p.accent_soft};
        border: 1px solid rgba(255, 255, 255, 0.05);
        color: {p.text};
    }}
    QPushButton#LauncherShellNavButton[active="true"] {{
        background-color: rgba(255, 92, 168, 0.18);
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
        font-size: 13px;
        font-weight: 700;
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
    QPushButton#LauncherShellSocialButton,
    QPushButton#LauncherShellChipButton {{
        background-color: rgba(255, 255, 255, 0.04);
        color: {p.text};
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px;
        padding: 9px 12px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#LauncherShellGhostButton:hover,
    QPushButton#LauncherShellSocialButton:hover,
    QPushButton#LauncherShellChipButton:hover {{
        background-color: {p.accent_soft};
        border: 1px solid {p.border};
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


def apply_launcher_shell_theme(widget: QWidget) -> QWidget:
    widget.setStyleSheet(get_launcher_shell_stylesheet())
    return widget
