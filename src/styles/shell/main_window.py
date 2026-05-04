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
QLabel#LauncherFooterHint {
    color: #c5a8bf;
    font-size: 9pt;
}

QLabel#LauncherFooterStatus {
    color: #ff84bd;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

QFrame#LauncherSpotlightCard {
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
"""
