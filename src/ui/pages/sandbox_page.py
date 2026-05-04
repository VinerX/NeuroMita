from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.widgets.chat_panel import setup_chat_panel


def build_sandbox_page(window) -> QWidget:
    sandbox_host = QWidget()
    sandbox_layout = QVBoxLayout(sandbox_host)
    sandbox_layout.setContentsMargins(0, 0, 0, 0)
    sandbox_layout.setSpacing(0)
    setup_chat_panel(window, sandbox_layout)
    return sandbox_host
