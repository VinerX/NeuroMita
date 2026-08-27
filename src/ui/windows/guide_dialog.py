from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from ui.app_icon import application_icon
from ui.widgets.guide_widget import GuideWidget
from ui.widgets.launcher_shell_theme import PALETTE
from utils import getTranslationVariant as _


class GuideDialog(QDialog):
    """Top-level guide window hosted by the application's WindowManager."""

    def __init__(self, settings_view_model, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._open_wiki_callback: Callable[[str], None] | None = None

        self.setObjectName("GuideDialog")
        self.setWindowTitle(_("Руководство NeuroMita", "NeuroMita Guide"))
        self.setWindowIcon(application_icon())
        self.setModal(False)

        flags = self.windowFlags()
        flags |= Qt.WindowType.WindowSystemMenuHint
        flags |= Qt.WindowType.WindowMinimizeButtonHint
        flags |= Qt.WindowType.WindowMaximizeButtonHint
        flags &= ~Qt.WindowType.WindowContextHelpButtonHint
        self.setWindowFlags(flags)

        self.setStyleSheet(
            f"QDialog#GuideDialog {{ background-color: {PALETTE.root_bg}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)

        self.guide_widget = GuideWidget(
            settings_view_model,
            parent=self,
            open_wiki=self._open_wiki,
        )
        self.guide_widget.closed.connect(self.close)
        root.addWidget(self.guide_widget)

        self._apply_screen_aware_geometry()

    def apply_payload(self, payload: dict | None) -> None:
        payload = payload if isinstance(payload, dict) else {}
        callback = payload.get("open_wiki")
        self._open_wiki_callback = callback if callable(callback) else None

    def prepare_for_show(self) -> None:
        self._apply_screen_aware_geometry(only_if_uninitialized=True)
        self.guide_widget.start()

    def _open_wiki(self, target: str) -> None:
        callback = self._open_wiki_callback
        if not callable(callback):
            return
        self.hide()
        callback(str(target or ""))

    def _apply_screen_aware_geometry(self, *, only_if_uninitialized: bool = False) -> None:
        if only_if_uninitialized and self.width() >= 900 and self.height() >= 600:
            return

        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1180, 820)
            return

        available = screen.availableGeometry()
        width = min(1180, max(760, int(available.width() * 0.94)))
        height = min(820, max(560, int(available.height() * 0.94)))
        self.resize(width, height)

        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())
