from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ui.widgets.launcher_shell_theme import PALETTE
from utils import _


_MODEL_LOADING_STYLE = f"""
QDialog#LauncherShellDialog {{
    background-color: {PALETTE.root_bg};
    color: {PALETTE.text};
}}
QFrame#LauncherShellCard {{
    background-color: {PALETTE.card_bg};
    border: 1px solid {PALETTE.border};
    border-radius: 24px;
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
}}
QProgressBar#LauncherShellProgressBar {{
    min-height: 16px;
    border: 1px solid {PALETTE.border};
    border-radius: 8px;
    background-color: {PALETTE.card_alt_bg};
    color: {PALETTE.text};
    text-align: center;
}}
QProgressBar#LauncherShellProgressBar::chunk {{
    border-radius: 7px;
    background-color: {PALETTE.accent};
}}
QPushButton#LauncherShellGhostButton {{
    background-color: rgba(255, 255, 255, 0.04);
    color: {PALETTE.text};
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
    min-width: 132px;
}}
QPushButton#LauncherShellGhostButton:hover {{
    background-color: {PALETTE.accent_soft};
    border: 1px solid {PALETTE.border};
}}
QLabel#LauncherShellHint {{
    color: {PALETTE.muted};
    font-size: 11px;
}}
"""


def create_model_loading_dialog(parent, model_name, cancel_callback, hide_callback=None):
    dialog = QDialog(parent)
    dialog.setObjectName("LauncherShellDialog")
    dialog.setStyleSheet(_MODEL_LOADING_STYLE)
    dialog.setWindowTitle(_("Загрузка модели", "Loading model") + f" {model_name}")
    dialog.setFixedSize(460, 320)
    dialog.setModal(True)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(18, 18, 18, 18)

    card = QFrame()
    card.setObjectName("LauncherShellCard")
    root.addWidget(card)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(12)

    eyebrow = QLabel("MODEL BOOTSTRAP")
    eyebrow.setObjectName("LauncherShellEyebrow")
    layout.addWidget(eyebrow)

    title_label = QLabel(_("Инициализация модели", "Initializing model") + f" {model_name}")
    title_label.setObjectName("LauncherShellTitle")
    title_label.setWordWrap(True)
    layout.addWidget(title_label)

    wait_label = QLabel(_("Пожалуйста, подождите, пока shell подготавливает модель к работе.", "Please wait while the shell prepares the model."))
    wait_label.setObjectName("LauncherShellBody")
    wait_label.setWordWrap(True)
    layout.addWidget(wait_label)

    loading_progress = QProgressBar()
    loading_progress.setObjectName("LauncherShellProgressBar")
    loading_progress.setRange(0, 0)
    loading_progress.setTextVisible(False)
    layout.addWidget(loading_progress)

    loading_status_label = QLabel(_("Инициализация...", "Initializing..."))
    loading_status_label.setObjectName("LauncherShellBody")
    loading_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    loading_status_label.setWordWrap(True)
    layout.addWidget(loading_status_label)

    layout.addStretch()

    if hide_callback is not None:
        hint_label = QLabel(_(
            "Окно можно скрыть — инициализация продолжится в фоне, "
            "её состояние видно в настройках озвучки.",
            "You can hide this window — initialization keeps running in the "
            "background, its state is shown in the voice settings.",
        ))
        hint_label.setObjectName("LauncherShellHint")
        hint_label.setWordWrap(True)
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint_label)

    buttons_layout = QHBoxLayout()
    buttons_layout.setSpacing(10)
    buttons_layout.addStretch()

    if hide_callback is not None:
        hide_button = QPushButton(_("Скрыть", "Hide"))
        hide_button.setObjectName("LauncherShellGhostButton")
        hide_button.clicked.connect(hide_callback)
        buttons_layout.addWidget(hide_button)

    cancel_button = QPushButton(_("Отменить", "Cancel"))
    cancel_button.setObjectName("LauncherShellGhostButton")
    cancel_button.clicked.connect(cancel_callback)
    buttons_layout.addWidget(cancel_button)

    buttons_layout.addStretch()
    layout.addLayout(buttons_layout)

    return dialog, loading_progress, loading_status_label
