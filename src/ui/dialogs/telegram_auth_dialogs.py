import asyncio

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.events import Events
from ui.widgets.launcher_shell_theme import PALETTE


_AUTH_DIALOG_STYLE = f"""
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
}}
QLineEdit#LauncherShellInput {{
    background-color: {PALETTE.card_alt_bg};
    color: {PALETTE.text};
    border: 1px solid {PALETTE.border};
    border-radius: 14px;
    padding: 11px 12px;
    font-size: 14px;
    selection-background-color: {PALETTE.accent};
}}
QLineEdit#LauncherShellInput:focus {{
    border: 1px solid {PALETTE.border_strong};
    background-color: {PALETTE.panel_soft};
}}
QPushButton#LauncherShellActionButton {{
    background-color: {PALETTE.accent};
    color: white;
    border: 1px solid {PALETTE.border_strong};
    border-radius: 14px;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 700;
    min-width: 126px;
}}
QPushButton#LauncherShellActionButton:hover {{
    background-color: {PALETTE.accent_hover};
}}
QPushButton#LauncherShellActionButton:pressed {{
    background-color: {PALETTE.accent_pressed};
}}
QPushButton#LauncherShellGhostButton {{
    background-color: rgba(255, 255, 255, 0.04);
    color: {PALETTE.text};
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
    min-width: 110px;
}}
QPushButton#LauncherShellGhostButton:hover {{
    background-color: {PALETTE.accent_soft};
    border: 1px solid {PALETTE.border};
}}
"""


def _build_auth_dialog(title: str, eyebrow: str, prompt: str, parent, *, is_password: bool = False):
    dialog = QDialog(parent)
    dialog.setObjectName("LauncherShellDialog")
    dialog.setStyleSheet(_AUTH_DIALOG_STYLE)
    dialog.setWindowTitle(title)
    dialog.setFixedSize(420, 240)
    dialog.setModal(True)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(18, 18, 18, 18)

    card = QFrame()
    card.setObjectName("LauncherShellCard")
    root.addWidget(card)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)

    eyebrow_label = QLabel(eyebrow)
    eyebrow_label.setObjectName("LauncherShellEyebrow")
    layout.addWidget(eyebrow_label)

    title_label = QLabel(title)
    title_label.setObjectName("LauncherShellTitle")
    layout.addWidget(title_label)

    prompt_label = QLabel(prompt)
    prompt_label.setObjectName("LauncherShellBody")
    prompt_label.setWordWrap(True)
    layout.addWidget(prompt_label)

    entry = QLineEdit()
    entry.setObjectName("LauncherShellInput")
    if is_password:
        entry.setEchoMode(QLineEdit.EchoMode.Password)
    else:
        entry.setMaxLength(10)
    entry.setFocus()
    layout.addWidget(entry)

    hint = QLabel("Enter подтверждает ввод, Esc отменяет окно.")
    hint.setObjectName("LauncherShellBody")
    layout.addWidget(hint)

    button_row = QHBoxLayout()
    button_row.addStretch()

    cancel_button = QPushButton("Отмена")
    cancel_button.setObjectName("LauncherShellGhostButton")
    cancel_button.clicked.connect(dialog.reject)
    button_row.addWidget(cancel_button)

    submit_button = QPushButton("Подтвердить")
    submit_button.setObjectName("LauncherShellActionButton")
    button_row.addWidget(submit_button)
    layout.addLayout(button_row)

    return dialog, entry, submit_button


def show_tg_code_dialog(parent, code_future, event_bus):
    dialog, code_entry, submit_button = _build_auth_dialog(
        "Подтверждение Telegram",
        "TELEGRAM LOGIN",
        "Введите код подтверждения из Telegram, чтобы завершить вход.",
        parent,
    )

    def submit_code():
        code = code_entry.text().strip()
        if code:
            if code_future and not code_future.done():
                loop = event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
                if loop and loop[0] and loop[0].is_running():
                    loop[0].call_soon_threadsafe(code_future.set_result, code)
            dialog.accept()
        else:
            QMessageBox.critical(dialog, "Ошибка", "Введите код подтверждения")

    def on_reject():
        if code_future and not code_future.done():
            loop = event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
            if loop and loop[0] and loop[0].is_running():
                loop[0].call_soon_threadsafe(code_future.set_exception, asyncio.CancelledError("Ввод кода отменен"))

    submit_button.clicked.connect(submit_code)
    code_entry.returnPressed.connect(submit_code)
    dialog.rejected.connect(on_reject)
    dialog.exec()


def show_tg_password_dialog(parent, password_future, event_bus):
    dialog, password_entry, submit_button = _build_auth_dialog(
        "Двухфакторная аутентификация",
        "ACCOUNT SECURITY",
        "Введите пароль двухфакторной аутентификации для продолжения.",
        parent,
        is_password=True,
    )

    def submit_password():
        pwd = password_entry.text().strip()
        if pwd:
            if password_future and not password_future.done():
                loop = event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
                if loop and loop[0] and loop[0].is_running():
                    loop[0].call_soon_threadsafe(password_future.set_result, pwd)
            dialog.accept()
        else:
            QMessageBox.critical(dialog, "Ошибка", "Введите пароль")

    def on_reject():
        if password_future and not password_future.done():
            loop = event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
            if loop and loop[0] and loop[0].is_running():
                loop[0].call_soon_threadsafe(password_future.set_exception, asyncio.CancelledError("Ввод пароля отменен"))

    submit_button.clicked.connect(submit_password)
    password_entry.returnPressed.connect(submit_password)
    dialog.rejected.connect(on_reject)
    dialog.exec()
