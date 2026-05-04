from PyQt6.QtWidgets import QWidget

from ui.pages.sandbox import SandboxPage


def build_sandbox_page(window) -> QWidget:
    return SandboxPage(window)
