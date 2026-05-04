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
    color: #ffffff;
    font-size: 30pt;
    font-weight: 800;
    letter-spacing: 0px;
}

QLabel#LauncherHomeSubtitle,
QLabel#LauncherHomeFootnote {
    color: #e2bccb;
    font-size: 12pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeFootnote {
    font-size: 9pt;
    color: #c39aab;
}

QProgressBar#LauncherHomeProgressBar {
    background-color: rgba(20, 8, 13, 0.78);
    border: 1px solid rgba(255, 92, 158, 0.30);
    border-radius: 5px;
    text-align: center;
}
QProgressBar#LauncherHomeProgressBar::chunk {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #ff80a9,
        stop: 1 #c81663
    );
    border-radius: 5px;
}

QLabel#LauncherHomeProgressLabel {
    color: #ffd2ec;
    font-size: 9pt;
    font-weight: 600;
}

QFrame#LauncherHomeUpdateChip,
QFrame#LauncherHomeNewsPanel,
QFrame#LauncherHomeStatusCard {
    background-color: rgba(20, 8, 13, 0.78);
    border: 1px solid rgba(255, 92, 158, 0.30);
    border-radius: 14px;
}

QFrame#LauncherHomeNewsItem {
    background: transparent;
    border: none;
    border-radius: 0;
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
    color: #f5e2e8;
    font-size: 10pt;
    letter-spacing: 0px;
}

QPushButton#LauncherHomeLinkButton {
    background: transparent;
    border: none;
    color: #ff80a9;
    font-size: 10pt;
    font-weight: 600;
    letter-spacing: 0px;
    padding: 0;
}

QPushButton#LauncherHomeLinkButton:hover {
    color: #ff9ec0;
}

QLabel#LauncherHomeStatusEyebrow,
QLabel#LauncherHomeNewsTitle,
QLabel#LauncherHomeCardTitle {
    color: #f5c9d4;
    font-size: 8.5pt;
    font-weight: 800;
    letter-spacing: 0px;
    text-transform: uppercase;
}

QLabel#LauncherHomeStatusValue {
    color: #ffffff;
    font-size: 14pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QPushButton#LauncherHomePrimaryButton {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #ff4d8a,
        stop: 1 #c81663
    );
    border: 1px solid rgba(255, 179, 212, 0.42);
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
        stop: 0 #ff73a8,
        stop: 1 #dd3a76
    );
}

QPushButton#LauncherHomeMenuButton {
    min-width: 44px;
    min-height: 56px;
    background-color: rgba(34, 16, 26, 0.96);
    border: 1px solid rgba(255, 92, 158, 0.22);
    border-left: 1px solid rgba(255, 255, 255, 0.10);
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    border-top-right-radius: 16px;
    border-bottom-right-radius: 16px;
    color: #ffd6e1;
    font-size: 16pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QPushButton#LauncherHomeMenuButton:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(60, 22, 38, 0.96),
        stop: 1 rgba(80, 28, 50, 0.96)
    );
    border: 1px solid rgba(255, 92, 158, 0.42);
    border-left: 1px solid rgba(255, 255, 255, 0.14);
}

QPushButton#LauncherHomeVerifyButton:hover {
    background-color: rgba(42, 16, 25, 0.96);
    border: 1px solid rgba(255, 92, 158, 0.32);
}

QPushButton#LauncherHomeVerifyButton {
    min-height: 46px;
    background-color: rgba(28, 10, 18, 0.94);
    border: 1px solid rgba(255, 92, 158, 0.18);
    border-radius: 14px;
    color: #f5c9d4;
    text-align: left;
    padding: 12px 14px;
    font-size: 10pt;
    font-weight: 600;
    letter-spacing: 0px;
}

QFrame#LauncherHomeDivider {
    background-color: rgba(90, 34, 51, 1);
}

QLabel#LauncherHomeNewsItemTitle {
    color: #ffffff;
    font-size: 10pt;
    font-weight: 700;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsItemBody {
    color: #b08a96;
    font-size: 8.5pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsDate {
    color: #8a6271;
    font-size: 8pt;
    letter-spacing: 0px;
}

QLabel#LauncherHomeNewsBadge {
    background-color: #ff4d8a;
    border-radius: 8px;
    color: #ffffff;
    padding: 2px 8px;
    font-size: 7.5pt;
    font-weight: 800;
    letter-spacing: 0px;
}
"""
