from __future__ import annotations

HOME_PAGE_QSS = r"""
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
    color: {text};
    font-size: 30pt;
    font-weight: 800;
    letter-spacing: 0px;
}

QLabel#LauncherHomeSubtitle,
QLabel#LauncherHomeFootnote {
    color: {muted};
    font-size: 12pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeFootnote {
    font-size: 9pt;
    color: {muted};
}

QFrame#LauncherHomeUpdateChip,
QFrame#LauncherHomeNewsPanel,
QFrame#LauncherHomeStatusCard {
    background-color: rgba({settings_panel_rgb}, 0.92);
    border: 1px solid rgba({accent_rgb}, 0.22);
    border-radius: 14px;
}

QFrame#LauncherHomeNewsItem,
QWidget#LauncherHomeNewsItems {
    background: transparent;
    border: none;
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
    color: {text};
    font-size: 10pt;
    letter-spacing: 0px;
}

QPushButton#LauncherHomeLinkButton {
    background: transparent;
    border: none;
    color: {accent_alt};
    font-size: 10pt;
    font-weight: 600;
    letter-spacing: 0px;
    padding: 0;
}

QPushButton#LauncherHomeLinkButton:hover {
    color: {accent_hover};
}

QLabel#LauncherHomeStatusEyebrow,
QLabel#LauncherHomeNewsTitle,
QLabel#LauncherHomeCardTitle {
    color: {accent_alt};
    font-size: 8.5pt;
    font-weight: 800;
    letter-spacing: 0px;
    text-transform: uppercase;
}

QLabel#LauncherHomeStatusValue {
    color: {text};
    font-size: 14pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QPushButton#LauncherHomePrimaryButton {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {accent},
        stop: 1 {slider_progress}
    );
    border: 1px solid rgba({accent_rgb_alt}, 0.42);
    border-top-left-radius: 16px;
    border-bottom-left-radius: 16px;
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
    color: #ffffff;
    padding: 16px 22px;
    font-size: 16pt;
    font-weight: 800;
    letter-spacing: 0px;
}

QPushButton#LauncherHomePrimaryButton:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {accent_alt},
        stop: 1 {slider_progress}
    );
}

QPushButton#LauncherHomePrimaryButton[mode="progress"]:disabled {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {accent},
        stop: 1 {slider_progress}
    );
    color: #ffffff;
    border: 1px solid rgba({accent_rgb_alt}, 0.42);
}

QPushButton#LauncherHomePrimaryButton[mode="unavailable"]:disabled {
    background-color: rgba({settings_panel_rgb}, 0.90);
    color: {muted};
    border: 1px solid rgba({accent_rgb}, 0.18);
}

QPushButton#LauncherHomeMenuButton {
    min-width: 44px;
    background-color: rgba({sidebar_panel_rgb}, 0.96);
    border: 1px solid rgba({accent_rgb}, 0.18);
    border-left: 1px solid rgba(255, 255, 255, 0.10);
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    border-top-right-radius: 16px;
    border-bottom-right-radius: 16px;
    color: {text};
    font-size: 16pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QPushButton#LauncherHomeMenuButton[hasUpdate="true"] {
    border: 1px solid rgba(255, 207, 125, 0.55);
    background-color: rgba(255, 207, 125, 0.10);
}

QPushButton#LauncherHomeMenuButton:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba({sidebar_panel_rgb}, 0.96),
        stop: 1 rgba({settings_panel_rgb}, 0.98)
    );
    border: 1px solid rgba({accent_rgb}, 0.34);
    border-left: 1px solid rgba(255, 255, 255, 0.14);
}

QPushButton#LauncherHomeMenuButton[mode="cancel"] {
    background-color: rgba(185, 57, 91, 0.72);
    border-color: rgba(255, 130, 160, 0.65);
}

QPushButton#LauncherHomeMenuButton[mode="locked"]:disabled {
    background-color: rgba({sidebar_panel_rgb}, 0.84);
    border-color: rgba({accent_rgb}, 0.10);
}

QPushButton#LauncherHomeVerifyButton:hover {
    background-color: rgba({settings_panel_rgb}, 0.96);
    border: 1px solid rgba({accent_rgb}, 0.28);
}

QPushButton#LauncherHomeVerifyButton {
    min-height: 46px;
    background-color: rgba({settings_panel_rgb}, 0.94);
    border: 1px solid rgba({accent_rgb}, 0.16);
    border-radius: 14px;
    color: {text};
    text-align: left;
    padding: 12px 14px;
    font-size: 10pt;
    font-weight: 600;
    letter-spacing: 0px;
}

QFrame#LauncherHomeDivider {
    background-color: rgba({accent_rgb}, 0.30);
}

QLabel#LauncherHomeNewsItemTitle {
    color: {text};
    font-size: 10pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsItemBody {
    color: {muted};
    font-size: 8.5pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsDate {
    color: {muted};
    font-size: 8pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsBadge {
    background-color: {accent};
    border-radius: 8px;
    color: #ffffff;
    padding: 2px 8px;
    font-size: 7.5pt;
    font-weight: 800;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewBadge {
    background-color: rgba(255, 207, 125, 0.16);
    border: 1px solid rgba(255, 207, 125, 0.55);
    border-radius: 7px;
    color: #ffcf7d;
    padding: 1px 7px;
    font-size: 7.5pt;
    font-weight: 800;
    letter-spacing: 0.4px;
}

QCheckBox#LauncherHomeStatusCheck {
    background: transparent;
    spacing: 0;
}
QCheckBox#LauncherHomeStatusCheck::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid rgba({accent_rgb}, 0.55);
    background-color: rgba({settings_panel_rgb}, 0.65);
}
QCheckBox#LauncherHomeStatusCheck::indicator:checked {
    background-color: {accent};
    border: 1px solid {accent};
    image: url(assets/launcher_ui/check.svg);
}
"""
