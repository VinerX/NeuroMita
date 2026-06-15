from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QVBoxLayout

from ui.widgets.launcher_shell_theme import PALETTE


_DIALOG_STYLE = f"""
QDialog#LauncherShellDialog {{
    background-color: {PALETTE.root_bg};
    color: {PALETTE.text};
}}
QFrame#LauncherShellCard {{
    background-color: {PALETTE.card_bg};
    border: 1px solid {PALETTE.border};
    border-radius: 22px;
}}
QLabel#LauncherShellEyebrow {{
    color: {PALETTE.accent_hover};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
}}
QLabel#LauncherShellTitle {{
    color: {PALETTE.text};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#LauncherShellBody {{
    color: {PALETTE.muted};
    font-size: 13px;
    line-height: 1.35em;
}}
QLabel#LauncherShellPath {{
    color: {PALETTE.text};
    background-color: {PALETTE.accent_soft};
    border: 1px solid {PALETTE.border};
    border-radius: 14px;
    padding: 10px 12px;
    font-size: 12px;
}}
QPushButton#LauncherShellActionButton {{
    background-color: {PALETTE.accent};
    color: white;
    border: 1px solid {PALETTE.border_strong};
    border-radius: 14px;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 700;
    min-width: 120px;
}}
QPushButton#LauncherShellActionButton:hover {{
    background-color: {PALETTE.accent_hover};
}}
QPushButton#LauncherShellActionButton:pressed {{
    background-color: {PALETTE.accent_pressed};
}}
"""


def _build_shell_dialog(parent, title: str, size: tuple[int, int]) -> tuple[QDialog, QVBoxLayout]:
    dialog = QDialog(parent)
    dialog.setObjectName("LauncherShellDialog")
    dialog.setStyleSheet(_DIALOG_STYLE)
    dialog.setWindowTitle(title)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
    dialog.setFixedSize(*size)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(18, 18, 18, 18)

    card = QFrame()
    card.setObjectName("LauncherShellCard")
    root.addWidget(card)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(10)
    return dialog, layout


def create_ffmpeg_install_popup(parent):
    dialog, layout = _build_shell_dialog(parent, "FFmpeg", (380, 178))

    eyebrow = QLabel("SYSTEM DEPENDENCY")
    eyebrow.setObjectName("LauncherShellEyebrow")
    eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(eyebrow)

    title = QLabel("Установка FFmpeg")
    title.setObjectName("LauncherShellTitle")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)

    label = QLabel("Идет установка FFmpeg...\nПожалуйста, подождите.")
    label.setObjectName("LauncherShellBody")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addStretch()

    return dialog


def show_ffmpeg_error_popup(parent):
    error_dialog, layout = _build_shell_dialog(parent, "Ошибка установки FFmpeg", (560, 340))
    error_dialog.setModal(True)

    eyebrow = QLabel("MANUAL SETUP REQUIRED")
    eyebrow.setObjectName("LauncherShellEyebrow")
    layout.addWidget(eyebrow)

    title = QLabel("Не удалось автоматически установить FFmpeg")
    title.setObjectName("LauncherShellTitle")
    title.setWordWrap(True)
    layout.addWidget(title)

    message = QLabel(
        "FFmpeg нужен для отдельных функций программы, например для обработки аудио.\n\n"
        "Скачайте его с официального сайта и распакуйте `ffmpeg.exe` в папку программы."
    )
    message.setObjectName("LauncherShellBody")
    message.setWordWrap(True)
    message.setTextFormat(Qt.TextFormat.MarkdownText)
    layout.addWidget(message)

    link = QLabel('<a href="https://ffmpeg.org/download.html">https://ffmpeg.org/download.html</a>')
    link.setObjectName("LauncherShellBody")
    link.setOpenExternalLinks(True)
    link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    layout.addWidget(link)

    path_label = QLabel(str(Path(".").resolve()))
    path_label.setObjectName("LauncherShellPath")
    path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    path_label.setWordWrap(True)
    layout.addWidget(path_label)

    layout.addStretch()

    ok_button = QPushButton("OK")
    ok_button.setObjectName("LauncherShellActionButton")
    ok_button.clicked.connect(error_dialog.accept)
    layout.addWidget(ok_button, alignment=Qt.AlignmentFlag.AlignCenter)

    error_dialog.exec()
