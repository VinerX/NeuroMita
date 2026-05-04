from PyQt6.QtWidgets import QWidget

from styles.main_window.shell_styles import (
    PALETTE,
    LauncherShellPalette,
    get_launcher_shell_stylesheet,
    resolve_launcher_asset,
)


def apply_launcher_shell_theme(widget: QWidget) -> QWidget:
    widget.setStyleSheet(get_launcher_shell_stylesheet())
    return widget


__all__ = [
    "PALETTE",
    "LauncherShellPalette",
    "apply_launcher_shell_theme",
    "get_launcher_shell_stylesheet",
    "resolve_launcher_asset",
]
