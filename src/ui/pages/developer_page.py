from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from ui.widgets.launcher_dashboard_helpers import (
    DashboardAction,
    create_shell_page_container,
    _create_hero_card,
)
from utils import _


class DeveloperPage(QWidget):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("DeveloperPage")
        self.gui.developer_page = self

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root, content_layout = create_shell_page_container()
        root.setParent(self)

        content_layout.addWidget(self._build_hero())
        content_layout.addWidget(self._build_finetune_card())
        content_layout.addStretch(1)

        root_layout.addWidget(root)

    # ── Hero ──────────────────────────────────────────────────────────────────

    def _build_hero(self) -> QFrame:
        return _create_hero_card(
            "DEV",
            _("Сбор данных для дообучения", "Fine-tune data collection"),
            _(
                "Сбор и экспорт данных для дообучения модели. Параметры отладки переехали в Песочницу → Отладка.",
                "Collect and export data for fine-tuning. Debug parameters moved to Sandbox → Debug.",
            ),
            actions=[
                DashboardAction(
                    _("Sandbox", "Sandbox"),
                    callback=lambda: self.gui.switch_main_page("sandbox"),
                    icon_name="fa6s.flask",
                    accent=False,
                ),
            ],
        )

    # ── Debug card ────────────────────────────────────────────────────────────

    def _build_debug_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel(_("Отладка", "Debug"))
        title.setObjectName("LauncherShellSectionTitle")
        layout.addWidget(title)

        subtitle = QLabel(_(
            "Параметры вывода structured output, системные сообщения, снапшоты и просмотр контекста.",
            "Structured output display, system messages, history snapshots and context viewer.",
        ))
        subtitle.setObjectName("LauncherShellMeta")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #333; margin: 4px 0;")
        layout.addWidget(sep)

        try:
            from ui.settings.debug_settings import setup_debug_panel_controls
            setup_debug_panel_controls(self.gui, layout)
        except Exception as exc:
            err = QLabel(f"[debug_settings error] {exc}")
            err.setWordWrap(True)
            layout.addWidget(err)

        return card

    # ── Finetune card ─────────────────────────────────────────────────────────

    def _build_finetune_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        try:
            from ui.settings.data_settings import setup_data_settings_controls
            setup_data_settings_controls(self.gui, layout)
        except Exception as exc:
            err = QLabel(f"[data_settings error] {exc}")
            err.setWordWrap(True)
            layout.addWidget(err)

        return card

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_activated(self):
        pass

    def on_deactivated(self):
        pass


def build_developer_page(window) -> QWidget:
    return DeveloperPage(window)
