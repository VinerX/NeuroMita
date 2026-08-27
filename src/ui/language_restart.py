from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

from utils import getTranslationVariant as _


def prompt_language_restart(parent: QWidget | None) -> bool:
    """Ask the user to restart now after changing the UI language."""
    try:
        from utils.app_restart import restart_app

        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Смена языка", "Language change"))
        box.setText(_(
            "Язык интерфейса изменён.\n\n"
            "Чтобы он применился полностью, нужен перезапуск.\n"
            "Перезапустить приложение сейчас?",
            "The interface language has been changed.\n\n"
            "A restart is required to apply it fully.\n"
            "Restart the app now?",
        ))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            restart_app()
            return True
        return False
    except Exception:
        return False
