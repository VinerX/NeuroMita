"""
Секция настроек "Разработка" — видна только в полном режиме интерфейса.
Объединяет: дебаг-параметры вывода + сбор данных для дообучения.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QVBoxLayout


def setup_developer_settings_controls(
    gui,
    parent_layout: QVBoxLayout,
    *,
    finetune_view_model,
) -> None:
    from ui.settings.debug_settings import setup_debug_panel_controls
    from ui.settings.data_settings import setup_data_settings_controls

    setup_debug_panel_controls(gui, parent_layout)

    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet("border: none; border-top: 1px solid #333; margin: 8px 0;")
    parent_layout.addWidget(sep)

    setup_data_settings_controls(
        gui,
        parent_layout,
        view_model=finetune_view_model,
    )
