from __future__ import annotations

MAIN_WINDOW_SHELL_QSS = r"""
QFrame#LauncherContentHost,
QStackedWidget#MainPageStack,
QStackedWidget#MainPageStack > QWidget {
    background: transparent;
    border: none;
}

QFrame#LauncherBrandCard,
QFrame#LauncherFooterCard {
    background-color: rgba({sidebar_panel_rgb}, 0.94);
    border: 1px solid rgba({accent_rgb}, 0.20);
    border-radius: 20px;
}

QFrame#LauncherBrandCard {
    background-color: rgba({settings_panel_rgb}, 0.98);
}

QLabel#LauncherBrandTitle {
    font-size: 17pt;
    font-weight: 800;
    color: {text};
}

QLabel#LauncherBrandSubtitle,
QLabel#LauncherFooterHint {
    color: {muted};
    font-size: 9pt;
}

QLabel#LauncherFooterStatus {
    color: {accent_alt};
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

QFrame#LauncherSpotlightCard {
    background-color: rgba({settings_panel_rgb}, 0.94);
    border: 1px solid rgba({accent_rgb}, 0.18);
    border-radius: 22px;
}

QLabel#LauncherSpotlightArt {
    min-width: 240px;
    min-height: 170px;
    border-radius: 18px;
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    color: {text};
    font-size: 18pt;
    font-weight: 800;
}
"""
