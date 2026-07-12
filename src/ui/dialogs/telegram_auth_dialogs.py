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

from ui.widgets.launcher_shell_theme import PALETTE
from utils import getTranslationVariant as _


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


def _build_auth_dialog(title: str, eyebrow: str, prompt: str, parent, *, is_password: bool = False,
                       error: str = ""):
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

    if error:
        error_label = QLabel(error)
        error_label.setObjectName("LauncherShellBody")
        error_label.setWordWrap(True)
        error_label.setStyleSheet("color: #e06c6c; font-weight: 600;")
        layout.addWidget(error_label)

    entry = QLineEdit()
    entry.setObjectName("LauncherShellInput")
    if is_password:
        entry.setEchoMode(QLineEdit.EchoMode.Password)
    else:
        entry.setMaxLength(10)
    entry.setFocus()
    layout.addWidget(entry)

    hint = QLabel(_("Enter подтверждает ввод, Esc отменяет окно.",
                    "Enter confirms, Esc cancels."))
    hint.setObjectName("LauncherShellBody")
    layout.addWidget(hint)

    button_row = QHBoxLayout()
    button_row.addStretch()

    cancel_button = QPushButton(_("Отмена", "Cancel"))
    cancel_button.setObjectName("LauncherShellGhostButton")
    cancel_button.clicked.connect(dialog.reject)
    button_row.addWidget(cancel_button)

    submit_button = QPushButton(_("Подтвердить", "Confirm"))
    submit_button.setObjectName("LauncherShellActionButton")
    button_row.addWidget(submit_button)
    layout.addLayout(button_row)

    return dialog, entry, submit_button


def show_tg_code_dialog(parent, actions, request_id: str, *, error: str = ""):
    from ui.dialogs.telegram_auth_presentation import RejectTelegramAuth, SubmitTelegramAuth

    dialog, code_entry, submit_button = _build_auth_dialog(
        _("Подтверждение Telegram", "Telegram confirmation"),
        "TELEGRAM LOGIN",
        _("Введите код подтверждения из Telegram, чтобы завершить вход.",
          "Enter the confirmation code from Telegram to finish signing in."),
        parent,
        error=error,
    )
    submitted = {"value": False}

    def submit_code():
        code = code_entry.text().strip()
        if not code:
            QMessageBox.critical(dialog, _("Ошибка", "Error"),
                                  _("Введите код подтверждения", "Enter the confirmation code"))
            return
        actions.dispatch(SubmitTelegramAuth(str(request_id), code))
        submitted["value"] = True
        dialog.accept()

    def on_reject():
        if not submitted["value"]:
            actions.dispatch(
                RejectTelegramAuth(
                    str(request_id),
                    _("Ввод кода отменён", "Code entry cancelled"),
                )
            )

    submit_button.clicked.connect(submit_code)
    code_entry.returnPressed.connect(submit_code)
    dialog.rejected.connect(on_reject)
    dialog.exec()


def show_tg_password_dialog(parent, actions, request_id: str, *, error: str = ""):
    from ui.dialogs.telegram_auth_presentation import RejectTelegramAuth, SubmitTelegramAuth

    dialog, password_entry, submit_button = _build_auth_dialog(
        _("Двухфакторная аутентификация", "Two-factor authentication"),
        "ACCOUNT SECURITY",
        _("Введите пароль двухфакторной аутентификации для продолжения.",
          "Enter your two-factor authentication password to continue."),
        parent,
        is_password=True,
        error=error,
    )
    submitted = {"value": False}

    def submit_password():
        password = password_entry.text().strip()
        if not password:
            QMessageBox.critical(dialog, _("Ошибка", "Error"),
                                  _("Введите пароль", "Enter the password"))
            return
        actions.dispatch(SubmitTelegramAuth(str(request_id), password))
        submitted["value"] = True
        dialog.accept()

    def on_reject():
        if not submitted["value"]:
            actions.dispatch(
                RejectTelegramAuth(
                    str(request_id),
                    _("Ввод пароля отменён", "Password entry cancelled"),
                )
            )

    submit_button.clicked.connect(submit_password)
    password_entry.returnPressed.connect(submit_password)
    dialog.rejected.connect(on_reject)
    dialog.exec()
